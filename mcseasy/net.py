# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""网络访问封装：统一超时、User-Agent、重试与原子下载。"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .config import APP_NAME, APP_VERSION
from .utils import sanitize_filename

USER_AGENT = APP_NAME + "/" + APP_VERSION + " (+https://github.com/HOE-Team/MCSEasy)"
DEFAULT_TIMEOUT = 20


class NetworkError(RuntimeError):
    """网络请求失败（已转换为可展示给用户的中文信息）。"""


class DownloadCancelled(Exception):
    """用户取消了下载。"""


def build_request(url: str, headers: Optional[dict] = None) -> urllib.request.Request:
    merged = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, headers=merged)


def _friendly(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 404:
            return "服务器上没有该资源（HTTP 404）"
        if error.code == 410:
            return "接口已下线（HTTP 410），请升级程序"
        return "服务器返回 HTTP %s" % error.code
    if isinstance(error, urllib.error.URLError):
        reason = getattr(error, "reason", error)
        return "无法连接网络（%s）" % reason
    if isinstance(error, TimeoutError):
        return "请求超时，请检查网络"
    return str(error) or error.__class__.__name__


def fetch_bytes(url: str, timeout: float = DEFAULT_TIMEOUT, retries: int = 1) -> bytes:
    """读取整个 URL 内容，失败时重试。"""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(build_request(url), timeout=timeout) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001 - 统一转换为中文错误
            last_error = error
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise NetworkError(_friendly(last_error or RuntimeError("未知错误")))


def fetch_json(url: str, timeout: float = DEFAULT_TIMEOUT, retries: int = 1):
    """读取并解析 JSON。"""
    raw = fetch_bytes(url, timeout=timeout, retries=retries)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NetworkError("返回内容不是有效的 JSON（%s）" % error) from error


def download_file(
    url: str,
    dest_dir,
    filename: Optional[str] = None,
    *,
    timeout: float = 30,
    chunk_size: int = 128 * 1024,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    open_hook: Optional[Callable[[object], None]] = None,
    retries: int = 2,
) -> Path:
    """下载文件到目标目录。

    - 先写入 .part 临时文件，成功后再重命名，避免留下半个文件；
    - 校验 Content-Length，防止被中断的连接蒙混过关；
    - 通过 cancelled 回调支持中途取消，open_hook 用于获取响应对象以便强制关闭。
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    name = sanitize_filename(
        filename or urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    )
    final_path = dest / name
    temp_path = dest / (name + ".part")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        downloaded = 0
        total = 0
        try:
            with urllib.request.urlopen(build_request(url), timeout=timeout) as response:
                if open_hook:
                    open_hook(response)
                total = int(response.headers.get("Content-Length") or 0)
                with open(temp_path, "wb") as handle:
                    while True:
                        if cancelled and cancelled():
                            raise DownloadCancelled()
                        block = response.read(chunk_size)
                        if not block:
                            break
                        handle.write(block)
                        downloaded += len(block)
                        if progress:
                            progress(downloaded, total)
            if cancelled and cancelled():
                raise DownloadCancelled()
            if total and downloaded < total:
                raise NetworkError(
                    "下载不完整（已下载 %d / 共 %d 字节）" % (downloaded, total)
                )
            os.replace(temp_path, final_path)
            return final_path
        except DownloadCancelled:
            _cleanup(temp_path)
            raise
        except Exception as error:  # noqa: BLE001
            _cleanup(temp_path)
            if cancelled and cancelled():
                raise DownloadCancelled() from error
            last_error = error
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
    if isinstance(last_error, NetworkError):
        raise last_error
    raise NetworkError(_friendly(last_error or RuntimeError("未知错误")))


def _cleanup(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
