"""逐次保存快照，原子写入；旧版快照仅供查看，拒绝未经核验的还原。"""
import base64
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencc_env.core.windows import no_reparse_path, notify_environment_change, read_shortcut, read_timezone, run_command, write_shortcut

SNAPSHOT_PATH = os.path.expanduser(r"~\.opencc_env_snapshot.json")


class BackupManager:
    SNAPSHOT_PATH = SNAPSHOT_PATH
    _lock = threading.RLock()

    @classmethod
    def _read(cls):
        path = Path(cls.SNAPSHOT_PATH)
        if not path.exists():
            return {"schema_version": 2, "entries": []}
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("快照文件结构无效")
        if raw.get("schema_version") == 2:
            if not isinstance(raw.get("entries"), list):
                raise ValueError("快照记录无效")
            return raw
        entries = []
        for key, value in raw.items():
            if isinstance(value, dict) and "data" in value:
                entries.append({"id": "legacy-" + key, "key": key, "timestamp": value.get("timestamp", ""),
                                "data": value["data"], "origin": "legacy", "restorable": False})
        return {"schema_version": 2, "entries": entries}

    @classmethod
    def get_history(cls):
        with cls._lock:
            return list(cls._read()["entries"])

    @classmethod
    def load_snapshots(cls):
        latest = {}
        for entry in cls.get_history():
            latest[entry["key"]] = entry
        return latest

    get_all_snapshots = load_snapshots

    @classmethod
    def save_snapshot(cls, key: str, data: Any):
        with cls._lock:
            temporary = None
            try:
                document = cls._read()
                document["entries"].append({"id": uuid.uuid4().hex, "key": key,
                    "timestamp": datetime.now(timezone.utc).isoformat(), "data": data,
                    "origin": "opencc-env/2", "restorable": True})
                path = no_reparse_path(cls.SNAPSHOT_PATH)
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                                 dir=path.parent, prefix=".opencc-", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(document, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                return True
            except (OSError, ValueError, TypeError):
                return False
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()

    @classmethod
    def get_snapshot(cls, key, snapshot_id=None):
        entries = [e for e in cls.get_history() if e["key"] == key and (snapshot_id is None or e["id"] == snapshot_id)]
        return entries[-1]["data"] if entries else None

    @classmethod
    def has_snapshot(cls, key):
        return key in cls.load_snapshots()

    @classmethod
    def _trusted(cls, key, snapshot_id=None):
        entries = [e for e in cls.get_history() if e["key"] == key and (snapshot_id is None or e["id"] == snapshot_id)]
        if not entries:
            raise ValueError("没有对应快照")
        entry = entries[-1]
        if not entry.get("restorable") or entry.get("origin") != "opencc-env/2":
            raise ValueError("旧版快照未经核验，已保留供查看；不能用于自动还原")
        return entry["data"]

    @classmethod
    def rollback_timezone(cls, snapshot_id=None):
        try:
            value = cls._trusted("timezone", snapshot_id)
            target = value["timezone"] if isinstance(value, dict) else value
            if not isinstance(target, str) or not target:
                raise ValueError("快照时区无效")
            result = run_command(["tzutil", "/s", target])
            if result.returncode or read_timezone() != target:
                return False, "时区还原未通过复查"
            return True, "时区已还原并读取确认"
        except Exception as exc:
            return False, "时区还原未完成：" + str(exc)

    @classmethod
    def rollback_shortcut(cls, snapshot_id=None):
        try:
            snap = cls._trusted("shortcut", snapshot_id)
            path = no_reparse_path(snap["path"])
            if not snap.get("existed", True):
                # 新建入口仅在它仍是本工具写入的版本时移除。
                if not path.exists():
                    return True, "新建入口已不存在"
                if read_shortcut(path).get("arguments") != snap.get("after_arguments"):
                    raise ValueError("快捷方式后来发生变化，停止自动还原")
                path.unlink()
                return not path.exists(), "已撤销本工具新建的入口"
            info = snap.get("info") or {"target_path": snap.get("target_path") or snap.get("target"),
                                        "arguments": snap.get("arguments", "")}
            if not info.get("target_path"):
                raise ValueError("快照没有有效启动目标")
            if not path.exists():
                raise ValueError("原快捷方式已不存在，停止自动还原")
            if snap.get("after_arguments") is not None and read_shortcut(path).get("arguments") != snap["after_arguments"]:
                raise ValueError("快捷方式后来发生变化，停止自动还原")
            if not write_shortcut(path, info):
                return False, "快捷方式还原未通过属性复查"
            return True, "快捷方式已还原并核对启动目标与参数"
        except Exception as exc:
            return False, "快捷方式还原未完成：" + str(exc)

    @classmethod
    def rollback_cli_settings(cls, snapshot_id=None):
        try:
            snap = cls._trusted("cli_settings", snapshot_id)
            path = no_reparse_path(snap["path"])
            expected = snap["after_sha256"]
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("配置文件后来发生变化，停止还原以避免覆盖新配置")
            if snap["existed"]:
                original = base64.b64decode(snap["content_base64"], validate=True)
                atomic_bytes(path, original)
                if path.read_bytes() != original:
                    return False, "配置还原后内容核对失败"
            else:
                path.unlink()
                if path.exists():
                    return False, "未能撤销新建配置"
            return True, "Claude 用户设置已还原；现有会话需重启以读取配置"
        except Exception as exc:
            return False, "配置还原未完成：" + str(exc)

    @classmethod
    def rollback_cli_env(cls, snapshot_id=None):
        """兼容新格式的旧功能；保持缺失、空值和注册表类型的区别。"""
        import winreg
        try:
            snap = cls._trusted("cli_env", snapshot_id)
            if not all(isinstance(snap.get(k), dict) for k in ("HTTP_PROXY", "HTTPS_PROXY")):
                raise ValueError("快照缺少环境变量类型与存在状态")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
                for name in ("HTTP_PROXY", "HTTPS_PROXY"):
                    item = snap[name]
                    if item["exists"]:
                        winreg.SetValueEx(key, name, 0, item["type"], item["value"])
                    else:
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                for name in ("HTTP_PROXY", "HTTPS_PROXY"):
                    item = snap[name]
                    try:
                        actual, kind = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        if item["exists"]:
                            raise ValueError("环境变量还原后仍不存在")
                    else:
                        if not item["exists"] or actual != item["value"] or kind != item["type"]:
                            raise ValueError("环境变量还原后不匹配")
            notify_environment_change()
            return True, "用户环境变量已还原并复查；已运行程序的环境不会自动刷新"
        except Exception as exc:
            return False, "环境变量还原未完成：" + str(exc)

    @classmethod
    def rollback_cache(cls, snapshot_id=None):
        try:
            snap = cls._trusted("cache", snapshot_id)
            from opencc_env.remediation.cache_cleaner import CacheCleaner
            if CacheCleaner.is_claude_running():
                raise ValueError("请先关闭 Claude 客户端再还原缓存")
            moves = snap["moves"]
            # 先检查全部冲突，避免只还原一部分。
            for move in moves:
                source, destination = no_reparse_path(move["source"]), no_reparse_path(move["destination"])
                if source.exists() or not destination.is_dir():
                    raise ValueError("缓存已重新生成或隔离目录缺失，停止还原：" + str(source))
            for move in reversed(moves):
                shutil.move(move["destination"], move["source"])
            if not all(Path(m["source"]).is_dir() and not Path(m["destination"]).exists() for m in moves):
                return False, "缓存还原未通过目录复查"
            return True, "隔离的缓存目录已还原；客户端显示效果需另行验证"
        except Exception as exc:
            return False, "缓存还原未完成：" + str(exc)

    @classmethod
    def rollback_startup(cls, snapshot_id=None):
        import winreg
        from opencc_env.remediation.startup_fixer import StartupFixer
        try:
            snap = cls._trusted("startup", snapshot_id)
            entries = snap["entries"]
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, StartupFixer.REG_PATH, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                for item in entries:
                    try:
                        winreg.QueryValueEx(key, item["name"])
                    except FileNotFoundError:
                        continue
                    raise ValueError("同名自启动项已经存在，停止还原")
                for item in entries:
                    winreg.SetValueEx(key, item["name"], 0, item["type"], item["command"])
                for item in entries:
                    if winreg.QueryValueEx(key, item["name"]) != (item["command"], item["type"]):
                        raise ValueError("自启动项还原后不匹配")
            return True, "所选当前用户 Run 启动项已还原并复查"
        except Exception as exc:
            return False, "自启动项还原未完成：" + str(exc)


def atomic_bytes(path, content):
    path = no_reparse_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".opencc-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
