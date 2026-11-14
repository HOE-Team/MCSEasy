# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""主窗口：导航、实例生命周期、服务器进程与全局异常兜底。"""

from __future__ import annotations

import base64
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, APP_TAGLINE, APP_VERSION, data_dir
from .dialogs import InstallerDialog, JvmSettingsDialog, ShortcutHelpDialog, VersionSettingsDialog
from .model import (
    Instance,
    InstanceStore,
    JavaInfo,
    LaunchError,
    Settings,
    build_launch_plan,
    check_launch_readiness,
    detect_java,
    detect_server,
    ensure_eula,
    find_installer_jar,
    read_server_properties,
    unique_name,
)
from .pages.about import AboutPage
from .pages.download import DownloadPage
from .pages.instances import InstancesPage
from .pages.settings import SettingsPage
from .pages.workspace import WorkspacePage
from .theme import Theme, app_icon, get_theme
from .utils import safe_int, shorten
from .widgets import IconButton, StatusBadge, Toaster
from .workers import BackupWorker, IconLoader, ResourceMonitor, Worker, WorkerHost, is_running

logger = logging.getLogger(__name__)

PAGE_META = (
    ("home", "home", "主页", "所有服务器实例一览"),
    ("workspace", "terminal", "实例", "当前实例的概览与控制台"),
    ("download", "download", "下载中心", "获取服务端核心、模组与插件"),
    ("settings", "settings", "设置", "外观、Java 与启动参数"),
    ("about", "info", "关于", "版本信息与开源许可"),
)


class JavaDetectWorker(Worker):
    """在后台探测 Java，避免启动时卡顿。"""

    found = Signal(object)

    def __init__(self, custom_path: str = "") -> None:
        super().__init__()
        self.custom_path = custom_path

    def execute(self) -> None:
        info = detect_java(self.custom_path)
        if not self.is_cancelled():
            self.found.emit(info)


class MainWindow(QMainWindow):
    """程序主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self._settings = Settings()
        self._store = InstanceStore(self._settings)
        self._instances: List[Instance] = self._store.load()
        self._current_index = 0
        self._theme: Theme = get_theme(self._settings.get_str("theme", "dark"))
        self._java_info = JavaInfo(
            path=shutil.which("java") or "",
            error="" if shutil.which("java") else "正在检测 Java…",
        )
        self._processes: Dict[str, QProcess] = {}
        self._stop_timers: Dict[str, QTimer] = {}
        self._stopping: Dict[str, bool] = {}
        self._resource_monitor: Optional[ResourceMonitor] = None
        self._warnings: List[str] = []
        self._closing = False
        self._timers: List[QTimer] = []
        self._output_warnings: Dict[str, set] = {}

        self.workers = WorkerHost(self)
        self.icons = IconLoader(self)
        self._toaster: Optional[Toaster] = None

        self.setWindowTitle("%s - %s" % (APP_NAME, APP_TAGLINE))
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1080, 700)
        self.resize(1360, 860)

        self._setup_ui()
        self._restore_window_geometry()
        self._apply_theme(self._theme.key, initial=True)
        self.refresh_instances()
        self._settings_page.refresh()
        self._install_shortcuts()

        # 恢复上次保存的外观与行为设置（refresh 时会屏蔽信号，需显式应用一次）
        self.set_transparency(self._settings.get_int("window_transparency_percent", 100))
        self.apply_auto_scroll(self._settings.get_bool("auto_scroll", True))
        self.apply_console_font_size(self._settings.get_int("console_font_size", 12))

        self._schedule(120, self.detect_java)
        self._schedule(400, self._refresh_warnings)

    def _schedule(self, delay_ms: int, callback) -> None:
        """延迟执行，并把定时器挂在窗口上，退出时可以安全取消。"""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._run_delayed(callback))
        timer.start(delay_ms)
        self._timers.append(timer)

    def _run_delayed(self, callback) -> None:
        if self._closing:
            return
        try:
            callback()
        except Exception:  # noqa: BLE001 - 延迟任务失败不应影响主循环
            logger.exception("延迟任务执行失败")

    # ==================== 对外属性 ====================
    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def instances(self) -> List[Instance]:
        return self._instances

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def java_info(self) -> JavaInfo:
        return self._java_info

    def current_instance(self) -> Optional[Instance]:
        if 0 <= self._current_index < len(self._instances):
            return self._instances[self._current_index]
        return None

    def find_instance(self, instance_id: str) -> Optional[Instance]:
        for instance in self._instances:
            if instance.id == instance_id:
                return instance
        return None

    def index_of(self, instance_id: str) -> int:
        for index, instance in enumerate(self._instances):
            if instance.id == instance_id:
                return index
        return -1

    def open_download_page(self, return_to_workspace: bool = False) -> None:
        """打开下载中心；传 True 表示下载完成后回到实例工作台。"""
        self._download_page.return_to_workspace = bool(return_to_workspace)
        self._go_to_page(2)

    def open_settings_page(self) -> None:
        self._go_to_page(3)

    def open_workspace(self, instance_id: str = "", console: bool = False) -> None:
        """进入实例工作台（可指定实例与是否直接显示控制台）。"""
        if instance_id:
            index = self.index_of(str(instance_id))
            if index >= 0:
                self.select_instance(index)
        self._go_to_page(1)
        self._workspace_page.update_instance_view()
        if console:
            self._workspace_page.show_console()

    def back_to_instances(self) -> None:
        self._go_to_page(0)

    def start_instance_by_id(self, instance_id: str) -> None:
        instance = self.find_instance(str(instance_id))
        if instance is not None:
            self.start_server(instance)

    def stop_instance_by_id(self, instance_id: str) -> None:
        self.stop_server(str(instance_id))

    def _open_running_instance(self) -> None:
        for instance in self._instances:
            if self.is_running(instance.id):
                self.open_workspace(instance.id, console=True)
                return
        self.notify("当前没有运行中的服务器")

    def _find_in_console(self) -> None:
        if self._stack.currentIndex() != 1:
            instance = self.current_instance()
            self.open_workspace(instance.id if instance else "", console=True)
        self._workspace_page._toggle_search()

    def recheck_environment(self) -> None:
        """重新探测 Java 并刷新实例状态。"""
        self.notify("正在重新检查运行环境…")
        self.detect_java()
        self.refresh_instances()

    def run_installer_for_current(self) -> None:
        """为当前实例运行 Forge / NeoForge 安装器。"""
        instance = self.current_instance()
        if instance is None or not instance.has_path:
            self.notify("请先为实例选择服务器目录", "error")
            return
        installer = find_installer_jar(instance.path)
        if installer is None:
            self.notify("该目录中没有找到安装器（*installer*.jar）", "error")
            return
        if not self._java_info.ok:
            self.notify("需要可用的 Java 才能运行安装器", "error")
            self._go_to_page(2)
            return

        dialog = InstallerDialog(
            self._theme,
            self.workers,
            self._java_info.path,
            str(installer),
            instance.path,
            self,
        )
        if bool(dialog.exec()):
            self.refresh_instances()
            self.notify("安装完成，现在可以启动服务器了", "success")

    def is_running(self, instance_id: str) -> bool:
        process = self._processes.get(instance_id)
        if process is None:
            return False
        try:
            return process.state() in (QProcess.Starting, QProcess.Running)
        except RuntimeError:
            return False

    def process_state(self, instance_id: str) -> str:
        """返回 stopped / starting / running / stopping，供界面显示明确状态。"""
        if not instance_id:
            return "stopped"
        if self._stopping.get(instance_id):
            return "stopping"
        process = self._processes.get(instance_id)
        if process is None:
            return "stopped"
        try:
            state = process.state()
        except RuntimeError:
            return "stopped"
        if state == QProcess.Starting:
            return "starting"
        if state == QProcess.Running:
            return "running"
        return "stopped"

    # ==================== 界面搭建 ====================
    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        self._central = central

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        right_layout.addWidget(self._build_top_bar())
        right_layout.addWidget(self._build_warning_bar())
        right_layout.addWidget(self._build_pages(), 1)

        layout.addWidget(right, 1)

        self._toaster = Toaster(central, self._theme)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        self.nav_list.setCurrentRow(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        logo_widget = QWidget()
        logo_widget.setObjectName("logoWidget")
        logo_layout = QVBoxLayout(logo_widget)
        logo_layout.setContentsMargins(16, 24, 16, 18)
        logo_layout.setSpacing(2)

        logo_label = QLabel(APP_NAME)
        logo_label.setObjectName("logoLabel")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_label)

        version_label = QLabel("v%s" % APP_VERSION)
        version_label.setObjectName("versionLabel")
        version_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(version_label)
        layout.addWidget(logo_widget)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setSelectionMode(QListWidget.SingleSelection)
        self.nav_list.setFocusPolicy(Qt.StrongFocus)
        self.nav_list.setAccessibleName("主导航")
        self.nav_list.setAccessibleDescription("用上下方向键切换页面，也可以按 Ctrl+1 到 Ctrl+4")
        self.nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for _page_id, icon_name, title, _subtitle in PAGE_META:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, icon_name)
            item.setSizeHint(QSize(176, 46))
            item.setIcon(self._theme.icon(icon_name, 19, "subtext"))
            self.nav_list.addItem(item)
        layout.addWidget(self.nav_list, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 14)
        footer.setSpacing(8)
        self._theme_button = IconButton(self._theme, "moon", "切换深色 / 浅色主题", 17)
        self._theme_button.clicked.connect(self._toggle_theme)
        footer.addWidget(self._theme_button)

        self._running_button = QPushButton("未运行")
        self._running_button.setObjectName("sideStatus")
        self._running_button.setFlat(True)
        self._running_button.setCursor(Qt.PointingHandCursor)
        self._running_button.setToolTip("没有运行中的服务器")
        self._running_button.clicked.connect(self._open_running_instance)
        footer.addWidget(self._running_button, 1)
        layout.addLayout(footer)
        return sidebar

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topBar")
        bar.setFixedHeight(62)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self._title_label = QLabel(PAGE_META[0][2])
        self._title_label.setObjectName("pageTitle")
        text_layout.addWidget(self._title_label)
        self._subtitle_label = QLabel(PAGE_META[0][3])
        self._subtitle_label.setObjectName("pageSubtitle")
        text_layout.addWidget(self._subtitle_label)
        layout.addLayout(text_layout)
        layout.addStretch(1)

        self._current_badge = StatusBadge("未选择实例", "accent")
        self._current_badge.setToolTip("当前正在操作的实例")
        layout.addWidget(self._current_badge)

        self._instance_badge = StatusBadge("0 个实例", "idle")
        layout.addWidget(self._instance_badge)

        self._java_badge = StatusBadge("Java 检测中", "idle")
        self._java_badge.setToolTip("Java 运行环境")
        layout.addWidget(self._java_badge)

        self._help_button = IconButton(self._theme, "info", "快捷键与帮助 (F1)", 17)
        self._help_button.clicked.connect(self.show_help)
        layout.addWidget(self._help_button)
        return bar

    def _build_warning_bar(self) -> QWidget:
        container = QWidget()
        container.setObjectName("warningBar")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(20, 4, 20, 4)
        layout.setSpacing(8)
        self._warning_layout = layout
        container.hide()
        self._warning_bar = container
        return container

    def _build_pages(self) -> QWidget:
        self._stack = QStackedWidget()
        self._instances_page = InstancesPage(self)
        self._workspace_page = WorkspacePage(self)
        self._download_page = DownloadPage(self)
        self._settings_page = SettingsPage(self)
        self._about_page = AboutPage(self)
        for page in (
            self._instances_page,
            self._workspace_page,
            self._download_page,
            self._settings_page,
            self._about_page,
        ):
            self._stack.addWidget(page)
        self._stack.setCurrentIndex(0)
        return self._stack

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._find_in_console)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.create_instance)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self._go_to_page(3))
        QShortcut(QKeySequence("F1"), self, activated=self.show_help)
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_current_page)
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._cycle_page(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._cycle_page(-1))
        for index in range(len(PAGE_META)):
            QShortcut(
                QKeySequence("Ctrl+%d" % (index + 1)),
                self,
                activated=lambda i=index: self._go_to_page(i),
            )

    def _cycle_page(self, step: int) -> None:
        count = self._stack.count()
        index = (self._stack.currentIndex() + step) % count
        self.nav_list.setCurrentRow(index)

    def _refresh_current_page(self) -> None:
        index = self._stack.currentIndex()
        if index == 0:
            self._instances_page.refresh()
            self.notify("已刷新实例列表", "success")
        elif index == 1:
            self._workspace_page.update_instance_view()
            self.notify("已刷新实例信息", "success")
        elif index == 2:
            self._download_page.refresh_versions()

    # ==================== 导航 ====================
    def show_help(self) -> None:
        dialog = ShortcutHelpDialog(self._theme, self)
        dialog.exec()

    def _go_to_page(self, index: int) -> None:
        if 0 <= index < self.nav_list.count():
            self.nav_list.setCurrentRow(index)

    def _on_nav_changed(self, index: int) -> None:
        if index < 0:
            return
        self._stack.setCurrentIndex(index)
        _page_id, _icon, title, subtitle = PAGE_META[index]
        self._title_label.setText(title)
        self._subtitle_label.setText(subtitle)
        self._update_nav_icons(index)

        if index in (0, 1):
            self._start_resource_monitor()
        else:
            self._stop_resource_monitor()

        if index == 0:
            self._instances_page.refresh()
        elif index == 1:
            self._workspace_page.update_instance_view()
        elif index == 2:
            self._download_page.on_show()
        elif index == 3:
            self._settings_page.refresh()
        elif index == 4:
            self._about_page.refresh()

    def _update_nav_icons(self, selected: int) -> None:
        for index in range(self.nav_list.count()):
            item = self.nav_list.item(index)
            icon_name = item.data(Qt.UserRole)
            if index == selected:
                item.setIcon(self._theme.icon(icon_name, 19, "on_accent"))
            else:
                item.setIcon(self._theme.icon(icon_name, 19, "subtext"))

    # ==================== 主题 ====================
    def _toggle_theme(self) -> None:
        key = "light" if self._theme.key == "dark" else "dark"
        self.set_theme(key)

    def set_theme(self, key: str) -> None:
        self._apply_theme(key)
        self._settings.set("theme", self._theme.key)
        self._settings_page.refresh()

    def _apply_theme(self, key: str, initial: bool = False) -> None:
        self._theme = get_theme(key)
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(self._theme.qss())

        self._theme_button.setIcon(self._theme.icon("sun" if self._theme.is_dark else "moon", 17, "subtext"))
        self._theme_button.setToolTip(
            "切换到浅色主题" if self._theme.is_dark else "切换到深色主题"
        )
        self._update_nav_icons(max(0, self.nav_list.currentRow()))
        self._instances_page.restyle(self._theme)
        self._workspace_page.restyle(self._theme)
        self._download_page.restyle(self._theme)
        self._settings_page.restyle(self._theme)
        self._about_page.restyle(self._theme)
        if self._toaster is not None:
            self._toaster.set_theme(self._theme)
        self._update_running_pill()

    def set_transparency(self, percent: int) -> None:
        value = max(40, min(100, int(percent)))
        self.setWindowOpacity(value / 100.0)
        self._settings.set("window_transparency_percent", value)

    # ==================== 主题辅助 ====================
    def app_icon_pixmap(self, size: int) -> Optional[QPixmap]:
        for name in ("icon.png", "logo.svg"):
            path = Path(__file__).resolve().parent.parent / name
            if path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return self._theme.pixmap("server", size, "accent")

    # ==================== 通知 ====================
    def notify(self, text: str, kind: str = "info") -> None:
        if not text:
            return
        logger.info("[notify] %s", text)
        if kind == "error":
            logger.error(text)
        if self._toaster is not None:
            self._toaster.show(text, kind)

    # ==================== 实例管理 ====================
    def _update_current_badge(self) -> None:
        instance = self.current_instance()
        if instance is None:
            self._current_badge.setText("未选择实例")
            self._current_badge.set_state("idle")
            return
        name = shorten(instance.display_name(), 16)
        self._current_badge.setText("当前：%s" % name)
        self._current_badge.set_state("accent")
        self._current_badge.setToolTip("当前正在操作的实例：%s" % instance.display_name())
        self._current_badge.setAccessibleName("当前实例：%s" % instance.display_name())

    def refresh_instances(self) -> None:
        if not self._instances:
            self._instances.append(Instance())
            self._current_index = 0
        self._current_index = max(0, min(self._current_index, len(self._instances) - 1))
        self._instances_page.refresh()
        self._workspace_page.prune_consoles({instance.id for instance in self._instances})
        self._workspace_page.update_instance_view()
        self._download_page.update_target()
        self._about_page.refresh()
        self._update_running_pill()
        self._update_current_badge()

    def persist_instances(self) -> None:
        self._store.save(self._instances)

    def select_instance(self, index: int) -> None:
        if 0 <= index < len(self._instances):
            self._current_index = index
            self._download_page.update_target()
            self._workspace_page.update_instance_view()
            self._update_current_badge()

    def create_instance(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "新建实例",
            "实例名称：",
            text=unique_name([i.name for i in self._instances], "新实例"),
        )
        if not ok:
            return
        instance = Instance(name=unique_name([i.name for i in self._instances], name.strip() or "新实例"))
        self._instances.append(instance)
        self._current_index = len(self._instances) - 1
        self.persist_instances()
        self.refresh_instances()
        self.notify("已创建实例「%s」" % instance.name, "success")

    def duplicate_instance(self) -> None:
        source = self.current_instance()
        if source is None:
            return
        clone = Instance.from_dict(source.to_dict())
        clone.id = Instance().id
        clone.name = unique_name([i.name for i in self._instances], source.name + " 副本")
        clone.path = ""
        clone.last_played = ""
        self._instances.append(clone)
        self._current_index = len(self._instances) - 1
        self.persist_instances()
        self.refresh_instances()
        self.notify("已复制实例配置，记得为新实例选择目录", "success")

    def rename_instance(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        name, ok = QInputDialog.getText(self, "重命名实例", "新名称：", text=instance.name)
        if not ok or not name.strip():
            return
        instance.name = name.strip()[:64]
        self.persist_instances()
        self.refresh_instances()

    def delete_instance(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        if len(self._instances) <= 1:
            self.notify("至少需要保留一个实例", "error")
            return
        if self.is_running(instance.id):
            self.notify("请先停止该实例的服务器再删除", "error")
            return
        answer = QMessageBox.question(
            self,
            "删除实例",
            "确定要移除实例「%s」吗？\n\n只会从列表中移除，不会删除磁盘上的服务器文件。"
            % instance.name,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._processes.pop(instance.id, None)
        self._stop_timers.pop(instance.id, None)
        self._instances = [item for item in self._instances if item.id != instance.id]
        self._current_index = max(0, self._current_index - 1)
        self.persist_instances()
        self.refresh_instances()
        self.notify("已移除实例「%s」" % instance.name, "success")

    def set_instance_path(self, instance_id: str, path: str) -> None:
        instance = self.find_instance(instance_id)
        if instance is None:
            return
        instance.path = path
        if not instance.loader or not instance.mc_version:
            server_type, version = detect_server(path)
            instance.loader = instance.loader or server_type
            instance.mc_version = instance.mc_version or version
        self.persist_instances()
        self.refresh_instances()
        self.notify("已设置实例目录", "success")

    # ==================== 设置相关 ====================
    def show_version_settings(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        dialog = VersionSettingsDialog(
            self._theme, instance.mc_version, instance.loader, self
        )
        if not bool(dialog.exec()):
            return
        version, loader = dialog.values()
        instance.mc_version = version
        instance.loader = loader
        self.persist_instances()
        self.refresh_instances()
        self.notify("版本信息已保存", "success")

    def show_jvm_settings(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        dialog = JvmSettingsDialog(
            self._theme,
            instance.min_mem,
            instance.max_mem,
            instance.custom_args,
            title="实例 JVM 设置 - %s" % instance.name,
            parent=self,
        )
        if not bool(dialog.exec()):
            return
        low, high, args = dialog.values()
        instance.min_mem = low
        instance.max_mem = high
        instance.custom_args = args
        self.persist_instances()
        self.refresh_instances()
        self.notify("JVM 设置已保存", "success")

    def reload_global_args(self) -> None:
        """全局参数变化后刷新提示（参数在启动时读取，无需重启程序）。"""

    def apply_console_font_size(self, size: int) -> None:
        for console in self._workspace_page._consoles.values():
            console.apply_font_size(size)

    def apply_auto_scroll(self, enabled: bool) -> None:
        self._workspace_page.auto_scroll_check.blockSignals(True)
        self._workspace_page.auto_scroll_check.setChecked(bool(enabled))
        self._workspace_page.auto_scroll_check.blockSignals(False)
        for console in self._workspace_page._consoles.values():
            console.set_auto_scroll(bool(enabled))

    def apply_default_settings(self) -> None:
        self._settings.sync()
        self.set_theme(self._settings.get_str("theme", "dark"))
        self.set_transparency(self._settings.get_int("window_transparency_percent", 100))
        self.apply_console_font_size(self._settings.get_int("console_font_size", 12))
        self.apply_auto_scroll(self._settings.get_bool("auto_scroll", True))

    # ==================== Java ====================
    def detect_java(self) -> None:
        if self._closing:
            return
        custom = self._settings.get_str("java_path", "")
        worker = JavaDetectWorker(custom)
        worker.found.connect(self._on_java_detected)
        self.workers.start(worker)

    def _on_java_detected(self, info: JavaInfo) -> None:
        self._java_info = info
        if info is not None and info.ok:
            self._java_badge.setText("Java %s" % (info.version or ""))
            self._java_badge.set_state("ok")
        else:
            self._java_badge.setText("未检测到 Java")
            self._java_badge.set_state("warn")
        self._settings_page.update_java(info)
        self._about_page.refresh()
        self._workspace_page.update_instance_view()
        self._refresh_warnings()

    # ==================== 警告 ====================
    def _refresh_warnings(self) -> None:
        warnings: List[str] = []
        if self._java_info is None or not self._java_info.ok:
            warnings.append("未检测到可用的 Java，服务器将无法启动（设置页可手动指定路径）")
        try:
            import psutil

            if (psutil.cpu_count(logical=False) or 0) < 2:
                warnings.append("CPU 物理核心少于 2 个，服务器可能较卡顿")
            total_mb = psutil.virtual_memory().total / (1024 ** 2)
            if total_mb < 2048:
                warnings.append("物理内存不足 2 GB，建议关闭其他程序")
            try:
                disk = psutil.disk_usage(str(data_dir()))
                if disk.free / (1024 ** 3) < 8:
                    warnings.append("数据目录所在磁盘剩余空间不足 8 GB")
            except Exception:
                pass
        except ImportError:
            pass
        self._warnings = warnings
        self._set_warnings(warnings)

    def _set_warnings(self, warnings: List[str]) -> None:
        while self._warning_layout.count():
            item = self._warning_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not warnings:
            self._warning_bar.hide()
            return

        self._warning_bar.show()
        for text in warnings[:3]:
            label = QLabel("⚠  " + text)
            label.setWordWrap(True)
            label.setStyleSheet(
                "background-color: %s; color: #1e1e2e; border-radius: 6px; padding: 3px 10px;"
                % self._theme.hex("yellow")
            )
            self._warning_layout.addWidget(label)
        self._warning_layout.addStretch(1)

    # ==================== 服务器进程 ====================
    def start_current_server(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        self.start_server(instance)

    def start_server(self, instance: Instance) -> None:
        if self.is_running(instance.id):
            self.notify("该实例的服务器已在运行", "error")
            return
        readiness = check_launch_readiness(instance, self._java_info)
        if not readiness.ok:
            if readiness.needs_java:
                answer = QMessageBox.question(
                    self,
                    "未找到 Java",
                    readiness.message() + "\n\n是否现在到设置页指定 Java 路径？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if answer == QMessageBox.Yes:
                    self._go_to_page(2)
            else:
                # 主页已经内联展示了原因，这里只用轻提示，避免打断操作
                self.notify(readiness.message(), "error")
            return
        if readiness.warning:
            self.notify(readiness.warning)

        java_exe = self._java_info.path or shutil.which("java") or ""
        global_args = self._settings.get_str("global_jvm_args", "")
        try:
            plan = build_launch_plan(instance, java_exe, global_args)
        except LaunchError as error:
            QMessageBox.warning(self, "无法启动", str(error))
            return
        except Exception as error:  # noqa: BLE001
            logger.exception("构造启动命令失败")
            QMessageBox.critical(self, "无法启动", "启动失败：%s" % error)
            return

        if ensure_eula(instance.path):
            logger.info("已自动同意 EULA：%s", instance.path)

        console = self._workspace_page.console_for(instance.id)
        if console is not None:
            console.clear_console()
            console.append_system("正在启动服务器（%s）" % plan.description)
            console.append_system("%s %s" % (plan.program, " ".join(plan.args)))

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.setWorkingDirectory(plan.workdir)
        process.setProgram(plan.program)
        process.setArguments(plan.args)
        # 让 run.bat / run.sh 之类脚本也能用到我们检测到的 Java
        if java_exe:
            java_dir = Path(java_exe).parent
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert(
                "PATH", str(java_dir) + os.pathsep + environment.value("PATH", "")
            )
            environment.insert("JAVA_HOME", str(java_dir.parent))
            process.setProcessEnvironment(environment)

        instance_id = instance.id
        process.readyReadStandardOutput.connect(lambda i=instance_id: self._on_process_output(i))
        process.started.connect(lambda i=instance_id: self._on_process_started(i))
        process.finished.connect(
            lambda code, _status, i=instance_id: self._on_process_finished(i, code)
        )
        process.errorOccurred.connect(
            lambda error, i=instance_id: self._on_process_error(i, error)
        )
        self._processes[instance_id] = process
        self._stopping[instance_id] = False
        self._output_warnings[instance_id] = set()

        logger.info("启动 %s：%s %s", instance.name, plan.program, " ".join(plan.args))
        process.start()

    def _on_process_started(self, instance_id: str) -> None:
        instance = self.find_instance(instance_id)
        if instance is not None:
            instance.last_played = self._now()
            self.persist_instances()
        self._instances_page.refresh()
        self._workspace_page.update_instance_view()
        self._update_running_pill()
        self.notify("服务器已启动", "success")
        # 用户点了启动，就直接把控制台送到眼前
        if self._stack.currentIndex() in (0, 1):
            self.open_workspace(instance_id, console=True)

    def _on_process_output(self, instance_id: str) -> None:
        process = self._processes.get(instance_id)
        if process is None:
            return
        data = bytes(process.readAllStandardOutput().data())
        console = self._workspace_page.console_for(instance_id)
        if console is not None and data:
            console.feed_bytes(data)
        if data:
            self._scan_output_for_problems(instance_id, data)

    def _on_process_error(self, instance_id: str, error) -> None:
        if error == QProcess.FailedToStart:
            self._workspace_page.console_for(instance_id)
            console = self._workspace_page.console_for(instance_id)
            if console is not None:
                console.append_system("进程启动失败")
            self.notify("进程启动失败，请检查 Java 路径与目录权限", "error")
            self._cleanup_process(instance_id)
            self._instances_page.refresh()
            self._workspace_page.update_instance_view()

    def _on_process_finished(self, instance_id: str, exit_code: int) -> None:
        instance = self.find_instance(instance_id)
        was_stopping = self._stopping.get(instance_id, False)
        console = self._workspace_page.console_for(instance_id)
        if console is not None:
            console.append_system("服务器进程已退出（退出码 %s）" % exit_code)

        self._cleanup_process(instance_id)
        self._instances_page.refresh()
        self._workspace_page.update_instance_view()
        self._workspace_page.update_process_metrics({})
        self._update_running_pill()

        if not was_stopping and exit_code not in (0, None):
            self.notify(
                "实例「%s」异常退出（退出码 %s），请在控制台查看日志"
                % (instance.name if instance else "", exit_code),
                "error",
            )
        elif was_stopping:
            self.notify("服务器已停止", "success")

    def _scan_output_for_problems(self, instance_id: str, data: bytes) -> None:
        """从服务器输出里识别常见启动失败原因，给出可直接行动的中文提示。"""
        warned = self._output_warnings.setdefault(instance_id, set())
        if (
            b"UnsupportedClassVersionError" in data
            or b"has been compiled by a more recent version" in data
        ) and "java" not in warned:
            warned.add("java")
            self.notify(
                "Java 版本过低导致启动失败：请到「设置 → Java 运行环境」换用与该版本匹配的 Java",
                "error",
            )
        if b"OutOfMemoryError" in data and "oom" not in warned:
            warned.add("oom")
            self.notify(
                "服务器内存不足（OutOfMemoryError）：可在「JVM 设置」中提高最大内存",
                "error",
            )
        if (
            b"Address already in use" in data or b"FAILED TO BIND TO PORT" in data
        ) and "port" not in warned:
            warned.add("port")
            self.notify("端口被占用，服务器无法监听：请关闭占用程序或修改 server-port", "error")

    def _cleanup_process(self, instance_id: str) -> None:
        timer = self._stop_timers.pop(instance_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        process = self._processes.pop(instance_id, None)
        if process is not None:
            process.deleteLater()
        self._stopping.pop(instance_id, None)

    def stop_current_server(self) -> None:
        instance = self.current_instance()
        if instance is not None:
            self.stop_server(instance.id)

    def stop_server(self, instance_id: str) -> None:
        process = self._processes.get(instance_id)
        if process is None:
            return
        try:
            state = process.state()
        except RuntimeError:
            return
        if state == QProcess.Starting:
            self.notify("服务器正在启动，请稍候再停止", "error")
            return
        if state != QProcess.Running:
            return
        if self._stopping.get(instance_id):
            return
        try:
            process.write(b"stop\n")
        except Exception:  # noqa: BLE001
            pass
        self._stopping[instance_id] = True

        instance = self.find_instance(instance_id)
        console = self._workspace_page.console_for(instance_id)
        if console is not None:
            console.append_system("已发送 stop 命令，正在等待服务器保存并退出…")

        force = self._settings.get_bool("force_stop_on_timeout", False)
        if instance is not None and instance.force_stop:
            force = True
        timeout = self._settings.get_int("stop_timeout", 30)
        if instance is not None and instance.stop_timeout:
            timeout = instance.stop_timeout
        if force:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda i=instance_id: self._force_kill(i))
            timer.start(max(5, safe_int(timeout, 30)) * 1000)
            self._stop_timers[instance_id] = timer

    def _force_kill(self, instance_id: str) -> None:
        process = self._processes.get(instance_id)
        if process is not None and process.state() == QProcess.Running:
            process.kill()
            self.notify("服务器未在超时内退出，已强制结束进程", "error")

    def send_command(self, text: str) -> bool:
        instance = self.current_instance()
        if instance is None:
            return False
        process = self._processes.get(instance.id)
        if process is None or process.state() != QProcess.Running:
            self.notify("服务器未在运行，无法发送命令", "error")
            return False
        try:
            process.write((text + "\n").encode("utf-8"))
        except Exception as error:  # noqa: BLE001
            self.notify("命令发送失败：%s" % error, "error")
            return False
        console = self._workspace_page.console_for(instance.id)
        if console is not None:
            console.append_output("> " + text)
        return True

    def _update_running_pill(self) -> None:
        running = sum(1 for instance in self._instances if self.is_running(instance.id))
        if running:
            self._running_button.setText("运行中 %d 个  →" % running)
            self._running_button.setToolTip("点击查看正在运行的服务器控制台")
            self._instance_badge.setText("运行中 %d / %d" % (running, len(self._instances)))
            self._instance_badge.set_state("ok")
        else:
            self._running_button.setText("未运行")
            self._running_button.setToolTip("没有运行中的服务器")
            self._instance_badge.setText("%d 个实例" % len(self._instances))
            self._instance_badge.set_state("idle")

    # ==================== 资源监控 ====================
    def _running_pids(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for instance_id, process in list(self._processes.items()):
            try:
                if process.state() == QProcess.Running:
                    pid = int(process.processId())
                    if pid:
                        result[instance_id] = pid
            except RuntimeError:
                continue
        return result

    def _start_resource_monitor(self) -> None:
        if is_running(self._resource_monitor):
            return
        monitor = ResourceMonitor(self._running_pids, self)
        monitor.cpu_updated.connect(self._instances_page.update_cpu)
        monitor.memory_updated.connect(self._instances_page.update_memory)
        monitor.disk_updated.connect(self._instances_page.update_disk)  # (read, write, percent)
        monitor.process_updated.connect(self._workspace_page.update_process_metrics)
        self._resource_monitor = monitor
        monitor.start()

    def _stop_resource_monitor(self) -> None:
        monitor = self._resource_monitor
        if monitor is None:
            return
        self._resource_monitor = None
        monitor.cancel()
        if not monitor.wait(2500):
            logger.warning("资源监控线程未能及时退出")
        monitor.deleteLater()

    # ==================== 其他功能 ====================
    def backup_world(self) -> None:
        instance = self.current_instance()
        if instance is None or not instance.has_path:
            self.notify("请先选择服务器目录", "error")
            return
        properties = read_server_properties(instance.path)
        world_name = properties.get("level-name", "world") or "world"
        world_path = Path(instance.path) / world_name
        if not world_path.is_dir():
            self.notify("还没有找到世界目录（%s），启动一次服务器后会自动生成" % world_name, "error")
            return
        target = Path(instance.path) / "backups"
        worker = BackupWorker(str(world_path), str(target), world_name)
        worker.succeeded.connect(
            lambda path: self.notify("世界已备份到 %s" % path, "success")
        )
        worker.error.connect(lambda message: self.notify(message, "error"))
        self.workers.start(worker)
        self.notify("正在后台备份世界…")

    # ==================== 窗口状态 ====================
    def _restore_window_geometry(self) -> None:
        raw = self._settings.get_str("window_geometry", "")
        if raw:
            try:
                geometry = base64.b64decode(raw.encode("ascii"))
                self.restoreGeometry(geometry)
            except Exception:
                logger.debug("恢复窗口位置失败", exc_info=True)
        else:
            self.resize(1360, 860)
        if self._settings.get_bool("window_maximized", False):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def _save_window_geometry(self) -> None:
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self._settings.set("window_geometry", geometry)
            self._settings.set("window_maximized", bool(self.isMaximized()))
        except Exception:
            logger.debug("保存窗口位置失败", exc_info=True)

    @staticmethod
    def _now() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M")

    # ==================== 退出 ====================
    def closeEvent(self, event) -> None:  # noqa: N802
        running = [instance for instance in self._instances if self.is_running(instance.id)]
        if running:
            answer = QMessageBox.question(
                self,
                "退出确认",
                "还有 %d 个服务器正在运行，退出前会先尝试正常关闭它们。\n是否继续退出？"
                % len(running),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            for instance in running:
                process = self._processes.get(instance.id)
                if process is not None and process.state() == QProcess.Running:
                    try:
                        process.write(b"stop\n")
                    except Exception:
                        pass
            for instance in running:
                process = self._processes.get(instance.id)
                if process is not None and process.state() == QProcess.Running:
                    if not process.waitForFinished(6000):
                        process.kill()
                        process.waitForFinished(2000)

        self._closing = True
        for timer in self._timers:
            timer.stop()
        self._timers.clear()
        self._save_window_geometry()
        self.persist_instances()
        self._settings.sync()
        self._stop_resource_monitor()
        self.workers.shutdown(3000)
        self.icons.shutdown()
        logger.info("程序退出")
        event.accept()