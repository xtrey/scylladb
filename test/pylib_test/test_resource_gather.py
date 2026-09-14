#
# Copyright (C) 2026-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
#
"""Tests for the per-test memory peak measured by ResourceGatherOn.

memory.peak only reports this test's peak on kernels where writing to the FD resets
it. Where it doesn't, the file holds the cgroup's lifetime high-water mark, and using
it makes every test inherit the peak of everything that ran before it in the worker.
"""

import logging
import pathlib
from types import SimpleNamespace

from test.pylib.resource_gather import ResourceGatherOn


def make_gatherer(cgroup: pathlib.Path) -> ResourceGatherOn:
    """A ResourceGatherOn with just the state these tests touch (no DB, no cgroups)."""
    gatherer = object.__new__(ResourceGatherOn)
    gatherer.test = SimpleNamespace(time_start=0.0, time_end=1.0, success=True)
    gatherer.test_id = 1
    gatherer.worker_id = 'gw0'
    gatherer.cgroup_path = cgroup
    gatherer._memory_peak_fd = None
    gatherer._memory_peak_reset = False
    gatherer._sampled_peak = 0
    gatherer._cpu_stat_start = None
    gatherer.logger = logging.getLogger(__name__)
    return gatherer


def test_memory_peak_uses_the_fd_when_it_can_be_reset(tmp_path):
    (tmp_path / 'memory.peak').write_text('4096\n')
    (tmp_path / 'memory.current').write_text('1024\n')
    gatherer = make_gatherer(tmp_path)

    gatherer.setup_test_tracking()
    assert gatherer._memory_peak_reset
    # A regular file accepts the write, so the reset "succeeds"; the value read back
    # is whatever the file holds, i.e. what the kernel would report for this test.
    (tmp_path / 'memory.peak').write_text('8192\n')
    assert gatherer.get_test_metrics().memory_peak == 8192


def test_memory_peak_falls_back_to_samples_when_it_cannot_be_reset(tmp_path):
    peak = tmp_path / 'memory.peak'
    peak.write_text('999999\n')       # the worker's lifetime peak - must not be used
    peak.chmod(0o444)                 # read-only: opening 'r+' fails, like an old kernel
    (tmp_path / 'memory.current').write_text('1024\n')
    gatherer = make_gatherer(tmp_path)

    gatherer.setup_test_tracking()
    assert not gatherer._memory_peak_reset
    assert gatherer._memory_peak_fd is None

    gatherer._sampled_peak = 4096     # as the monitor thread would have recorded
    assert gatherer.get_test_metrics().memory_peak == 4096


def test_fallback_takes_a_final_sample_for_short_tests(tmp_path):
    peak = tmp_path / 'memory.peak'
    peak.write_text('999999\n')
    peak.chmod(0o444)
    (tmp_path / 'memory.current').write_text('7000\n')
    gatherer = make_gatherer(tmp_path)

    gatherer.setup_test_tracking()
    # Test shorter than the 1 s sampling interval: the monitor recorded nothing.
    assert gatherer.get_test_metrics().memory_peak == 7000


def test_no_cgroup_files_leaves_memory_peak_unset(tmp_path):
    gatherer = make_gatherer(tmp_path)
    gatherer.setup_test_tracking()
    assert gatherer.get_test_metrics().memory_peak is None
