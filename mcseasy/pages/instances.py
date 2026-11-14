# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""主页：服务器实例卡片墙。

只负责回答一个问题：「我有哪几台服务器，它们现在怎么样」。
点击卡片进入实例工作台；启动/停止可以直接在卡片上完成。
系统资源收成底部一条细状态条，不抢主内容的注意力。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..model import Instance, detect_server
from ..theme import Theme
from ..utils import human_size, open_path
from ..widgets import (
    ElidedLabel,
    IconButton,
    MiniMeter,
    StatusBadge,
    apply_property,
)

logger = logging.getLogger(__name__)


class InstanceCard(QFrame):
    """一台服务器的概览卡片。"""

    open_requested = Signal(str)
    start_requested = Signal(str)
    stop_requested = Signal(str)
    menu_requested = Signal(str, QPoint)
    folder_dropped = Signal(str, str)

    def __init__(self, theme: Theme, instance: Instance, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("instanceCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._instance_id = instance.id
        self._theme = theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_label = ElidedLabel(instance.display_name())
        self.name_label.setObjectName("instanceName")
        top.addWidget(self.name_label, 1)
        self.type_label = QLabel("未识别")
        self.type_label.setObjectName("muted")
        top.addWidget(self.type_label, 0, Qt.AlignTop)
        layout.addLayout(top)

        self.path_label = ElidedLabel(instance.path or "未选择目录")
        self.path_label.setObjectName("muted")
        layout.addWidget(self.path_label)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.state_badge = StatusBadge("已停止", "idle")
        meta.addWidget(self.state_badge)
        self.last_label = QLabel("从未启动")
        self.last_label.setObjectName("muted")
        meta.addWidget(self.last_label, 1)
        self.memory_label = QLabel("")
        self.memory_label.setObjectName("muted")
        meta.addWidget(self.memory_label)
        layout.addLayout(meta)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.action_button = QPushButton("启动")
        self.action_button.setObjectName("primary")
        self.action_button.setFixedHeight(32)
        self.action_button.setMinimumWidth(84)
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.clicked.connect(self._on_action)
        actions.addWidget(self.action_button)

        self.open_button = QPushButton("进入")
        self.open_button.setObjectName("ghost")
        self.open_button.setIcon(theme.icon("chevron-right", 14, "subtext"))
        self.open_button.setFixedHeight(32)
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.clicked.connect(lambda: self.open_requested.emit(self._instance_id))
        actions.addWidget(self.open_button)

        actions.addStretch(1)
        self.menu_button = IconButton(theme, "settings", "更多操作", 16)
        self.menu_button.clicked.connect(self._on_menu)
        actions.addWidget(self.menu_button)
        layout.addLayout(actions)

        self.update_content(instance, "stopped")

    # ---- 数据 ----
    def update_content(self, instance: Instance, process_state: str) -> None:
        self._instance_id = instance.id
        self.name_label.set_full_text(instance.display_name())
        self.setAccessibleName("服务器 %s" % instance.display_name())
        self.path_label.set_full_text(instance.path or "未选择目录")

        server_type, version = ("", "")
        if instance.path and os.path.isdir(instance.path):
            server_type, version = detect_server(instance.path)
        server_type = server_type or instance.loader
        version = version or instance.mc_version
        if server_type:
            self.type_label.setText(("%s %s" % (server_type, version)).strip())
        else:
            self.type_label.setText("未识别")
        self.last_label.setText(instance.last_played or "从未启动")
        self.memory_label.setText("%d ~ %d GB" % (instance.min_mem, instance.max_mem))

        state_text, state_key = {
            "starting": ("启动中", "warn"),
            "running": ("运行中", "ok"),
            "stopping": ("停止中", "warn"),
            "error": ("异常", "error"),
        }.get(process_state, ("已停止", "idle"))
        self.state_badge.setText(state_text)
        self.state_badge.set_state(state_key)
        apply_property(self, "running", process_state == "running")
        self.state_badge.setAccessibleName("%s：%s" % (instance.display_name(), state_text))

        if process_state == "starting":
            self.action_button.setText("启动中")
            self.action_button.setObjectName("primary")
            self.action_button.setEnabled(False)
        elif process_state == "running":
            self.action_button.setText("停止")
            self.action_button.setObjectName("danger")
            self.action_button.setEnabled(True)
        elif process_state == "stopping":
            self.action_button.setText("停止中")
            self.action_button.setObjectName("danger")
            self.action_button.setEnabled(False)
        else:
            self.action_button.setText("启动")
            self.action_button.setObjectName("primary")
            self.action_button.setEnabled(bool(instance.path) and os.path.isdir(instance.path))
            if not self.action_button.isEnabled():
                self.action_button.setToolTip("先为这个实例选择服务器目录")
            else:
                self.action_button.setToolTip("")

        style = self.action_button.style()
        style.unpolish(self.action_button)
        style.polish(self.action_button)
        self.open_button.setAccessibleName("进入 %s" % instance.display_name())
        self.action_button.setAccessibleName(
            "%s %s" % (self.action_button.text(), instance.display_name())
        )
        self.setToolTip(instance.path or "未选择目录")

    # ---- 交互 ----
    def _on_action(self) -> None:
        if self.action_button.text() == "启动":
            self.start_requested.emit(self._instance_id)
        else:
            self.stop_requested.emit(self._instance_id)

    def _on_menu(self) -> None:
        self.menu_requested.emit(self._instance_id, self.menu_button.mapToGlobal(QPoint(0, 28)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.open_requested.emit(self._instance_id)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        apply_property(self, "hovered", True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        apply_property(self, "hovered", False)
        super().leaveEvent(event)

    # ---- 拖放导入 ----
    @staticmethod
    def _first_directory(event) -> str:  # noqa: ANN001
        mime = event.mimeData()
        if not mime.hasUrls():
            return ""
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            candidate = url.toLocalFile()
            if candidate and Path(candidate).is_dir():
                return candidate
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._first_directory(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        folder = self._first_directory(event)
        if not folder:
            event.ignore()
            return
        self.folder_dropped.emit(self._instance_id, folder)
        event.acceptProposedAction()

    def restyle(self, theme: Theme) -> None:
        self._theme = theme
        self.menu_button.setIcon(theme.icon("settings", 16, "subtext"))


class AddCard(QFrame):
    """卡片墙末尾的「添加服务器」占位卡片。"""

    clicked = Signal()

    def __init__(self, theme: Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("addCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setCursor(Qt.PointingHandCursor)
        self._theme = theme
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("添加服务器")
        self.setToolTip("新建实例，或下载一个全新的服务端")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        layout.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(theme.pixmap("plus", 30, "overlay"))
        layout.addWidget(self.icon_label)

        title = QLabel("添加服务器")
        title.setObjectName("valueStrong")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("新建实例或下载服务端")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        apply_property(self, "hovered", True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        apply_property(self, "hovered", False)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        """自绘圆角虚线框。

        Qt 的 QSS 对「1px 圆角虚线」支持不佳：左右两条边会被裁掉、圆角处容易断线，
        所以这里用 QPainter 画一条完整的虚线，悬停时再填充底色。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        hovered = bool(self.property("hovered"))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)

        if hovered:
            painter.fillPath(path, self._theme.color("surface0"))
            color = self._theme.color("accent")
        else:
            color = self._theme.color("surface2")

        pen = QPen(color, 1)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([4.0, 3.0])
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    def restyle(self, theme: Theme) -> None:
        self._theme = theme
        self.icon_label.setPixmap(theme.pixmap("plus", 30, "overlay"))
        self.update()


class InstancesPage(QWidget):
    """服务器实例卡片墙。"""

    COLUMN_WIDTH = 320

    def __init__(self, app, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.app = app
        self._cards: Dict[str, InstanceCard] = {}
        self._order: List[str] = []
        self._columns = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        # 顶部：标题 + 过滤 + 主要操作
        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("我的服务器")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        header.addWidget(self.count_label)
        header.addStretch(1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤服务器…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(200)
        self.filter_edit.setAccessibleName("过滤服务器列表")
        self.filter_edit.textChanged.connect(self.refresh)
        header.addWidget(self.filter_edit)

        self.add_button = QPushButton("新建实例")
        self.add_button.setIcon(app.theme.icon("plus", 16, "on_accent"))
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(app.create_instance)
        header.addWidget(self.add_button)

        self.download_button = QPushButton("下载服务端")
        self.download_button.setIcon(app.theme.icon("download", 16, "subtext"))
        self.download_button.clicked.connect(app.open_download_page)
        header.addWidget(self.download_button)
        layout.addLayout(header)

        hint = QLabel("点击卡片进入工作台；也可以把服务器文件夹直接拖到卡片上导入。")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        # 卡片区域
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.container.setObjectName("cardContainer")
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

        self.empty_label = QLabel("没有匹配的服务器，试试清空过滤条件。")
        self.empty_label.setObjectName("hint")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        # 底部系统状态条
        status = QFrame()
        status.setObjectName("card")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(16, 8, 16, 8)
        status_layout.setSpacing(22)
        caption = QLabel("系统")
        caption.setObjectName("muted")
        status_layout.addWidget(caption)
        self.cpu_meter = MiniMeter("CPU")
        self.mem_meter = MiniMeter("内存")
        self.disk_meter = MiniMeter("磁盘")
        for meter in (self.cpu_meter, self.mem_meter, self.disk_meter):
            meter.setMinimumWidth(180)
            status_layout.addWidget(meter, 1)
        layout.addWidget(status)

        self.add_card = AddCard(app.theme)
        self.add_card.clicked.connect(self._show_add_menu)
        self.refresh()

    # ==================== 数据刷新 ====================
    def refresh(self) -> None:
        keyword = (self.filter_edit.text() or "").strip().lower()
        instances = self.app.instances

        visible = [
            instance
            for instance in instances
            if not keyword or keyword in ("%s %s" % (instance.name, instance.path)).lower()
        ]

        self._clear_cards()
        self._order = [instance.id for instance in visible]
        for instance in visible:
            card = InstanceCard(self.app.theme, instance)
            card.open_requested.connect(self.app.open_workspace)
            card.start_requested.connect(self.app.start_instance_by_id)
            card.stop_requested.connect(self.app.stop_instance_by_id)
            card.menu_requested.connect(self._show_card_menu)
            card.folder_dropped.connect(self._on_folder_dropped)
            self._cards[instance.id] = card
        self._relayout(force=True)

        total = len(instances)
        self.count_label.setText(
            ("%d / %d 台" % (len(visible), total)) if keyword else ("%d 台" % total)
        )
        self.empty_label.setVisible(not visible)
        self.container.setVisible(bool(visible))

    def _clear_cards(self) -> None:
        add_card = getattr(self, "add_card", None)
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if widget is add_card:
                # 「添加服务器」占位卡是常驻控件，只从布局里摘下，不能销毁
                continue
            widget.setParent(None)
            widget.deleteLater()
        self._cards.clear()

    def _available_width(self, width_hint: int = 0) -> int:
        """可用来排卡片的宽度。

        刚构建时 scroll 的 viewport 可能还是 0，此时退回到页面宽度，
        避免第一次布局把卡片排成单列。
        """
        for candidate in (width_hint, self.scroll.viewport().width(), self.width() - 40):
            if candidate and candidate > 0:
                return candidate
        return self.COLUMN_WIDTH

    def _relayout(self, force: bool = False, width_hint: int = 0) -> None:
        width = self._available_width(width_hint)
        columns = max(1, min(4, (width + 12) // (self.COLUMN_WIDTH + 12)))
        if not force and columns == self._columns:
            return
        self._columns = columns

        while self.grid.count():
            self.grid.takeAt(0)
        for index, instance_id in enumerate(self._order):
            card = self._cards.get(instance_id)
            if card is None:
                continue
            self.grid.addWidget(card, index // columns, index % columns)
        # 末尾放一张「添加服务器」占位卡，空状态也不至于显得荒凉
        position = len(self._order)
        self.grid.addWidget(self.add_card, position // columns, position % columns)
        self.add_card.setVisible(not self.filter_edit.text().strip())
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout(width_hint=event.size().width() - 40)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 页面第一次真正获得尺寸后再排一次，保证列数正确
        self._relayout(force=True)

    # ==================== 交互 ====================
    def _on_folder_dropped(self, instance_id: str, path: str) -> None:
        instance = self.app.find_instance(instance_id)
        if instance is None:
            return
        if self.app.is_running(instance.id):
            self.app.notify("服务器正在运行，无法更换目录", "error")
            return
        self.app.set_instance_path(instance.id, path)

    def _show_card_menu(self, instance_id: str, position: QPoint) -> None:
        instance = self.app.find_instance(instance_id)
        if instance is None:
            return
        self.app.select_instance(self.app.index_of(instance.id))

        menu = QMenu(self)
        menu.addAction(self.app.theme.icon("terminal", 16), "打开工作台", lambda: self.app.open_workspace(instance.id))
        menu.addSeparator()
        menu.addAction(self.app.theme.icon("edit", 16), "重命名", self.app.rename_instance)
        menu.addAction(self.app.theme.icon("copy", 16), "复制实例", self.app.duplicate_instance)
        menu.addAction(self.app.theme.icon("settings", 16), "版本设置", self.app.show_version_settings)
        menu.addAction(self.app.theme.icon("activity", 16), "JVM 设置", self.app.show_jvm_settings)
        menu.addSeparator()
        open_action = menu.addAction(
            self.app.theme.icon("folder", 16), "打开目录", lambda: self._open_folder(instance)
        )
        open_action.setEnabled(bool(instance.path) and os.path.isdir(instance.path))
        menu.addSeparator()
        menu.addAction(self.app.theme.icon("trash", 16), "删除实例", self.app.delete_instance)
        menu.exec(position)

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(self.app.theme.icon("plus", 16), "新建实例", self.app.create_instance)
        menu.addAction(
            self.app.theme.icon("download", 16),
            "下载服务端核心",
            lambda: self.app.open_download_page(True),
        )
        menu.exec(self.cursor().pos())

    def _open_folder(self, instance: Instance) -> None:
        if instance.path and not open_path(instance.path):
            self.app.notify("无法打开目录，可能已被移动或删除", "error")

    # ==================== 资源数值 ====================
    def update_cpu(self, value: float) -> None:
        self.cpu_meter.set_value(value)

    def update_memory(self, percent: float, used_gb: float, total_gb: float) -> None:
        self.mem_meter.set_value(percent, "%.1f/%.1fG" % (used_gb, total_gb))

    def update_disk(self, read_kb: float, write_kb: float, percent: float = 0.0) -> None:
        self.disk_meter.set_value(percent, "%.0f%%" % percent)
        self.disk_meter.setToolTip(
            "磁盘使用率 %.0f%%\n读 %s/s · 写 %s/s"
            % (percent, human_size(read_kb * 1024), human_size(write_kb * 1024))
        )

    # ==================== 主题 ====================
    def restyle(self, theme: Theme) -> None:
        self.add_button.setIcon(theme.icon("plus", 16, "on_accent"))
        self.download_button.setIcon(theme.icon("download", 16, "subtext"))
        for card in self._cards.values():
            card.restyle(theme)
        self.add_card.restyle(theme)