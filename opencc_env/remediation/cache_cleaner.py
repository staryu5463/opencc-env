"""仅隔离桌面渲染缓存；不强杀进程、不永久删除、不清理 CLI 数据。"""
import os
import shutil
import uuid
from pathlib import Path
from opencc_env.core.backup import BackupManager
from opencc_env.core.windows import run_command, no_reparse_path


class CacheCleaner:
    @staticmethod
    def is_claude_running():
        result = run_command(["tasklist","/FI","IMAGENAME eq claude.exe","/NH"])
        if result.returncode:
            raise OSError("未能确认 Claude 进程状态")
        return "claude.exe" in result.stdout.lower()

    @staticmethod
    def get_cache_directories():
        roaming = Path(os.environ.get("APPDATA",""))
        local = Path(os.environ.get("LOCALAPPDATA",""))
        return [str(base/name) for base in (roaming/"Claude",roaming/"AnthropicClaude",local/"AnthropicClaude")
                for name in ("Cache","Code Cache","GPUCache","DawnWebGPUCache")]

    @staticmethod
    def scan_cache_size():
        total,files,existing,errors = 0,0,[],[]
        for folder in CacheCleaner.get_cache_directories():
            path = Path(folder)
            if not path.is_dir():
                continue
            existing.append(folder)
            try:
                no_reparse_path(path)
                for root,dirs,names in os.walk(path,followlinks=False):
                    dirs[:] = [d for d in dirs if not Path(root,d).is_symlink() and not getattr(Path(root,d).lstat(),"st_file_attributes",0)&0x400]
                    for name in names:
                        item = Path(root,name)
                        if not item.is_symlink():
                            total += item.stat().st_size
                            files += 1
            except (OSError,ValueError) as exc:
                errors.append(str(exc))
        return {"total_size_bytes":total,"total_size_mb":round(total/1048576,2),"total_files":files,"existing_dirs":existing,"errors":errors}

    @staticmethod
    def clean_cache():
        moved = []
        try:
            if CacheCleaner.is_claude_running():
                return False,"请先关闭 Claude 客户端；本工具不会强制结束会话"
            paths = [no_reparse_path(p) for p in CacheCleaner.get_cache_directories() if Path(p).is_dir()]
            if not paths:
                return True,"未发现这些缓存目录；未据此判断白屏恢复"
            quarantine = no_reparse_path(Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"OpenCC-Env/quarantine"/uuid.uuid4().hex)
            moves = [{"source":str(p),"destination":str(quarantine/(str(i)+"-"+p.name))} for i,p in enumerate(paths)]
            if not BackupManager.save_snapshot("cache",{"moves":moves}):
                return False,"快照保存失败，停止隔离缓存"
            quarantine.mkdir(parents=True,exist_ok=False)
            for move in moves:
                shutil.move(move["source"],move["destination"])
                moved.append(move)
                if Path(move["source"]).exists() or not Path(move["destination"]).is_dir():
                    raise OSError("目录移动复查失败")
            return True,f"已隔离并核对 {len(moves)} 处缓存，可在操作历史中还原；白屏效果未验证"
        except Exception as exc:
            errors = []
            for move in reversed(moved):
                try:
                    if Path(move["source"]).exists():
                        raise OSError("原路径已有新内容")
                    shutil.move(move["destination"],move["source"])
                except OSError as rollback_exc:
                    errors.append(str(rollback_exc))
            return False,"缓存隔离未完成："+str(exc)+("；撤回存在错误："+"；".join(errors) if errors else "；已撤回已移动目录")
