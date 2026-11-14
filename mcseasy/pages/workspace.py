# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""实例工作台：只处理「这一台服务器」。

顶部是身份与状态，下面分成两个标签页：

    概览  — 按状态显示：开始使用 / 准备启动 / 实例概览 / 运行状态
    控制台 — 日志、查找、导出与命令输入

启动服务器后会自动切到控制台，让用户立刻看到输出。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model import Instance, check_launch_readiness, detect_server, read_server_properties
from ..theme import Theme
from ..utils import format_duration, open_path
from ..widgets import (
    Card,
    ChecklistRow,
    ConsoleView,
    ElidedLabel,
    HistoryLineEdit,
    IconButton,
    StatusBadge,
    apply_property,
)

logger = logging.getLogger(__name__)


class WorkspacePage(QWidget):
    """单实例工作台。"""

    PANEL_ONBOARDING = 0
    PANEL_PREPARE = 1
    PANEL_READY = 2
    PANEL_RUNNING = 3

    TAB_OVERVIEW = 0
    TAB_CONSOLE = 1

    def __init__(self, app, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.app = app
        self._consoles: Dict[str, ConsoleView] = {}
        self._checks: Dict[str, ChecklistRow] = {}
        self._build_ui()

    # ==================== 构建 ====================
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.setObjectName("workspaceTabs")
        self.tabs.addTab(self._build_overview_tab(), "概览")
        self.tabs.addTab(self._build_console_tab(), "控制台")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)

        self.back_button = QPushButton("返回列表")
        self.back_button.setObjectName("ghost")
        self.back_button.setIcon(self.app.theme.icon("arrow-left", 16, "subtext"))
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.clicked.connect(self.app.back_to_instances)
        header.addWidget(self.back_button)

        self.name_label = ElidedLabel("—")
        self.name_label.setObjectName("pageTitle")
        self.name_label.setMinimumWidth(120)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header.addWidget(self.name_label, 1)

        self.status_badge = StatusBadge("已停止", "idle")
        header.addWidget(self.status_badge)

        self.more_button = QPushButton("更多操作")
        self.more_button.setIcon(self.app.theme.icon("settings", 16, "subtext"))
        self.more_button.setCursor(Qt.PointingHandCursor)
        self.more_button.clicked.connect(self._show_more_menu)
        header.addWidget(self.more_button)
        return header

    # ---- 概览页 ----
    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(12, 14, 12, 12)
        outer.setSpacing(12)

        left = QWidget()
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.state_stack = QStackedWidget()
        self.state_stack.addWidget(self._build_onboarding_panel())
        self.state_stack.addWidget(self._build_prepare_panel())
        self.state_stack.addWidget(self._build_ready_panel())
        self.state_stack.addWidget(self._build_running_panel())
        self.state_stack.setCurrentIndex(self.PANEL_ONBOARDING)
        layout.addWidget(self.state_stack, 1)

        self.action_hint = QLabel("")
        self.action_hint.setObjectName("actionHint")
        self.action_hint.setWordWrap(True)
        self.action_hint.hide()
        layout.addWidget(self.action_hint)
        outer.addWidget(left, 3)

        # 右侧：最近日志预览（一键跳到完整控制台）
        self.preview_card = Card("最近日志")
        self.preview_card.setMinimumWidth(300)
        self.preview_card.setMaximumWidth(420)
        self.log_preview = QPlainTextEdit()
        self.log_preview.setObjectName("console")
        self.log_preview.setReadOnly(True)
        self.log_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_preview.setMaximumBlockCount(200)
        self.log_preview.setPlaceholderText("暂无日志，启动服务器后这里会显示最近几行输出。")
        self.log_preview.setAccessibleName("最近日志预览")
        self.preview_card.add(self.log_preview)
        self.open_console_button = QPushButton("查看完整控制台")
        self.open_console_button.setObjectName("ghost")
        self.open_console_button.setIcon(self.app.theme.icon("chevron-right", 14, "subtext"))
        self.open_console_button.setLayoutDirection(Qt.RightToLeft)
        self.open_console_button.clicked.connect(self.show_console)
        self.preview_card.add(self.open_console_button)
        outer.addWidget(self.preview_card, 2)

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(1000)
        self._preview_timer.timeout.connect(self.refresh_log_preview)
        return page

    def _on_tab_changed(self, index: int) -> None:
        if index == self.TAB_OVERVIEW:
            self.refresh_log_preview()
            instance = self.app.current_instance()
            if instance is not None and self.app.is_running(instance.id):
                self._preview_timer.start()
        else:
            self._preview_timer.stop()

    def refresh_log_preview(self) -> None:
        """把控制台最后几行同步到概览页，方便不切换标签就能扫一眼。"""
        instance = self.app.current_instance()
        console = self._consoles.get(instance.id) if instance else None
        if console is None:
            self.log_preview.clear()
            return
        lines = console.toPlainText().splitlines()[-40:]
        self.log_preview.setPlainText("\n".join(lines))
        bar = self.log_preview.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _build_onboarding_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = Card("开始使用")
        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(self.app.theme.pixmap("server", 46, "accent"))
        card.add(icon)

        title = QLabel("先给这个实例一个服务器目录")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        card.add(title)

        hint = QLabel("可以选一个已经装好的服务器文件夹，也可以下载一个全新的服务端核心。")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        card.add(hint)

        self.onboarding_pick_button = QPushButton("选择已有文件夹")
        self.onboarding_pick_button.setIcon(self.app.theme.icon("folder", 18, "on_accent"))
        self.onboarding_pick_button.setObjectName("primary")
        self.onboarding_pick_button.setMinimumHeight(38)
        self.onboarding_pick_button.clicked.connect(self._select_directory)
        card.add(self.onboarding_pick_button)

        self.onboarding_download_button = QPushButton("去下载服务端核心")
        self.onboarding_download_button.setIcon(self.app.theme.icon("download", 18, "subtext"))
        self.onboarding_download_button.setMinimumHeight(38)
        self.onboarding_download_button.clicked.connect(
            lambda: self.app.open_download_page(return_to_workspace=True)
        )
        card.add(self.onboarding_download_button)

        tip = QLabel("小提示：也可以在「主页」把服务器文件夹拖到实例卡片上。")
        tip.setObjectName("muted")
        tip.setAlignment(Qt.AlignCenter)
        tip.setWordWrap(True)
        card.add(tip)

        card.setMaximumWidth(620)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        layout.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return panel

    def _build_prepare_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = Card("准备启动")
        intro = QLabel("完成下面几项后就能启动服务器，点击右侧按钮可直接处理。")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        card.add(intro)

        rows = QVBoxLayout()
        rows.setContentsMargins(0, 4, 0, 4)
        rows.setSpacing(2)
        for key in ("java", "core", "installer", "port"):
            row = ChecklistRow(self.app.theme)
            row.action_triggered.connect(self._on_check_action)
            row.hide()
            self._checks[key] = row
            rows.addWidget(row)
        card.add(rows)

        self.recheck_button = QPushButton("重新检查")
        self.recheck_button.setObjectName("ghost")
        self.recheck_button.clicked.connect(self.app.recheck_environment)
        card.add(self.recheck_button)

        card.setMaximumWidth(620)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        layout.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return panel

    def _build_ready_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = Card("实例概览")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)

        self.path_label = ElidedLabel("未选择目录")
        self.path_label.setObjectName("value")
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.addWidget(self.path_label, 1)
        self.pick_path_button = QPushButton("更换")
        self.pick_path_button.clicked.connect(self._select_directory)
        path_row.addWidget(self.pick_path_button)
        self.reveal_button = IconButton(self.app.theme, "folder", "打开实例目录", 16)
        self.reveal_button.clicked.connect(self._open_directory)
        path_row.addWidget(self.reveal_button)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        form.addRow("目录", path_widget)

        self.server_type_badge = StatusBadge("未识别", "idle")
        self.server_version_label = QLabel("")
        self.server_version_label.setObjectName("muted")
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(self.server_type_badge)
        type_row.addWidget(self.server_version_label)
        type_row.addStretch(1)
        type_widget = QWidget()
        type_widget.setLayout(type_row)
        form.addRow("服务端", type_widget)

        self.memory_label = QLabel("2 GB ~ 4 GB")
        self.memory_label.setObjectName("value")
        form.addRow("内存", self.memory_label)

        self.properties_label = QLabel("—")
        self.properties_label.setObjectName("value")
        form.addRow("服务器配置", self.properties_label)

        self.last_played_label = QLabel("从未启动")
        self.last_played_label.setObjectName("muted")
        form.addRow("最近启动", self.last_played_label)

        self.jvm_label = QLabel("默认")
        self.jvm_label.setObjectName("muted")
        form.addRow("JVM 参数", self.jvm_label)
        card.add(form)

        quick_title = QLabel("快捷操作")
        quick_title.setObjectName("muted")
        card.add(quick_title)

        quick = QGridLayout()
        quick.setSpacing(8)
        self._quick_buttons = []
        for index, (icon_name, text, handler) in enumerate(
            (
                ("folder", "打开目录", self._open_directory),
                ("package", "模组目录", self._open_mods),
                ("plugin-and-mod", "插件目录", self._open_plugins),
                ("world", "备份世界", self.app.backup_world),
            )
        ):
            button = QPushButton(text)
            button.setIcon(self.app.theme.icon(icon_name, 16, "subtext"))
            button.setMinimumHeight(34)
            button.clicked.connect(handler)
            quick.addWidget(button, index // 2, index % 2)
            self._quick_buttons.append((button, icon_name))
        card.add(quick)
        card.body.addStretch(1)

        self.start_button = QPushButton("启动服务器")
        self.start_button.setObjectName("success")
        self.start_button.setAccessibleName("启动服务器")
        self.start_button.setIcon(self.app.theme.icon("play", 18, "on_green"))
        self.start_button.setMinimumHeight(44)
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.app.start_current_server)
        card.add(self.start_button)

        layout.addWidget(card, 1)
        return panel

    def _build_running_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = Card("运行状态")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)

        self.run_uptime_label = QLabel("—")
        self.run_uptime_label.setObjectName("valueStrong")
        form.addRow("运行时长", self.run_uptime_label)

        self.run_mem_label = QLabel("—")
        self.run_mem_label.setObjectName("value")
        form.addRow("进程内存", self.run_mem_label)

        self.run_cpu_label = QLabel("—")
        self.run_cpu_label.setObjectName("value")
        form.addRow("进程 CPU", self.run_cpu_label)

        self.run_port_label = QLabel("—")
        self.run_port_label.setObjectName("value")
        form.addRow("监听端口", self.run_port_label)

        self.run_world_label = QLabel("—")
        self.run_world_label.setObjectName("value")
        form.addRow("世界", self.run_world_label)
        card.add(form)
        card.body.addStretch(1)

        self.stop_button = QPushButton("停止服务器")
        self.stop_button.setObjectName("danger")
        self.stop_button.setAccessibleName("停止服务器")
        self.stop_button.setIcon(self.app.theme.icon("stop", 18, "on_red"))
        self.stop_button.setMinimumHeight(44)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.clicked.connect(self.app.stop_current_server)
        card.add(self.stop_button)

        self.running_open_button = QPushButton("打开服务器目录")
        self.running_open_button.setObjectName("ghost")
        self.running_open_button.setIcon(self.app.theme.icon("folder", 16, "subtext"))
        self.running_open_button.clicked.connect(self._open_directory)
        card.add(self.running_open_button)

        hint = QLabel("停止时会先发送 stop 命令，让服务器保存世界后再退出。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)

        layout.addWidget(card, 1)
        return panel

    # ---- 控制台页 ----
    def _build_console_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.search_button = IconButton(self.app.theme, "search", "查找 (Ctrl+F)", 16)
        self.search_button.clicked.connect(self._toggle_search)
        toolbar.addWidget(self.search_button)

        self.clear_button = IconButton(self.app.theme, "trash", "清空控制台", 16)
        self.clear_button.clicked.connect(self._clear_console)
        toolbar.addWidget(self.clear_button)

        self.export_button = IconButton(self.app.theme, "save", "导出控制台日志", 16)
        self.export_button.clicked.connect(self._export_console)
        toolbar.addWidget(self.export_button)

        toolbar.addStretch(1)
        self.auto_scroll_check = QCheckBox("自动滚动")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.toggled.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self.auto_scroll_check)
        layout.addLayout(toolbar)

        search_bar = QWidget()
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("在控制台中查找…")
        self.search_edit.setAccessibleName("在控制台中查找")
        self.search_edit.textChanged.connect(self._on_search_text)
        self.search_edit.returnPressed.connect(lambda: self._find_next(False))
        search_layout.addWidget(self.search_edit, 1)
        self.search_count = QLabel("")
        self.search_count.setObjectName("muted")
        search_layout.addWidget(self.search_count)
        self.search_prev_button = IconButton(self.app.theme, "arrow-up", "上一个", 14)
        self.search_prev_button.clicked.connect(lambda: self._find_next(True))
        search_layout.addWidget(self.search_prev_button)
        self.search_next_button = IconButton(self.app.theme, "arrow-down", "下一个", 14)
        self.search_next_button.clicked.connect(lambda: self._find_next(False))
        search_layout.addWidget(self.search_next_button)
        self.search_close_button = IconButton(self.app.theme, "x", "关闭查找", 14)
        self.search_close_button.clicked.connect(self._toggle_search)
        search_layout.addWidget(self.search_close_button)
        self.search_bar = search_bar
        search_bar.hide()
        layout.addWidget(search_bar)

        self.console_stack = QStackedWidget()
        self.console_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.console_stack, 1)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)
        self.command_edit = HistoryLineEdit()
        self.command_edit.setAccessibleName("服务器命令输入")
        self.command_edit.setAccessibleDescription("按回车发送；用上下方向键翻阅历史命令")
        self.command_edit.setPlaceholderText("输入命令，回车发送（↑/↓ 历史）")
        self.command_edit.returnPressed.connect(self._send_command)
        command_row.addWidget(self.command_edit, 1)

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("primary")
        self.send_button.setAccessibleName("发送命令")
        self.send_button.clicked.connect(self._send_command)
        command_row.addWidget(self.send_button)
        layout.addLayout(command_row)
        return page

    # ==================== 状态刷新 ====================
    def show_console(self) -> None:
        self._preview_timer.stop()
        self.tabs.setCurrentIndex(self.TAB_CONSOLE)

    def show_overview(self) -> None:
        self.tabs.setCurrentIndex(self.TAB_OVERVIEW)

    def update_instance_view(self) -> None:
        instance = self.app.current_instance()
        if instance is None:
            self.name_label.set_full_text("未选择实例")
            self.status_badge.setText("未选择")
            self.status_badge.set_state("idle")
            self.state_stack.setCurrentIndex(self.PANEL_ONBOARDING)
            self.action_hint.hide()
            return

        self.name_label.set_full_text(instance.display_name())
        process_state = self.app.process_state(instance.id)
        readiness = check_launch_readiness(instance, self.app.java_info)

        badge = {
            "starting": ("启动中", "warn"),
            "running": ("运行中", "ok"),
            "stopping": ("停止中", "warn"),
        }.get(process_state, ("已停止", "idle"))
        self.status_badge.setText(badge[0])
        self.status_badge.set_state(badge[1])

        self._update_checklist(readiness)
        self._update_ready_panel(instance)
        self._update_running_panel(instance)

        if not instance.path or not os.path.isdir(instance.path):
            panel = self.PANEL_ONBOARDING
        elif not readiness.ok:
            panel = self.PANEL_PREPARE
        elif process_state in ("starting", "running", "stopping"):
            panel = self.PANEL_RUNNING
        else:
            panel = self.PANEL_READY
        self.state_stack.setCurrentIndex(panel)

        running_command = process_state == "running"
        self.command_edit.setEnabled(running_command)
        self.send_button.setEnabled(running_command)
        self.send_button.setToolTip("" if running_command else "服务器未运行时无法发送命令")
        self.command_edit.setPlaceholderText(
            "输入命令，回车发送（↑/↓ 历史）"
            if running_command
            else "服务器未运行，启动后即可发送命令"
        )

        if process_state == "stopping":
            self.stop_button.setText("正在停止…")
            self.stop_button.setEnabled(False)
        else:
            self.stop_button.setText("停止服务器")
            self.stop_button.setEnabled(True)
        self.start_button.setEnabled(readiness.ok and process_state != "starting")
        self.start_button.setToolTip("" if readiness.ok else readiness.message())

        # 服务器自己在运行时端口当然被占用，此时不再提示端口冲突
        warning = readiness.warning if process_state == "stopped" else ""
        self.action_hint.setText(warning or "")
        self.action_hint.setVisible(bool(warning))
        apply_property(self.action_hint, "level", "warn" if warning else "")

        self._show_console_for(instance.id)
        self.preview_card.setVisible(panel in (self.PANEL_READY, self.PANEL_RUNNING))
        self.refresh_log_preview()

    def _update_checklist(self, readiness) -> None:
        for row in self._checks.values():
            row.hide()
        for check in readiness.checks:
            key = check.get("key", "")
            row = self._checks.get(key)
            if row is None:
                continue
            action_label = ""
            if not check.get("ok"):
                action_label = {
                    "java": "去设置",
                    "core": "去下载",
                    "installer": "运行安装器",
                }.get(key, "")
            row.configure(
                self.app.theme,
                key,
                bool(check.get("ok")),
                str(check.get("title") or ""),
                str(check.get("detail") or ""),
                action_label,
            )
            row.show()

    def _on_check_action(self, key: str) -> None:
        if key == "java":
            self.app.open_settings_page()
        elif key == "core":
            self.app.open_download_page(return_to_workspace=True)
        elif key == "installer":
            self.app.run_installer_for_current()

    def _update_ready_panel(self, instance: Instance) -> None:
        self.path_label.set_full_text(instance.path or "未选择目录")
        self.pick_path_button.setText("更换" if instance.path else "选择")
        self.reveal_button.setEnabled(bool(instance.path) and os.path.isdir(instance.path))

        server_type, version = ("", "")
        if instance.path and os.path.isdir(instance.path):
            server_type, version = detect_server(instance.path)
        server_type = server_type or instance.loader
        version = version or instance.mc_version

        if server_type:
            self.server_type_badge.setText(server_type)
            self.server_type_badge.set_state("accent")
        else:
            self.server_type_badge.setText("未识别")
            self.server_type_badge.set_state("idle")
        self.server_version_label.setText(("MC " + version) if version else "")

        self.memory_label.setText("%d GB ~ %d GB" % (instance.min_mem, instance.max_mem))
        args = instance.custom_args.strip()
        self.jvm_label.setText(args if len(args) <= 80 else args[:77] + "…")
        self.jvm_label.setToolTip(args)
        self.jvm_label.setText("默认" if not args else self.jvm_label.text())

        properties = read_server_properties(instance.path) if instance.path else {}
        parts = []
        if properties.get("server-port"):
            parts.append("端口 %s" % properties["server-port"])
        if properties.get("max-players"):
            parts.append("上限 %s 人" % properties["max-players"])
        if properties.get("level-name"):
            parts.append("世界 %s" % properties["level-name"])
        self.properties_label.setText(" · ".join(parts) if parts else "—")
        self.last_played_label.setText(instance.last_played or "从未启动")

        self.run_port_label.setText(str(properties.get("server-port", "25565")))
        self.run_world_label.setText(str(properties.get("level-name", "world")))

    def _update_running_panel(self, instance: Instance) -> None:
        if not self.app.is_running(instance.id):
            self.run_uptime_label.setText("—")
            self.run_mem_label.setText("—")
            self.run_cpu_label.setText("—")

    def update_process_metrics(self, metrics: dict) -> None:
        instance = self.app.current_instance()
        if instance is None:
            return
        data = metrics.get(instance.id)
        if not data:
            self.run_uptime_label.setText("—")
            self.run_mem_label.setText("—")
            self.run_cpu_label.setText("—")
            return
        cpu, rss_mb, uptime = data
        self.run_uptime_label.setText(format_duration(uptime))
        self.run_mem_label.setText("%.0f MB" % rss_mb)
        self.run_cpu_label.setText("%.0f%%" % cpu)

    # ==================== 控制台 ====================
    def console_for(self, instance_id: str) -> Optional[ConsoleView]:
        if not instance_id:
            return None
        console = self._consoles.get(instance_id)
        if console is not None:
            return console
        console = ConsoleView(self.app.theme)
        console.set_auto_scroll(self.auto_scroll_check.isChecked())
        console.apply_font_size(self.app.settings.get_int("console_font_size", 12))
        console.set_empty_text(
            "还没有日志",
            "启动服务器后，日志会实时显示在这里；也可以直接输入 list、say、stop 等命令。",
        )
        self._consoles[instance_id] = console
        self.console_stack.addWidget(console)
        return console

    def _show_console_for(self, instance_id: str) -> None:
        console = self.console_for(instance_id)
        if console is not None and self.console_stack.currentWidget() is not console:
            self.console_stack.setCurrentWidget(console)

    def remove_console(self, instance_id: str) -> None:
        console = self._consoles.pop(instance_id, None)
        if console is not None:
            self.console_stack.removeWidget(console)
            console.deleteLater()

    def prune_consoles(self, valid_ids) -> None:
        for instance_id in list(self._consoles):
            if instance_id not in valid_ids:
                self.remove_console(instance_id)

    def _current_console(self) -> Optional[ConsoleView]:
        instance = self.app.current_instance()
        return self.console_for(instance.id) if instance else None

    def _send_command(self) -> None:
        text = self.command_edit.text().strip()
        if not text:
            return
        if self.app.send_command(text):
            self.command_edit.add_history(text)
            self.command_edit.clear()

    def _clear_console(self) -> None:
        console = self._current_console()
        if console is not None:
            console.clear_console()

    def _export_console(self) -> None:
        console = self._current_console()
        instance = self.app.current_instance()
        if console is None or instance is None:
            return
        default_name = (instance.name or "console") + "-console.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出控制台日志", default_name, "文本文件 (*.txt *.log);;所有文件 (*)"
        )
        if not path:
            return
        if console.save_to_file(path):
            self.app.notify("控制台日志已保存", "success")
        else:
            self.app.notify("保存失败，请检查路径权限", "error")

    def _on_auto_scroll_toggled(self, checked: bool) -> None:
        for console in self._consoles.values():
            console.set_auto_scroll(checked)
        self.app.settings.set("auto_scroll", bool(checked))

    def _toggle_search(self) -> None:
        visible = not self.search_bar.isVisible()
        self.search_bar.setVisible(visible)
        if visible:
            self.search_edit.setFocus()
            self.search_edit.selectAll()
        else:
            console = self._current_console()
            if console is not None:
                console.set_search("")
            self.search_count.setText("")

    def _on_search_text(self, text: str) -> None:
        console = self._current_console()
        if console is None:
            return
        count = console.set_search(text)
        self.search_count.setText("%d 处" % count if text else "")
        if text and count:
            self._find_next(False)

    def _find_next(self, backward: bool) -> None:
        console = self._current_console()
        if console is None:
            return
        if console.find_next(backward):
            total = console.match_count()
            current = console.current_match() + 1
            self.search_count.setText("%d/%d" % (current, total))

    # ==================== 目录与菜单 ====================
    def _select_directory(self) -> None:
        instance = self.app.current_instance()
        if instance is None:
            return
        start_dir = instance.path if instance.path and os.path.isdir(instance.path) else ""
        path = QFileDialog.getExistingDirectory(self, "选择服务器实例目录", start_dir)
        if not path:
            return
        self.app.set_instance_path(instance.id, path)

    def _open_directory(self) -> None:
        instance = self.app.current_instance()
        if instance is None or not instance.path:
            self.app.notify("请先选择服务器目录", "error")
            return
        if not open_path(instance.path):
            self.app.notify("无法打开目录，可能已被移动或删除", "error")

    def _show_more_menu(self) -> None:
        instance = self.app.current_instance()
        if instance is None:
            return
        has_path = instance.has_path
        menu = QMenu(self)

        menu.addAction(self.app.theme.icon("settings", 16), "版本设置", self.app.show_version_settings)
        menu.addAction(self.app.theme.icon("activity", 16), "JVM 设置", self.app.show_jvm_settings)
        menu.addSeparator()
        open_action = menu.addAction(self.app.theme.icon("folder", 16), "打开服务器目录", self._open_directory)
        mods_action = menu.addAction(self.app.theme.icon("package", 16), "打开模组目录", self._open_mods)
        plugins_action = menu.addAction(
            self.app.theme.icon("plugin-and-mod", 16), "打开插件目录", self._open_plugins
        )
        properties_action = menu.addAction(
            self.app.theme.icon("save", 16), "打开 server.properties", self._open_properties
        )
        menu.addSeparator()
        backup_action = menu.addAction(self.app.theme.icon("world", 16), "备份世界", self.app.backup_world)
        menu.addAction(self.app.theme.icon("refresh", 16), "重新检测服务端", self._redetect)

        for action in (open_action, mods_action, plugins_action, properties_action, backup_action):
            action.setEnabled(has_path)
        menu.exec(self.more_button.mapToGlobal(QPoint(0, self.more_button.height())))

    def _open_mods(self) -> None:
        self._open_subdirectory("mods", "模组")

    def _open_plugins(self) -> None:
        self._open_subdirectory("plugins", "插件")

    def _open_subdirectory(self, name: str, label: str) -> None:
        instance = self.app.current_instance()
        if instance is None or not instance.has_path:
            self.app.notify("请先选择服务器目录", "error")
            return
        target = Path(instance.path) / name
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.app.notify("无法创建%s目录：%s" % (label, error), "error")
            return
        if not open_path(target):
            self.app.notify("无法打开目录", "error")

    def _open_properties(self) -> None:
        instance = self.app.current_instance()
        if instance is None or not instance.has_path:
            self.app.notify("请先选择服务器目录", "error")
            return
        target = Path(instance.path) / "server.properties"
        if not target.exists():
            self.app.notify("该目录下还没有 server.properties，启动一次服务器后会自动生成", "error")
            return
        if not open_path(target):
            self.app.notify("无法打开文件，请检查是否关联了编辑器", "error")

    def _redetect(self) -> None:
        self.app.refresh_instances()
        self.app.notify("已重新检测服务端信息", "success")

    # ==================== 主题 ====================
    def restyle(self, theme: Theme) -> None:
        self.back_button.setIcon(theme.icon("arrow-left", 16, "subtext"))
        self.more_button.setIcon(theme.icon("settings", 16, "subtext"))
        self.open_console_button.setIcon(theme.icon("chevron-right", 14, "subtext"))
        self.onboarding_pick_button.setIcon(theme.icon("folder", 18, "on_accent"))
        self.onboarding_download_button.setIcon(theme.icon("download", 18, "subtext"))
        self.start_button.setIcon(theme.icon("play", 18, "on_green"))
        self.stop_button.setIcon(theme.icon("stop", 18, "on_red"))
        self.running_open_button.setIcon(theme.icon("folder", 16, "subtext"))
        for button, icon_name in self._quick_buttons:
            button.setIcon(theme.icon(icon_name, 16, "subtext"))
        for button, name, size in (
            (self.search_button, "search", 16),
            (self.clear_button, "trash", 16),
            (self.export_button, "save", 16),
            (self.reveal_button, "folder", 16),
            (self.search_prev_button, "arrow-up", 14),
            (self.search_next_button, "arrow-down", 14),
            (self.search_close_button, "x", 14),
        ):
            button.setIcon(theme.icon(name, size, "subtext"))
        for console in self._consoles.values():
            console.set_theme(theme)