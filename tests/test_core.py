# coding=utf-8
"""核心逻辑的单元测试（不依赖 Qt 窗口）。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import http.server
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcseasy import services
from mcseasy.model import (
    Instance,
    InstanceStore,
    JavaInfo,
    LaunchError,
    Settings,
    build_launch_plan,
    detect_server,
    ensure_eula,
    find_installer_jar,
    find_server_jar,
    parse_java_version,
    read_server_properties,
    unique_name,
)
from mcseasy.net import NetworkError, download_file
from mcseasy.utils import (
    OutputDecoder,
    human_size,
    natural_sort_key,
    safe_int,
    sanitize_filename,
    shorten,
    sort_versions,
)


class TestSortingAndFormatting(unittest.TestCase):
    def test_natural_sort_key(self):
        values = ["1.10", "1.9", "1.9.4", "1.20.1"]
        self.assertEqual(sorted(values, key=natural_sort_key), ["1.9", "1.9.4", "1.10", "1.20.1"])

    def test_sort_versions_desc_and_dedup(self):
        self.assertEqual(
            sort_versions(["1.9", "1.10", "1.9", "1.2"]), ["1.10", "1.9", "1.2"]
        )
        self.assertEqual(sort_versions(None), [])

    def test_human_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1024), "1.0 KB")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size("bad"), "0 B")

    def test_safe_int(self):
        self.assertEqual(safe_int("12"), 12)
        self.assertEqual(safe_int("x", 5), 5)
        self.assertEqual(safe_int("99", minimum=1, maximum=10), 10)
        self.assertEqual(safe_int(None, 7), 7)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename('a<>b|c?.jar'), "a__b_c_.jar")
        self.assertEqual(sanitize_filename(""), "download.bin")

    def test_shorten(self):
        self.assertEqual(shorten("abc", 10), "abc")
        self.assertEqual(len(shorten("x" * 100, 10)), 10)
        self.assertTrue(shorten("x" * 100, 10).endswith("…"))


class TestOutputDecoder(unittest.TestCase):
    def test_utf8_split_across_chunks(self):
        decoder = OutputDecoder()
        text = "服务器已启动\n"
        raw = text.encode("utf-8")
        first = decoder.feed(raw[:5])
        second = decoder.feed(raw[5:])
        self.assertEqual((first + second), text)

    def test_gbk_fallback(self):
        decoder = OutputDecoder()
        self.assertEqual(decoder.feed("你好\n".encode("gbk")), "你好\n")

    def test_flush_returns_remainder(self):
        decoder = OutputDecoder()
        self.assertEqual(decoder.feed(b"partial"), "partial")
        self.assertEqual(decoder.feed(b" more"), " more")
        self.assertEqual(decoder.flush(), "")

    def test_empty(self):
        decoder = OutputDecoder()
        self.assertEqual(decoder.feed(b""), "")
        self.assertEqual(decoder.flush(), "")


class TestInstanceModel(unittest.TestCase):
    def test_defaults(self):
        instance = Instance()
        self.assertTrue(instance.id)
        self.assertEqual(instance.min_mem, 2)
        self.assertEqual(instance.max_mem, 4)

    def test_from_legacy_dict(self):
        instance = Instance.from_dict(
            {
                "name": "老实例",
                "path": "C:/server",
                "min_mem": "4",
                "max_mem": "8",
                "loader_type": "Paper",
                "stop_timeout": "60",
            }
        )
        self.assertEqual(instance.name, "老实例")
        self.assertEqual(instance.min_mem, 4)
        self.assertEqual(instance.max_mem, 8)
        self.assertEqual(instance.loader, "Paper")
        self.assertEqual(instance.stop_timeout, 60)

    def test_from_dict_clamps_values(self):
        instance = Instance.from_dict({"min_mem": "16", "max_mem": "4", "stop_timeout": "0"})
        self.assertGreater(instance.max_mem, instance.min_mem)
        self.assertEqual(instance.stop_timeout, 1)

    def test_from_garbage(self):
        self.assertEqual(Instance.from_dict(None).min_mem, 2)
        self.assertEqual(Instance.from_dict({}).name, "未命名实例")

    def test_roundtrip(self):
        instance = Instance(name="测试", path="/tmp/x", mc_version="1.21.4")
        clone = Instance.from_dict(instance.to_dict())
        self.assertEqual(clone.id, instance.id)
        self.assertEqual(clone.name, "测试")

    def test_unique_name(self):
        self.assertEqual(unique_name(["a"], "b"), "b")
        self.assertEqual(unique_name(["a"], "a"), "a (2)")
        self.assertEqual(unique_name(["a", "a (2)"], "a"), "a (3)")

    def test_has_path(self):
        self.assertFalse(Instance(path="/definitely/not/here").has_path)


class TestInstanceStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.settings = Settings(Path(self.temp) / "settings.ini")
        self.store = InstanceStore(self.settings)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_empty_returns_default(self):
        instances = self.store.load()
        self.assertEqual(len(instances), 1)

    def test_roundtrip(self):
        self.store.save([Instance(name="A"), Instance(name="B")])
        loaded = self.store.load()
        self.assertEqual([i.name for i in loaded], ["A", "B"])

    def test_corrupt_json(self):
        self.settings.set(InstanceStore.KEY, "{not json")
        self.assertEqual(len(self.store.load()), 1)

    def test_duplicate_ids_are_fixed(self):
        payload = [{"id": "same", "name": "A"}, {"id": "same", "name": "B"}]
        self.settings.set(InstanceStore.KEY, json.dumps(payload))
        loaded = self.store.load()
        self.assertNotEqual(loaded[0].id, loaded[1].id)


class TestServerDetection(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _touch(self, name: str) -> Path:
        path = self.temp / name
        path.write_bytes(b"x")
        return path

    def test_paper(self):
        self._touch("paper-1.21.4-232.jar")
        self.assertEqual(detect_server(str(self.temp)), ("Paper", "1.21.4"))

    def test_fabric(self):
        self._touch("fabric-server-mc.1.21.4-loader.0.16.9-launcher.1.0.1.jar")
        self.assertEqual(detect_server(str(self.temp))[0], "Fabric")

    def test_vanilla(self):
        self._touch("minecraft-server-1.20.1.jar")
        self.assertEqual(detect_server(str(self.temp)), ("Vanilla", "1.20.1"))

    def test_unknown(self):
        self.assertEqual(detect_server(str(self.temp)), ("", ""))

    def test_missing_dir(self):
        self.assertEqual(detect_server(str(self.temp / "nope")), ("", ""))

    def test_find_server_jar_skips_installer(self):
        self._touch("forge-1.20.1-47.2.0-installer.jar")
        self._touch("paper-1.20.1-100.jar")
        self.assertEqual(find_server_jar(self.temp).name, "paper-1.20.1-100.jar")

    def test_find_installer(self):
        self._touch("forge-1.20.1-47.2.0-installer.jar")
        self.assertEqual(find_installer_jar(self.temp).name, "forge-1.20.1-47.2.0-installer.jar")

    def test_read_server_properties(self):
        (self.temp / "server.properties").write_text(
            "#comment\nserver-port=25565\nmax-players=20\nmotd=Hello=World\n", encoding="utf-8"
        )
        props = read_server_properties(self.temp)
        self.assertEqual(props["server-port"], "25565")
        self.assertEqual(props["motd"], "Hello=World")

    def test_read_properties_missing(self):
        self.assertEqual(read_server_properties(self.temp), {})


class TestEula(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_creates_when_missing(self):
        self.assertTrue(ensure_eula(self.temp))
        self.assertIn("eula=true", (self.temp / "eula.txt").read_text(encoding="utf-8"))

    def test_fixes_false(self):
        (self.temp / "eula.txt").write_text("eula=false\n", encoding="utf-8")
        self.assertTrue(ensure_eula(self.temp))
        self.assertIn("eula=true", (self.temp / "eula.txt").read_text(encoding="utf-8"))

    def test_noop_when_true(self):
        (self.temp / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        self.assertFalse(ensure_eula(self.temp))


class TestLaunchPlan(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _instance(self, **kwargs) -> Instance:
        return Instance(name="t", path=str(self.temp), **kwargs)

    def test_jar_plan(self):
        (self.temp / "server.jar").write_bytes(b"x")
        plan = build_launch_plan(self._instance(min_mem=2, max_mem=4), "java")
        self.assertEqual(plan.program, "java")
        self.assertIn("-Xms2G", plan.args)
        self.assertIn("-Xmx4G", plan.args)
        self.assertIn("-jar", plan.args)
        self.assertIn("server.jar", plan.args)
        self.assertEqual(plan.workdir, str(self.temp))

    def test_custom_args_appended(self):
        (self.temp / "server.jar").write_bytes(b"x")
        plan = build_launch_plan(self._instance(custom_args="-Dfoo=1"), "java", "-XX:+UseG1GC")
        self.assertIn("-XX:+UseG1GC", plan.args)
        self.assertIn("-Dfoo=1", plan.args)

    def test_installer_only_raises(self):
        (self.temp / "forge-1.20.1-47.2.0-installer.jar").write_bytes(b"x")
        with self.assertRaises(LaunchError):
            build_launch_plan(self._instance(), "java")

    def test_missing_jar_raises(self):
        with self.assertRaises(LaunchError):
            build_launch_plan(self._instance(), "java")

    def test_missing_dir_raises(self):
        instance = Instance(path=str(self.temp / "nope"))
        with self.assertRaises(LaunchError):
            build_launch_plan(instance, "java")

    def test_run_script_preferred(self):
        (self.temp / "run.bat").write_text("java @user_jvm_args.txt", encoding="utf-8")
        (self.temp / "run.sh").write_text("java @user_jvm_args.txt", encoding="utf-8")
        plan = build_launch_plan(self._instance(), "java")
        self.assertIn(plan.program, {"cmd", "sh"})
        # 现代 Forge 通过 user_jvm_args.txt 传入内存
        self.assertTrue((self.temp / "user_jvm_args.txt").exists())

    def test_args_file_plan(self):
        lib = self.temp / "libraries" / "net" / "minecraftforge" / "forge" / "1.20.1-47.2.0"
        lib.mkdir(parents=True)
        (lib / "win_args.txt").write_text("-cp x", encoding="utf-8")
        (lib / "unix_args.txt").write_text("-cp x", encoding="utf-8")
        plan = build_launch_plan(self._instance(), "java")
        self.assertEqual(plan.program, "java")
        self.assertTrue(any(arg.startswith("@") for arg in plan.args))


class TestJavaParsing(unittest.TestCase):
    def test_java8(self):
        self.assertEqual(parse_java_version('java version "1.8.0_301"'), ("1.8.0_301", 8))

    def test_java17(self):
        self.assertEqual(parse_java_version('openjdk version "17.0.2" 2022-01-18'), ("17.0.2", 17))

    def test_java21(self):
        self.assertEqual(parse_java_version('openjdk version "21.0.13" 2025-10-21 LTS'), ("21.0.13", 21))

    def test_unknown(self):
        self.assertEqual(parse_java_version("garbage"), ("", 0))

    def test_java_info_summary(self):
        self.assertEqual(JavaInfo(path="x", version="21").summary(), "Java 21")
        self.assertEqual(JavaInfo(error="未检测到 Java").summary(), "未检测到 Java")


class TestNeoForgeVersion(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(services.neoforge_mc_version("21.1.80"), "1.21.1")
        self.assertEqual(services.neoforge_mc_version("20.2.3"), "1.20.2")
        self.assertEqual(services.neoforge_mc_version("bad"), "")


class TestDownloadResolution(unittest.TestCase):
    def test_paper(self):
        payload = {
            "id": 232,
            "downloads": {
                "server:default": {
                    "name": "paper-1.21.4-232.jar",
                    "size": 100,
                    "checksums": {"sha256": "abc"},
                    "url": "https://example.invalid/paper.jar",
                }
            },
        }
        with mock.patch.object(services, "fetch_json", return_value=payload):
            spec = services.resolve_server_download("paper", "1.21.4")
        self.assertEqual(spec.name, "paper-1.21.4-232.jar")
        self.assertEqual(spec.sha256, "abc")
        self.assertFalse(spec.requires_install)

    def test_paper_missing_build(self):
        with mock.patch.object(services, "fetch_json", return_value={"downloads": {}}):
            with self.assertRaises(NetworkError):
                services.resolve_server_download("paper", "1.21.4")

    def test_vanilla(self):
        manifest = {"versions": [{"id": "1.20.1", "url": "https://example.invalid/v.json"}]}
        detail = {"downloads": {"server": {"url": "https://example.invalid/s.jar", "size": 5}}}

        def fake_fetch(url, **kwargs):
            return manifest if "manifest" in url else detail

        with mock.patch.object(services, "fetch_json", side_effect=fake_fetch):
            spec = services.resolve_server_download("vanilla", "1.20.1")
        self.assertEqual(spec.name, "minecraft-server-1.20.1.jar")
        self.assertEqual(spec.size, 5)

    def test_fabric(self):
        def fake_fetch(url, **kwargs):
            if url.endswith("/versions/loader"):
                return [{"version": "0.16.9", "stable": True}]
            if url.endswith("/versions/installer"):
                return [{"version": "1.0.1", "stable": True}]
            raise AssertionError(url)

        with mock.patch.object(services, "fetch_json", side_effect=fake_fetch):
            spec = services.resolve_server_download("fabric", "1.21.4")
        self.assertIn("fabric", spec.name)
        self.assertIn("0.16.9", spec.url)
        self.assertFalse(spec.requires_install)

    def test_forge_installer(self):
        builds = [{"version": "47.2.0", "recommended": True}]
        with mock.patch.object(services, "fetch_json", return_value=builds):
            spec = services.resolve_server_download("forge", "1.20.1")
        self.assertTrue(spec.requires_install)
        self.assertIn("installer", spec.name)

    def test_neoforge_installer(self):
        payload = {"versions": ["21.1.80", "21.1.79"]}
        with mock.patch.object(services, "fetch_json", return_value=payload):
            spec = services.resolve_server_download("neoforge", "1.21.1")
        self.assertTrue(spec.requires_install)
        self.assertIn("neoforge", spec.name)

    def test_unknown_type(self):
        with self.assertRaises(NetworkError):
            services.resolve_server_download("unknown", "1.0")


class TestModrinthParsing(unittest.TestCase):
    def test_search_normalises(self):
        payload = {
            "hits": [
                {
                    "project_id": "abc",
                    "title": "Demo",
                    "description": "desc",
                    "author": "me",
                    "downloads": 42,
                    "icon_url": "https://example.invalid/i.png",
                }
            ]
        }
        with mock.patch.object(services, "fetch_json", return_value=payload):
            results = services.modrinth_search(query="demo", project_type="mod")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "abc")
        self.assertEqual(results[0]["downloads"], 42)

    def test_pick_primary_file(self):
        version = {"files": [{"url": "a"}, {"url": "b", "primary": True}]}
        self.assertEqual(services.pick_primary_file(version)["url"], "b")
        self.assertIsNone(services.pick_primary_file({"files": []}))


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    payload = b"hello world" * 100

    def do_GET(self):  # noqa: N802
        if self.path == "/missing":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):  # noqa: A003
        pass


class TestDownloadFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_download_ok(self):
        seen = []
        path = download_file(
            "http://127.0.0.1:%d/file.bin" % self.port,
            self.temp,
            "out.bin",
            progress=lambda done, total: seen.append((done, total)),
            retries=0,
        )
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), _QuietHandler.payload)
        self.assertTrue(seen)

    def test_download_404_raises(self):
        with self.assertRaises(NetworkError):
            download_file(
                "http://127.0.0.1:%d/missing" % self.port, self.temp, "x.bin", retries=0
            )
        self.assertFalse((self.temp / "x.bin.part").exists())

    def test_download_cancel(self):
        with self.assertRaises(Exception):
            download_file(
                "http://127.0.0.1:%d/file.bin" % self.port,
                self.temp,
                "c.bin",
                cancelled=lambda: True,
                retries=0,
            )
        self.assertFalse((self.temp / "c.bin.part").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)