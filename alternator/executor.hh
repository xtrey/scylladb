/*
 * Copyright 2019-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
 */

#pragma once

#include <seastar/core/future.hh>
#include "audit/audit.hh"
#include "seastarx.hh"
#include <seastar/core/sharded.hh>
#include <seastar/util/noncopyable_function.hh>

#include "service/migration_manager.hh"
#include "service/client_state.hh"
#include "service_permit.hh"
#include "db/timeout_clock.hh"
#include "db/config.hh"

#include "alternator/error.hh"
#include "stats.hh"
#include "utils/rjson.hh"
#include "utils/updateable_value.hh"
#include "utils/simple_value_with_expiry.hh"

#include "tracing/trace_state.hh"

namespace db {
    class system_distributed_keyspace;
}

namespace audit {
class audit_info_alternator;
}

namespace query {
class partition_slice;
class result;
}

namespace cql3::selection {
    class selection;
}

namespace service {
    class storage_proxy;
    class cas_shard;
    class storage_service;
}

namespace vector_search {
    class vector_store_client;
}

namespace cdc {
    class metadata;
}

namespace gms {

class gossiper;

}

class schema_builder;

#include "alternator/attribute_path.hh"

namespace alternator {

enum class table_status;
class rmw_operation;
class put_or_delete_item;

schema_ptr get_table(service::storage_proxy& proxy, const rjson::value& request);
bool is_alternator_keyspace(const sstring& ks_name);
// Wraps the db::get_tags_of_table and throws if the table is missing the tags extension.
const std::map<sstring, sstring>& get_tags_of_table_or_throw(schema_ptr schema);

namespace parsed {
class expression_cache;
}

class executor : public peering_sharded_service<executor> {
    gms::gossiper& _gossiper;
    service::storage_service& _ss;
    service::storage_proxy& _proxy;
    service::migration_manager& _mm;
    db::system_distributed_keyspace& _sdks;
    cdc::metadata& _cdc_metadata;
    vector_search::vector_store_client& _vsc;
    utils::updateable_value<bool> _enforce_authorization;
    utils::updateable_value<bool> _warn_authorization;
    seastar::sharded<audit::audit>& _audit;
    // An smp_service_group to be used for limiting the concurrency when
    // forwarding Alternator request between shards - if necessary for LWT.
    smp_service_group _ssg;

    std::unique_ptr<parsed::expression_cache> _parsed_expression_cache;

    struct describe_table_info_manager;
    std::unique_ptr<describe_table_info_manager> _describe_table_info_manager;

    future<> cache_newly_calculated_size_on_all_shards(schema_ptr schema, std::uint64_t size_in_bytes, std::chrono::nanoseconds ttl);
    future<> fill_table_size(rjson::value &table_description, schema_ptr schema, bool deleting);
public:
    using client_state = service::client_state;
    // request_return_type is the return type of the executor methods, which
    // can be one of:
    // 1. A string, which is the response body for the request.
    // 2. A body_writer, an asynchronous function (returning future<>) that
    //    takes an output_stream and writes the response body into it.
    // 3. An api_error, which is an error response that should be returned to
    //    the client.
    // The body_writer is used for streaming responses, where the response body
    // is written in chunks to the output_stream. This allows for efficient
    // handling of large responses without needing to allocate a large buffer
    // in memory.
    using body_writer = noncopyable_function<future<>(output_stream<char>&&)>;
    using request_return_type = std::variant<std::string, body_writer, api_error>;
    stats _stats;
    // The metric_groups object holds this stat object's metrics registered
    // as long as the stats object is alive.
    seastar::metrics::metric_groups _metrics;
    static constexpr auto ATTRS_COLUMN_NAME = ":attrs";
    static constexpr auto KEYSPACE_NAME_PREFIX = "alternator_";
    static constexpr std::string_view INTERNAL_TABLE_PREFIX = ".scylla.alternator.";

    executor(gms::gossiper& gossiper,
             service::storage_proxy& proxy,
             service::storage_service& ss,
             service::migration_manager& mm,
             db::system_distributed_keyspace& sdks,
             cdc::metadata& cdc_metadata,
             vector_search::vector_store_client& vsc,
             smp_service_group ssg,
             utils::updateable_value<uint32_t> default_timeout_in_ms);
    ~executor();

    future<request_return_type> create_table(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> describe_table(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> delete_table(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> update_table(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> put_item(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> get_item(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> delete_item(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> update_item(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> list_tables(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> scan(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> describe_endpoints(client_state& client_state, service_permit permit, rjson::value request, std::string host_header, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> batch_write_item(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> batch_get_item(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> query(client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> tag_resource(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> untag_resource(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> list_tags_of_resource(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> update_time_to_live(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> describe_time_to_live(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> list_streams(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> describe_stream(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> get_shard_iterator(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> get_records(client_state& client_state, tracing::trace_state_ptr, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);
    future<request_return_type> describe_continuous_backups(client_state& client_state, service_permit permit, rjson::value request, std::unique_ptr<audit::audit_info_alternator>& audit_info);

    future<> start();
    future<> stop();

    static sstring table_name(const schema&);
    static db::timeout_clock::time_point default_timeout();
private:
    static thread_local utils::updateable_value<uint32_t> s_default_timeout_in_ms;
public:
    static schema_ptr find_table(service::storage_proxy&, std::string_view table_name);
    static schema_ptr find_table(service::storage_proxy&, const rjson::value& request);

private:
    friend class rmw_operation;

    // Helper to set up auditing for an Alternator operation. Checks whether
    // the operation should be audited (via will_log()) and if so, allocates
    // and populates audit_info. No allocation occurs when auditing is disabled.
    void maybe_audit(std::unique_ptr<audit::audit_info_alternator>& audit_info,
                     audit::statement_category category,
                     std::string_view ks_name,
                     std::string_view table_name,
                     std::string_view operation_name,
                     const rjson::value& request,
                     std::optional<db::consistency_level> cl = std::nullopt);

    static void describe_key_schema(rjson::value& parent, const schema&, std::unordered_map<std::string,std::string> * = nullptr, const std::map<sstring, sstring> *tags = nullptr);
    future<rjson::value> fill_table_description(schema_ptr schema, table_status tbl_status, service::client_state& client_state, tracing::trace_state_ptr trace_state, service_permit permit);
    future<executor::request_return_type> create_table_on_shard0(service::client_state&& client_state, tracing::trace_state_ptr trace_state, rjson::value request, bool enforce_authorization,
            bool warn_authorization, const db::tablets_mode_t::mode tablets_mode, std::unique_ptr<audit::audit_info_alternator>& audit_info);

    future<> do_batch_write(
        std::vector<std::pair<schema_ptr, put_or_delete_item>> mutation_builders,
        service::client_state& client_state,
        tracing::trace_state_ptr trace_state,
        service_permit permit);

    future<> cas_write(schema_ptr schema, service::cas_shard cas_shard, const dht::decorated_key& dk,
        const std::vector<put_or_delete_item>& mutation_builders, service::client_state& client_state,
        tracing::trace_state_ptr trace_state, service_permit permit);

public:
    static void describe_key_schema(rjson::value& parent, const schema& schema, std::unordered_map<std::string,std::string>&, const std::map<sstring, sstring> *tags = nullptr);

    static std::optional<rjson::value> describe_single_item(schema_ptr,
        const query::partition_slice&,
        const cql3::selection::selection&,
        const query::result&,
        const std::optional<attrs_to_get>&,
        uint64_t* = nullptr);

    // Converts a multi-row selection result to JSON compatible with DynamoDB.
    // For each row, this method calls item_callback, which takes the size of
    // the item as the parameter.
    static future<std::vector<rjson::value>> describe_multi_item(schema_ptr schema,
        const query::partition_slice&& slice,
        shared_ptr<cql3::selection::selection> selection,
        foreign_ptr<lw_shared_ptr<query::result>> query_result,
        shared_ptr<const std::optional<attrs_to_get>> attrs_to_get,
        noncopyable_function<void(uint64_t)> item_callback = {});

    static void describe_single_item(const cql3::selection::selection&,
        const std::vector<managed_bytes_opt>&,
        const std::optional<attrs_to_get>&,
        rjson::value&,
        uint64_t* item_length_in_bytes = nullptr,
        bool = false);

    static bool add_stream_options(const rjson::value& stream_spec, schema_builder&, service::storage_proxy& sp);
    static void supplement_table_info(rjson::value& descr, const schema& schema, service::storage_proxy& sp);
    static void supplement_table_stream_info(rjson::value& descr, const schema& schema, const service::storage_proxy& sp);
};

// is_big() checks approximately if the given JSON value is "bigger" than
// the given big_size number of bytes. The goal is to *quickly* detect
// oversized JSON that, for example, is too large to be serialized to a
// contiguous string - we don't need an accurate size for that. Moreover,
// as soon as we detect that the JSON is indeed "big", we can return true
// and don't need to continue calculating its exact size.
// For simplicity, we use a recursive implementation. This is fine because
// Alternator limits the depth of JSONs it reads from inputs, and doesn't
// add more than a couple of levels in its own output construction.
bool is_big(const rjson::value& val, int big_size = 100'000);

// Check CQL's Role-Based Access Control (RBAC) permission (MODIFY,
// SELECT, DROP, etc.) on the given table. When permission is denied an
// appropriate user-readable api_error::access_denied is thrown.
future<> verify_permission(bool enforce_authorization, bool warn_authorization, const service::client_state&, const schema_ptr&, auth::permission, alternator::stats& stats);

/**
 * Make return type for serializing the object "streamed",
 * i.e. direct to HTTP output stream. Note: only useful for
 * (very) large objects as there are overhead issues with this
 * as well, but for massive lists of return objects this can
 * help avoid large allocations/many re-allocs
 */
executor::body_writer make_streamed(rjson::value&&);

// returns table creation time in seconds since epoch for `db_clock`
double get_table_creation_time(const schema &schema);

// result of parsing ARN (Amazon Resource Name)
// ARN format is `arn:<partition>:<service>:<region>:<account-id>:<resource-type>/<resource-id>/<postfix>`
// we ignore partition, service and account-id
// resource-type must be string "table"
// resource-id will be returned as table_name
// region will be returned as keyspace_name
// postfix is a string after resource-id and will be returned as is (whole), including separator.
struct arn_parts {
    std::string_view keyspace_name;
    std::string_view table_name;
    std::string_view postfix;
};
// arn - arn to parse
// arn_field_name - identifier of the ARN, used only when reporting an error (in error messages), for example "Incorrect resource identifier `<arn_field_name>`"
// type_name - used only when reporting an error (in error messages), for example "... is not a valid <type_name> ARN ..."
// expected_postfix - optional filter of postfix value (part of ARN after resource-id, including separator, see comments for struct arn_parts).
//    If is empty - then postfix value must be empty as well
//    if not empty - postfix value must start with expected_postfix, but might be longer
arn_parts parse_arn(std::string_view arn, std::string_view arn_field_name, std::string_view type_name, std::string_view expected_postfix);

// The format is ks1|ks2|ks3... and table1|table2|table3...
sstring print_names_for_audit(const std::set<sstring>& names);

map_type attrs_type();
lw_shared_ptr<stats> get_stats_from_schema(service::storage_proxy& sp, const schema& schema);
std::string view_name(std::string_view table_name, std::string_view index_name,
        const std::string& delim = ":", bool validate_len = true);
std::string gsi_name(std::string_view table_name, std::string_view index_name,
        bool validate_len = true);
std::string lsi_name(std::string_view table_name, std::string_view index_name,
        bool validate_len = true);
std::string get_table_name(const rjson::value& request);
schema_ptr try_get_internal_table(data_dictionary::database db, std::string_view table_name);
std::optional<int> get_int_attribute(const rjson::value& value, std::string_view attribute_name);
bool get_bool_attribute(const rjson::value& value, std::string_view attribute_name, bool default_return);
void check_key(const rjson::value& key, const schema_ptr& schema);
schema_ptr get_table_from_batch_request(const service::storage_proxy& proxy, const rjson::value::ConstMemberIterator& batch_request);
void verify_all_are_used(
        const rjson::value* field,
        const std::unordered_set<std::string>& used,
        const char* field_name,
        const char* operation);

}
