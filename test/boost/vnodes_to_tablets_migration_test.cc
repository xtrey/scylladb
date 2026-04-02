/*
 * Copyright (C) 2026-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
 */

#undef SEASTAR_TESTING_MAIN
#include <seastar/testing/test_case.hh>
#include <seastar/util/bool_class.hh>

#include "db/config.hh"
#include "test/lib/cql_test_env.hh"
#include "locator/tablets.hh"
#include "service/storage_service.hh"

using aligned_last_token = bool_class<class aligned_last_token_tag>;

BOOST_AUTO_TEST_SUITE(vnodes_to_tablets_migration_test)

// Verify creation of extra tablet for wrap-around vnodes.
//
// Tablets cannot wrap around the token ring as vnodes do; the last token of
// the last tablet must always be MAX_TOKEN. So, when we build the tablet map,
// if a wrap-around vnode exists (i.e., the last vnode token is not MAX_TOKEN),
// it needs to be split into two tablets: (last_vnode_token, last_token()] and
// [first_token(), first_vnode_token].
static future<> test_migration_tablet_boundaries(aligned_last_token aligned) {
    std::vector<int64_t> tokens{-7686143364045646507, 0, 7158264828641642373}; // some random tokens
    if (aligned) {
        tokens.back() = dht::last_token().raw();
    }

    cql_test_config cfg;
    auto initial_token = fmt::format("{}", fmt::join(tokens, ", "));
    cfg.db_config->initial_token.set(std::move(initial_token));

    return do_with_cql_env_thread([tokens, aligned] (cql_test_env& e) {
        auto ks_name = sstring("test_migration_ks");
        e.execute_cql(format("CREATE KEYSPACE {} "
                "WITH replication = {{'class': 'NetworkTopologyStrategy', 'replication_factor': 1}} "
                "AND tablets = {{'enabled': false}}", ks_name)).get();

        e.execute_cql(format("CREATE TABLE {}.t (pk int PRIMARY KEY)", ks_name)).get();
        auto tid = e.local_db().find_schema(ks_name, "t")->id();

        e.get_storage_service().local().prepare_for_tablets_migration(ks_name).get();

        auto& stm = e.local_db().get_shared_token_metadata();
        auto& tmap = stm.get()->tablets().get_tablet_map(tid);

        auto expected = std::vector<dht::token>{};
        for (const auto& t : tokens) {
            expected.push_back(dht::token(t));
        }
        if (!aligned) {
            expected.push_back(dht::last_token());
        }

        auto actual = std::vector<dht::token>{};
        for (size_t i = 0; i < tmap.tablet_count(); ++i) {
            actual.push_back(tmap.get_last_token(locator::tablet_id(i)));
        }
        BOOST_TEST_INFO("actual: " << fmt::format("{}", fmt::join(actual, ", ")));
        BOOST_TEST_INFO("expected: " << fmt::format("{}", fmt::join(expected, ", ")));
        BOOST_REQUIRE_EQUAL_COLLECTIONS(actual.begin(), actual.end(), expected.begin(), expected.end());
    }, cfg);
}

// When the last vnode token != MAX_TOKEN, the wrap-around vnode is split
// into two tablets. Expect one more tablet than vnodes.
SEASTAR_TEST_CASE(test_unaligned_last_token) {
    return test_migration_tablet_boundaries(aligned_last_token::no);
}

// When the last vnode token == MAX_TOKEN, no split is needed.
// Expect exactly one tablet per vnode.
SEASTAR_TEST_CASE(test_aligned_last_token) {
    return test_migration_tablet_boundaries(aligned_last_token::yes);
}

BOOST_AUTO_TEST_SUITE_END()
