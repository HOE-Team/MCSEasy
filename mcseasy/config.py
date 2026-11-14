# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""全局配置：版本信息、目录定位与日志初始化。

该模块**不导入 Qt**，因此可以被测试或命令行工具单独使用。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "MCSEasy"
APP_VERSION = "1.5.0"
APP_ORG = "HOE Team"
APP_TAGLINE = "Minecraft 服务器管理工具"
APP_ID = "MCSEasy"

EULA_FILE_NAME = "eula.txt"
SERVER_PROPERTIES_FILE = "server.properties"

#: 支持下载的服务端类型（顺序即为界面显示顺序）
SERVER_TYPES = ("Vanilla", "Paper", "Fabric", "Forge", "NeoForge")
#: 使用插件目录的服务端
PLUGIN_LOADERS = frozenset({"paper", "bukkit", "spigot", "purpur"})
#: 使用 mods 目录的服务端
MOD_LOADERS = frozenset({"forge", "neoforge", "fabric", "quilt"})

#: 打包后（PyInstaller）用于定位随包资源的目录
_FROZEN_RESOURCE_DIR = getattr(sys, "_MEIPASS", None)

logger = logging.getLogger(__name__)


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境中。"""
    return bool(getattr(sys, "frozen", False))


def project_dir() -> Path:
    """源码根目录（打包后为解包出的临时目录）。"""
    if _FROZEN_RESOURCE_DIR:
        return Path(_FROZEN_RESOURCE_DIR)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """拼接随程序分发的资源路径（如 svg 图标）。"""
    return project_dir().joinpath(*parts)


def _platform_data_root() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / f".{APP_NAME.lower()}"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_dir / APP_NAME


_data_dir_cache: Path | None = None


def data_dir() -> Path:
    """可写的用户数据目录，首次调用时创建。

    如果常规位置不可写（只读 U 盘、受限账户等），退回系统临时目录，
    保证程序在任何情况下都能启动。
    """
    global _data_dir_cache
    if _data_dir_cache is not None:
        return _data_dir_cache

    override = os.environ.get("MCSEASY_DATA_DIR", "").strip()
    if override:
        # 便携版 / 自动化测试可以用环境变量指定独立的数据目录
        candidates = [Path(override).expanduser()]
    else:
        candidates = [_platform_data_root(), Path(tempfile.gettempdir()) / APP_NAME]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _data_dir_cache = candidate
            return candidate
        except OSError:
            continue
    # 理论上不会走到这里；兜底返回临时目录，后续写入失败由调用方处理
    _data_dir_cache = Path(tempfile.gettempdir())
    return _data_dir_cache


def logs_dir() -> Path:
    """日志目录。"""
    path = data_dir() / "logs"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(tempfile.gettempdir())
    return path


def settings_path() -> Path:
    """QSettings 使用的 ini 文件路径（避免写注册表，便于迁移与排查）。"""
    return data_dir() / "settings.ini"


def default_server_root() -> Path:
    """下载服务端时默认使用的根目录。"""
    return data_dir() / "servers"


_logging_ready = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """配置全局日志：滚动文件 + 可用的标准错误流。

    窗口模式下 `sys.stderr` 可能为 `None`，直接使用 `StreamHandler` 会在
    运行期抛异常，这里做了显式判断。
    """
    global _logging_ready
    root = logging.getLogger()
    if _logging_ready:
        return root

    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    try:
        handler = RotatingFileHandler(
            logs_dir() / "mcseasy.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass  # 无法写日志时不影响程序运行

    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            stream_handler = logging.StreamHandler(stream)
            stream_handler.setFormatter(formatter)
            root.addHandler(stream_handler)
        except Exception:  # pragma: no cover - 极端环境
            pass

    if not root.handlers:
        root.addHandler(logging.NullHandler())

    _logging_ready = True
    root.info("%s %s 启动，数据目录: %s", APP_NAME, APP_VERSION, data_dir())
    return root