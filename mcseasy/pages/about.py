# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""关于页：版本信息、环境信息与相关链接。"""

from __future__ import annotations

import logging
import platform
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_TAGLINE, APP_VERSION, data_dir, logs_dir
from ..theme import Theme
from ..utils import open_path
from ..widgets import Card

logger = logging.getLogger(__name__)

PROJECT_URL = "https://github.com/HOE-Team/MCSEasy"
ISSUE_URL = "https://github.com/HOE-Team/MCSEasy/issues"


class AutoTextBrowser(QTextBrowser):
    """高度随内容自动伸缩的富文本框，避免卡片里出现大片空白。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutText")
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

    def setHtml(self, html: str) -> None:  # noqa: N802 - Qt 接口
        super().setHtml(html)
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        document = self.document()
        width = max(120, self.viewport().width())
        document.setTextWidth(width)
        height = int(document.size().height()) + 6
        height = max(40, height)
        if abs(self.height() - height) > 2:
            self.setFixedHeight(height)


class AboutPage(QWidget):
    """关于页。"""

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

        layout.addWidget(self._build_hero_card())
        layout.addWidget(self._build_features_card())
        layout.addWidget(self._build_environment_card())
        layout.addWidget(self._build_links_card())
        layout.addStretch(1)

        self.refresh()

    def _build_hero_card(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(18)

        self.logo_label = QLabel()
        self.logo_label.setFixedSize(72, 72)
        self.logo_label.setAlignment(Qt.AlignCenter)
        row.addWidget(self.logo_label)

        text = QVBoxLayout()
        text.setSpacing(4)
        title = QLabel(APP_NAME)
        title.setObjectName("pageTitle")
        text.addWidget(title)

        self.version_label = QLabel("版本 %s" % APP_VERSION)
        self.version_label.setObjectName("valueStrong")
        text.addWidget(self.version_label)

        tagline = QLabel(APP_TAGLINE + " · 帮助有需要的用户快速部署并监视 Minecraft 服务器")
        tagline.setObjectName("hint")
        tagline.setWordWrap(True)
        text.addWidget(tagline)
        row.addLayout(text, 1)
        card.add(row)
        return card

    def _build_features_card(self) -> Card:
        card = Card("主要功能")
        browser = AutoTextBrowser()
        self.features_browser = browser
        browser.setHtml(
            "<ul style='line-height:1.7'>"
            "<li><b>两级界面</b>：主页是服务器卡片墙，单台服务器的一切在独立的实例工作台里。</li>"
            "<li><b>状态驱动</b>：工作台按「开始使用 → 准备启动 → 实例概览 → 运行状态」自动切换。</li>"
            "<li><b>服务端下载</b>：Vanilla / Paper / Fabric / Forge / NeoForge，自动写入 EULA，"
            "Forge 系可直接运行安装器。</li>"
            "<li><b>模组与插件</b>：内置 Modrinth 搜索，按游戏版本与加载器筛选后一键下载。</li>"
            "<li><b>实时控制台</b>：逐实例独立日志、命令历史、关键字查找与日志导出。</li>"
            "<li><b>资源监视</b>：系统 CPU / 内存 / 磁盘，以及运行中服务器进程的内存与 CPU。</li>"
            "<li><b>个性化</b>：深色 / 浅色主题、窗口不透明度与等宽字体字号。</li>"
            "<li><b>可访问性</b>：完整键盘导航、F1 快捷键帮助、屏幕阅读器标签与 AA 级对比度。</li>"
            "</ul>"
        )
        card.add(browser)
        return card

    def _build_environment_card(self) -> Card:
        card = Card("环境信息")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(8)

        self.python_label = QLabel()
        self.qt_label = QLabel()
        self.os_label = QLabel()
        self.java_label = QLabel()
        self.data_label = QLabel()
        self.instances_label = QLabel()
        for label in (
            self.python_label,
            self.qt_label,
            self.os_label,
            self.java_label,
            self.data_label,
            self.instances_label,
        ):
            label.setObjectName("muted")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)

        form.addRow("Python", self.python_label)
        form.addRow("Qt", self.qt_label)
        form.addRow("操作系统", self.os_label)
        form.addRow("Java", self.java_label)
        form.addRow("数据目录", self.data_label)
        form.addRow("实例数量", self.instances_label)
        card.add(form)

        row = QHBoxLayout()
        row.setSpacing(8)
        copy_button = QPushButton("复制诊断信息")
        copy_button.setObjectName("primary")
        copy_button.clicked.connect(self._copy_diagnostics)
        row.addWidget(copy_button)
        log_button = QPushButton("打开日志目录")
        log_button.clicked.connect(lambda: open_path(logs_dir()))
        row.addWidget(log_button)
        row.addStretch(1)
        card.add(row)
        return card

    def _build_links_card(self) -> Card:
        card = Card("链接")
        browser = AutoTextBrowser()
        self.links_browser = browser
        browser.setHtml(
            "<p>项目主页：<a href='%s'>%s</a></p>"
            "<p>问题反馈：<a href='%s'>GitHub Issues</a></p>"
            "<p>开源协议：MIT License · Copyright (c) 2024-2025 HOE Team</p>"
            "<p>第三方组件：PySide6 (LGPL v3)、psutil (BSD 3-Clause)、"
            "Modrinth API、PaperMC、FabricMC、Mojang、BMCLAPI</p>" % (PROJECT_URL, PROJECT_URL, ISSUE_URL)
        )
        card.add(browser)
        return card

    # ==================== 数据 ====================
    def refresh(self) -> None:
        icon = self.app.app_icon_pixmap(64)
        if icon is not None:
            self.logo_label.setPixmap(icon)
        self.python_label.setText(sys.version.split()[0])
        try:
            import PySide6

            qt_version = PySide6.__version__
        except Exception:  # pragma: no cover
            qt_version = "未知"
        self.qt_label.setText(qt_version)
        self.os_label.setText(platform.platform())

        info = self.app.java_info
        if info is not None and getattr(info, "ok", False):
            self.java_label.setText("%s  ·  %s" % (info.version, info.path))
        else:
            self.java_label.setText("未检测到可用的 Java")
        self.data_label.setText(str(data_dir()))
        self.instances_label.setText("%d 个" % len(self.app.instances))
        self._apply_text_palette()

    def _apply_text_palette(self) -> None:
        theme = self.app.theme
        for browser in (getattr(self, "features_browser", None), getattr(self, "links_browser", None)):
            if browser is None:
                continue
            palette = browser.palette()
            palette.setColor(QPalette.Link, theme.color("blue"))
            palette.setColor(QPalette.Text, theme.color("text"))
            browser.setPalette(palette)
            browser.repaint()

    def _copy_diagnostics(self) -> None:
        lines = [
            "%s %s" % (APP_NAME, APP_VERSION),
            "Python: %s" % sys.version.split()[0],
            "Qt: %s" % self.qt_label.text(),
            "OS: %s" % self.os_label.text(),
            "Java: %s" % self.java_label.text(),
            "数据目录: %s" % self.data_label.text(),
            "实例数量: %s" % self.instances_label.text(),
        ]
        info = self.app.java_info
        if info is not None and getattr(info, "detail", ""):
            lines.append("Java 详情: %s" % info.detail)
        QApplication.clipboard().setText("\n".join(lines))
        self.app.notify("诊断信息已复制到剪贴板", "success")

    def restyle(self, theme: Theme) -> None:
        self.refresh()
        self._apply_text_palette()