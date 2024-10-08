/*
 * Copyright (C) 2017-present ScyllaDB
 */

/*
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

#pragma once

namespace seastar {

template <typename T>
class shared_ptr;

template <typename T, typename... A>
shared_ptr<T> make_shared(A&&... a);

}

using namespace seastar;
using seastar::shared_ptr;
using seastar::make_shared;
