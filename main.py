# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""MCSEasy 启动入口。

真正的实现位于 mcseasy 包中；本文件只负责初始化 Qt、日志与全局异常兜底，
以便 PyInstaller 仍然可以简单地以 main.py 作为打包入口。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from pathlib import Path

# 允许直接运行本文件（以及打包后）时正确导入同目录的 mcseasy 包
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import qInstallMessageHandler, QtMsgType  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mcseasy.config import (  # noqa: E402
    APP_NAME,
    APP_ORG,
    APP_TAGLINE,
    APP_VERSION,
    data_dir,
    setup_logging,
)
from mcseasy.theme import app_icon  # noqa: E402

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Hiragino Sans GB",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "Segoe UI",
    "DejaVu Sans",
)


def _pick_font() -> QFont:
    """挑选一个能正常显示中文的界面字体。"""
    try:
        families = {name for name in QFontDatabase.families()}
    except Exception:  # pragma: no cover
        return QFont()
    for candidate in _FONT_CANDIDATES:
        if candidate in families:
            font = QFont(candidate)
            font.setPointSize(9)
            return font
    return QFont()


def _install_message_handler() -> None:
    """把 Qt 的警告写进日志，避免只在控制台一闪而过。"""

    def handler(mode, context, message):  # noqa: ANN001
        text = str(message)
        if "QFontDatabase" in text or "QFSFileEngine" in text:
            return
        if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            logger.error("[Qt] %s", text)
        elif mode == QtMsgType.QtWarningMsg:
            logger.warning("[Qt] %s", text)
        else:
            logger.debug("[Qt] %s", text)

    qInstallMessageHandler(handler)


def _install_excepthook() -> None:
    """未捕获异常不再让程序直接消失，而是记录并提示。"""

    def hook(exc_type, exc_value, exc_tb):  # noqa: ANN001
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "未捕获异常：\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        try:
            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    "%s 遇到问题" % APP_NAME,
                    "程序遇到了未预期的错误，但不会立即退出。\n\n"
                    "%s: %s\n\n详细信息已写入日志目录：\n%s"
                    % (exc_type.__name__, exc_value, data_dir() / "logs"),
                )
        except Exception:  # pragma: no cover - 弹窗失败也不能再抛
            pass

    sys.excepthook = hook

    def thread_hook(args):  # noqa: ANN001
        logger.error(
            "线程 %s 未捕获异常：%s",
            getattr(args.thread, "name", "?"),
            "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            ),
        )

    threading.excepthook = thread_hook


def _selftest() -> int:
    """离屏自检：构建主窗口、遍历所有页面后退出。

    打包后可以用 MCSEasy.exe --selftest 快速确认程序能正常启动。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    setup_logging()
    try:
        from mcseasy.window import MainWindow

        application = QApplication.instance() or QApplication(sys.argv[:1])
        application.setStyle("Fusion")
        application.setFont(_pick_font())
        window = MainWindow()
        window.resize(1280, 800)
        window.show()
        application.processEvents()
        # 走两轮页面切换 + 卡片墙重建，覆盖「刷新后控件被销毁」这类问题
        for _ in range(2):
            for index in range(window._stack.count()):
                window.nav_list.setCurrentRow(index)
                application.processEvents()
            window._instances_page.refresh()
            application.processEvents()
        window.set_theme("light")
        application.processEvents()
        window.set_theme("dark")
        application.processEvents()
        window.close()
        application.processEvents()
        print("SELFTEST OK")
        return 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("SELFTEST FAILED")
        return 1


def main() -> int:
    setup_logging()
    _install_excepthook()

    # Qt 6 已经默认启用高 DPI 缩放；复用已存在的实例，便于嵌入与自动化测试
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName("mcseasy")
    app.setStyle("Fusion")
    app.setFont(_pick_font())
    app.setWindowIcon(app_icon())

    _install_message_handler()

    # 延迟导入，确保日志与字体在窗口构建前初始化完成
    from mcseasy.window import MainWindow

    window = MainWindow()
    window.show()
    logger.info("%s %s 已启动", APP_NAME, APP_VERSION)
    return app.exec()


if __name__ == "__main__":
    if "--version" in sys.argv:
        print("%s %s" % (APP_NAME, APP_VERSION))
        raise SystemExit(0)
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--help" in sys.argv or "-h" in sys.argv:
        print("%s %s - %s" % (APP_NAME, APP_VERSION, APP_TAGLINE))
        print("用法：main.py [--version] [--selftest]")
        raise SystemExit(0)
    raise SystemExit(main())