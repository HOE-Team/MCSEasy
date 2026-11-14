# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""主题系统：配色、样式表与图标。

配色参考 Catppuccin（Mocha / Latte），同一套 token 同时驱动深色与浅色界面。
所有控件通过 objectName 或动态属性取色，因此切换主题时只需要重新应用
一次样式表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from string import Template
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .config import data_dir, resource_path


@dataclass(frozen=True)
class Theme:
    """一套完整的视觉主题。"""

    key: str
    label: str
    is_dark: bool
    colors: Dict[str, str] = field(default_factory=dict)
    _qss: str = ""

    # ---- 颜色 ----
    def color(self, token: str, fallback: str = "#cdd6f4") -> QColor:
        return QColor(self.colors.get(token, fallback))

    def hex(self, token: str, fallback: str = "#cdd6f4") -> str:
        return self.colors.get(token, fallback)

    # ---- 图标 ----
    def icon(self, name: str, size: int = 20, token: str = "subtext") -> QIcon:
        return svg_icon(name, size, self.hex(token))

    def pixmap(self, name: str, size: int = 20, token: str = "subtext") -> QPixmap:
        return svg_pixmap(name, size, self.hex(token))

    # ---- 样式表 ----
    def qss(self) -> str:
        if not self._qss:
            object.__setattr__(self, "_qss", _build_qss(self))
        return self._qss


_DARK = {
    "bg": "#1e1e2e",
    "mantle": "#181825",
    "crust": "#11111b",
    "card": "#181825",
    "console_bg": "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "border": "#313244",
    "overlay": "#8087a2",
    "subtext": "#a6adc8",
    "text": "#cdd6f4",
    "accent": "#cba6f7",
    "accent_hover": "#b4befe",
    "on_accent": "#1e1e2e",
    "blue": "#89b4fa",
    "green": "#a6e3a1",
    "green_hover": "#94e2d5",
    "on_green": "#14201a",
    "on_yellow": "#14201a",
    "highlight_bg": "#f9e2af",
    "highlight_text": "#1e1e2e",
    "yellow": "#f9e2af",
    "red": "#f38ba8",
    "red_hover": "#eba0ac",
    "on_red": "#2b1220",
    "teal": "#94e2d5",
    "selection": "#45475a",
}

_LIGHT = {
    "bg": "#eff1f5",
    "mantle": "#e6e9ef",
    "crust": "#dce0e8",
    "card": "#ffffff",
    "console_bg": "#ffffff",
    "surface0": "#e6e9ef",
    "surface1": "#dce0e8",
    "surface2": "#ccd0da",
    "border": "#dce0e8",
    "overlay": "#686b80",
    "subtext": "#5c5f77",
    "text": "#4c4f69",
    "accent": "#8839ef",
    "accent_hover": "#7287fd",
    "on_accent": "#ffffff",
    "blue": "#1e66f5",
    "green": "#2e7d1f",
    "green_hover": "#28731a",
    "on_green": "#ffffff",
    "on_yellow": "#1e1e2e",
    "highlight_bg": "#ffe08a",
    "highlight_text": "#3d3f52",
    "yellow": "#df8e1d",
    "red": "#d20f39",
    "red_hover": "#b70d32",
    "on_red": "#ffffff",
    "teal": "#179299",
    "selection": "#ccd0da",
}

THEMES: Dict[str, Theme] = {
    "dark": Theme("dark", "深色", True, _DARK),
    "light": Theme("light", "浅色", False, _LIGHT),
}

DEFAULT_THEME = "dark"


def get_theme(key: str | None = None) -> Theme:
    return THEMES.get((key or DEFAULT_THEME).lower(), THEMES[DEFAULT_THEME])


# ==================== SVG 图标 ====================
@lru_cache(maxsize=512)
def svg_pixmap(name: str, size: int = 20, color: str = "#cdd6f4") -> QPixmap:
    """把 svg 渲染成指定颜色、指定逻辑尺寸的位图。

    以 2 倍分辨率渲染并设置 devicePixelRatio，高分屏下不会发虚。
    找不到图标时返回空位图，绝不抛异常。
    """
    size = max(8, int(size))
    scale = 2
    path = resource_path("svg", f"{name}.svg")
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    if not path.exists():
        pixmap.setDevicePixelRatio(scale)
        return pixmap

    try:
        renderer = QSvgRenderer(str(path))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
    except Exception:  # pragma: no cover - 损坏的 svg 不应拖垮界面
        pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def svg_icon(name: str, size: int = 20, color: str = "#cdd6f4") -> QIcon:
    icon = QIcon()
    icon.addPixmap(svg_pixmap(name, size, color))
    return icon


def _asset_file(theme: Theme, name: str, token: str, size: int) -> str:
    """为样式表生成着色后的 png，返回可用于 url() 的路径。"""
    color = theme.hex(token)
    cache_dir = data_dir() / "assets"
    filename = "%s-%s-%d-%s.png" % (name, color.lstrip("#"), size, theme.key)
    target = cache_dir / filename
    if not target.exists():
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            svg_pixmap(name, size, color).save(str(target), "PNG")
        except Exception:  # pragma: no cover
            return ""
    return target.as_posix()


def _build_qss(theme: Theme) -> str:
    """根据主题生成完整样式表。"""
    values = dict(theme.colors)
    values.update(
        {
            "arrow_icon": _asset_file(theme, "arrow-down", "subtext", 16),
            "arrow_up_icon": _asset_file(theme, "arrow-up", "subtext", 16),
            "check_icon": _asset_file(theme, "check", "on_accent", 14),
            "dash_icon": _asset_file(theme, "check-indeterminate", "on_accent", 14),
            "font": _font_family(),
            "mono": _mono_family(),
        }
    )
    try:
        return Template(_QSS_TEMPLATE).safe_substitute(values)
    except Exception:  # pragma: no cover - 样式问题不应阻止程序启动
        return ""


def _font_family() -> str:
    return (
        '"Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", '
        '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Noto Sans", sans-serif'
    )


def _mono_family() -> str:
    return (
        '"Cascadia Mono", "Consolas", "JetBrains Mono", "Sarasa Mono SC", '
        '"DejaVu Sans Mono", monospace'
    )


_QSS_TEMPLATE = """
QWidget {
    font-family: $font;
    color: $text;
    font-size: 13px;
}
QMainWindow, QDialog, QWidget#root { background-color: $bg; }
QToolTip {
    background-color: $surface1;
    color: $text;
    border: 1px solid $surface2;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 12px;
}

/* ---------- 侧边栏 ---------- */
QWidget#sidebar { background-color: $mantle; border-right: 1px solid $border; }
QWidget#logoWidget { background-color: transparent; }
QLabel#logoLabel { color: $accent; font-size: 22px; font-weight: 700; }
QLabel#versionLabel { color: $overlay; font-size: 11px; }
QListWidget#navList { background: transparent; border: none; outline: none; padding: 4px 0; }
QListWidget#navList::item { padding: 0px 12px; margin: 2px 10px; border-radius: 8px; color: $subtext; }
QListWidget#navList::item:hover { background-color: $surface0; color: $text; }
QListWidget#navList::item:selected { background-color: $accent; color: $on_accent; font-weight: 600; }
QLabel#sidebarFooter { color: $overlay; font-size: 11px; }

/* ---------- 顶栏 ---------- */
QWidget#topBar { background-color: $mantle; border-bottom: 1px solid $border; }
QLabel#pageTitle { font-size: 17px; font-weight: 700; color: $text; }
QLabel#pageSubtitle { font-size: 12px; color: $subtext; }

/* ---------- 卡片 ---------- */
QFrame#card { background-color: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QLabel#cardTitle { font-size: 13px; font-weight: 700; color: $text; }
QLabel#hint { color: $subtext; font-size: 12px; }
QLabel#muted { color: $overlay; font-size: 12px; }
QLabel#value { color: $text; font-size: 13px; }
QLabel#valueStrong { color: $text; font-size: 13px; font-weight: 600; }
QFrame#separator { background-color: $border; border: none; }

/* ---------- 分组框 ---------- */
QGroupBox {
    background-color: $card;
    border: 1px solid $border;
    border-radius: 12px;
    margin-top: 16px;
    padding: 18px 14px 14px 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: $subtext;
    font-weight: 600;
    font-size: 12px;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background-color: $surface0;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 7px 15px;
    color: $text;
    font-size: 13px;
    min-height: 18px;
}
QPushButton:hover { background-color: $surface1; border-color: $surface2; }
QPushButton:pressed { background-color: $surface2; }
QPushButton:disabled { background-color: $surface0; color: $overlay; border-color: $border; }
QPushButton:focus { border: 2px solid $accent; }
QPushButton#ghost:focus, QPushButton#iconButton:focus { border: 2px solid $accent; background-color: $surface0; }
QPushButton#primary { background-color: $accent; border-color: $accent; color: $on_accent; font-weight: 600; }
QPushButton#primary:hover { background-color: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:disabled { background-color: $surface0; border-color: $border; color: $overlay; }
QPushButton#success { background-color: $green; border-color: $green; color: $on_green; font-weight: 600; }
QPushButton#success:hover { background-color: $green_hover; border-color: $green_hover; }
QPushButton#success:disabled { background-color: $surface0; border-color: $border; color: $overlay; }
QPushButton#danger { background-color: $red; border-color: $red; color: $on_red; font-weight: 600; }
QPushButton#danger:hover { background-color: $red_hover; border-color: $red_hover; }
QPushButton#danger:disabled { background-color: $surface0; border-color: $border; color: $overlay; }
QPushButton#ghost { background-color: transparent; border-color: transparent; color: $subtext; }
QPushButton#ghost:hover { background-color: $surface0; color: $text; }
QPushButton#iconButton {
    background-color: transparent;
    border-color: transparent;
    border-radius: 7px;
    padding: 5px;
    color: $subtext;
}
QPushButton#iconButton:hover { background-color: $surface0; color: $text; }

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QComboBox {
    background-color: $surface0;
    placeholder-text-color: $overlay;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
    color: $text;
    min-height: 20px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: $surface2; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 2px solid $accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $overlay; background-color: $mantle; }
QLineEdit[readOnly="true"] { background-color: $mantle; color: $subtext; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url("$arrow_icon"); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background-color: $card;
    border: 1px solid $surface2;
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: $surface1;
    selection-color: $text;
}
QComboBox QAbstractItemView::item { padding: 6px 10px; border-radius: 6px; min-height: 20px; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url("$arrow_up_icon"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("$arrow_icon"); width: 10px; height: 10px; }

/* ---------- 复选框 ---------- */
QCheckBox { spacing: 8px; color: $text; }
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid $surface2;
    border-radius: 5px;
    background-color: $surface0;
}
QCheckBox:focus { color: $accent; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:focus { border: 2px solid $accent; }
QCheckBox::indicator:checked { background-color: $accent; border-color: $accent; image: url("$check_icon"); }
QCheckBox::indicator:indeterminate { background-color: $accent; border-color: $accent; image: url("$dash_icon"); }

/* ---------- 列表 ---------- */
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-radius: 8px; }
QListWidget::item:hover { background-color: $surface0; }
QListWidget::item:selected { background-color: $surface0; color: $text; }
QListWidget::item:selected:active { background-color: $surface1; color: $text; }
QListWidget:focus { border: 1px solid $accent; }
QListWidget#navList:focus { border: none; }
QListWidget#instanceList::item { padding: 2px 4px; margin: 2px 0px; }

/* ---------- 文本区 ---------- */
QPlainTextEdit#console {
    placeholder-text-color: $overlay;
    background-color: $console_bg;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 8px;
    color: $text;
    font-family: $mono;
    font-size: 12px;
    selection-background-color: $selection;
    selection-color: $text;
}
QTextBrowser#aboutText { background-color: transparent; border: none; color: $text; }
QTextBrowser#aboutText a { color: $blue; }

/* ---------- 标签页 ---------- */
QTabWidget::pane { border: 1px solid $border; border-radius: 10px; background-color: $card; top: -1px; }
QTabWidget#workspaceTabs::pane { border: none; background: transparent; }
QTabWidget::tab-bar { left: 4px; }
QTabBar::tab {
    background-color: transparent;
    border: none;
    padding: 8px 18px;
    margin: 0px 2px 6px 0px;
    border-radius: 8px;
    color: $subtext;
    font-size: 13px;
}
QTabBar::tab:hover { background-color: $surface0; color: $text; }
QTabBar::tab:selected { background-color: $surface0; color: $text; font-weight: 600; }
QTabBar::tab:focus { border: 2px solid $accent; }
QTabWidget::pane:focus { border-color: $accent; }

/* ---------- 进度条 / 滑块 ---------- */
QProgressBar {
    border: 1px solid $border;
    border-radius: 6px;
    background-color: $surface0;
    color: $text;
    text-align: center;
    font-size: 11px;
    min-height: 16px;
    max-height: 16px;
}
QProgressBar::chunk { background-color: $accent; border-radius: 5px; }
QProgressBar#miniBar {
    border: none;
    background-color: $surface0;
    min-height: 6px;
    max-height: 6px;
    border-radius: 3px;
}
QProgressBar#miniBar::chunk { background-color: $green; border-radius: 3px; }
QProgressBar#miniBar[level="warn"]::chunk { background-color: $yellow; }
QProgressBar#miniBar[level="error"]::chunk { background-color: $red; }
QSlider::groove:horizontal { height: 6px; background-color: $surface0; border-radius: 3px; }
QSlider::sub-page:horizontal { background-color: $accent; border-radius: 3px; }
QSlider::handle:horizontal {
    background-color: $card;
    border: 2px solid $accent;
    width: 14px;
    height: 14px;
    margin: -6px 0px;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover { background-color: $accent; }
QSlider:focus::groove:horizontal { border: 1px solid $accent; }

/* ---------- 滚动条 ---------- */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QWidget#cardContainer { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background-color: $surface2; min-height: 32px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background-color: $overlay; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background-color: $surface2; min-width: 32px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background-color: $overlay; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------- 其他 ---------- */
QSplitter::handle { background-color: transparent; }
QSplitter::handle:horizontal { width: 12px; }
QSplitter::handle:vertical { height: 12px; }
QMenu { background-color: $card; border: 1px solid $surface2; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; color: $text; }
QMenu::item:selected { background-color: $surface0; }
QMenu::item:disabled { color: $overlay; }
QMenu::separator { height: 1px; background-color: $border; margin: 4px 8px; }
QMessageBox { background-color: $bg; }
QMessageBox QLabel { color: $text; }

/* ---------- 实例卡片 ---------- */
QFrame#instanceCard { background-color: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#instanceCard[hovered="true"] { border-color: $accent; }
QFrame#instanceCard[running="true"] { border-color: $green; }
/* 虚线框由 AddCard 自绘（QSS 的圆角虚线在 Qt 下会缺边） */
QLabel#instanceName { font-size: 15px; font-weight: 700; color: $text; }
QPushButton#sideStatus {
    background: transparent;
    border: none;
    color: $subtext;
    font-size: 11px;
    text-align: left;
    padding: 0px;
}
QPushButton#sideStatus:hover { color: $text; }

/* ---------- 项目卡片 ---------- */
QFrame#projectCard { background-color: transparent; border: 1px solid transparent; border-radius: 10px; }
QFrame#projectCard[hovered="true"] { background-color: $surface0; border-color: $surface1; }
QLabel#projectTitle { font-size: 13px; font-weight: 600; color: $text; }

/* ---------- 动态属性 ---------- */
QLabel#badge { border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }
QLabel#badge[state="ok"] { background-color: $green; color: $on_green; }
QLabel#badge[state="idle"] { background-color: $surface1; color: $text; }
QLabel#badge[state="warn"] { background-color: $yellow; color: $on_yellow; }
QLabel#badge[state="error"] { background-color: $red; color: $on_red; }
QLabel#badge[state="accent"] { background-color: $accent; color: $on_accent; }
QLabel#statusDot { font-size: 13px; color: $overlay; }
QLabel#statusDot[state="running"] { color: $green; }
QLabel#statusDot[state="stopped"] { color: $overlay; }
QLabel#statusDot[state="error"] { color: $red; }
QLabel#actionHint { color: $subtext; font-size: 12px; }
QLabel#actionHint[level="warn"] { color: $text; }
QLabel#actionHint[level="error"] { color: $red; }
QLabel#emptyTitle { color: $text; font-size: 15px; font-weight: 600; }
QLabel#emptyHint { color: $subtext; font-size: 12px; }
QFrame#toast { background-color: $surface1; border: 1px solid $surface2; border-radius: 10px; }
QFrame#toast QLabel#toastText { color: $text; font-size: 12px; }
QFrame#toast[kind="error"] { background-color: $red; border-color: $red; }
QFrame#toast[kind="error"] QLabel#toastText { color: $on_red; font-weight: 600; }
QFrame#toast[kind="success"] { background-color: $green; border-color: $green; }
QFrame#toast[kind="success"] QLabel#toastText { color: $on_green; font-weight: 600; }
"""


def app_icon() -> QIcon:
    """程序图标：优先使用 ico，其次 png，最后回退到内置图标。"""
    icon = QIcon()
    for name in ("icon.ico", "icon.png"):
        path = resource_path(name)
        if path.exists():
            icon.addFile(str(path))
    if icon.isNull():
        icon = svg_icon("server", 64, THEMES[DEFAULT_THEME].hex("accent"))
    return icon