# coding=utf-8
"""界面与进程管理的集成测试（离屏运行，不需要真实显示器）。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# 必须在导入 mcseasy 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_DATA_DIR = tempfile.mkdtemp(prefix="mcseasy-test-")
os.environ["MCSEASY_DATA_DIR"] = _DATA_DIR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mcseasy.config import settings_path  # noqa: E402
from mcseasy.model import Instance  # noqa: E402
from mcseasy.widgets import ConsoleView, RingGauge  # noqa: E402
from mcseasy.theme import get_theme  # noqa: E402

QT_MESSAGES = []


def _message_handler(mode, context, message):  # noqa: ANN001
    QT_MESSAGES.append(str(message))


qInstallMessageHandler(_message_handler)

_APP = None


def get_app() -> QApplication:
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv)
        _APP.setStyle("Fusion")
    return _APP


def pump(seconds: float = 0.2) -> None:
    app = get_app()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_until(predicate, timeout: float = 20.0) -> bool:
    app = get_app()
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        try:
            if predicate():
                return True
        except RuntimeError:
            return False
        time.sleep(0.02)
    return False


def reset_settings() -> None:
    path = settings_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    # 清空设置文件，让每个用例从默认状态开始


class WindowTestBase(unittest.TestCase):
    """创建真实主窗口的测试基类（不包含测试用例本身）。"""

    def setUp(self):
        get_app()
        reset_settings()
        from mcseasy.window import MainWindow

        self.window = MainWindow()
        self.window.resize(1280, 800)
        self.window.show()
        pump(0.3)

    def tearDown(self):
        with mock.patch("mcseasy.window.QMessageBox.question", return_value=16384):
            self.window.close()
        pump(0.2)


class WorkerSafetyTest(unittest.TestCase):
    """线程对象被销毁后，辅助函数不能抛异常。"""

    def test_is_running_handles_deleted_worker(self):
        from mcseasy.workers import Worker, cancel_worker, is_running

        class _QuickWorker(Worker):
            def execute(self) -> None:
                return

        worker = _QuickWorker()
        worker.start()
        self.assertTrue(worker.wait(3000))
        worker.deleteLater()
        pump(0.2)
        self.assertFalse(is_running(worker))
        cancel_worker(worker)

    def test_none_worker(self):
        from mcseasy.workers import cancel_worker, is_running

        self.assertFalse(is_running(None))
        cancel_worker(None)


class WindowTestCase(WindowTestBase):
    """界面行为测试。"""

    # ---- 基础 ----
    def test_pages_and_theme(self):
        self.assertEqual(self.window._stack.count(), 5)
        for index in range(5):
            self.window.nav_list.setCurrentRow(index)
            pump(0.1)
            self.assertEqual(self.window._stack.currentIndex(), index)
        self.window.set_theme("light")
        pump(0.2)
        self.assertEqual(self.window.theme.key, "light")
        self.window.set_theme("dark")
        pump(0.2)
        self.assertEqual(self.window.theme.key, "dark")

    def test_stylesheet_has_no_parse_error(self):
        for key in ("dark", "light"):
            self.window.set_theme(key)
            pump(0.3)
        parse_errors = [m for m in QT_MESSAGES if "Could not parse stylesheet" in m]
        self.assertEqual(parse_errors, [])

    def test_resource_monitor_updates(self):
        self.window.nav_list.setCurrentRow(0)
        page = self.window._instances_page
        self.assertTrue(wait_until(lambda: page.cpu_meter.isVisible(), timeout=5))
        self.assertTrue(
            wait_until(
                lambda: page.mem_meter.value_label.text() != "—",
                timeout=8,
            )
        )

    def test_workspace_state_panels(self):
        window = self.window
        window.open_workspace(window.instances[0].id)
        pump(0.2)
        self.assertEqual(window._stack.currentIndex(), 1)
        workspace = window._workspace_page
        self.assertEqual(workspace.state_stack.currentIndex(), workspace.PANEL_ONBOARDING)
        self.assertFalse(workspace.start_button.isEnabled())

        temp = Path(tempfile.mkdtemp())
        try:
            (temp / "paper-1.21.4-232.jar").write_bytes(b"x")
            window.set_instance_path(window.instances[0].id, str(temp))
            pump(0.2)
            self.assertEqual(workspace.state_stack.currentIndex(), workspace.PANEL_READY)
            self.assertTrue(workspace.start_button.isEnabled())
            window.back_to_instances()
            pump(0.1)
            self.assertEqual(window._stack.currentIndex(), 0)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_card_opens_workspace(self):
        window = self.window
        page = window._instances_page
        card = page._cards[window.instances[0].id]
        card.open_requested.emit(window.instances[0].id)
        pump(0.2)
        self.assertEqual(window._stack.currentIndex(), 1)
        self.assertEqual(window._workspace_page.name_label.full_text(), window.instances[0].name)

    def test_card_wall_uses_multiple_columns(self):
        """回归：窗口足够宽时卡片必须并排，而不是被排成单列。"""
        page = self.window._instances_page
        self.window.resize(1400, 880)
        pump(0.4)
        page._relayout(force=True)
        pump(0.1)
        self.assertGreaterEqual(page._columns, 2)
        self.assertGreaterEqual(page.grid.count(), 2)
        row0, col0, _rs0, _cs0 = page.grid.getItemPosition(0)
        row1, col1, _rs1, _cs1 = page.grid.getItemPosition(1)
        self.assertEqual(row0, row1)
        self.assertNotEqual(col0, col1)

    def test_repeated_refresh_keeps_add_card(self):
        """回归：刷新卡片墙不能把常驻的「添加服务器」卡删掉（曾导致 C++ 对象已销毁崩溃）。"""
        page = self.window._instances_page
        for _ in range(3):
            page.refresh()
            pump(0.25)
        # 访问已销毁的 C++ 对象会抛 RuntimeError，这里必须能正常读写
        self.assertTrue(page.add_card.isVisible())
        self.assertEqual(page.add_card.parent(), page.container)
        page.filter_edit.setText("不存在的服务器")
        pump(0.3)
        page.filter_edit.setText("")
        pump(0.3)
        self.assertIsNotNone(page.add_card.parent())
        self.assertIn(page.add_card, [page.grid.itemAt(i).widget() for i in range(page.grid.count())])

    def test_instance_filter(self):
        window = self.window
        with mock.patch("mcseasy.window.QInputDialog.getText", return_value=("阿尔法", True)):
            window.create_instance()
        with mock.patch("mcseasy.window.QInputDialog.getText", return_value=("贝塔", True)):
            window.create_instance()
        pump(0.1)
        page = window._instances_page
        page.filter_edit.setText("阿尔法")
        pump(0.1)
        self.assertEqual(len(page._cards), 1)
        page.filter_edit.setText("")
        pump(0.1)
        self.assertEqual(len(page._cards), len(window.instances))

    def test_drop_folder_sets_path(self):
        window = self.window
        temp = Path(tempfile.mkdtemp())
        try:
            page = window._instances_page
            page._on_folder_dropped(window.instances[0].id, str(temp))
            pump(0.1)
            self.assertEqual(window.instances[0].path, str(temp))
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    # ---- 实例管理 ----
    def test_create_rename_duplicate_delete(self):
        window = self.window
        with mock.patch("mcseasy.window.QInputDialog.getText", return_value=("测试服", True)):
            window.create_instance()
        pump(0.1)
        self.assertEqual(window.instances[-1].name, "测试服")

        with mock.patch("mcseasy.window.QInputDialog.getText", return_value=("改名了", True)):
            window.rename_instance()
        pump(0.1)
        self.assertEqual(window.instances[-1].name, "改名了")

        before = len(window.instances)
        window.duplicate_instance()
        pump(0.1)
        self.assertEqual(len(window.instances), before + 1)
        self.assertEqual(window.instances[-1].path, "")

        with mock.patch("mcseasy.window.QMessageBox.question", return_value=16384):
            window.delete_instance()
        pump(0.1)
        self.assertEqual(len(window.instances), before)

    def test_cannot_delete_last_instance(self):
        window = self.window
        window._instances = [Instance(name="only")]  # noqa: SLF001
        window.refresh_instances()
        with mock.patch.object(window, "notify") as notify:
            window.delete_instance()
        self.assertTrue(notify.called)
        self.assertEqual(len(window.instances), 1)

    def test_instances_persist_across_windows(self):
        window = self.window
        window._instances[0].name = "持久化测试"  # noqa: SLF001
        window.persist_instances()
        window.close()
        pump(0.2)

        from mcseasy.window import MainWindow

        second = MainWindow()
        second.show()
        pump(0.2)
        self.assertIn("持久化测试", [i.name for i in second.instances])
        with mock.patch("mcseasy.window.QMessageBox.question", return_value=16384):
            second.close()
        pump(0.2)
        self.window = second  # 让 tearDown 正常关闭

    def test_set_instance_path_detects_server(self):
        window = self.window
        temp = Path(tempfile.mkdtemp())
        try:
            (temp / "paper-1.21.4-232.jar").write_bytes(b"x")
            instance = window.instances[0]
            window.set_instance_path(instance.id, str(temp))
            pump(0.1)
            self.assertEqual(instance.path, str(temp))
            self.assertEqual(instance.loader, "Paper")
            self.assertEqual(instance.mc_version, "1.21.4")
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    # ---- 控制台 ----
    def test_console_search_and_limit(self):
        console = ConsoleView(get_theme("dark"))
        console.append_output("first line\nsecond line\nthird line")
        self.assertEqual(console.set_search("line"), 3)
        self.assertTrue(console.find_next())
        console.set_search("")
        self.assertFalse(console.find_next())
        self.assertLessEqual(console.maximumBlockCount(), ConsoleView.MAX_BLOCKS)

    def test_console_output_decoding(self):
        console = ConsoleView(get_theme("dark"))
        console.feed_bytes("正在启动\n".encode("utf-8"))
        self.assertIn("正在启动", console.toPlainText())

    def test_gauge_clamps(self):
        gauge = RingGauge("CPU")
        gauge.set_value(150)
        self.assertLessEqual(gauge._value, 100)  # noqa: SLF001
        gauge.set_value(-10)
        self.assertGreaterEqual(gauge._value, 0)  # noqa: SLF001
        gauge.set_value("bad")
        self.assertEqual(gauge._value, 0)  # noqa: SLF001


class ProcessLifecycleTest(WindowTestBase):
    """用一个假的服务器脚本验证启动、输出、命令与停止流程。"""

    def _make_fake_server(self) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="mcseasy-fake-"))
        (directory / "fake_server.py").write_text(
            "import sys\n"
            "print('fake server ready', flush=True)\n"
            "for line in sys.stdin:\n"
            "    line = line.strip()\n"
            "    if not line:\n"
            "        continue\n"
            "    print('cmd:' + line, flush=True)\n"
            "    if line == 'stop':\n"
            "        print('fake server stopped', flush=True)\n"
            "        break\n",
            encoding="utf-8",
        )
        python = sys.executable.replace('"', "")
        if sys.platform.startswith("win"):
            (directory / "run.bat").write_text(
                '@echo off\r\n"%s" -u "fake_server.py"\r\n' % python, encoding="utf-8"
            )
        else:
            script = directory / "run.sh"
            script.write_text('#!/bin/sh\n"%s" -u fake_server.py\n' % python, encoding="utf-8")
            script.chmod(0o755)
        return directory

    def test_start_send_stop(self):
        window = self.window
        directory = self._make_fake_server()
        try:
            instance = window.instances[0]
            window.set_instance_path(instance.id, str(directory))
            pump(0.1)
            console = window._workspace_page.console_for(instance.id)  # noqa: SLF001
            self.assertIsNotNone(console)

            window.start_server(instance)
            self.assertTrue(
                wait_until(lambda: window.is_running(instance.id), timeout=20),
                "服务器进程没有启动",
            )
            self.assertTrue(
                wait_until(lambda: "fake server ready" in console.toPlainText(), timeout=20),
                "没有收到服务器输出：%r" % console.toPlainText(),
            )
            # 启动后应自动跳到工作台的控制台标签
            self.assertEqual(window._stack.currentIndex(), 1)
            self.assertEqual(
                window._workspace_page.tabs.currentIndex(),
                window._workspace_page.TAB_CONSOLE,
            )
            self.assertTrue(window._workspace_page.stop_button.isEnabled())  # noqa: SLF001

            self.assertTrue(window.send_command("list"))
            self.assertTrue(
                wait_until(lambda: "cmd:list" in console.toPlainText(), timeout=20),
                "命令没有被服务器收到",
            )

            window.stop_server(instance.id)
            self.assertTrue(
                wait_until(lambda: not window.is_running(instance.id), timeout=25),
                "服务器没有停止",
            )
            pump(0.5)
            self.assertIn("fake server stopped", console.toPlainText())
            window._workspace_page.show_overview()  # noqa: SLF001
            pump(0.1)
            self.assertTrue(window._workspace_page.start_button.isEnabled())  # noqa: SLF001
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_installer_dialog_handles_failure(self):
        """安装器对话框必须能启动子进程、接收输出并处理失败。"""
        from mcseasy.dialogs import InstallerDialog

        dialog = InstallerDialog(
            get_theme("dark"),
            self.window.workers,
            sys.executable,
            str(self._make_fake_server() / "fake_server.py"),
            str(self.window.instances[0].path or os.getcwd()),
            self.window,
        )
        dialog.show()
        pump(0.2)
        self.assertTrue(
            wait_until(lambda: "失败" in dialog.status_label.text(), timeout=25),
            "安装器错误没有被报告：%r" % dialog.status_label.text(),
        )
        dialog.reject()
        pump(0.3)

    def test_start_missing_path_reports_error(self):
        window = self.window
        instance = window.instances[0]
        instance.path = ""
        with mock.patch.object(window, "notify") as notify:
            window.start_server(instance)
        self.assertTrue(notify.called)


class EntryPointTest(unittest.TestCase):
    """验证真正被 PyInstaller 使用的入口可以完整启动。"""

    def test_main_entry(self):
        get_app()
        reset_settings()
        import main as entry

        created = []

        from mcseasy.window import MainWindow

        original_init = MainWindow.__init__

        def tracking_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created.append(self)

        with mock.patch.object(QApplication, "exec", return_value=0), mock.patch.object(
            MainWindow, "__init__", tracking_init
        ):
            self.assertEqual(entry.main(), 0)
        for window in created:
            with mock.patch("mcseasy.window.QMessageBox.question", return_value=16384):
                window.close()
        pump(0.2)


def tearDownModule():
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)