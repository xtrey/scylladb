/*
 * Copyright (C) 2019-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
 */



#pragma once

#include "restrictions/restrictions_config.hh"
#include "db/tri_mode_restriction.hh"
#include "utils/updateable_value.hh"

namespace db { class config; }

namespace cql3 {

struct cql_config {
    restrictions::restrictions_config restrictions;
    utils::updateable_value<uint32_t> select_internal_page_size;
    utils::updateable_value<db::tri_mode_restriction> strict_allow_filtering;

    explicit cql_config(const db::config& cfg)
        : restrictions(cfg)
        , select_internal_page_size(cfg.select_internal_page_size)
        , strict_allow_filtering(cfg.strict_allow_filtering)
    {}
    struct default_tag{};
    cql_config(default_tag)
        : restrictions(restrictions::restrictions_config::default_tag{})
        , select_internal_page_size(10000)
        , strict_allow_filtering(db::tri_mode_restriction(db::tri_mode_restriction_t::mode::WARN))
    {}
};

extern const cql_config default_cql_config;

}
