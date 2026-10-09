"""状态优先的审计引擎，评分仅描述已检测的配置，不代表账号风险。"""
import importlib
import pkgutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from opencc_env.core.base_probe import BaseProbe, CheckResult, Severity, Status

SEVERITY_WEIGHTS = {Severity.CRITICAL: 35, Severity.HIGH: 25, Severity.MEDIUM: 15, Severity.LOW: 10, Severity.INFO: 0}
BUILTIN_MODULES = ("probe_network", "probe_timezone", "probe_shortcut", "probe_proxy_rules", "probe_leak", "probe_cli_settings")


class AuditEngine:
    def __init__(self):
        self.probes = []
        self.results = {}
        self.overall_score = None
        self.risk_level = "NOT_CHECKED"
        self.metrics = {}
        self.discovery_errors = []
        self._operation_lock = threading.Lock()

    def register_probe(self, probe):
        if any(item.id == probe.id for item in self.probes):
            raise ValueError("重复的检测 ID：" + probe.id)
        self.probes.append(probe)

    def auto_discover_probes(self, probes_dir=None):
        import opencc_env.probes as package
        modules = set(BUILTIN_MODULES)
        for item in pkgutil.iter_modules([probes_dir] if probes_dir else package.__path__):
            if item.name.startswith("probe_"):
                modules.add(item.name)
        self.discovery_errors = []
        for name in sorted(modules):
            try:
                module = importlib.import_module("opencc_env.probes." + name)
                for obj in vars(module).values():
                    if isinstance(obj, type) and issubclass(obj, BaseProbe) and obj is not BaseProbe and obj.__module__ == module.__name__:
                        instance = obj()
                        if not any(p.id == instance.id for p in self.probes):
                            self.register_probe(instance)
            except Exception as exc:
                self.discovery_errors.append(name + ": " + str(exc))

    def _checked(self, probe):
        try:
            result = probe.run_check()
            if not isinstance(result, CheckResult) or result.probe_id != probe.id:
                raise ValueError("检测返回值不符合约定")
            if result.score is not None and (isinstance(result.score, bool) or not 0 <= result.score <= 100):
                raise ValueError("检测得分超出范围")
            return result
        except Exception as exc:
            return CheckResult(probe.id, probe.name, probe.category, Status.ERROR, None,
                               "未能完成检测", str(exc), details={"error": str(exc)})

    def run_all(self, max_workers=4, on_result=None):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("已有检测或修复正在进行")
        started = time.monotonic()
        try:
            self.results.clear()
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(self._checked, p): p for p in self.probes}
                for future in as_completed(futures):
                    probe = futures[future]
                    self.results[probe.id] = future.result()
                    if on_result:
                        on_result(self.results[probe.id])
            self._compute_overall_metrics()
            return {**self.metrics, "results": dict(self.results),
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_seconds": round(time.monotonic() - started, 2)}
        finally:
            self._operation_lock.release()

    def _compute_overall_metrics(self):
        applicable = [(p, self.results.get(p.id)) for p in self.probes
                      if p.level != Severity.INFO and
                      (self.results.get(p.id) is None or self.results[p.id].status not in (Status.INFO, Status.NOT_APPLICABLE))]
        total = sum(SEVERITY_WEIGHTS[p.level] for p, _ in applicable)
        incomplete = bool(self.discovery_errors) or any(r.status == Status.ERROR for r in self.results.values()) or any(r is None or r.status == Status.ERROR or r.score is None for _, r in applicable)
        known_sum = sum(r.score * SEVERITY_WEIGHTS[p.level] for p, r in applicable if r and r.score is not None and r.status != Status.ERROR)
        self.overall_score = int(known_sum / total) if total and not incomplete else None
        results = list(self.results.values())
        if not self.probes or not results:
            self.risk_level = "NOT_CHECKED"
        elif incomplete or any(r.status == Status.ERROR for r in results):
            self.risk_level = "INCOMPLETE"
        elif any(r.status == Status.FAIL for r in results):
            self.risk_level = "ISSUES"
        elif any(r.status == Status.WARN for r in results):
            self.risk_level = "ATTENTION"
        else:
            self.risk_level = "READY"
        rows = []
        for p in self.probes:
            r = self.results.get(p.id)
            included = any(p is item[0] for item in applicable)
            weight = SEVERITY_WEIGHTS[p.level] if included else 0
            percent = 100 * weight / total if total else 0
            deduction = (100 - r.score) * weight / total if included and total and r and r.score is not None and r.status != Status.ERROR else None
            rows.append({"probe_id": p.id, "name": p.name, "weight": weight,
                         "weight_percent": percent, "score": r.score if r else None,
                         "deduction": deduction, "included": included,
                         "reason": "参与配置评分" if included else "信息或不适用项目，不计分"})
        counts = {status.value: sum(r.status == status for r in results) for status in Status}
        self.metrics = {"overall_score": self.overall_score, "risk_level": self.risk_level,
                        "scoring": rows, "counts": counts, "discovery_errors": list(self.discovery_errors),
                        "model_note": "自定义配置参考评分；不是封号概率。失败和未完成状态优先于总分。"}

    def run_fix_single(self, probe_id):
        if not self._operation_lock.acquire(blocking=False):
            return False, "已有检测或修复正在进行"
        try:
            probe = next((p for p in self.probes if p.id == probe_id), None)
            previous = self.results.get(probe_id)
            if not probe or not probe.auto_fixable or not previous or not previous.auto_fixable:
                return False, "此项目当前不能自动修改"
            try:
                ok, message = probe.run_fix()
                actual = self._checked(probe)
                self.results[probe_id] = actual
                self._compute_overall_metrics()
                if not ok:
                    return False, message
                if actual.status != Status.PASS:
                    return False, message + "；复查尚未通过：" + actual.title
                return True, message + "；配置复查通过"
            except Exception as exc:
                return False, "修复未完成：" + str(exc)
        finally:
            self._operation_lock.release()

    def run_fix_all(self, selected_ids=None):
        if selected_ids is None:
            return [{"success": False, "message": "请先选择并确认要修改的项目"}]
        reports = []
        for pid in selected_ids:
            probe = next((p for p in self.probes if p.id == pid), None)
            ok, message = self.run_fix_single(pid)
            reports.append({"probe_id": pid, "probe_name": probe.name if probe else pid, "success": ok, "message": message})
        return reports
