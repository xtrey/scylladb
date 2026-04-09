/*
 * Copyright (C) 2019-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
 */



#pragma once

#include "restrictions/restrictions_config.hh"
#include "utils/updateable_value.hh"

namespace db { class config; }

namespace cql3 {

struct cql_config {
    restrictions::restrictions_config restrictions;
    utils::updateable_value<uint32_t> select_internal_page_size;

    explicit cql_config(const db::config& cfg)
        : restrictions(cfg)
        , select_internal_page_size(cfg.select_internal_page_size)
    {}
    struct default_tag{};
    cql_config(default_tag)
        : restrictions(restrictions::restrictions_config::default_tag{})
        , select_internal_page_size(10000)
    {}
};

extern const cql_config default_cql_config;

}
