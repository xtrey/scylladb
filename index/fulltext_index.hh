/*
 * Copyright 2026-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
 */

#pragma once

#include "schema/schema.hh"

#include "data_dictionary/data_dictionary.hh"
#include "cql3/statements/index_target.hh"
#include "index/secondary_index_manager.hh"

#include <vector>

namespace secondary_index {

class fulltext_index : public custom_index {
public:
    std::string_view index_type_name() const override {
        return "fulltext";
    }

    fulltext_index() = default;
    ~fulltext_index() override = default;
    std::optional<cql3::description> describe(const index_metadata& im, const schema& base_schema) const override;
    bool view_should_exist() const override;
    void validate(const schema& schema, const cql3::statements::index_specific_prop_defs& properties,
            const std::vector<::shared_ptr<cql3::statements::index_target>>& targets, const gms::feature_service& fs,
            const data_dictionary::database& db) const override;
    utils::UUID index_version(const schema& schema) override;

private:
    void check_target(const schema& schema, const std::vector<::shared_ptr<cql3::statements::index_target>>& targets) const;
    void check_index_options(const cql3::statements::index_specific_prop_defs& properties) const;
};

std::unique_ptr<secondary_index::custom_index> fulltext_index_factory();

} // namespace secondary_index
