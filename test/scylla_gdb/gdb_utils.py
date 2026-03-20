# Copyright 2025-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.0
"""
GDB helper functions for `scylla_gdb` tests.
They should be loaded to GDB by "-x {dir}/gdb_utils.py}",
when loaded, they can be run in gdb e.g. `python get_sstables()`

Depends on helper functions injected to GDB by `scylla-gdb.py` script.
(sharded, for_each_table, seastar_lw_shared_ptr, find_sstables, find_vptrs, resolve,
get_seastar_memory_start_and_size).
"""

import gdb
import uuid

# Protocol markers shared with GDBSession in conftest.py.
# The hex suffix avoids collisions with real command output.
_GDB_RC_PREFIX = "===GDB_RC="
_GDB_ERR_MARKER = "===GDB_ERR_7f3a2b==="
_GDB_DONE_MARKER = "===GDB_DONE_7f3a2b==="


def run_cmd(cmd):
    """Execute a GDB command and write structured output for the test harness.

    Called by ``GDBSession.execute()`` through ``python run_cmd(...)``.
    Handles both native GDB commands (via ``gdb.execute(to_string=True)``)
    and ``python ...`` commands (via ``exec`` with stdout capture).

    The output format is::

        ===GDB_RC=<N>===
        <stdout text>
        ===GDB_ERR_7f3a2b===
        <stderr text>
        ===GDB_DONE_7f3a2b===
    """
    import sys
    import io

    rc = 0
    out = ""
    err = ""

    try:
        if cmd.startswith("python "):
            # Python commands use print(), which goes to sys.stdout directly.
            # Redirect stdout to a StringIO so we can capture the output.
            py_code = cmd[len("python "):]
            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()
            try:
                exec(py_code, globals())
                out = captured.getvalue()
            finally:
                sys.stdout = old_stdout
        else:
            # Native GDB commands – capture with to_string=True.
            out = gdb.execute(cmd, to_string=True) or ""
    except gdb.error as e:
        err = str(e)
        rc = 1
    except Exception as e:
        err = str(e)
        rc = 1

    # Write structured result to real stdout (goes through the pipe to
    # GDBSession._read_command_output).
    sys.stdout.write(f"{_GDB_RC_PREFIX}{rc}===\n")
    if out:
        sys.stdout.write(out)
        if not out.endswith('\n'):
            sys.stdout.write('\n')
    sys.stdout.write(f"{_GDB_ERR_MARKER}\n")
    if err:
        sys.stdout.write(err)
        if not err.endswith('\n'):
            sys.stdout.write('\n')
    sys.stdout.write(f"{_GDB_DONE_MARKER}\n")
    sys.stdout.flush()


def get_schema():
    """Execute GDB commands to get schema information."""
    db = sharded(gdb.parse_and_eval('::debug::the_database')).local()
    table = next(for_each_table(db))
    ptr = seastar_lw_shared_ptr(table['_schema']).get()
    print('schema=', ptr)


def get_sstables():
    """Execute GDB commands to get sstables information."""
    sst = next(find_sstables())
    print(f"sst=(sstables::sstable *)", sst)


def get_task():
    """
    Some commands need a task to work on. The following fixture finds one.
    Because we stopped Scylla while it was idle, we don't expect to find
    any ready task with get_local_tasks(), but we can find one with a
    find_vptrs() loop. I noticed that a nice one (with multiple tasks chained
    to it for "scylla fiber") is one from http_server::do_accept_one.
    """
    for obj_addr, vtable_addr in find_vptrs():
        name = resolve(vtable_addr, startswith='vtable for seastar::continuation')
        if name and 'do_accept_one' in name:
            print(f"task={obj_addr.cast(gdb.lookup_type('uintptr_t'))}")
            break


def get_coroutine():
    """Similar to get_task(), but looks for a coroutine frame."""
    target = 'service::topology_coordinator::run() [clone .resume]'
    for obj_addr, vtable_addr in find_vptrs():
        name = resolve(vtable_addr)
        if name and name.strip() == target:
            print(f"coroutine_config={obj_addr.cast(gdb.lookup_type('uintptr_t'))}")
