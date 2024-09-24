from pathlib import PosixPath, Path

import yaml
from _pytest.nodes import Collector

from test.pylib.cpp.item import CppFile

all_modes = {'debug': 'Debug',
             'release': 'RelWithDebInfo',
             'dev': 'Dev',
             }

def pytest_addoption(parser):
    parser.addoption('--mode', action='store', required=True,
                     help='Scylla build mode. Tests can use it to adjust their behavior.')
    parser.addoption(
        "--tmpdir",
        action="store",
        default="testlog",
        help="""Path to temporary test data and log files. The data is
            further segregated per build mode. Default: ./testlog.""",
    )

def read_suite_config():
    with open(Path(__file__).resolve().parent / 'suite.yaml', "r") as cfg_file:
        cfg = yaml.safe_load(cfg_file.read())
        if not isinstance(cfg, dict):
            raise RuntimeError("Failed to load tests in {}: suite.yaml is empty")
        return cfg

def pytest_collect_file(file_path: PosixPath, parent: Collector):
    config = parent.config
    suite_config = read_suite_config()
    mode = config.getoption('mode')
    disabled_tests = set(suite_config.get("disable", []))
    disabled_tests.update(suite_config.get("skip_in_" + mode, []))
    run_in_m = set(suite_config.get("run_in_" + mode, []))

    for a in all_modes:
        if a == mode:
            continue
        skip_in_m = set(suite_config.get("run_in_" + a, []))
        disabled_tests.update(skip_in_m - run_in_m)
    args = [
        "--",
        '--overprovisioned',
        '--unsafe-bypass-fsync 1',
        '--kernel-page-cache 1',
        '--blocked-reactor-notify-ms 2000000',
        '--collectd 0',
        '--max-networking-io-control-blocks=100',
    ]
    custom_args = suite_config.get("custom_args", {})
    if file_path.suffix == ".cc" and '.inc' not in file_path.suffixes:
        no_parallel_run = False
        test_name = file_path.stem
        if test_name in disabled_tests:
            return None
        if test_name in suite_config.get('no_parallel_cases'):
            no_parallel_run = True
        project_root = Path(__file__).resolve().parent.parent.parent
        executable = Path(f'{project_root}/build/{mode}/test/boost') / file_path.stem
        temp_dir = project_root / config.getoption('tmpdir')

        args.extend(custom_args.get(file_path.stem, ['-c2', '-m2G']))
        args = [' '.join(args)]
        return CppFile.from_parent(parent=parent, mode=mode, temp_dir=temp_dir, executable=executable, arguments=args, no_parallel_run=no_parallel_run, path=file_path)
