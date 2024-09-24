from pathlib import Path
from typing import Sequence, Any, Iterator

import pytest
from _pytest._code.code import TerminalRepr
from pytest_cpp.error import CppFailureRepr, CppFailureError

from test.pylib.cpp.boost import BoostTestFacade


class CppItem(pytest.Item):
    facade = None

    def __init__(
        self,
        *,
        executable: Path,
        facade: BoostTestFacade,
        arguments: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.facade = facade
        self.executable = executable
        self._arguments = arguments


    def runtest(self) -> None:
        failures, output = self.facade.run_test(
            str(self.executable),
            self.name,
            self._arguments,
            harness=self.config.getini("cpp_harness"),
        )
        # Report the c++ output in its own sections
        self.add_report_section("call", "c++", output)

        if self.config.getini("cpp_verbose"):
            print(output)

        if failures:
            raise CppFailureError(failures)

    def repr_failure(  # type:ignore[override]
        self, excinfo: pytest.ExceptionInfo[BaseException], **kwargs: Any
    ) -> str | TerminalRepr | CppFailureRepr:
        if isinstance(excinfo.value, CppFailureError):
            return CppFailureRepr(excinfo.value.failures)
        return pytest.Item.repr_failure(self, excinfo)

    def reportinfo(self) -> tuple[Any, int, str]:
        return self.path, 0, self.name


class CppFile(pytest.File):
    def __init__(
        self,
        *,
        executable: Path,
        mode: str,
        temp_dir: Path,
        no_parallel_run: bool = False,
        arguments: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.facade = BoostTestFacade(mode=mode, temp_dir=temp_dir)
        self.executable = executable
        self.no_parallel_run = no_parallel_run
        self._arguments = arguments


    def collect(self) -> Iterator[CppItem]:
        harness_collect = self.config.getini("cpp_harness_collect")
        tests = self.facade.list_tests(
            str(self.executable),
            self.no_parallel_run,
            harness_collect=harness_collect,
        )
        if len(tests) == 1:
            yield CppItem.from_parent(
                self,
                name=tests[0],
                executable=self.executable,
                facade=self.facade,
                arguments=self._arguments,
            )
        else:
            for test_id in tests:
                args = [f'--run_test={test_id}']
                args.extend(self._arguments)
                yield CppItem.from_parent(
                    self,
                    name=test_id,
                    executable=self.executable,
                    facade=self.facade,
                    arguments=args,
                )
