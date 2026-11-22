"""检查更新对话框：查询 GitHub / Gitee 最新版本，可一键下载并自动安装。"""
from __future__ import annotations

import tempfile
import webbrowser
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from config import APP_NAME, APP_VERSION, BASE_DIR, REPO_HOME, REPO_MIRROR
from core import self_update, updater


class CheckWorker(QThread):
    """后台查版本，避免点按钮时界面假死（网络不通要等超时）。"""

    done = Signal(object)

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self._source = source

    def run(self) -> None:
        self.done.emit(updater.check(APP_VERSION, self._source))


class ApplyWorker(QThread):
    """下载更新包 → 校验 → 就地替换 app/，全程在后台跑。"""

    progress = Signal(int, int)      # 已下载字节, 总字节
    status = Signal(str)
    ok = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, file_name: str, version: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._file_name = file_name
        self._version = version

    def run(self) -> None:
        try:
            if not self_update.supported():
                raise RuntimeError("当前是 EXE 打包版，无法只替换 app/，请下载整包替换")
            tmp_dir = Path(tempfile.gettempdir()) / "ScreenEye_update"
            dest = tmp_dir / (self._file_name or "update.zip")
            self.status.emit(f"正在下载 {self._file_name} …")
            self_update.download(
                self._url,
                dest,
                progress=lambda got, total: self.progress.emit(got, total),
                cancel=lambda: self.isInterruptionRequested(),
            )
            self.status.emit("下载完成，正在校验压缩包 …")
            ok, msg = self_update.install(dest, Path(BASE_DIR), self._version)
            if not ok:
                raise RuntimeError(msg)
            self_update.cleanup_old_backups(Path(BASE_DIR))
            try:
                dest.unlink()
            except Exception:  # noqa: BLE001
                pass
            self.ok.emit(msg)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def _mb(num: int) -> str:
    return f"{num / 1048576:.1f} MB" if num >= 1048576 else f"{num / 1024:.0f} KB"


def _size_hint(asset) -> str:
    """Gitee 接口有时不返回附件大小，这时不要显示一对空括号。"""
    size = getattr(asset, "size", 0) or 0
    return f"（{updater.pretty_size(size)}）" if size > 0 else ""


class UpdateDialog(QDialog):
    def __init__(self, result: dict | None = None, parent=None, source: str = "auto"):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · 检查更新")
        self.resize(780, 560)
        self._result = result or {}
        self._source = source
        self._worker: CheckWorker | None = None
        self._apply: ApplyWorker | None = None
        self._asset = None
        self._build()
        if result:
            self._render(result)
        else:
            self._start_check()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        self.lbl_head = QLabel("当前版本 v%s" % APP_VERSION)
        self.lbl_head.setStyleSheet("font-size:16px;font-weight:600;")
        lay.addWidget(self.lbl_head)

        self.lbl_status = QLabel("正在检查…")
        self.lbl_status.setObjectName("Muted")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.txt_notes = QPlainTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setPlaceholderText("这里会显示新版本的更新说明")
        lay.addWidget(self.txt_notes, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        self.lbl_links = QLabel("")
        self.lbl_links.setObjectName("Muted")
        self.lbl_links.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_links.setWordWrap(True)
        lay.addWidget(self.lbl_links)

        row = QHBoxLayout()
        self.btn_check = QPushButton("重新检查")
        self.btn_check.clicked.connect(self._start_check)
        self.btn_gh = QPushButton("GitHub 发行页")
        self.btn_gh.clicked.connect(lambda: webbrowser.open(self._page("GitHub", REPO_HOME + "/releases")))
        self.btn_gitee = QPushButton("Gitee 发行页")
        self.btn_gitee.clicked.connect(lambda: webbrowser.open(self._page("Gitee", REPO_MIRROR + "/releases")))
        self.btn_apply = QPushButton("自动下载并安装")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self._auto_install)
        self.btn_download = QPushButton("只打开下载链接")
        self.btn_download.clicked.connect(self._download)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setObjectName("Ghost")
        self.btn_close.clicked.connect(self._on_close)

        row.addWidget(self.btn_check)
        row.addWidget(self.btn_gh)
        row.addWidget(self.btn_gitee)
        row.addStretch(1)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_download)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        for b in (self.btn_gh, self.btn_gitee, self.btn_download, self.btn_apply):
            b.setEnabled(False)
        if not self_update.supported():
            self.btn_apply.setToolTip("EXE 打包版无法只替换 app/，请下载整包")

    # ------------------------------------------------------------------
    def _start_check(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_check.setEnabled(False)
        self.lbl_status.setText("正在连接 GitHub / Gitee 检查更新…")
        self.lbl_head.setText("当前版本 v%s" % APP_VERSION)
        self._worker = CheckWorker(self._source, self)
        self._worker.done.connect(self._on_checked)
        self._worker.start()

    def _on_checked(self, result: object) -> None:
        self.btn_check.setEnabled(True)
        self._result = result if isinstance(result, dict) else {}
        self._render(self._result)

    def _page(self, source: str, fallback: str) -> str:
        rel = (self._result.get("releases") or {}).get(source)
        return getattr(rel, "page_url", "") or fallback

    def _render(self, result: dict) -> None:
        current = result.get("current_version") or (0, 0, 0)
        latest = result.get("latest")
        releases = result.get("releases") or {}
        errors = result.get("errors") or []

        lines = []
        wanted = {
            "auto": ("GitHub", "Gitee"),
            "github": ("GitHub",),
            "gitee": ("Gitee",),
        }.get((self._source or "auto").lower(), ("GitHub", "Gitee"))
        for label in wanted:
            rel = releases.get(label)
            if rel is None:
                lines.append(f"{label}：未取到（网络不通或被限流）")
            else:
                lines.append(f"{label}：最新 v{rel.version_text}（{rel.tag}）")
        self.lbl_links.setText("　|　".join(lines))

        if latest is not None and latest.version > current:
            self.lbl_head.setText(
                "发现新版本 v%s　→　当前 v%s" % (latest.version_text, result.get("current") or APP_VERSION)
            )
            self.lbl_head.setStyleSheet("font-size:16px;font-weight:600;color:#2dd4bf;")
            self._asset = self_update.pick_package(latest)
            if self._asset is None:
                # 该源只有分卷/没有资产时，退到 Gitee 的源码包
                self._asset = self_update.pick_package(releases.get("Gitee"))
            if self._asset is not None and self_update.supported():
                self.lbl_status.setText(
                    "可以直接点「自动下载并安装」：下载 %s%s，校验后替换 app/ 并重启。"
                    "规则、模板、日志和便携 Python 都不会动，旧版本会留一份备份。"
                    % (self._asset.name, _size_hint(self._asset))
                )
                self.btn_apply.setEnabled(True)
            elif not self_update.supported():
                self.lbl_status.setText("当前是打包版 EXE，请用「只打开下载链接」下载整包替换。")
            else:
                self.lbl_status.setText(
                    "该版本只有分卷压缩包，无法一键安装，请用「只打开下载链接」手动下载全部卷。"
                )
            notes = latest.notes.strip()
            if not notes and releases.get("Gitee") is not None:
                notes = releases["Gitee"].notes.strip()
            if not notes:
                notes = "（该来源未提供发行说明，可点「GitHub 发行页」查看）"
            self.txt_notes.setPlainText(notes)
            self.btn_download.setEnabled(True)
        elif latest is not None:
            self.lbl_head.setText("已是最新版本 v%s" % APP_VERSION)
            self.lbl_head.setStyleSheet("font-size:16px;font-weight:600;color:#34d399;")
            self.lbl_status.setText("当前版本与远端一致，无需更新。")
            self.txt_notes.setPlainText("没有更新的版本。")
            self._asset = None
            self.btn_apply.setEnabled(False)
            self.btn_download.setEnabled(False)
        else:
            self.lbl_head.setText("暂时无法检查更新")
            self.lbl_head.setStyleSheet("font-size:16px;font-weight:600;color:#fbbf24;")
            self.lbl_status.setText(
                "网络或平台限制导致查询失败，可直接打开仓库发行页手动确认：\n" + "\n".join(errors[:3])
            )
            self._asset = None
            self.btn_apply.setEnabled(False)

        self.btn_gh.setEnabled(True)
        self.btn_gitee.setEnabled(True)

    # ------------------------------------------------------------------
    def _download(self) -> None:
        """只把附件链接丢给浏览器，不自动安装。"""
        latest = self._result.get("latest")
        urls: list[str] = [a.url for a in (latest.assets if latest else []) if a.url]
        if urls:
            for u in urls:
                webbrowser.open(u)
            self.lbl_status.setText("已在浏览器中打开 %d 个下载链接。" % len(urls))
            return
        for label, fallback in (("GitHub", REPO_HOME + "/releases"), ("Gitee", REPO_MIRROR + "/releases")):
            page = self._page(label, fallback)
            if page:
                webbrowser.open(page)
                self.lbl_status.setText("该来源未提供附件直链，已打开发行页，请手动选择下载。")
                return

    def _auto_install(self) -> None:
        asset = self._asset
        latest = self._result.get("latest")
        if asset is None or latest is None:
            self.lbl_status.setText("没有可自动安装的包，请改用「只打开下载链接」。")
            return
        if self._apply is not None and self._apply.isRunning():
            return

        answer = QMessageBox.question(
            self,
            "确认更新",
            "将下载 %s%s，并替换当前程序文件后重启。\n"
            "规则、模板、日志与便携 Python 都不会受影响，旧版本备份在 data\\_update_backup。\n\n继续吗？"
            % (asset.name, _size_hint(asset)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.bar.setFormat("准备下载…")
        self.btn_apply.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.btn_download.setEnabled(False)
        self._apply = ApplyWorker(asset.url, asset.name, latest.version_text, self)
        self._apply.progress.connect(self._on_progress)
        self._apply.status.connect(self.lbl_status.setText)
        self._apply.ok.connect(self._on_applied)
        self._apply.failed.connect(self._on_apply_failed)
        self._apply.start()

    def _on_progress(self, got: int, total: int) -> None:
        if total > 0:
            pct = int(got * 100 / total)
            self.bar.setValue(pct)
            self.bar.setFormat(f"下载中 {_mb(got)} / {_mb(total)}（{pct}%）")
        else:
            self.bar.setFormat(f"下载中 {_mb(got)}")

    def _on_applied(self, msg: str) -> None:
        self.bar.setValue(100)
        self.bar.setFormat("已完成")
        self.lbl_status.setText(msg)
        self.btn_check.setEnabled(True)
        ask = QMessageBox.question(
            self,
            "更新完成",
            f"{msg}\n\n现在重启程序让新版本生效吗？（选否也可以下次启动生效）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ask == QMessageBox.StandardButton.Yes:
            self._do_restart()
        else:
            self.btn_apply.setEnabled(False)

    def _on_apply_failed(self, msg: str) -> None:
        self.bar.setVisible(False)
        self.btn_check.setEnabled(True)
        self.btn_apply.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.lbl_status.setText("自动更新失败：" + msg)
        QMessageBox.warning(
            self,
            "自动更新失败",
            f"{msg}\n\n可以改用「只打开下载链接」手动下载新版本替换。",
        )

    def _do_restart(self) -> None:
        ok, msg = self_update.restart_app()
        if not ok:
            QMessageBox.warning(self, "重启失败", msg)
            return
        parent = self.parent()
        try:
            if hasattr(parent, "shutdown"):
                parent.shutdown()       # 保存设置、停引擎、收托盘
        except Exception:  # noqa: BLE001
            pass
        self.accept()
        QApplication.instance().quit()

    def _on_close(self) -> None:
        if self._apply is not None and self._apply.isRunning():
            if (
                QMessageBox.question(self, "正在下载", "更新还在下载，确定取消并退出吗？")
                != QMessageBox.StandardButton.Yes
            ):
                return
            self._apply.requestInterruption()
        self.accept()

    # ------------------------------------------------------------------
    @staticmethod
    def open_and_wait(parent=None, source: str = "auto") -> None:
        dlg = UpdateDialog(None, parent, source)
        dlg.exec()


def show_result_if_any(parent, result: dict, log=None) -> bool:
    """自动检查用：有新版本时弹窗，否则只写一条日志。返回是否有新版本。"""
    latest = (result or {}).get("latest")
    current = (result or {}).get("current_version") or (0, 0, 0)
    if latest is not None and latest.version > current:
        if log:
            log("warn", f"发现新版本 v{latest.version_text}（当前 v{APP_VERSION}），可在「检查更新」里查看")
        dlg = UpdateDialog(result, parent)
        dlg.exec()
        return True
    if log:
        if latest is not None:
            log("info", f"已是最新版本 v{APP_VERSION}")
        else:
            log("warn", "检查更新失败：" + "；".join((result or {}).get("errors", [])[:2]))
    return False
