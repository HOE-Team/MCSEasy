# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""各类对话框：JVM 设置、版本设置、Modrinth 文件选择。"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QTextBrowser,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import SERVER_TYPES
from .services import pick_primary_file
from .theme import Theme
from .utils import shorten
from .widgets import Card, LoadingOverlay
from .workers import InstallerWorker, ModrinthVersionsWorker, WorkerHost, cancel_worker, is_running

logger = logging.getLogger(__name__)


class JvmSettingsDialog(QDialog):
    """内存与 JVM 参数设置。"""

    def __init__(
        self,
        theme: Theme,
        min_mem: int = 2,
        max_mem: int = 4,
        custom_args: str = "",
        title: str = "实例 JVM 设置",
        description: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._theme = theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        if description:
            hint = QLabel(description)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        form_card = Card("内存")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)

        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 512)
        self.min_spin.setSuffix(" GB")
        self.min_spin.setValue(max(1, int(min_mem)))
        form.addRow("最小内存", self.min_spin)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(2, 512)
        self.max_spin.setSuffix(" GB")
        self.max_spin.setValue(max(2, int(max_mem)))
        form.addRow("最大内存", self.max_spin)

        form_card.add(form)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        for text, low, high in (("轻量 2/4", 2, 4), ("标准 4/8", 4, 8), ("大型 8/16", 8, 16)):
            button = QPushButton(text)
            button.setObjectName("ghost")
            button.clicked.connect(lambda _=False, a=low, b=high: self._apply_preset(a, b))
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        form_card.add(preset_row)

        self.system_hint = QLabel()
        self.system_hint.setObjectName("muted")
        self.system_hint.setWordWrap(True)
        form_card.add(self.system_hint)
        layout.addWidget(form_card)

        args_card = Card("JVM 参数")
        self.args_edit = QLineEdit(custom_args)
        self.args_edit.setPlaceholderText("例如：-XX:+UseG1GC -Dfile.encoding=UTF-8")
        args_card.add(self.args_edit)
        args_hint = QLabel("多个参数用空格分隔，会追加在内存参数之后。")
        args_hint.setObjectName("muted")
        args_hint.setWordWrap(True)
        args_card.add(args_hint)
        layout.addWidget(args_card)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.min_spin.valueChanged.connect(self._sync_limits)
        self.max_spin.valueChanged.connect(self._sync_limits)
        self._sync_limits()
        self._update_system_hint()

    def _apply_preset(self, low: int, high: int) -> None:
        self.min_spin.setValue(low)
        self.max_spin.setValue(high)

    def _sync_limits(self) -> None:
        self.max_spin.setMinimum(self.min_spin.value() + 1)

    def _update_system_hint(self) -> None:
        try:
            import psutil

            total_gb = psutil.virtual_memory().total / (1024 ** 3)
            recommended = int(total_gb * 0.5)
            self.system_hint.setText(
                "本机物理内存约 %.1f GB，建议最大内存不超过 %.0f GB。" % (total_gb, max(2, recommended))
            )
        except Exception:
            self.system_hint.setText("无法读取本机内存信息，请手动设置合适的数值。")

    def _on_accept(self) -> None:
        if self.max_spin.value() <= self.min_spin.value():
            QMessageBox.warning(self, "提示", "最大内存必须大于最小内存。")
            return
        self.accept()

    def values(self):
        return self.min_spin.value(), self.max_spin.value(), self.args_edit.text().strip()


class VersionSettingsDialog(QDialog):
    """记录实例的服务端类型与 MC 版本（用于过滤模组、显示信息）。"""

    def __init__(
        self,
        theme: Theme,
        mc_version: str = "",
        loader: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("版本设置")
        self.setMinimumWidth(420)
        self._theme = theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        card = Card("服务器版本")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)

        self.loader_combo = QComboBox()
        self.loader_combo.addItem("自动检测", "")
        for server_type in SERVER_TYPES:
            self.loader_combo.addItem(server_type, server_type)
        if loader:
            index = self.loader_combo.findData(loader)
            if index < 0:
                index = self.loader_combo.findData(loader.capitalize())
            if index >= 0:
                self.loader_combo.setCurrentIndex(index)
        form.addRow("服务端类型", self.loader_combo)

        self.version_edit = QLineEdit(mc_version)
        self.version_edit.setPlaceholderText("例如：1.21.4（留空则由程序自动识别）")
        form.addRow("Minecraft 版本", self.version_edit)
        card.add(form)

        hint = QLabel(
            "这些信息用于筛选模组/插件，并在主页显示。"
            "实际启动时程序会优先读取目录中的服务端文件。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        layout.addWidget(card)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return self.version_edit.text().strip(), self.loader_combo.currentData() or ""


class VersionPickerDialog(QDialog):
    """选择 Modrinth 上某个项目具体版本的文件。"""

    def __init__(
        self,
        theme: Theme,
        workers: WorkerHost,
        project: dict,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._workers = workers
        self._project = project
        self._versions: List[dict] = []
        self._selected_file: Optional[dict] = None
        self._worker: Optional[ModrinthVersionsWorker] = None

        self.setWindowTitle("选择文件 - %s" % project.get("title", ""))
        self.setMinimumSize(640, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = Card(str(project.get("title") or "未知项目"))
        description = QLabel(shorten(project.get("description", ""), 160))
        description.setObjectName("hint")
        description.setWordWrap(True)
        header.add(description)
        self.meta_label = QLabel()
        self.meta_label.setObjectName("muted")
        header.add(self.meta_label)
        layout.addWidget(header)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("MC 版本"))
        self.version_combo = QComboBox()
        self.version_combo.setEditable(True)
        self.version_combo.setMinimumWidth(120)
        self.version_combo.addItem(game_version or "")
        self.version_combo.setCurrentIndex(0)
        filter_row.addWidget(self.version_combo)

        filter_row.addWidget(QLabel("加载器"))
        self.loader_combo = QComboBox()
        self.loader_combo.addItem("全部", "")
        for name in ("fabric", "forge", "neoforge", "quilt"):
            self.loader_combo.addItem(name, name)
        if loader:
            index = self.loader_combo.findData(loader.lower())
            if index >= 0:
                self.loader_combo.setCurrentIndex(index)
        filter_row.addWidget(self.loader_combo)

        refresh = QPushButton("筛选")
        refresh.setObjectName("primary")
        refresh.clicked.connect(self._reload)
        filter_row.addWidget(refresh)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _: self._accept_selection())
        layout.addWidget(self.list_widget, 1)

        self.status_label = QLabel("正在获取版本列表…")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("下载所选")
        self.ok_button.setObjectName("primary")
        self.ok_button.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._overlay = LoadingOverlay(self.list_widget, theme, "正在获取版本…")
        self.list_widget.installEventFilter(self._overlay)

        self._reload()

    # ---- 数据 ----
    def _reload(self) -> None:
        project_id = self._project.get("project_id") or self._project.get("id")
        if not project_id:
            self.status_label.setText("该项目缺少 ID，无法获取版本。")
            return
        if is_running(self._worker):
            cancel_worker(self._worker)

        self.list_widget.clear()
        self.ok_button.setEnabled(False)
        self.status_label.setText("正在获取版本列表…")
        self._overlay.start("正在获取版本…")

        game_version = self.version_combo.currentText().strip() or None
        loader = self.loader_combo.currentData() or None

        worker = ModrinthVersionsWorker(project_id, game_version, loader, parent=self)
        worker.results.connect(self._on_versions)
        worker.error.connect(self._on_error)
        self._worker = worker
        self._workers.start(worker)

    def _on_versions(self, versions: list) -> None:
        self._overlay.stop()
        self._versions = versions or []
        self.list_widget.clear()
        if not self._versions:
            self.status_label.setText("没有符合筛选条件的文件，试试放宽条件。")
            return

        for version in self._versions:
            files = version.get("files") or []
            if not files:
                continue
            loaders = ", ".join(version.get("loaders") or []) or "-"
            games = ", ".join(version.get("game_versions") or []) or "-"
            downloads = version.get("downloads") or 0
            name = version.get("name") or version.get("version_number") or "未命名"
            date = str(version.get("date_published") or "")[:10]
            text = "%s  ·  %s  ·  MC %s  ·  %s  ·  %s 次下载" % (
                name,
                loaders,
                games,
                date,
                "{:,}".format(downloads),
            )
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, version)
            item.setToolTip(text)
            self.list_widget.addItem(item)

        count = self.list_widget.count()
        self.status_label.setText("共 %d 个版本，双击可直接选择。" % count)
        if count:
            self.list_widget.setCurrentRow(0)
            self.ok_button.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self._overlay.stop()
        self.status_label.setText("获取失败：%s" % message)

    def _accept_selection(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择一个版本。")
            return
        version = item.data(Qt.UserRole) or {}
        primary = pick_primary_file(version)
        if not primary or not primary.get("url"):
            QMessageBox.warning(self, "提示", "该版本没有可下载的文件。")
            return
        self._selected_file = {
            "url": primary.get("url"),
            "filename": primary.get("filename") or "download.jar",
            "size": primary.get("size") or 0,
            "version": version.get("name") or version.get("version_number") or "",
            "game_versions": version.get("game_versions") or [],
            "loaders": version.get("loaders") or [],
        }
        self.accept()

    def selected_file(self) -> Optional[dict]:
        return self._selected_file

    def closeEvent(self, event) -> None:  # noqa: N802
        if is_running(self._worker):
            cancel_worker(self._worker)
        self._overlay.stop()
        super().closeEvent(event)

class InstallerDialog(QDialog):
    """运行 Forge / NeoForge 安装器并展示实时日志。"""

    def __init__(
        self,
        theme: Theme,
        workers: WorkerHost,
        java_exe: str,
        installer_path: str,
        workdir: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._workers = workers
        self._finished_ok = False
        self.setWindowTitle("安装服务端")
        self.setMinimumSize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("正在安装服务端")
        title.setObjectName("valueStrong")
        layout.addWidget(title)

        description = QLabel(
            "安装器会下载所需的库文件，首次安装可能需要几分钟，期间请保持网络连接。"
        )
        description.setObjectName("hint")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("console")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.log_view, 1)

        self.status_label = QLabel("准备中…")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        self.close_button = QPushButton("取消安装")
        self.close_button.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.close_button)
        layout.addLayout(row)

        worker = InstallerWorker(java_exe, installer_path, workdir)
        worker.output.connect(self._append_log)
        worker.error.connect(self._on_error)
        worker.succeeded.connect(self._on_success)
        self._worker = worker
        self._workers.start(worker)

    def _append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.status_label.setText(line[:120])

    def _on_error(self, message: str) -> None:
        self.status_label.setText("安装失败：%s" % message)
        self.close_button.setText("关闭")

    def _on_success(self) -> None:
        self._finished_ok = True
        self.status_label.setText("安装完成。")
        self.close_button.setText("完成")
        self.accept()

    def reject(self) -> None:  # noqa: D401
        if is_running(self._worker):
            cancel_worker(self._worker)
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if is_running(self._worker):
            cancel_worker(self._worker)
        super().closeEvent(event)

class ShortcutHelpDialog(QDialog):
    """快捷键与辅助功能说明。"""

    def __init__(self, theme: Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("快捷键与帮助")
        self.setMinimumSize(560, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("快捷键与辅助功能")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        browser = QTextBrowser()
        browser.setObjectName("aboutText")
        browser.setOpenExternalLinks(False)
        browser.setHtml(
            "<style>td { padding: 3px 10px 3px 0; } h3 { margin-bottom: 4px; }</style>"
            "<h3>常用快捷键</h3>"
            "<table>"
            "<tr><td><b>Ctrl + N</b></td><td>新建实例</td></tr>"
            "<tr><td><b>Ctrl + F</b></td><td>在当前控制台中查找</td></tr>"
            "<tr><td><b>Ctrl + ,</b></td><td>打开设置</td></tr>"
            "<tr><td><b>Ctrl + 1 / 2 / 3 / 4 / 5</b></td><td>切换到主页 / 实例 / 下载中心 / 设置 / 关于</td></tr>"
            "<tr><td><b>Ctrl + Tab</b></td><td>循环切换页面（Shift 反向）</td></tr>"
            "<tr><td><b>F5</b></td><td>刷新当前页面（实例信息 / 版本列表）</td></tr>"
            "<tr><td><b>F1</b></td><td>打开本帮助</td></tr>"
            "<tr><td><b>Enter</b></td><td>发送控制台命令</td></tr>"
            "<tr><td><b>↑ / ↓</b></td><td>在命令输入框中翻阅历史命令</td></tr>"
            "<tr><td><b>拖放文件夹</b></td><td>把服务器文件夹拖到左侧实例上即可设置目录</td></tr>"
            "</table>"
            "<h3>辅助功能</h3>"
            "<ul>"
            "<li>侧边栏可以先用 <b>Tab</b> 聚焦，再用方向键切换页面。</li>"
            "<li>「设置 → 外观」提供深色 / 浅色主题与窗口不透明度；"
            "「控制台」提供字号调节。</li>"
            "<li>所有图标按钮都有悬停提示与无障碍名称，屏幕阅读器可以朗读。</li>"
            "<li>状态不会只用颜色表示：运行中 / 已停止同时有文字说明。</li>"
            "</ul>"
            "<h3>界面说明</h3>"
            "<p><b>主页</b>是服务器卡片墙，点卡片进入<b>实例工作台</b>；"
            "工作台的<b>概览</b>会按状态显示「开始使用 → 准备启动 → 实例概览 → 运行状态」，"
            "<b>控制台</b>里是日志与命令。启动服务器后会自动切到控制台。</p>"
        )
        layout.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)