/*
 * Copyright (C) 2018-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
 */

#pragma once

#include "schema/schema_fwd.hh"
#include "locator/host_id.hh"

#include <seastar/core/future.hh>
#include <seastar/core/sstring.hh>

#include <unordered_map>

namespace cql3 {
class query_processor;
}

namespace cdc {
    class topology_description;
    class streams_version;
} // namespace cdc

namespace service {
    class storage_proxy;
    class migration_manager;
}

namespace db {

class system_distributed_keyspace {
public:
    static constexpr auto NAME = "system_distributed";

    static constexpr auto VIEW_BUILD_STATUS = "view_build_status";

    /* This table is used by CDC clients to learn about available CDC streams. */
    static constexpr auto CDC_DESC_V2 = "cdc_streams_descriptions_v2";

    /* Used by CDC clients to learn CDC generation timestamps. */
    static constexpr auto CDC_TIMESTAMPS = "cdc_generation_timestamps";

    /* Previous version of the "cdc_streams_descriptions_v2" table.
     * We use it in the upgrade procedure to ensure that CDC generations appearing
     * in the old table also appear in the new table, if necessary. */
    static constexpr auto CDC_DESC_V1 = "cdc_streams_descriptions";

    /* Information required to modify/query some system_distributed tables, passed from the caller. */
    struct context {
        /* How many different token owners (endpoints) are there in the token ring? */
        size_t num_token_owners;
    };
private:
    cql3::query_processor& _qp;
    service::migration_manager& _mm;
    service::storage_proxy& _sp;

    bool _started = false;
    bool _forced_cdc_timestamps_schema_sync = false;

public:
    static std::vector<schema_ptr> all_distributed_tables();

    system_distributed_keyspace(cql3::query_processor&, service::migration_manager&, service::storage_proxy&);

    future<> start();
    future<> stop();

    bool started() const { return _started; }

    future<> create_cdc_desc(db_clock::time_point, const cdc::topology_description&, context);
    future<bool> cdc_desc_exists(db_clock::time_point, context);

    future<std::map<db_clock::time_point, cdc::streams_version>> cdc_get_versioned_streams(db_clock::time_point not_older_than, context);

    future<db_clock::time_point> cdc_current_generation_timestamp(context);

private:
    future<> create_tables(std::vector<schema_ptr> tables);
};

}
