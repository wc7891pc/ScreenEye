"""检查更新：从 GitHub / Gitee 读取最新发行版信息。

设计要点：
- GitHub 优先用 REST API；API 限流（403）时自动回退到 `releases/latest` 的 302 跳转，
  从跳转地址里解析出版本号，保证"能不能查到新版本"这件事不依赖配额。
- Gitee 用公开 API，无需令牌；能直接拿到发行说明与附件列表。
- 任何网络异常都收进 errors 列表，不抛给界面，避免点了按钮就崩。
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field

GITHUB_REPO = "wc7891pc/ScreenEye"
GITEE_REPO = "zhangjiahang7891/ScreenEye"
TIMEOUT = 8.0
UA = "ScreenEye-Updater/1.0 (+https://github.com/%s)" % GITHUB_REPO

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(text: str) -> tuple[int, int, int]:
    """把 `v1.8` / `V1.8.2` / `release-1.9` 统一成 (1, 8, 0) 方便比较。"""
    found = _VERSION_RE.search(str(text or ""))
    if not found:
        return (0, 0, 0)
    return tuple(int(x or 0) for x in found.groups()[:3])  # type: ignore[return-value]


@dataclass
class ReleaseAsset:
    name: str
    size: int
    url: str


@dataclass
class Release:
    source: str                       # "GitHub" / "Gitee"
    tag: str                          # 原始 tag，如 v1.8
    version: tuple[int, int, int]     # 归一化版本
    name: str = ""
    notes: str = ""
    page_url: str = ""
    assets: list[ReleaseAsset] = field(default_factory=list)

    @property
    def version_text(self) -> str:
        parts = list(self.version)
        while len(parts) > 2 and parts[-1] == 0:
            parts.pop()
        return ".".join(str(x) for x in parts)


def _ssl_context() -> ssl.SSLContext:
    """打包版 Python 有时缺根证书，失败就退回不校验（只读公开版本信息，风险可接受）。"""
    try:
        return ssl.create_default_context()
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


def _open(url: str, *, head: bool = False):
    req = urllib.request.Request(url, method="HEAD" if head else "GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/vnd.github+json")
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context())
    except urllib.error.URLError as exc:
        # 证书问题兜底再试一次（不校验证书）
        if isinstance(getattr(exc, "reason", None), ssl.SSLError):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
        raise


def _json(url: str) -> dict:
    with _open(url) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_github() -> Release:
    """GitHub 最新发行版；API 限流时退化为跳转解析。"""
    api = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        data = _json(api)
        tag = str(data.get("tag_name") or "")
        assets = [
            ReleaseAsset(str(a.get("name")), int(a.get("size") or 0), str(a.get("browser_download_url") or ""))
            for a in (data.get("assets") or [])
        ]
        return Release(
            source="GitHub",
            tag=tag,
            version=parse_version(tag),
            name=str(data.get("name") or tag),
            notes=str(data.get("body") or ""),
            page_url=str(data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"),
            assets=assets,
        )
    except Exception:  # noqa: BLE001  —— 403 限流 / 网络被拦，走下面的跳转方案
        pass

    latest = f"https://github.com/{GITHUB_REPO}/releases/latest"
    with _open(latest, head=True) as resp:
        final = resp.geturl() or ""
    tag = final.rstrip("/").rsplit("/", 1)[-1] if "/tag/" in final else ""
    if not tag:
        raise RuntimeError("GitHub 未返回可用版本号")
    return Release(
        source="GitHub",
        tag=tag,
        version=parse_version(tag),
        name=tag,
        notes="",
        page_url=final or f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
        assets=[],
    )


def fetch_gitee() -> Release:
    """Gitee 最新发行版（公开接口，不带令牌也能读）。"""
    api = f"https://gitee.com/api/v5/repos/{GITEE_REPO}/releases/latest"
    data = _json(api)
    tag = str(data.get("tag_name") or "")
    assets = [
        ReleaseAsset(str(a.get("name")), int(a.get("size") or 0), str(a.get("browser_download_url") or ""))
        for a in (data.get("assets") or [])
    ]
    page = data.get("html_url") or f"https://gitee.com/{GITEE_REPO}/releases/tag/{tag}"
    return Release(
        source="Gitee",
        tag=tag,
        version=parse_version(tag),
        name=str(data.get("name") or tag),
        notes=str(data.get("body") or ""),
        page_url=str(page),
        assets=assets,
    )


def check(current: str, source: str = "auto") -> dict:
    """查询最新版本。

    source: auto / github / gitee
    返回 {"current":..., "latest": Release|None, "releases":{源名: Release}, "errors":[...]}
    """
    out: dict = {
        "current": current,
        "current_version": parse_version(current),
        "latest": None,
        "releases": {},
        "errors": [],
    }
    jobs = {
        "github": [("GitHub", fetch_github)],
        "gitee": [("Gitee", fetch_gitee)],
        "auto": [("GitHub", fetch_github), ("Gitee", fetch_gitee)],
    }.get((source or "auto").lower(), [("GitHub", fetch_github), ("Gitee", fetch_gitee)])

    for label, fn in jobs:
        try:
            rel = fn()
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{label}：{type(exc).__name__}: {exc}")
            continue
        out["releases"][label] = rel
        if rel.version > (0, 0, 0):
            best = out["latest"]
            if best is None or rel.version > best.version:
                out["latest"] = rel

    return out


def pretty_size(num: int) -> str:
    if num <= 0:
        return ""
    if num >= 1024 * 1024:
        return f"{num / 1048576:.1f} MB"
    return f"{num / 1024:.0f} KB"
