# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""MCSEasy - Minecraft 服务器部署与监视工具。

本包只包含界面与业务实现，程序入口仍然是仓库根目录的 `main.py`。
"""

from .config import APP_NAME, APP_VERSION

__all__ = ["APP_NAME", "APP_VERSION"]
