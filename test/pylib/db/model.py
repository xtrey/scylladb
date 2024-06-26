from attrs import define, field


@define(init=False)
class TestMetricRecord:

    # id: int = field(default=0)
    architecture: str = field(default='')
    mode: str = field(default='')
    test_name: str = field(default='')
    cpu_usage_user: int = field(default=0)
    cpu_usage_system: int = field(default=0)
    memory_usage_highest: int = field(default=0)
