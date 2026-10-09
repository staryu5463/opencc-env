"""工作台偏好，只保存界面状态；测试可通过路径完全隔离。"""
import json
import os
from pathlib import Path


class Preferences:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OpenCC-Env" / "interface.json"
        try:
            self.values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}

    def save(self, values):
        from opencc_env.core.backup import atomic_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(self.path, (json.dumps(values, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        self.values = values
