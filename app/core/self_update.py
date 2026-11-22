"""自动更新：下载发行版压缩包 → 备份旧的 app/ → 就地替换 → 重启生效。

只替换 `app/`（程序逻辑）和 `assets/`（图标等静态资源），
`runtime/`（便携 Python）和 `data/`（规则、模板、日志、设置）完全不动，
因此升级不会丢规则。替换前会把旧 `app/` 挪到 `data/_update_backup/`，失败可回滚。
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from core.updater import Release, ReleaseAsset
from config import BASE_DIR

TIMEOUT = 20.0
UA = "ScreenEye-Updater/1.0"
TARGET_DIRS = ("app", "assets")     # 只替换这两块
STAGE_PREFIX = "ScreenEyeUpd_"


# ----------------------------------------------------------------------
# 选包
# ----------------------------------------------------------------------
def pick_package(release: Release | None) -> ReleaseAsset | None:
    """挑一个可用来升级的 zip：优先源码包，其次小体积包，最后才考虑整包。"""
    if release is None:
        return None
    zips = [a for a in release.assets if a.url and a.name.lower().endswith(".zip")]
    if not zips:
        return None
    prefer = [a for a in zips if ("源码" in a.name) or ("source" in a.name.lower())]
    if prefer:
        return min(prefer, key=lambda a: a.size or 1 << 62)
    exact = [a for a in zips if "part" not in a.name.lower()]
    if exact:
        return exact[0]
    return None            # 只有分卷，不自作主张拼包


# ----------------------------------------------------------------------
# 下载
# ----------------------------------------------------------------------
def download(url: str, dest: Path, progress=None, cancel=None) -> Path:
    """流式下载，progress(已下载字节, 总字节) 回调，cancel() 返回 True 时中止。"""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp, dest.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            if cancel and cancel():
                raise RuntimeError("已取消下载")
            chunk = resp.read(262144)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    return dest


# ----------------------------------------------------------------------
# 安装
# ----------------------------------------------------------------------
def _find_base(names: list[str]) -> str | None:
    for n in names:
        p = n.replace("\\", "/")
        if p.endswith("app/main.py"):
            return p[: -len("app/main.py")]
    return None


def inspect_zip(zip_path: Path) -> dict:
    """返回 {ok, base, dirs, files, reason}，供界面提前告知能否自动安装。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"压缩包无法打开：{exc}"}
    base = _find_base(names)
    if base is None:
        return {"ok": False, "reason": "压缩包里没有找到 app/main.py，不是本程序的发行包"}
    dirs = [d for d in TARGET_DIRS if any(n.replace("\\", "/").startswith(base + d + "/") for n in names)]
    return {"ok": True, "base": base, "dirs": dirs, "reason": ""}


def install(zip_path: Path, root: Path, version: str = "") -> tuple[bool, str]:
    """把 zip 里的 app/、assets/ 替换到 root。返回 (是否成功, 说明)。"""
    info = inspect_zip(zip_path)
    if not info.get("ok"):
        return False, str(info.get("reason"))
    base = info["base"]
    staging = root / f"{STAGE_PREFIX}{int(time.time())}"
    backup_root = root / "data" / "_update_backup"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / stamp

    safe = True
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            norm = name.replace("\\", "/")
            if not norm.startswith(base):
                continue
            rel = norm[len(base):]
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                if rel:
                    safe = False
                continue
            if not rel.startswith(tuple(d + "/" for d in TARGET_DIRS)):
                continue
            target = (staging / rel).resolve()
            if not str(target).startswith(str(staging.resolve())):
                safe = False
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if norm.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                with zf.open(name) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    if not safe:
        shutil.rmtree(staging, ignore_errors=True)
        return False, "压缩包内含非法路径，已中止安装"

    new_app = staging / "app"
    if not (new_app / "main.py").exists():
        shutil.rmtree(staging, ignore_errors=True)
        return False, "解压后缺少 app/main.py，已中止安装"

    moved: list[tuple[Path, Path]] = []
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for d in info["dirs"]:
            src_new = staging / d
            if not src_new.exists():
                continue
            dst_old = root / d
            if dst_old.exists():
                bak = backup_dir / d
                shutil.move(str(dst_old), str(bak))
                moved.append((dst_old, bak))
            shutil.move(str(src_new), str(dst_old))
        (backup_root / "last_update.json").write_text(
            json.dumps(
                {"version": version, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "backup": str(backup_dir)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        # 回滚：把已经挪走的旧目录搬回去
        for dst_old, bak in moved:
            try:
                if dst_old.exists():
                    shutil.rmtree(dst_old, ignore_errors=True)
                if bak.exists():
                    shutil.move(str(bak), str(dst_old))
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(staging, ignore_errors=True)
        return False, f"替换文件失败，已回滚：{exc}"
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return True, f"已更新到 v{version}，旧版本备份在 {backup_dir}"


# ----------------------------------------------------------------------
# 重启
# ----------------------------------------------------------------------
def restart_app() -> tuple[bool, str]:
    """拉起新进程后由调用方退出当前进程。打包成 EXE 时也能用。"""
    try:
        root = Path(BASE_DIR)
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable], cwd=str(root), close_fds=True)
            return True, "已启动新版本"
        # 源码 / 便携版：优先用 pythonw，避免升级后残留一个黑框
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
        script = Path(sys.argv[0])
        if not script.is_absolute():
            script = Path.cwd() / script
        if not script.exists():                 # 从别的目录启动时兜底
            script = root / "app" / "main.py"
        subprocess.Popen([str(exe), str(script)], cwd=str(root), close_fds=True)
        return True, "已启动新版本"
    except Exception as exc:  # noqa: BLE001
        return False, f"自动重启失败，请手动启动：{exc}"


def supported() -> bool:
    """EXE 版不能靠替换 app/ 生效（代码已打进 exe），只能整包替换。"""
    return not getattr(sys, "frozen", False)


def cleanup_old_backups(root: Path, keep: int = 2) -> None:
    """只保留最近几次备份，避免占地方。"""
    backup_root = root / "data" / "_update_backup"
    if not backup_root.exists():
        return
    items = sorted([p for p in backup_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    for p in items[:-keep]:
        shutil.rmtree(p, ignore_errors=True)
