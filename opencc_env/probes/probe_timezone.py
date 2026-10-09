"""读取本机时区；时区信息不用于判断账号风险，也不自动改为其他地区。"""
from datetime import datetime
from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status
from opencc_env.core.windows import read_timezone


class TimezoneProbe(BaseProbe):
    id = "probe_timezone"
    name = "本机时区"
    category = "System"
    level = Severity.INFO

    def run_check(self):
        try:
            current = read_timezone()
            offset = datetime.now().astimezone().utcoffset()
            minutes = int(offset.total_seconds() / 60) if offset is not None else None
            utc = "未知" if minutes is None else "UTC" + ("+" if minutes >= 0 else "-") + f"{abs(minutes)//60:02d}:{abs(minutes)%60:02d}"
            return CheckResult(self.id, self.name, self.category, Status.INFO, None,
                "已读取本机时区", current + " · " + utc,
                details={"current_timezone": current, "utc_offset": utc, "source": "Windows tzutil /g"},
                remedy_guide="此处展示实际系统设置；不以时区名称推断所在地或账号封禁概率。")
        except Exception as exc:
            return CheckResult(self.id, self.name, self.category, Status.ERROR, None,
                               "时区读取失败", "未取得有效时区，不能按正常状态显示。", details={"error": str(exc)})
