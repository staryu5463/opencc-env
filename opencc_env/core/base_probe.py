"""统一检测状态；信息项与不适用项不参与配置评分。"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class Status(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    ERROR = "ERROR"
    INFO = "INFO"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class CheckResult:
    probe_id: str
    probe_name: str
    category: str
    status: Status
    score: int | None
    title: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    remedy_title: str = ""
    remedy_guide: str = ""
    auto_fixable: bool = False


class BaseProbe:
    id = "base_probe"
    name = "基础检测"
    category = "General"
    level = Severity.MEDIUM
    auto_fixable = False

    def run_check(self) -> CheckResult:
        raise NotImplementedError

    def run_fix(self) -> tuple[bool, str]:
        return False, "此项仅提供检测，请查看具体说明。"
