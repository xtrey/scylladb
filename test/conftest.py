#
# Copyright (C) 2024-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.0
#
import _pytest
import pytest

from test import TEST_RUNNER
from test.pylib.report_plugin import ReportPlugin


pytest_plugins = []

def dynamic_scope() -> _pytest.scope._ScopeName:
    """Dynamic scope for fixtures which rely on a current test.py suite/test.

    Even though test.py not running tests anymore, there is some logic still there that requires module scope.
    When using runpy runner, all custom logic should be disabled and scope should be session.
    """
    if TEST_RUNNER == "runpy":
        return "session"
    return "module"


if TEST_RUNNER == "runpy":
    @pytest.fixture(scope="session")
    def testpy_test() -> None:
        return None
else:
    pytest_plugins.append("test.pylib.runner")


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(ReportPlugin())
