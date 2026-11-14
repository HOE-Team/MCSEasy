# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""后台线程：所有耗时操作都不在主线程执行。

设计要点：
- 统一的 Worker 基类负责捕获异常并转成 error 信号，避免线程静默崩溃；
- WorkerHost 持有正在运行的任务，程序退出时统一中断并等待，杜绝
  "QThread: Destroyed while thread is still running"；
- 图标下载使用 QThreadPool，不会因为卡片数量多而创建几十个线程。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal

from . import net, services
from .config import data_dir
from .utils import human_size

logger = logging.getLogger(__name__)


class Worker(QThread):
    """带异常兜底的 QThread 基类。"""

    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cancelled = threading.Event()

    # ---- 生命周期辅助 ----
    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def run(self) -> None:  # noqa: D401 - Qt 接口
        try:
            self.execute()
        except Exception as error:  # noqa: BLE001 - 线程内不允许抛出
            logger.exception("%s 执行失败", self.__class__.__name__)
            message = str(error) or error.__class__.__name__
            try:
                self.error.emit(message)
            except RuntimeError:
                pass

    def execute(self) -> None:  # pragma: no cover - 由子类实现
        raise NotImplementedError


def is_running(worker: Optional[Worker]) -> bool:
    """安全地判断线程是否仍在运行。

    WorkerHost 会在 finished 后调用 deleteLater，此时 Python 包装对象仍在、
    但底层 C++ 对象可能已销毁，直接调用 isRunning 会抛 RuntimeError。
    """
    if worker is None:
        return False
    try:
        return bool(worker.isRunning())
    except RuntimeError:
        return False


def cancel_worker(worker: Optional[Worker]) -> None:
    """安全地取消线程。"""
    if worker is None:
        return
    try:
        worker.cancel()
        worker.requestInterruption()
    except RuntimeError:
        pass


class ResourceMonitor(Worker):
    """系统资源采样（CPU / 内存 / 磁盘吞吐 / 指定进程指标）。"""

    cpu_updated = Signal(float)
    memory_updated = Signal(float, float, float)
    disk_updated = Signal(float, float, float)
    process_updated = Signal(dict)

    INTERVAL = 1.0

    def __init__(self, get_pids_callback=None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._get_pids = get_pids_callback
        self._processes: Dict[int, object] = {}

    def execute(self) -> None:
        try:
            import psutil
        except ImportError as error:  # pragma: no cover
            self.error.emit("缺少 psutil 依赖：%s" % error)
            return

        try:
            psutil.cpu_percent(interval=None)  # 预热，避免首次采样恒为 0
        except Exception:
            pass

        previous_io = None
        previous_time = time.monotonic()

        while not self.is_cancelled():
            try:
                cpu = float(psutil.cpu_percent(interval=None))
                memory = psutil.virtual_memory()
                self.cpu_updated.emit(max(0.0, min(100.0, cpu)))
                self.memory_updated.emit(
                    float(memory.percent),
                    memory.used / (1024 ** 3),
                    memory.total / (1024 ** 3),
                )

                now = time.monotonic()
                elapsed = max(0.001, now - previous_time)
                previous_time = now
                io = psutil.disk_io_counters()
                read_rate = 0.0
                write_rate = 0.0
                if io is not None:
                    if previous_io is not None:
                        read_rate = max(0.0, (io.read_bytes - previous_io.read_bytes) / elapsed / 1024)
                        write_rate = max(0.0, (io.write_bytes - previous_io.write_bytes) / elapsed / 1024)
                    previous_io = io
                try:
                    usage = float(psutil.disk_usage(str(data_dir())).percent)
                except Exception:
                    usage = 0.0
                self.disk_updated.emit(read_rate, write_rate, usage)
                self._sample_processes(psutil)
            except Exception:
                logger.debug("资源采样失败", exc_info=True)
            self._cancelled.wait(self.INTERVAL)

    def _sample_processes(self, psutil_module) -> None:
        """采样正在运行的服务器进程：CPU、内存与运行时长。"""
        if self._get_pids is None:
            return
        try:
            pids = self._get_pids() or {}
        except Exception:
            return

        metrics = {}
        alive = set()
        for instance_id, pid in list(pids.items()):
            if not pid:
                continue
            alive.add(pid)
            try:
                process = self._processes.get(pid)
                if process is None:
                    process = psutil_module.Process(pid)
                    process.cpu_percent(None)
                    self._processes[pid] = process
                metrics[instance_id] = (
                    float(process.cpu_percent(None)),
                    process.memory_info().rss / (1024 ** 2),
                    max(0.0, time.time() - process.create_time()),
                )
            except Exception:
                self._processes.pop(pid, None)
        for pid in list(self._processes):
            if pid not in alive:
                self._processes.pop(pid, None)
        try:
            self.process_updated.emit(metrics)
        except RuntimeError:
            pass


class VersionsWorker(Worker):
    """获取服务端核心的版本列表。"""

    fetched = Signal(list)

    def __init__(self, server_type: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.server_type = server_type

    def execute(self) -> None:
        versions = services.fetch_server_versions(self.server_type)
        if not self.is_cancelled():
            self.fetched.emit(versions)


class ResolveDownloadWorker(Worker):
    """解析服务端下载地址（部分接口需要额外请求，放到后台）。"""

    resolved = Signal(object)

    def __init__(self, server_type: str, mc_version: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.server_type = server_type
        self.mc_version = mc_version

    def execute(self) -> None:
        spec = services.resolve_server_download(self.server_type, self.mc_version)
        if not self.is_cancelled():
            self.resolved.emit(spec)


class DownloadWorker(Worker):
    """通用文件下载（服务端核心与 Mod 共用）。"""

    progress = Signal(int, str)
    succeeded = Signal(str)

    def __init__(
        self,
        url: str,
        dest_dir: str,
        filename: str = "",
        expected_size: int = 0,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.dest_dir = dest_dir
        self.filename = filename
        self.expected_size = expected_size
        self._response = None

    def cancel(self) -> None:
        super().cancel()
        # 关闭 socket 让阻塞中的 read 立即返回
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def execute(self) -> None:
        def on_progress(downloaded: int, total: int) -> None:
            total = total or self.expected_size
            percent = int(downloaded * 100 / total) if total else 0
            self.progress.emit(
                max(0, min(100, percent)),
                "%s / %s" % (human_size(downloaded), human_size(total) if total else "未知"),
            )

        def on_open(response) -> None:
            self._response = response

        try:
            path = net.download_file(
                self.url,
                self.dest_dir,
                self.filename or None,
                progress=on_progress,
                cancelled=self.is_cancelled,
                open_hook=on_open,
            )
        except net.DownloadCancelled:
            self.error.emit("下载已取消")
            return
        if self.is_cancelled():
            return
        self.succeeded.emit(str(path))


class ModrinthSearchWorker(Worker):
    """搜索 Modrinth。"""

    results = Signal(list)

    def __init__(
        self,
        query: str = "",
        project_type: str = "mod",
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        limit: int = 24,
        sort_by_downloads: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.query = query
        self.project_type = project_type
        self.game_version = game_version
        self.loader = loader
        self.limit = limit
        self.sort_by_downloads = sort_by_downloads

    def execute(self) -> None:
        results = services.modrinth_search(
            query=self.query,
            project_type=self.project_type,
            game_version=self.game_version,
            loader=self.loader,
            limit=self.limit,
            sort_by_downloads=self.sort_by_downloads,
        )
        if not self.is_cancelled():
            self.results.emit(results)


class ModrinthVersionsWorker(Worker):
    """获取某个项目的文件列表。"""

    results = Signal(list)

    def __init__(
        self,
        project_id: str,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.game_version = game_version
        self.loader = loader

    def execute(self) -> None:
        versions = services.modrinth_versions(self.project_id, self.game_version, self.loader)
        if not self.is_cancelled():
            self.results.emit(versions)


class InstallerWorker(Worker):
    """运行 Forge / NeoForge 安装器，并把输出流式传回界面。"""

    output = Signal(str)
    succeeded = Signal()

    def __init__(
        self, java_exe: str, installer_path: str, workdir: str, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self.java_exe = java_exe or "java"
        self.installer_path = installer_path
        self.workdir = workdir
        self._process: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        super().cancel()
        process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass

    def execute(self) -> None:
        command = [self.java_exe, "-jar", self.installer_path, "--installServer"]
        self.output.emit("$ " + " ".join(command))
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            self._process = subprocess.Popen(
                command,
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs,
            )
        except OSError as error:
            self.error.emit("无法启动安装器：%s" % error)
            return

        process = self._process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            if self.is_cancelled():
                break
            text = line.rstrip()
            if text:
                self.output.emit(text)
        try:
            code = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            code = -1

        if self.is_cancelled():
            self.error.emit("安装已取消")
            return
        if code != 0:
            self.error.emit("安装器返回错误码 %s，请查看日志" % code)
            return
        self.succeeded.emit()


class BackupWorker(Worker):
    """把世界目录打包成 zip 备份。"""

    progress = Signal(int)
    succeeded = Signal(str)

    def __init__(
        self, source_dir: str, target_dir: str, label: str = "world", parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.label = label

    def execute(self) -> None:
        source = Path(self.source_dir)
        if not source.is_dir():
            self.error.emit("世界上不存在：%s" % source)
            return
        target_dir = Path(self.target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = target_dir / ("%s-%s.zip" % (self.label, stamp))

        files = [p for p in source.rglob("*") if p.is_file()]
        total = max(1, len(files))
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for index, path in enumerate(files):
                    if self.is_cancelled():
                        break
                    archive.write(path, path.relative_to(source.parent))
                    if index % 32 == 0:
                        self.progress.emit(int(index * 100 / total))
        except Exception as error:  # noqa: BLE001
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            self.error.emit("备份失败：%s" % error)
            return

        if self.is_cancelled():
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            self.error.emit("备份已取消")
            return
        self.progress.emit(100)
        self.succeeded.emit(str(target))


class WorkerHost(QObject):
    """统一管理后台线程的生命周期。"""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._workers: Dict[Worker, None] = {}
        self._closed = False

    def start(self, worker: Worker) -> Worker:
        if self._closed:
            # 程序正在退出：不再启动新线程，避免 "QThread destroyed while running"
            logger.debug("已关闭的 WorkerHost 拒绝启动 %s", worker.__class__.__name__)
            worker.deleteLater()
            return worker
        self._workers[worker] = None
        worker.finished.connect(lambda w=worker: self._release(w))
        worker.start()
        return worker

    def _release(self, worker: Worker) -> None:
        self._workers.pop(worker, None)
        worker.deleteLater()

    def busy(self) -> bool:
        return any(w.isRunning() for w in self._workers)

    def shutdown(self, timeout_ms: int = 4000) -> None:
        """取消并等待所有线程结束，之后不再接受新任务。"""
        self._closed = True
        workers = list(self._workers)
        for worker in workers:
            try:
                worker.cancel()
                worker.requestInterruption()
            except Exception:
                pass
        deadline = time.monotonic() + timeout_ms / 1000.0
        for worker in workers:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining <= 0:
                break
            if not worker.wait(remaining):
                logger.warning("线程 %s 未能在退出前结束", worker.__class__.__name__)
        self._workers.clear()


# ==================== 图标加载（线程池） ====================
class _IconSignals(QObject):
    done = Signal(str, bytes)


class _IconTask(QRunnable):
    def __init__(self, url: str, signals: _IconSignals) -> None:
        super().__init__()
        self.url = url
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:  # pragma: no cover - 依赖网络
        data = b""
        try:
            data = net.fetch_bytes(self.url, timeout=6, retries=0)
        except Exception:
            data = b""
        try:
            self.signals.done.emit(self.url, data)
        except RuntimeError:
            pass


class IconLoader(QObject):
    """按 URL 去重的异步图标加载器。"""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cache: Dict[str, bytes] = {}
        self._callbacks: Dict[str, List[Callable[[bytes], None]]] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(6)
        self._signals = _IconSignals(self)
        self._signals.done.connect(self._on_done)

    def cached(self, url: str) -> Optional[bytes]:
        return self._cache.get(url)

    def load(self, url: str, callback: Callable[[bytes], None]) -> None:
        if not url:
            callback(b"")
            return
        if url in self._cache:
            callback(self._cache[url])
            return
        self._callbacks.setdefault(url, []).append(callback)
        if len(self._callbacks[url]) == 1:
            self._pool.start(_IconTask(url, self._signals))

    def _on_done(self, url: str, data: bytes) -> None:
        self._cache[url] = data
        for callback in self._callbacks.pop(url, []):
            try:
                callback(data)
            except RuntimeError:
                continue

    def shutdown(self) -> None:
        self._callbacks.clear()
        try:
            self._pool.clear()
            if not self._pool.waitForDone(8000):
                logger.warning("图标下载线程未能在退出前结束")
        except Exception:
            pass