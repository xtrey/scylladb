import logging
import platform
from pathlib import Path

from attrs import define, field
from test.pylib.db.model import TestMetricRecord


@define
class ResourceGather:
    test_metrics: TestMetricRecord = field(init=False, default=TestMetricRecord())
    test = field(init=True)
    cgroup_path: Path = field(init=True)

    def get_test_metrics(self) -> TestMetricRecord:
        self.test_metrics.test_name = self.test.uname
        self.test_metrics.mode = self.test.mode
        self.test_metrics.architecture = platform.machine()
        with open(self.cgroup_path / 'memory.peak', 'r') as file:
            self.test_metrics.memory_usage_highest = file.read()
        with open(self.cgroup_path / 'cpu.stat', 'r') as file:
            for line in file.readlines():
                if line.startswith('user_usec'):
                    self.test_metrics.cpu_usage_user = line.split(' ')[1]
                if line.startswith('system_usec'):
                    self.test_metrics.cpu_usage_system = line.split(' ')[1]

        return self.test_metrics
