# Copyright 2022-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.0
"""Conftest for Scylla GDB tests.

Provides a persistent ``GDBSession`` that loads debug symbols once per module
and reuses the same GDB process for every command in that module.  The previous
approach spawned a brand-new GDB for **every** ``execute_gdb_command()`` call,
each time loading the multi-GB release debug symbols from scratch.  With many
xdist workers running concurrently this caused OOM.
"""

import os
import re
import subprocess
import threading

import pytest

from test.pylib.runner import testpy_test_fixture_scope
from test.pylib.suite.python import PythonTest


# ---------------------------------------------------------------------------
# GDBSession – persistent GDB wrapper
# ---------------------------------------------------------------------------

class GDBSession:
    """A long-lived GDB process attached to a Scylla server.

    Debug symbols are loaded once in ``__init__`` and the session is reused for
    every command issued via ``execute()``.  Communication uses a simple
    marker-based protocol: each command is dispatched through the ``run_cmd()``
    helper defined in ``gdb_utils.py``, which writes structured delimiters
    around stdout / stderr / return-code so the Python side can parse them
    reliably even when ``(gdb)`` prompts are interleaved.
    """

    READY_MARKER = "===GDB_READY==="
    DONE_MARKER = "===GDB_DONE_7f3a2b==="
    RC_PREFIX = "===GDB_RC="
    ERR_MARKER = "===GDB_ERR_7f3a2b==="

    def __init__(self, scylla_exe: str, scylla_pid: str,
                 scylla_gdb_py: str, gdb_utils_py: str):
        cmd = [
            "gdb", "-q", "--nx",
            "-se", scylla_exe,
            "-p", scylla_pid,
            "-ex", "set python print-stack full",
            "-ex", "set pagination off",
            "-x", scylla_gdb_py,
            "-x", gdb_utils_py,
            # Print the ready marker once all scripts are loaded so the
            # constructor knows when it is safe to start sending commands.
            "-ex", f'python print("{self.READY_MARKER}")',
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Drain stderr in a background thread to prevent the pipe buffer from
        # filling up and blocking GDB.
        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True,
        )
        self._stderr_thread.start()

        self._wait_for_ready()

    # -- internal helpers ---------------------------------------------------

    def _drain_stderr(self) -> None:
        """Read stderr continuously so the OS pipe buffer never fills up."""
        try:
            for line in self._proc.stderr:
                with self._stderr_lock:
                    self._stderr_lines.append(line)
        except ValueError:
            pass  # pipe closed

    def _wait_for_ready(self) -> None:
        """Block until GDB has finished loading all scripts."""
        while True:
            line = self._proc.stdout.readline()
            if not line:
                with self._stderr_lock:
                    err = "".join(self._stderr_lines)
                raise RuntimeError(
                    f"GDB exited during initialisation.  stderr:\n{err}"
                )
            if self.READY_MARKER in line:
                return

    # -- public API ---------------------------------------------------------

    def execute(self, command: str) -> subprocess.CompletedProcess:
        """Send *command* to GDB and return the result.

        The command is executed via the ``run_cmd()`` helper defined in
        ``gdb_utils.py``.

        Returns:
            A ``CompletedProcess`` with *returncode*, *stdout* and *stderr*
            populated from the structured markers printed by ``run_cmd()``.
        """
        if self._proc.poll() is not None:
            raise RuntimeError("GDB process has already exited")

        # Send the command through the run_cmd() dispatcher.
        self._proc.stdin.write(f"python run_cmd({repr(command)})\n")
        self._proc.stdin.flush()

        return self._read_command_output(command)

    def close(self) -> None:
        """Quit GDB and clean up."""
        if self._proc.poll() is not None:
            return
        try:
            self._proc.stdin.write("quit\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()

    # -- output parsing -----------------------------------------------------

    def _read_command_output(self, command: str) -> subprocess.CompletedProcess:
        """Parse the structured output produced by ``run_cmd()``."""
        rc = 0
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        in_error = False

        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                raise RuntimeError(
                    f"GDB exited while executing: {command}"
                )

            # GDB may prefix lines with its "(gdb) " prompt (no trailing
            # newline, so it gets concatenated with the next write).
            content = self._strip_prompt(raw)

            if self.DONE_MARKER in content:
                break

            if self.RC_PREFIX in content:
                m = re.search(r"===GDB_RC=(\d+)===", content)
                if m:
                    rc = int(m.group(1))
                continue

            if self.ERR_MARKER in content:
                in_error = True
                continue

            # Skip empty / prompt-only lines.
            if not content.strip():
                continue

            if in_error:
                stderr_lines.append(content)
            else:
                stdout_lines.append(content)

        return subprocess.CompletedProcess(
            args=command,
            returncode=rc,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
        )

    @staticmethod
    def _strip_prompt(line: str) -> str:
        """Remove leading ``(gdb) `` prompt fragments from *line*."""
        out = line
        while True:
            stripped = out.lstrip()
            if stripped.startswith("(gdb)"):
                out = stripped[5:]
            else:
                break
        return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope=testpy_test_fixture_scope)
async def scylla_server(testpy_test: PythonTest | None):
    """Return a running Scylla server instance from the active test cluster."""
    async with testpy_test.run_ctx(options=testpy_test.suite.options) as cluster:
        yield next(iter(cluster.running.values()))


@pytest.fixture(scope="module")
def gdb_session(scylla_server, request):
    """Start a persistent GDB session attached to the Scylla process.

    Debug symbols are loaded **once** and the session is reused for every
    ``execute_gdb_command()`` call within the module.  This avoids the
    enormous memory cost of loading multi-GB release debug info for each
    individual test, which previously caused OOM under parallel xdist
    execution.
    """
    scylla_gdb_py = os.path.join(
        request.fspath.dirname, "..", "..", "scylla-gdb.py",
    )
    gdb_utils_py = os.path.join(request.fspath.dirname, "gdb_utils.py")

    session = GDBSession(
        scylla_exe=str(scylla_server.exe),
        scylla_pid=str(scylla_server.cmd.pid),
        scylla_gdb_py=scylla_gdb_py,
        gdb_utils_py=gdb_utils_py,
    )
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def execute_gdb_command(
    gdb_session: GDBSession,
    scylla_command: str | None = None,
    full_command: str | None = None,
) -> subprocess.CompletedProcess:
    """Execute a single GDB command in the persistent session.

    Args:
        gdb_session: ``GDBSession`` instance from the ``gdb_session`` fixture.
        scylla_command: Scylla GDB command name/args (from ``scylla-gdb.py``).
            Mutually exclusive with *full_command*.
        full_command: Raw GDB command string to execute.
            Mutually exclusive with *scylla_command*.

    Returns:
        A ``CompletedProcess`` with *returncode*, *stdout* and *stderr*.
    """
    if full_command:
        return gdb_session.execute(full_command)
    return gdb_session.execute(f"scylla {scylla_command}")
