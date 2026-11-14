# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""设置页：外观、Java、JVM、停止行为、数据与日志。"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import data_dir, logs_dir
from ..model import DEFAULT_SETTINGS
from ..theme import THEMES, Theme
from ..utils import open_path
from ..widgets import Card, StatusBadge

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    """设置页。"""

    def __init__(self, app, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 12, 20, 24)
        layout.setSpacing(14)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        layout.addWidget(self._build_appearance_card())
        layout.addWidget(self._build_console_card())
        layout.addWidget(self._build_java_card())
        layout.addWidget(self._build_jvm_card())
        layout.addWidget(self._build_stop_card())
        layout.addWidget(self._build_data_card())
        layout.addStretch(1)

        self.refresh()

    # ==================== 外观 ====================
    def _build_appearance_card(self) -> Card:
        card = Card("外观")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)

        self.theme_combo = QComboBox()
        for key, theme in THEMES.items():
            self.theme_combo.addItem(theme.label, key)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow("主题", self.theme_combo)

        transparency_row = QHBoxLayout()
        self.transparency_slider = QSlider(Qt.Horizontal)
        self.transparency_slider.setRange(40, 100)
        self.transparency_slider.setSingleStep(5)
        self.transparency_slider.valueChanged.connect(self._on_transparency_changed)
        transparency_row.addWidget(self.transparency_slider, 1)
        self.transparency_value = QLabel("100%")
        self.transparency_value.setObjectName("muted")
        self.transparency_value.setFixedWidth(48)
        transparency_row.addWidget(self.transparency_value)
        widget = QWidget()
        widget.setLayout(transparency_row)
        form.addRow("窗口不透明度", widget)

        card.add(form)
        hint = QLabel("调低不透明度可以让窗口半透明，方便边看教程边操作。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _on_theme_changed(self, _index: int) -> None:
        key = self.theme_combo.currentData()
        if key:
            self.app.set_theme(str(key))

    def _on_transparency_changed(self, value: int) -> None:
        self.transparency_value.setText("%d%%" % value)
        self.app.set_transparency(value)

    # ==================== 控制台 ====================
    def _build_console_card(self) -> Card:
        card = Card("控制台")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("字号"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setSuffix(" px")
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        row.addWidget(self.font_size_spin)
        row.addSpacing(16)
        self.auto_scroll_check = QCheckBox("新日志自动滚动到底部")
        self.auto_scroll_check.toggled.connect(self._on_auto_scroll_changed)
        row.addWidget(self.auto_scroll_check)
        row.addStretch(1)
        card.add(row)
        hint = QLabel("单个控制台最多保留 20000 行，超出后自动丢弃最早的日志，避免内存持续增长。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _on_font_size_changed(self, value: int) -> None:
        self.app.settings.set("console_font_size", int(value))
        self.app.apply_console_font_size(int(value))

    def _on_auto_scroll_changed(self, checked: bool) -> None:
        self.app.settings.set("auto_scroll", bool(checked))
        self.app.apply_auto_scroll(bool(checked))

    # ==================== Java ====================
    def _build_java_card(self) -> Card:
        card = Card("Java 运行环境")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.java_state = StatusBadge("检测中", "idle")
        row.addWidget(self.java_state)
        self.java_path_label = QLabel("正在检测…")
        self.java_path_label.setObjectName("muted")
        self.java_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.java_path_label, 1)
        card.add(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        detect = QPushButton("重新检测")
        detect.clicked.connect(self.app.detect_java)
        buttons.addWidget(detect)
        choose = QPushButton("手动选择 java")
        choose.clicked.connect(self._choose_java)
        buttons.addWidget(choose)
        clear = QPushButton("清除自定义路径")
        clear.clicked.connect(self._clear_java)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        card.add(buttons)

        hint = QLabel("Minecraft 需要 Java 才能运行：1.17 以下建议 Java 8，1.18 及以上建议 Java 17 或更高。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _choose_java(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择 java 可执行文件",
            "",
            "可执行文件 (*.exe);;所有文件 (*)",
        )
        if not filename:
            return
        self.app.settings.set("java_path", filename)
        self.app.detect_java()
        self.app.notify("已保存自定义 Java 路径", "success")

    def _clear_java(self) -> None:
        self.app.settings.set("java_path", "")
        self.app.detect_java()
        self.app.notify("已切换为自动检测 Java", "success")

    def update_java(self, info) -> None:
        if info is not None and getattr(info, "ok", False):
            self.java_state.setText("可用")
            self.java_state.set_state("ok")
            self.java_path_label.setText("%s  ·  %s" % (info.version or "", info.path))
            self.java_path_label.setToolTip(info.path)
        else:
            self.java_state.setText("未检测到")
            self.java_state.set_state("error")
            message = getattr(info, "error", "") if info is not None else ""
            self.java_path_label.setText(message or "未找到 Java，请安装后重新检测")
            self.java_path_label.setToolTip("")

    # ==================== 全局 JVM ====================
    def _build_jvm_card(self) -> Card:
        card = Card("全局 JVM 参数")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.global_args_edit = QLineEdit()
        self.global_args_edit.setPlaceholderText("例如：-XX:+UseG1GC -Dfile.encoding=UTF-8")
        row.addWidget(self.global_args_edit, 1)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self._save_global_args)
        row.addWidget(save)
        card.add(row)
        hint = QLabel("会追加到每个实例的启动参数中；实例自己的 JVM 参数优先级更高。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _save_global_args(self) -> None:
        value = self.global_args_edit.text().strip()
        self.app.settings.set("global_jvm_args", value)
        self.app.reload_global_args()
        self.app.notify("全局 JVM 参数已保存", "success")

    # ==================== 停止行为 ====================
    def _build_stop_card(self) -> Card:
        card = Card("服务器停止行为")
        self.force_stop_check = QCheckBox("发送 stop 后超时仍未退出时强制结束进程")
        self.force_stop_check.toggled.connect(
            lambda checked: self.app.settings.set("force_stop_on_timeout", bool(checked))
        )
        card.add(self.force_stop_check)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("超时时间"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.valueChanged.connect(
            lambda value: self.app.settings.set("stop_timeout", int(value))
        )
        row.addWidget(self.timeout_spin)
        row.addStretch(1)
        card.add(row)
        return card

    # ==================== 数据 ====================
    def _build_data_card(self) -> Card:
        card = Card("数据与日志")
        path_label = QLabel("数据目录：%s" % data_dir())
        path_label.setObjectName("muted")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(path_label)

        log_label = QLabel("日志目录：%s" % logs_dir())
        log_label.setObjectName("muted")
        log_label.setWordWrap(True)
        log_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(log_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        open_data = QPushButton("打开数据目录")
        open_data.clicked.connect(lambda: open_path(data_dir()))
        row.addWidget(open_data)
        open_logs = QPushButton("打开日志目录")
        open_logs.clicked.connect(lambda: open_path(logs_dir()))
        row.addWidget(open_logs)
        reset = QPushButton("恢复默认设置")
        reset.clicked.connect(self._restore_defaults)
        row.addWidget(reset)
        row.addStretch(1)
        card.add(row)

        hint = QLabel("恢复默认设置只会重置界面与启动参数，不会删除实例和服务器文件。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认设置",
            "确定要把所有设置恢复为默认值吗？实例与服务器文件不会受影响。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        for key, value in DEFAULT_SETTINGS.items():
            self.app.settings.set(key, value)
        self.app.settings.set("stop_timeout", 30)
        self.app.apply_default_settings()
        self.refresh()
        self.app.notify("已恢复默认设置", "success")

    # ==================== 刷新 ====================
    def refresh(self) -> None:
        settings = self.app.settings
        blocked = [self.theme_combo, self.transparency_slider, self.font_size_spin, self.auto_scroll_check,
                   self.force_stop_check, self.timeout_spin, self.global_args_edit]
        for widget in blocked:
            widget.blockSignals(True)

        theme_key = str(settings.get("theme", "dark"))
        index = self.theme_combo.findData(theme_key)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        transparency = settings.get_int("window_transparency_percent", 100)
        self.transparency_slider.setValue(max(40, min(100, transparency)))
        self.transparency_value.setText("%d%%" % transparency)

        self.font_size_spin.setValue(settings.get_int("console_font_size", 12))
        self.auto_scroll_check.setChecked(settings.get_bool("auto_scroll", True))
        self.global_args_edit.setText(settings.get_str("global_jvm_args", ""))
        self.force_stop_check.setChecked(settings.get_bool("force_stop_on_timeout", False))
        self.timeout_spin.setValue(max(5, min(600, settings.get_int("stop_timeout", 30))))

        for widget in blocked:
            widget.blockSignals(False)

        self.update_java(self.app.java_info)

    def restyle(self, theme: Theme) -> None:
        self.update_java(self.app.java_info)