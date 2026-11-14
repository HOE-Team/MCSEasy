# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""自绘与通用控件。

这里的控件都不依赖主窗口，便于单独测试与复用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .theme import Theme, get_theme
from .utils import OutputDecoder, shorten


def apply_property(widget: QWidget, name: str, value) -> None:
    """设置动态属性并刷新样式（用于 :hover / 状态徽章）。"""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def elide(text: str, widget: QWidget, width: int) -> str:
    return QFontMetrics(widget.font()).elidedText(str(text), Qt.ElideMiddle, max(20, width))


def rounded_pixmap(pixmap: QPixmap, radius: int = 10) -> QPixmap:
    """把位图裁成圆角，用于项目图标。"""
    if pixmap.isNull():
        return pixmap
    size = pixmap.size()
    result = QPixmap(size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    return result


class ElidedLabel(QLabel):
    """自动省略中间字符的标签，避免长路径把布局撑破。"""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._full_text = str(text or "")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextFormat(Qt.PlainText)
        self.setToolTip(self._full_text)
        self._update_elide()

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._update_elide()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self) -> None:
        width = max(20, self.width() - 2)
        super().setText(
            QFontMetrics(self.font()).elidedText(self._full_text, Qt.ElideMiddle, width)
        )


class Card(QFrame):
    """带标题与操作区的内容卡片。"""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)

        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        if title:
            outer.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)

    def add(self, item) -> None:
        if isinstance(item, QWidget):
            self.body.addWidget(item)
        else:
            self.body.addLayout(item)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget)


class RingGauge(QWidget):
    """环形仪表：标题 + 百分比 + 底部说明。"""

    def __init__(self, title: str = "", unit: str = "%", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._unit = unit
        self._value = 0.0
        self._detail = ""
        self._theme: Theme = get_theme()
        self.setMinimumSize(108, 128)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setAccessibleName(title or "仪表")

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_value(self, value: float, detail: Optional[str] = None) -> None:
        try:
            self._value = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            self._value = 0.0
        if detail is not None:
            self._detail = detail
        # 让屏幕阅读器也能读到当前数值，而不是只有一圈颜色
        self.setAccessibleName("%s %.0f%s" % (self._title or "仪表", self._value, self._unit))
        self.setAccessibleDescription(self._detail)
        self.update()

    def set_detail(self, detail: str) -> None:
        self._detail = detail
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(150, 150)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        theme = self._theme
        width, height = self.width(), self.height()
        title_h = 18 if self._title else 0
        detail_h = 18 if self._detail else 0
        side = min(width - 8, height - title_h - detail_h - 6)
        side = max(36, side)
        cx = width / 2.0
        cy = title_h + side / 2.0 + 1
        pen_w = max(5, int(side * 0.09))
        radius = side / 2.0 - pen_w / 2.0
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        if self._title:
            font = QFont(self.font())
            font.setPointSizeF(max(7.5, min(10.0, side * 0.085)))
            painter.setFont(font)
            painter.setPen(theme.color("subtext"))
            painter.drawText(
                QRectF(0, 0, width, title_h),
                Qt.AlignHCenter | Qt.AlignVCenter,
                self._title,
            )

        painter.setPen(QPen(theme.color("surface1"), pen_w, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 90 * 16, -360 * 16)

        if self._value > 60:
            color = theme.color("yellow") if self._value <= 85 else theme.color("red")
        else:
            color = theme.color("green")
        if self._value > 0:
            painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, 90 * 16, -int(360 * self._value / 100.0) * 16)

        font = QFont(self.font())
        font.setPointSizeF(max(9.0, min(20.0, side * 0.22)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(theme.color("text"))
        value_text = "%.0f%s" % (self._value, self._unit)
        painter.drawText(
            QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
            Qt.AlignCenter,
            value_text,
        )

        if self._detail:
            font.setPointSizeF(max(7.0, min(9.5, side * 0.075)))
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(theme.color("overlay"))
            painter.drawText(
                QRectF(0, cy + side / 2.0 + 2, width, detail_h),
                Qt.AlignHCenter | Qt.AlignVCenter,
                self._detail,
            )
        painter.end()


class StatusBadge(QLabel):
    """带状态颜色的徽章。"""

    def __init__(self, text: str = "", state: str = "idle", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignCenter)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        apply_property(self, "state", state)
        self.setAccessibleName(self.text())

    def setText(self, text: str) -> None:  # noqa: N802 - Qt 接口
        super().setText(text)
        self.setAccessibleName(text)


class StatusDot(QLabel):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("●", parent)
        self.setObjectName("statusDot")
        self.setFixedWidth(14)
        self.setAlignment(Qt.AlignCenter)
        self.set_state("stopped")
        self.setToolTip("已停止")
        self.setAccessibleName("服务器状态：已停止")

    def set_state(self, state: str) -> None:
        apply_property(self, "state", state)
        label = {"running": "运行中", "stopped": "已停止", "error": "异常"}.get(state, state)
        self.setToolTip(label)
        self.setAccessibleName("服务器状态：%s" % label)


class IconButton(QPushButton):
    """只显示图标的按钮。"""

    def __init__(
        self,
        theme: Theme,
        icon_name: str,
        tooltip: str = "",
        size: int = 18,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("iconButton")
        self.setIcon(theme.icon(icon_name, size, "subtext"))
        self.setIconSize(QSize(size, size))
        self.setFixedSize(size + 14, size + 14)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(tooltip or icon_name)
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleDescription(tooltip)


class InstanceRow(QWidget):
    """实例列表中的一行：状态点 + 名称 + 类型。"""

    def __init__(self, name: str, subtitle: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 8, 6)
        layout.setSpacing(8)

        self.dot = StatusDot()
        layout.addWidget(self.dot)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.name_label = QLabel(name)
        self.name_label.setObjectName("valueStrong")
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_layout.addWidget(self.name_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("muted")
        self.subtitle_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.subtitle_label.setVisible(bool(subtitle))
        text_layout.addWidget(self.subtitle_label)

        layout.addLayout(text_layout, 1)
        self._name = name
        self._subtitle = subtitle
        self._state = "stopped"
        self.setToolTip(name)
        self._sync_accessible()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = max(40, self.name_label.width())
        self.name_label.setText(elide(self._name, self.name_label, width))
        self.subtitle_label.setText(elide(self._subtitle, self.subtitle_label, width))

    def set_running(self, running: bool) -> None:
        self._state = "running" if running else "stopped"
        self.dot.set_state(self._state)
        self._sync_accessible()

    def _sync_accessible(self) -> None:
        state_text = "运行中" if self._state == "running" else "已停止"
        detail = "%s，%s" % (self._name, state_text)
        if self._subtitle:
            detail += "，%s" % self._subtitle
        self.setAccessibleName(detail)

    def set_name(self, name: str) -> None:
        self._name = name
        self.setToolTip(name)
        self.name_label.setText(elide(name, self.name_label, max(40, self.name_label.width())))

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = subtitle
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        self._sync_accessible()


class EmptyState(QWidget):
    """空状态提示。"""

    def __init__(
        self,
        theme: Theme,
        icon_name: str,
        title: str,
        hint: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(10)
        layout.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(theme.pixmap(icon_name, 44, "overlay"))
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("emptyHint")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(bool(hint))
        layout.addWidget(self.hint_label)

        self.button_row = QHBoxLayout()
        self.button_row.addStretch(1)
        self.button_row.addStretch(1)
        layout.addLayout(self.button_row)
        layout.addStretch(1)

    def add_button(self, button: QPushButton) -> None:
        self.button_row.insertWidget(self.button_row.count() - 1, button)

    def set_theme(self, theme: Theme, icon_name: str) -> None:
        self.icon_label.setPixmap(theme.pixmap(icon_name, 44, "overlay"))


class MiniMeter(QWidget):
    """紧凑的资源指示条：标题 + 细进度条 + 数值。"""

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("muted")
        self.title_label.setFixedWidth(36)
        layout.addWidget(self.title_label)

        self.bar = QProgressBar()
        self.bar.setObjectName("miniBar")
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar, 1)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("muted")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFixedWidth(70)
        layout.addWidget(self.value_label)

        self.setAccessibleName(title)
        self.bar.setAccessibleName(title)

    def set_value(self, percent: float, text: str = "") -> None:
        try:
            value = max(0.0, min(100.0, float(percent)))
        except (TypeError, ValueError):
            value = 0.0
        self.bar.setValue(int(round(value)))
        self.value_label.setText(text or ("%.0f%%" % value))
        level = "error" if value >= 85 else "warn" if value >= 60 else "ok"
        apply_property(self.bar, "level", level)
        description = "%s %s" % (self.accessibleName(), self.value_label.text())
        self.bar.setAccessibleDescription(description)
        self.value_label.setToolTip(description)


class ChecklistRow(QWidget):
    """启动检查清单中的一行：状态图标 + 说明 + 可选操作按钮。"""

    action_triggered = Signal(str)

    def __init__(self, theme: Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._key = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title_label = QLabel()
        self.title_label.setObjectName("value")
        text_layout.addWidget(self.title_label)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        text_layout.addWidget(self.detail_label)
        layout.addLayout(text_layout, 1)

        self.action_button = QPushButton()
        self.action_button.setObjectName("ghost")
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.setFixedHeight(26)
        self.action_button.hide()
        self.action_button.clicked.connect(lambda: self.action_triggered.emit(self._key))
        layout.addWidget(self.action_button, 0, Qt.AlignTop)

    def configure(
        self,
        theme: Theme,
        key: str,
        ok: bool,
        title: str,
        detail: str,
        action_label: str = "",
    ) -> None:
        self._theme = theme
        self._key = key
        self.icon.setPixmap(
            theme.pixmap("check-circle" if ok else "alert", 18, "green" if ok else "red")
        )
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.detail_label.setToolTip(detail)
        self.action_button.setVisible(bool(action_label))
        if action_label:
            self.action_button.setText(action_label)
            self.action_button.setAccessibleName("%s：%s" % (title, action_label))
        state_text = "已完成" if ok else "待处理"
        self.setAccessibleName("%s，%s，%s" % (title, state_text, detail))

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme


class ProjectCard(QFrame):
    """Modrinth 项目卡片。"""

    clicked = Signal(dict)
    download_requested = Signal(dict)

    def __init__(self, data: dict, theme: Theme, icon_provider, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(88)
        self.setMaximumHeight(104)
        self.data = data
        self._theme = theme

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        self.thumb = QLabel()
        self.thumb.setFixedSize(56, 56)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(
            "background-color: %s; border-radius: 10px;" % theme.hex("surface0")
        )
        fallback = theme.pixmap("package", 26, "overlay")
        self.thumb.setPixmap(fallback)
        layout.addWidget(self.thumb)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)

        full_title = str(data.get("title") or "未知项目")
        title = QLabel(shorten(full_title, 48))
        title.setObjectName("projectTitle")
        title.setToolTip(full_title)
        info.addWidget(title)

        author = data.get("author") or "未知作者"
        downloads = int(data.get("downloads") or 0)
        meta = QLabel("%s · %s 次下载" % (shorten(author, 18), "{:,}".format(downloads)))
        meta.setObjectName("muted")
        info.addWidget(meta)

        description = QLabel(shorten(data.get("description", ""), 90))
        description.setObjectName("hint")
        description.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info.addWidget(description)

        layout.addLayout(info, 1)

        self.download_button = QPushButton("下载")
        self.download_button.setObjectName("primary")
        self.download_button.setFixedWidth(72)
        self.download_button.setCursor(Qt.PointingHandCursor)
        self.download_button.setAccessibleName("下载 %s" % full_title)
        self.download_button.clicked.connect(
            lambda: self.download_requested.emit(self.data)
        )
        self.setAccessibleName(full_title)
        self.setAccessibleDescription(str(data.get("description") or ""))
        layout.addWidget(self.download_button, 0, Qt.AlignVCenter)

        icon_url = data.get("icon_url") or ""
        if icon_url and icon_provider is not None:
            icon_provider(icon_url, self._on_icon_loaded)
        self._description = description

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        full = shorten(self.data.get("description", ""), 90)
        self._description.setText(elide(full, self._description, self._description.width()))

    def _on_icon_loaded(self, data: bytes) -> None:
        if not data:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        scaled = pixmap.scaled(56, 56, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.thumb.setPixmap(rounded_pixmap(scaled, 10))

    # ---- 交互 ----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.data)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        apply_property(self, "hovered", True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        apply_property(self, "hovered", False)
        super().leaveEvent(event)


class LoadingOverlay(QWidget):
    """覆盖在容器上的加载遮罩。"""

    def __init__(self, parent: QWidget, theme: Theme, text: str = "加载中…") -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._angle = 0
        self._text = text
        self._theme = theme
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.parent() and event.type() in (QEvent.Resize, QEvent.Show):
            self.setGeometry(self.parent().rect())
        return False

    def start(self, text: Optional[str] = None) -> None:
        if text:
            self._text = text
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._angle = 0
        self._timer.start()
        self.raise_()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        overlay = QColor(self._theme.hex("bg"))
        overlay.setAlpha(200)
        painter.fillRect(self.rect(), overlay)

        cx, cy = self.width() // 2, self.height() // 2 - 8
        radius = 22
        pen_width = 3
        for index in range(12):
            alpha = 40 + index * 16
            angle = (self._angle + index * 30) % 360
            color = QColor(self._theme.hex("accent"))
            color.setAlpha(min(255, alpha))
            painter.setPen(QPen(color, pen_width, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                (90 - angle) * 16,
                -int(26 * 16),
            )

        painter.setPen(self._theme.color("subtext"))
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, cy + radius + 14, self.width(), 24),
            Qt.AlignHCenter | Qt.AlignTop,
            self._text,
        )
        painter.end()


class Toast(QFrame):
    """右下角浮动提示。"""

    def __init__(
        self,
        host: QWidget,
        text: str,
        kind: str,
        theme: Theme,
        timeout: int = 3200,
        on_closed: Optional[Callable[["Toast"], None]] = None,
    ) -> None:
        super().__init__(host)
        self._on_closed = on_closed
        self.setObjectName("toast")
        self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)
        self._host = host
        self._timeout = timeout

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        icon_name = {"success": "check-circle", "error": "alert"}.get(kind, "info")
        token = {"success": "on_green", "error": "on_red"}.get(kind, "subtext")
        icon_label = QLabel()
        icon_label.setPixmap(theme.pixmap(icon_name, 16, token))
        layout.addWidget(icon_label)

        self.label = QLabel(shorten(text, 90))
        self.label.setObjectName("toastText")
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(200)
        self.label.setMaximumWidth(360)
        layout.addWidget(self.label)

        self.adjustSize()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(timeout)

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        callback, self._on_closed = self._on_closed, None
        if callback is not None:
            try:
                callback(self)
            except Exception:
                pass
        self.deleteLater()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.dismiss()
        super().mousePressEvent(event)


class Toaster(QObject):
    """管理一组 Toast 的位置与生命周期。"""

    def __init__(self, host: QWidget, theme: Theme) -> None:
        super().__init__(host)
        self._host = host
        self._theme = theme
        self._toasts: List[Toast] = []
        host.installEventFilter(self)
        self._filter_target = host

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme

    def show(self, text: str, kind: str = "info", timeout: int = 3200) -> None:
        if not text:
            return
        toast = Toast(self._host, text, kind, self._theme, timeout, self._forget)
        toast.show()
        self._toasts.append(toast)
        # 最多同时显示 3 条
        while len(self._toasts) > 3:
            oldest = self._toasts.pop(0)
            oldest.dismiss()
        self._reposition()

    def _forget(self, toast: "Toast") -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._filter_target and event.type() == QEvent.Resize:
            self._reposition()
        return False

    def _reposition(self) -> None:
        host = self._host
        margin = 20
        # 留出底部状态条 / 命令输入行的高度，避免遮住它们
        offset = 84
        for toast in reversed(list(self._toasts)):
            try:
                if not toast.isVisible():
                    continue
            except RuntimeError:
                self._toasts.remove(toast)
                continue
            toast.adjustSize()
            width = toast.width()
            height = toast.height()
            x = max(margin, (host.width() - width) // 2)
            y = host.height() - height - offset
            toast.move(QPoint(max(0, x), max(0, y)))
            offset += height + 8


class HistoryLineEdit(QLineEdit):
    """支持 ↑ / ↓ 翻阅历史命令的输入框。"""

    MAX_HISTORY = 100

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._history: List[str] = []
        self._index = 0
        self._draft = ""

    def add_history(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            del self._history[: max(0, len(self._history) - self.MAX_HISTORY)]
        self._index = len(self._history)
        self._draft = ""

    def history(self) -> List[str]:
        return list(self._history)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Up:
            self._show_previous()
            return
        if event.key() == Qt.Key_Down:
            self._show_next()
            return
        super().keyPressEvent(event)

    def _show_previous(self) -> None:
        if not self._history:
            return
        if self._index >= len(self._history):
            self._draft = self.text()
        self._index = max(0, self._index - 1)
        self.setText(self._history[self._index])
        self.selectAll()

    def _show_next(self) -> None:
        if not self._history:
            return
        if self._index < len(self._history) - 1:
            self._index += 1
            self.setText(self._history[self._index])
        else:
            self._index = len(self._history)
            self.setText(self._draft)
        self.selectAll()


class DropListWidget(QListWidget):
    """支持把文件夹拖进来设置实例目录的列表。"""

    folder_dropped = Signal(int, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDropIndicatorShown(True)

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

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._first_directory(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        folder = self._first_directory(event)
        if not folder:
            event.ignore()
            return
        item = self.itemAt(event.position().toPoint())
        index = self.row(item) if item is not None else self.currentRow()
        self.folder_dropped.emit(index, folder)
        event.acceptProposedAction()


class ConsoleView(QPlainTextEdit):
    """服务器控制台：限制行数、自动滚动、编码容错、查找与导出。"""

    MAX_BLOCKS = 20000

    def __init__(self, theme: Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("console")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(self.MAX_BLOCKS)
        self.setAccessibleName("服务器控制台输出")
        self._empty_title = "还没有日志"
        self._empty_hint = "启动服务器后，日志会实时显示在这里。"
        self._decoder = OutputDecoder()
        self._auto_scroll = True
        self._theme = theme
        self._search_text = ""
        self._matches: List[QTextCursor] = []
        self._current_match = -1
        # 服务器输出很频繁，查找高亮做防抖，避免每来一行就全量重扫
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._refresh_search)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ---- 主题 ----
    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        size = self.font().pointSize()
        self.apply_font_size(size if size > 0 else 12)
        self.viewport().update()

    def set_empty_text(self, title: str, hint: str = "") -> None:
        """设置控制台为空时居中显示的提示。"""
        self._empty_title = title
        self._empty_hint = hint
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self.document().isEmpty():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.viewport().rect()
        center_x = rect.center().x()
        top = max(24, rect.center().y() - 84)

        icon = self._theme.pixmap("terminal", 40, "overlay")
        painter.drawPixmap(center_x - 20, top, icon)

        font = QFont(self.font())
        font.setPointSize(max(10, self.font().pointSize() + 1))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._theme.color("subtext"))
        painter.drawText(
            QRect(0, top + 52, rect.width(), 26), Qt.AlignHCenter, self._empty_title
        )

        if self._empty_hint:
            font.setPointSize(max(8, self.font().pointSize()))
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(self._theme.color("overlay"))
            painter.drawText(
                QRect(32, top + 82, max(60, rect.width() - 64), 64),
                Qt.AlignHCenter | Qt.TextWordWrap,
                self._empty_hint,
            )
        painter.end()

    def apply_font_size(self, size: int) -> None:
        font = QFont(self.font())
        font.setPointSize(max(7, min(24, size)))
        self.setFont(font)

    # ---- 输出 ----
    def feed_bytes(self, data: bytes) -> None:
        text = self._decoder.feed(data)
        if text:
            self.append_output(text)

    def append_output(self, text: str) -> None:
        if not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        if not text:
            return
        self.appendPlainText(text)
        if self._auto_scroll:
            self.scroll_to_bottom()
        if self._search_text and not self._search_timer.isActive():
            self._search_timer.start()

    def _refresh_search(self) -> None:
        if self._search_text:
            self.set_search(self._search_text, keep_current=True)

    def append_system(self, text: str) -> None:
        self.append_output("\n--- %s ---" % text)

    def clear_console(self) -> None:
        self.clear()
        self._matches = []
        self._current_match = -1

    def scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = bool(enabled)
        if self._auto_scroll:
            self.scroll_to_bottom()

    def _on_scroll(self, value: int) -> None:
        bar = self.verticalScrollBar()
        # 用户主动向上翻页时暂停自动滚动
        self._auto_scroll = value >= bar.maximum() - 8

    def save_to_file(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.toPlainText())
            return True
        except OSError:
            return False

    # ---- 查找 ----
    def set_search(self, text: str, keep_current: bool = False) -> int:
        previous = self._current_match
        self._search_text = text
        self._search_timer.stop()
        self._matches = []
        self._current_match = -1
        if not text:
            self.setExtraSelections([])
            return 0

        document = self.document()
        cursor = QTextCursor(document)
        while len(self._matches) < 2000:
            cursor = document.find(text, cursor)
            if cursor.isNull():
                break
            self._matches.append(QTextCursor(cursor))

        if keep_current and previous >= 0 and self._matches:
            self._current_match = min(previous, len(self._matches) - 1)
        self._highlight()
        return len(self._matches)

    def find_next(self, backward: bool = False) -> bool:
        if not self._matches:
            return False
        if self._current_match < 0:
            self._current_match = len(self._matches) - 1 if backward else 0
        else:
            step = -1 if backward else 1
            self._current_match = (self._current_match + step) % len(self._matches)
        self._highlight()
        cursor = self._matches[self._current_match]
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def match_count(self) -> int:
        return len(self._matches)

    def current_match(self) -> int:
        return self._current_match

    def _highlight(self) -> None:
        selections = []
        base = QTextCharFormat()
        base.setBackground(QColor(self._theme.hex("highlight_bg")))
        base.setForeground(QColor(self._theme.hex("highlight_text")))
        for index, cursor in enumerate(self._matches):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            if index == self._current_match:
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(self._theme.hex("accent")))
                fmt.setForeground(QColor(self._theme.hex("on_accent")))
                selection.format = fmt
            else:
                selection.format = base
            selections.append(selection)
        self.setExtraSelections(selections)