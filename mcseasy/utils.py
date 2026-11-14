# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""与 Qt 界面弱耦合的小工具函数。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def natural_sort_key(value: str) -> list:
    """自然排序键：让 1.9 < 1.10 而不是字符串比较。"""
    parts = re.split(r"(\d+)", str(value))
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def sort_versions(versions) -> list:
    """按自然顺序倒序排列版本号（新的在前）。"""
    return sorted(dict.fromkeys(versions or ()), key=natural_sort_key, reverse=True)


def human_size(num_bytes: float) -> str:
    """把字节数格式化为易读字符串。"""
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def safe_int(value, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    """把任意输入转成整数，失败或越界时返回可用的值。"""
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def sanitize_filename(name: str, fallback: str = "download.bin") -> str:
    """去掉文件名中的路径分隔符与非法字符。"""
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    name = name.strip(" .")
    return name or fallback


def format_duration(seconds: float) -> str:
    """把秒数格式化成 12:34 或 1:02:03。"""
    try:
        total = int(max(0, float(seconds)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


def shorten(text: str, limit: int = 60) -> str:
    """按字符数截断并补省略号。"""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def open_path(path) -> bool:
    """用系统默认方式打开文件或目录，跨平台且不抛异常。"""
    try:
        target = Path(path)
        if not target.exists():
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))))
    except Exception:
        return False


def reveal_path(path) -> bool:
    """在文件管理器中定位文件（失败时退化为打开所在目录）。"""
    try:
        target = Path(path)
        if not target.exists():
            return False
        if sys.platform.startswith("win"):
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(target)])
            return True
        if sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", "-R", str(target)])
            return True
        return open_path(target.parent)
    except Exception:
        return False


class OutputDecoder:
    """把服务器输出字节流转成文本。

    Minecraft 服务端通常输出 UTF-8（我们启动时也会显式指定
    `-Dfile.encoding=UTF-8`），但中文 Windows 上的旧版服务端可能输出 GBK。
    这里逐块解码，自动识别常见编码，并缓存推断结果，避免同一段日志
    反复出现乱码。
    """

    def __init__(self) -> None:
        self._encoding: str | None = None
        self._buffer = b""

    MAX_BUFFER = 1 << 20  # 1 MB 仍无法解码时强制输出，避免无限增长

    def feed(self, data: bytes) -> str:
        if data:
            self._buffer += data
        if not self._buffer:
            return ""

        text = self._try_decode(self._buffer)
        if text is not None:
            self._buffer = b""
            return text

        if len(self._buffer) > self.MAX_BUFFER:
            encoding = self._encoding or "utf-8"
            text = self._buffer.decode(encoding, errors="replace")
            self._buffer = b""
            return text
        # 可能是多字节字符被截断，等待下一块数据
        return ""

    def _try_decode(self, chunk: bytes) -> str | None:
        """尝试解码整块数据；如果只是结尾的多字节字符不完整，返回 None 等待续传。"""
        if self._encoding:
            try:
                return chunk.decode(self._encoding)
            except UnicodeDecodeError as error:
                if error.reason.startswith("unexpected end of data"):
                    return None
                self._encoding = None

        try:
            text = chunk.decode("utf-8")
            self._encoding = "utf-8"
            return text
        except UnicodeDecodeError as error:
            # 结尾处被切断的 UTF-8 字符：先不判定编码，等下一块
            if error.reason.startswith("unexpected end of data"):
                return None

        # UTF-8 失败后再尝试 GB18030（中文 Windows 上的旧版服务端）
        try:
            text = chunk.decode("gb18030")
        except UnicodeDecodeError:
            return None
        self._encoding = "gb18030"
        return text

    def flush(self) -> str:
        data, self._buffer = self._buffer, b""
        if not data:
            return ""
        for encoding in (self._encoding, "utf-8", "gb18030", "latin-1"):
            if not encoding:
                continue
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1", errors="replace")