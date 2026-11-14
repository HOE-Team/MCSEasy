# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""数据模型与本地环境探测。

包含：
- Instance / InstanceStore：实例的持久化（带旧版本数据迁移）
- Settings：应用设置的读写封装
- Java 探测与服务端识别
- 启动命令的推导（原版 jar、Paper、Forge/NeoForge 的 run 脚本、args 文件）
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time as _time
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QSettings

from .config import EULA_FILE_NAME, SERVER_PROPERTIES_FILE, settings_path
from .utils import natural_sort_key, safe_int

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "theme": "dark",
    "window_transparency_percent": 100,
    "global_jvm_args": "",
    "auto_scroll": True,
    "console_font_size": 12,
    "java_path": "",
    "check_updates": True,
    "close_confirmation": True,
}


# ==================== 设置 ====================
class Settings:
    """对 QSettings 的轻量封装，统一处理类型转换与默认值。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        try:
            self._settings = QSettings(str(path or settings_path()), QSettings.IniFormat)
        except Exception:  # pragma: no cover - 极端环境
            self._settings = QSettings()

    def get(self, key: str, default=None):
        try:
            return self._settings.value(key, default)
        except Exception:  # pragma: no cover
            return default

    def set(self, key: str, value) -> None:
        try:
            self._settings.setValue(key, value)
        except Exception:  # pragma: no cover
            logger.debug("写入设置失败: %s", key)

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return default if value is None else str(value)

    def get_int(self, key: str, default: int = 0) -> int:
        return safe_int(self.get(key, default), default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def sync(self) -> None:
        try:
            self._settings.sync()
        except Exception:  # pragma: no cover
            pass


# ==================== 实例 ====================
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Instance:
    """一个服务器实例。id 在实例生命周期内保持不变，用于关联进程与控制台。"""

    id: str = field(default_factory=new_id)
    name: str = "默认实例"
    path: str = ""
    min_mem: int = 2
    max_mem: int = 4
    custom_args: str = ""
    mc_version: str = ""
    loader: str = ""
    force_stop: bool = False
    stop_timeout: int = 30
    last_played: str = ""
    created: str = field(default_factory=_now)

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Instance":
        data = data or {}
        instance = cls()
        instance.id = str(data.get("id") or new_id())
        instance.name = str(data.get("name") or "未命名实例")[:64]
        instance.path = str(data.get("path") or "")
        instance.min_mem = safe_int(data.get("min_mem"), 2, 1, 512)
        instance.max_mem = safe_int(data.get("max_mem"), 4, 1, 512)
        if instance.max_mem <= instance.min_mem:
            instance.max_mem = min(512, instance.min_mem + 1)
        instance.custom_args = str(data.get("custom_args") or "")
        instance.mc_version = str(data.get("mc_version") or "")
        instance.loader = str(data.get("loader") or data.get("loader_type") or "")
        instance.force_stop = bool(data.get("force_stop"))
        instance.stop_timeout = safe_int(data.get("stop_timeout"), 30, 1, 3600)
        instance.last_played = str(data.get("last_played") or "")
        instance.created = str(data.get("created") or _now())
        return instance

    # ---- 便捷属性 ----
    @property
    def has_path(self) -> bool:
        return bool(self.path) and os.path.isdir(self.path)

    def display_name(self) -> str:
        return self.name or "未命名实例"

    def invalidate_cache(self) -> None:
        """清空由外部目录变化导致的缓存。"""


class InstanceStore:
    """实例列表的读写，兼容 1.2/1.3 版本的旧数据。"""

    KEY = "instances"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self) -> List[Instance]:
        raw = self._settings.get(self.KEY, "")
        if not raw:
            return [Instance()]
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            logger.warning("实例配置损坏，已重置为默认实例")
            return [Instance()]
        if not isinstance(data, list) or not data:
            return [Instance()]

        instances: List[Instance] = []
        seen_ids = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            instance = Instance.from_dict(item)
            while instance.id in seen_ids:
                instance.id = new_id()
            seen_ids.add(instance.id)
            instances.append(instance)
        return instances or [Instance()]

    def save(self, instances: Iterable[Instance]) -> None:
        payload = [item.to_dict() for item in instances]
        try:
            self._settings.set(self.KEY, json.dumps(payload, ensure_ascii=False))
            self._settings.sync()
        except Exception:  # pragma: no cover
            logger.exception("保存实例列表失败")


def unique_name(existing: Iterable[str], base: str) -> str:
    """生成不与现有名称重复的名字。"""
    names = {n for n in existing}
    base = (base or "新实例").strip() or "新实例"
    if base not in names:
        return base
    index = 2
    while "%s (%d)" % (base, index) in names:
        index += 1
    return "%s (%d)" % (base, index)


# ==================== Java 探测 ====================
@dataclass
class JavaInfo:
    path: str = ""
    version: str = ""
    major: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.path) and not self.error

    def summary(self) -> str:
        if not self.ok:
            return self.error or "未检测到 Java"
        return "Java %s" % (self.version or "?")


def _hidden_process_kwargs() -> dict:
    """Windows 下不弹出控制台窗口。"""
    if sys.platform.startswith("win"):
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        return {"creationflags": creationflags}
    return {}


def parse_java_version(output: str) -> Tuple[str, int]:
    """从 java -version 输出里提取版本号与大版本。"""
    text = output or ""
    match = re.search(r'version\s+"([^"]+)"', text)
    if not match:
        match = re.search(r"openjdk\s+([0-9][^\s]*)", text, re.IGNORECASE)
    if not match:
        match = re.search(r"(\d+\.\d+[^\s]*)", text)
    if not match:
        return "", 0
    version = match.group(1)
    if version.startswith("1."):
        parts = version.split(".")
        major = safe_int(parts[1] if len(parts) > 1 else 0, 0)
    else:
        major = safe_int(re.split(r"[.\-_+]", version)[0], 0)
    return version, major


def probe_java(executable: str) -> JavaInfo:
    """执行 java -version 判断是否为可用的 JRE/JDK。"""
    if not executable:
        return JavaInfo(error="未检测到 Java")
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            timeout=8,
            check=False,
            **_hidden_process_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        return JavaInfo(path=executable, error="无法执行 Java：%s" % error)
    output = (result.stderr or b"").decode("utf-8", "replace") + (
        result.stdout or b""
    ).decode("utf-8", "replace")
    version, major = parse_java_version(output)
    if not version:
        return JavaInfo(path=executable, error="无法识别 Java 版本")
    return JavaInfo(path=executable, version=version, major=major)


def _candidate_java_paths() -> List[str]:
    candidates: List[str] = []
    java_home = os.environ.get("JAVA_HOME", "").strip()
    if java_home:
        exe = Path(java_home) / "bin" / ("java.exe" if sys.platform.startswith("win") else "java")
        candidates.append(str(exe))

    which = shutil.which("java")
    if which:
        candidates.append(which)

    if sys.platform.startswith("win"):
        roots = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        ]
        patterns = [
            "Java/*/bin/java.exe",
            "Eclipse Adoptium/*/bin/java.exe",
            "Eclipse Foundation/*/bin/java.exe",
            "Zulu/*/bin/java.exe",
            "BellSoft/*/bin/java.exe",
            "Microsoft/jdk*/bin/java.exe",
            "Amazon Corretto/*/bin/java.exe",
            "Semeru/*/bin/java.exe",
        ]
        for root in roots:
            for pattern in patterns:
                try:
                    candidates.extend(str(p) for p in sorted(root.glob(pattern), reverse=True))
                except OSError:
                    continue
    elif sys.platform == "darwin":
        try:
            candidates.extend(
                str(p) for p in sorted(Path("/Library/Java/JavaVirtualMachines").glob("*/Contents/Home/bin/java"))
            )
        except OSError:
            pass
    else:
        for base in ("/usr/lib/jvm", "/usr/java", "/opt/java"):
            try:
                candidates.extend(str(p) for p in sorted(Path(base).glob("*/bin/java")))
            except OSError:
                continue

    seen = set()
    unique: List[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def detect_java(custom_path: str = "", max_probe: int = 4) -> JavaInfo:
    """探测可用的 Java：优先自定义路径，其次 PATH / JAVA_HOME / 常见安装目录。"""
    custom_path = (custom_path or "").strip().strip('"')
    if custom_path:
        info = probe_java(custom_path)
        if info.ok:
            return info

    for candidate in _candidate_java_paths()[:max_probe]:
        info = probe_java(candidate)
        if info.ok:
            return info

    if custom_path:
        return JavaInfo(path=custom_path, error="指定的 Java 路径不可用")
    return JavaInfo(error="未在系统 PATH 中找到可用的 Java")


# ==================== 服务端识别 ====================
_JAR_PATTERNS = (
    (re.compile(r"^paper[-_.]?(?P<ver>\d+\.\d+(?:\.\d+)?)", re.I), "Paper"),
    (re.compile(r"^purpur", re.I), "Purpur"),
    (re.compile(r"^fabric[-_]?server.*?mc\.?(?P<ver>\d+\.\d+(?:\.\d+)?)", re.I), "Fabric"),
    (re.compile(r"^forge[-_]?(?P<ver>\d+\.\d+(?:\.\d+)?)", re.I), "Forge"),
    (re.compile(r"^neoforge", re.I), "NeoForge"),
    (re.compile(r"^quilt", re.I), "Quilt"),
    (re.compile(r"^(?:minecraft|vanilla)[-_]?server[-_]?(?P<ver>\d+\.\d+(?:\.\d+)?)", re.I), "Vanilla"),
)

_SERVER_JAR_PRIORITY = ("paper", "purpur", "fabric", "neoforge", "forge", "quilt", "spigot", "bukkit", "minecraft", "server")


def list_server_jars(path) -> List[Path]:
    """列出目录里可作为服务端核心的 jar（排除安装器）。"""
    directory = Path(path)
    try:
        jars = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".jar"]
    except OSError:
        return []
    usable = []
    for jar in jars:
        name = jar.name.lower()
        if "installer" in name:
            continue
        usable.append(jar)
    return usable


def find_server_jar(path) -> Optional[Path]:
    """在目录中选择最像服务端核心的 jar。"""
    jars = list_server_jars(path)
    if not jars:
        return None
    for keyword in _SERVER_JAR_PRIORITY:
        matched = sorted((j for j in jars if keyword in j.name.lower()), key=lambda p: p.name)
        if matched:
            return matched[0]
    if len(jars) == 1:
        return jars[0]
    return sorted(jars, key=lambda p: p.name)[0]


def find_installer_jar(path) -> Optional[Path]:
    """找到 Forge/NeoForge 安装器 jar。"""
    try:
        for jar in Path(path).iterdir():
            if jar.suffix.lower() == ".jar" and "installer" in jar.name.lower():
                return jar
    except OSError:
        pass
    return None


def detect_server(path) -> Tuple[str, str]:
    """推断实例的服务端类型与 MC 版本，返回 (类型, 版本)，未知时为空字符串。"""
    if not path:
        return "", ""
    directory = Path(path)
    if not directory.is_dir():
        return "", ""

    try:
        names = [p.name for p in directory.iterdir()]
    except OSError:
        return "", ""

    for name in sorted(names):
        if not name.endswith(".jar"):
            continue
        for pattern, server_type in _JAR_PATTERNS:
            match = pattern.search(name)
            if match:
                version = match.groupdict().get("ver") or ""
                if not version:
                    version = _guess_version_from_name(name)
                return server_type, version

    # Forge / NeoForge 的现代版本只有 run 脚本与 libraries 目录
    try:
        forge_dir = directory / "libraries" / "net" / "minecraftforge" / "forge"
        if forge_dir.is_dir():
            for version_dir in sorted(forge_dir.iterdir(), key=lambda p: natural_sort_key(p.name), reverse=True):
                parts = version_dir.name.split("-", 1)
                if parts:
                    return "Forge", parts[0]
    except OSError:
        pass
    try:
        neo_dir = directory / "libraries" / "net" / "neoforged" / "neoforge"
        if neo_dir.is_dir():
            return "NeoForge", ""
    except OSError:
        pass

    if (directory / "server.properties").exists() or (directory / "eula.txt").exists():
        return "Vanilla", ""
    return "", ""


def _guess_version_from_name(name: str) -> str:
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", name)
    return match.group(1) if match else ""


def read_server_properties(path) -> Dict[str, str]:
    """读取 server.properties（只读、容错）。"""
    result: Dict[str, str] = {}
    target = Path(path) / SERVER_PROPERTIES_FILE
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


# ==================== EULA ====================
def ensure_eula(path) -> bool:
    """确保 eula.txt 为 eula=true。返回是否发生了写入。"""
    eula = Path(path) / EULA_FILE_NAME
    try:
        if eula.exists():
            content = eula.read_text(encoding="utf-8", errors="replace")
            if re.search(r"^\s*eula\s*=\s*true", content, re.I | re.M):
                return False
            new_content = re.sub(r"(?im)^\s*eula\s*=\s*false", "eula=true", content)
            if new_content == content:
                new_content = content.rstrip() + "\neula=true\n"
            eula.write_text(new_content, encoding="utf-8")
            return True
        eula.write_text("# 由 MCSEasy 自动生成\neula=true\n", encoding="utf-8")
        return True
    except OSError as error:
        logger.warning("写入 eula.txt 失败: %s", error)
        return False


# ==================== 启动命令 ====================
class LaunchError(RuntimeError):
    """无法构造启动命令。"""


@dataclass
class LaunchPlan:
    program: str
    args: List[str]
    workdir: str
    description: str = ""
    needs_install: bool = False


def _sync_user_jvm_args(directory: Path, min_mem: int, max_mem: int, extra_args: str) -> None:
    """现代 Forge/NeoForge 通过 user_jvm_args.txt 传入内存参数。"""
    script_names = ("run.bat", "run.sh", "run.cmd")
    mentions = False
    for name in script_names:
        script = directory / name
        try:
            if script.exists() and "user_jvm_args" in script.read_text(encoding="utf-8", errors="ignore"):
                mentions = True
                break
        except OSError:
            continue
    if not mentions:
        return
    target = directory / "user_jvm_args.txt"
    try:
        lines = ["# 由 MCSEasy 写入的内存参数", "-Xms%dG" % min_mem, "-Xmx%dG" % max_mem]
        if extra_args.strip():
            lines.append(extra_args.strip())
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as error:
        logger.debug("写入 user_jvm_args.txt 失败: %s", error)


def _find_args_file(directory: Path) -> Optional[Path]:
    if sys.platform.startswith("win"):
        names = ("win_args.txt",)
    else:
        names = ("unix_args.txt",)
    for base in (
        directory / "libraries" / "net" / "minecraftforge" / "forge",
        directory / "libraries" / "net" / "neoforged" / "neoforge",
    ):
        try:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir(), key=lambda p: natural_sort_key(p.name), reverse=True):
                for name in names:
                    candidate = child / name
                    if candidate.exists():
                        return candidate
        except OSError:
            continue
    return None


def build_launch_plan(
    instance: Instance, java_exe: str, global_args: str = "", prepare: bool = True
) -> LaunchPlan:
    """依据实例目录的实际情况推导启动方式。

    支持三种主流布局：
    1. 存在 run.bat / run.sh（现代 Forge / NeoForge 安装后生成）
    2. 存在 libraries/**/win_args.txt（Forge 的启动参数文件）
    3. 存在独立的服务端 jar（Vanilla / Paper / Fabric / 旧版 Forge）
    """
    directory = Path(instance.path)
    if not instance.path or not directory.is_dir():
        raise LaunchError("实例目录不存在，请重新选择路径。")

    min_mem = max(1, int(instance.min_mem))
    max_mem = max(min_mem + 1, int(instance.max_mem))
    extra = " ".join(filter(None, [global_args.strip(), instance.custom_args.strip()]))

    # 1) 官方启动脚本
    for script_name in ("run.bat", "run.cmd"):
        script = directory / script_name
        if sys.platform.startswith("win") and script.exists():
            if prepare:
                _sync_user_jvm_args(directory, min_mem, max_mem, extra)
            return LaunchPlan(
                program="cmd",
                args=["/c", script_name, "nogui"],
                workdir=str(directory),
                description="通过 %s 启动" % script_name,
            )
    unix_script = directory / "run.sh"
    if unix_script.exists() and not sys.platform.startswith("win"):
        if prepare:
            _sync_user_jvm_args(directory, min_mem, max_mem, extra)
        return LaunchPlan(
            program="sh",
            args=["run.sh", "nogui"],
            workdir=str(directory),
            description="通过 run.sh 启动",
        )

    # 2) Forge 参数文件
    args_file = _find_args_file(directory)
    if args_file is not None:
        jvm_args = ["-Xms%dG" % min_mem, "-Xmx%dG" % max_mem, "-Dfile.encoding=UTF-8"]
        if extra:
            jvm_args.extend(extra.split())
        return LaunchPlan(
            program=java_exe,
            args=jvm_args + ["@" + str(args_file), "nogui"],
            workdir=str(directory),
            description="通过 Forge 参数文件启动",
        )

    # 3) 普通 jar
    jar = find_server_jar(directory)
    if jar is None:
        installer = find_installer_jar(directory)
        if installer is not None:
            raise LaunchError(
                "目录中只有安装器（%s），请先运行安装器生成服务端。" % installer.name
            )
        raise LaunchError("未找到服务端核心文件 (.jar)。可以到「下载中心」下载服务端核心。")

    jvm_args = ["-Xms%dG" % min_mem, "-Xmx%dG" % max_mem, "-Dfile.encoding=UTF-8"]
    if extra:
        jvm_args.extend(extra.split())
    return LaunchPlan(
        program=java_exe,
        args=jvm_args + ["-jar", jar.name, "nogui"],
        workdir=str(directory),
        description="java -jar %s" % jar.name,
    )

# ==================== 启动前自检 ====================
@dataclass
class LaunchReadiness:
    """启动前的检查结果，用于在界面上给出明确的原因与建议。"""

    ok: bool
    reason: str = ""
    hint: str = ""
    warning: str = ""
    needs_install: bool = False
    needs_java: bool = False
    checks: list = field(default_factory=list)

    def message(self) -> str:
        parts = [part for part in (self.reason, self.hint) if part]
        return " ".join(parts)

    def failed_checks(self) -> list:
        return [check for check in self.checks if not check.get("ok")]


def _mc_version_tuple(text: str):
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not match:
        return None
    return tuple(int(part) if part else 0 for part in match.groups())


def required_java_major(mc_version: str) -> int:
    """根据 Minecraft 版本推断最低 Java 大版本。

    只对 1.x 系列给出结论；无法识别时返回 0，表示不做判断（避免误报）。
    """
    version = _mc_version_tuple(mc_version)
    if not version:
        return 0
    major, minor, patch = version
    if major != 1:
        return 0
    if (minor, patch) >= (20, 5):
        return 21
    if minor >= 18:
        return 17
    if minor == 17:
        return 16
    return 8


def java_compatibility_warning(mc_version: str, java_major: int) -> str:
    """返回 Java 版本不匹配的提示；没有问题时返回空字符串。"""
    required = required_java_major(mc_version)
    if not required or not java_major:
        return ""
    if java_major < required:
        return (
            "Minecraft %s 需要 Java %d 或更高版本，当前检测到 Java %d，服务器可能启动失败。"
            % (mc_version, required, java_major)
        )
    if required == 8 and java_major >= 17:
        return (
            "Minecraft %s 属于旧版本，建议使用 Java 8；当前 Java %d 可能导致不兼容。"
            % (mc_version, java_major)
        )
    return ""


_PORT_CACHE: Dict[int, tuple] = {}
_PORT_CACHE_TTL = 2.0


def port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    """检查端口是否已被占用（短时间缓存，避免界面刷新时反复探测）。"""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    now = _time.monotonic()
    cached = _PORT_CACHE.get(port)
    if cached is not None and now - cached[0] < _PORT_CACHE_TTL:
        return cached[1]

    result = False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.15)
        result = probe.connect_ex(("127.0.0.1", port)) == 0
    except (OSError, ValueError):
        result = False
    finally:
        try:
            probe.close()
        except OSError:
            pass
    _PORT_CACHE[port] = (now, result)
    return result


def server_port(path) -> int:
    properties = read_server_properties(path)
    return safe_int(properties.get("server-port"), 25565, 1, 65535)


def check_launch_readiness(instance: Instance, java_info: Optional[JavaInfo] = None) -> LaunchReadiness:
    """检查实例能否启动，返回可展示的检查清单与建议。"""
    checks = []

    java_ok = java_info is not None and java_info.ok
    checks.append(
        {
            "key": "java",
            "ok": java_ok,
            "title": "Java 运行环境",
            "detail": java_info.summary() if java_info is not None else "未检测到 Java",
        }
    )

    path_ok = bool(instance.path) and os.path.isdir(instance.path)
    core_ok = False
    needs_install = False
    core_detail = ""
    if not instance.path:
        core_detail = "还没有选择服务器目录"
    elif not path_ok:
        core_detail = "目录不存在：%s" % instance.path
    else:
        try:
            plan = build_launch_plan(instance, (java_info.path if java_ok else "") or "java", prepare=False)
            core_ok = True
            core_detail = plan.description or "已找到可用的启动方式"
        except LaunchError as error:
            core_detail = str(error)
            needs_install = "安装器" in core_detail
        except Exception as error:  # noqa: BLE001
            logger.debug("启动自检失败", exc_info=True)
            core_detail = "无法解析启动方式：%s" % error
    checks.append(
        {
            "key": "installer" if needs_install else "core",
            "ok": core_ok,
            "title": "服务端核心",
            "detail": core_detail,
        }
    )

    if not path_ok:
        return LaunchReadiness(
            False,
            "还没有可用的服务器目录。",
            "点击「选择」指定一个存放服务端文件的文件夹，或把文件夹拖到左侧实例上。",
            checks=checks,
        )

    if not java_ok:
        return LaunchReadiness(
            False,
            "未检测到可用的 Java。",
            "请到「设置 → Java 运行环境」手动指定 java 可执行文件。",
            needs_java=True,
            checks=checks,
        )

    if not core_ok:
        hint = (
            "可以点「运行安装器」完成安装，之后即可启动。"
            if needs_install
            else "可以到「下载中心 → 服务端核心」下载对应版本。"
        )
        return LaunchReadiness(
            False,
            core_detail,
            hint,
            needs_install=needs_install,
            checks=checks,
        )

    warning = java_compatibility_warning(instance.mc_version, java_info.major)
    port = server_port(instance.path)
    port_ok = not port_in_use(port)
    checks.append(
        {
            "key": "port",
            "ok": port_ok,
            "title": "服务器端口",
            "detail": ("端口 %d 可用" % port) if port_ok else ("端口 %d 已被其他程序占用" % port),
        }
    )
    if not warning and not port_ok:
        warning = "端口 %d 已被占用，服务器可能无法正常启动；请关闭占用该端口的程序或修改 server-port。" % port
    return LaunchReadiness(True, warning=warning, checks=checks)