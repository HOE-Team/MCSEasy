# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""与外部服务交互的纯函数（不依赖 Qt，便于测试）。

覆盖：
- 服务端核心的版本列表与下载地址（Vanilla / Paper / Fabric / Forge / NeoForge）
- Modrinth 的搜索与版本查询
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode

from .net import NetworkError, fetch_json
from .utils import natural_sort_key, sort_versions

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest.json"
PAPER_API = "https://fill.papermc.io/v3/projects/paper"
FABRIC_META = "https://meta.fabricmc.net/v2"
FORGE_META = "https://bmclapi2.bangbang93.com/forge"
NEOFORGE_MAVEN_API = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
MODRINTH_API = "https://api.modrinth.com/v2"


@dataclass
class DownloadSpec:
    """一个可下载的服务端核心。"""

    name: str
    url: str
    size: int = 0
    sha256: str = ""
    kind: str = "jar"  # jar（直接可运行） / installer（需要安装）
    server_type: str = ""
    mc_version: str = ""
    version: str = ""

    @property
    def requires_install(self) -> bool:
        return self.kind == "installer"


# ==================== 版本列表 ====================
def fetch_server_versions(server_type: str) -> List[str]:
    """返回指定服务端类型可用的 Minecraft 版本（新的在前）。"""
    server_type = (server_type or "").lower()
    if server_type == "vanilla":
        return _vanilla_versions()
    if server_type == "paper":
        return _paper_versions()
    if server_type == "fabric":
        return _fabric_versions()
    if server_type == "forge":
        return _forge_versions()
    if server_type == "neoforge":
        return _neoforge_versions()
    raise NetworkError("未知的服务端类型：%s" % server_type)


def _vanilla_versions() -> List[str]:
    data = fetch_json(MOJANG_MANIFEST)
    entries = [item for item in data.get("versions", []) if item.get("id")]
    releases = [item["id"] for item in entries if item.get("type") == "release"]
    others = [item["id"] for item in entries if item.get("type") != "release"]
    return releases + others


def _paper_versions() -> List[str]:
    data = fetch_json(PAPER_API)
    groups = data.get("versions", {})
    collected: List[str] = []
    if isinstance(groups, dict):
        for values in groups.values():
            if isinstance(values, list):
                collected.extend(str(v) for v in values)
    elif isinstance(groups, list):
        collected.extend(str(v) for v in groups)
    return sort_versions(collected)


def _fabric_versions() -> List[str]:
    data = fetch_json(FABRIC_META + "/versions/game")
    stable = [item["version"] for item in data if item.get("stable") and item.get("version")]
    snapshot = [item["version"] for item in data if not item.get("stable") and item.get("version")]
    return list(dict.fromkeys(stable + snapshot))


def _forge_versions() -> List[str]:
    data = fetch_json(FORGE_META + "/minecraft")
    if not isinstance(data, list):
        raise NetworkError("Forge 版本列表格式异常")
    return sort_versions([str(v) for v in data])


def neoforge_mc_version(neo_version: str) -> str:
    """把 NeoForge 版本号映射成 Minecraft 版本，例如 21.1.80 -> 1.21.1。"""
    parts = str(neo_version).split(".")
    if len(parts) < 2:
        return ""
    major, minor = parts[0], parts[1]
    if not (major.isdigit() and minor.isdigit()):
        return ""
    return "1.%s.%s" % (major, minor)


def _neoforge_versions() -> List[str]:
    data = fetch_json(NEOFORGE_MAVEN_API)
    raw = data.get("versions", []) if isinstance(data, dict) else []
    versions = set()
    for item in raw:
        text = str(item)
        if "beta" in text.lower() or "snapshot" in text.lower():
            continue
        mapped = neoforge_mc_version(text)
        if mapped:
            versions.add(mapped)
    return sort_versions(versions)


# ==================== 下载地址 ====================
def resolve_server_download(server_type: str, mc_version: str) -> DownloadSpec:
    """根据服务端类型与 MC 版本解析出下载信息。"""
    server_type = (server_type or "").lower()
    mc_version = (mc_version or "").strip()
    if not mc_version:
        raise NetworkError("请先选择 Minecraft 版本")
    if server_type == "vanilla":
        return _resolve_vanilla(mc_version)
    if server_type == "paper":
        return _resolve_paper(mc_version)
    if server_type == "fabric":
        return _resolve_fabric(mc_version)
    if server_type == "forge":
        return _resolve_forge(mc_version)
    if server_type == "neoforge":
        return _resolve_neoforge(mc_version)
    raise NetworkError("未知的服务端类型：%s" % server_type)


def _resolve_vanilla(mc_version: str) -> DownloadSpec:
    data = fetch_json(MOJANG_MANIFEST)
    entry = next((v for v in data.get("versions", []) if v.get("id") == mc_version), None)
    if not entry:
        raise NetworkError("Minecraft %s 不存在" % mc_version)
    detail = fetch_json(entry["url"])
    server = (detail.get("downloads") or {}).get("server")
    if not server or not server.get("url"):
        raise NetworkError("Minecraft %s 没有可用的服务端下载" % mc_version)
    return DownloadSpec(
        name="minecraft-server-%s.jar" % mc_version,
        url=server["url"],
        size=int(server.get("size") or 0),
        sha256=str(server.get("sha256") or ""),
        server_type="Vanilla",
        mc_version=mc_version,
        version=mc_version,
    )


def _resolve_paper(mc_version: str) -> DownloadSpec:
    data = fetch_json("%s/versions/%s/builds/latest" % (PAPER_API, quote(mc_version)))
    downloads = data.get("downloads") or {}
    entry = downloads.get("server:default") or next(iter(downloads.values()), None)
    if not entry or not entry.get("url"):
        raise NetworkError("Paper 没有 %s 的可用构建" % mc_version)
    checksums = entry.get("checksums") or {}
    return DownloadSpec(
        name=str(entry.get("name") or "paper-%s.jar" % mc_version),
        url=entry["url"],
        size=int(entry.get("size") or 0),
        sha256=str(checksums.get("sha256") or ""),
        server_type="Paper",
        mc_version=mc_version,
        version=str(data.get("id") or ""),
    )


def _resolve_fabric(mc_version: str) -> DownloadSpec:
    loaders = fetch_json(FABRIC_META + "/versions/loader")
    if not isinstance(loaders, list) or not loaders:
        raise NetworkError("无法获取 Fabric Loader 版本列表")
    loader = next((item for item in loaders if item.get("stable")), loaders[0]).get("version")
    if not loader:
        raise NetworkError("无法确定 Fabric Loader 版本")

    installer = "1.0.1"
    try:
        installers = fetch_json(FABRIC_META + "/versions/installer")
        if isinstance(installers, list) and installers:
            preferred = next((i for i in installers if i.get("stable")), installers[0])
            installer = str(preferred.get("version") or installer)
    except NetworkError:
        pass

    url = "%s/versions/loader/%s/%s/%s/server/jar" % (
        FABRIC_META,
        quote(mc_version),
        quote(str(loader)),
        quote(installer),
    )
    return DownloadSpec(
        name="fabric-server-%s-%s.jar" % (mc_version, loader),
        url=url,
        server_type="Fabric",
        mc_version=mc_version,
        version=str(loader),
    )


def _resolve_forge(mc_version: str) -> DownloadSpec:
    builds = fetch_json("%s/minecraft/%s" % (FORGE_META, quote(mc_version)))
    if not isinstance(builds, list) or not builds:
        raise NetworkError("Forge 没有 %s 的构建" % mc_version)
    valid = [b for b in builds if b.get("version")]
    if not valid:
        raise NetworkError("Forge 没有 %s 的可用构建" % mc_version)
    preferred = next((b for b in valid if b.get("recommended")), None)
    if preferred is None:
        preferred = sorted(valid, key=lambda b: natural_sort_key(str(b.get("version"))))[-1]
    forge_version = str(preferred["version"])
    filename = "forge-%s-%s-installer.jar" % (mc_version, forge_version)
    url = "%s/%s-%s/%s" % (FORGE_MAVEN, quote(mc_version), quote(forge_version), filename)
    return DownloadSpec(
        name=filename,
        url=url,
        kind="installer",
        server_type="Forge",
        mc_version=mc_version,
        version=forge_version,
    )


def _resolve_neoforge(mc_version: str) -> DownloadSpec:
    data = fetch_json(NEOFORGE_MAVEN_API)
    raw = data.get("versions", []) if isinstance(data, dict) else []
    matches = [
        str(item)
        for item in raw
        if neoforge_mc_version(str(item)) == mc_version and "beta" not in str(item).lower()
    ]
    if not matches:
        raise NetworkError("NeoForge 没有 %s 的稳定构建" % mc_version)
    best = sorted(matches, key=natural_sort_key)[-1]
    filename = "neoforge-%s-installer.jar" % best
    url = "%s/%s/%s" % (NEOFORGE_MAVEN, quote(best), filename)
    return DownloadSpec(
        name=filename,
        url=url,
        kind="installer",
        server_type="NeoForge",
        mc_version=mc_version,
        version=best,
    )


# ==================== Modrinth ====================
def modrinth_search(
    query: str = "",
    project_type: str = "mod",
    game_version: Optional[str] = None,
    loader: Optional[str] = None,
    limit: int = 24,
    sort_by_downloads: bool = False,
) -> List[Dict]:
    """搜索 Modrinth 上的模组 / 插件 / 整合包。"""
    params = {
        "limit": max(1, min(100, int(limit))),
        "index": "downloads" if sort_by_downloads else "relevance",
    }
    if query:
        params["query"] = query

    facets = [["project_type:%s" % project_type]]
    if game_version:
        facets.append(["versions:%s" % game_version])
    if loader:
        facets.append(["categories:%s" % loader.lower()])
    params["facets"] = json.dumps(facets, separators=(",", ":"))

    data = fetch_json("%s/search?%s" % (MODRINTH_API, urlencode(params)))
    hits = data.get("hits", []) if isinstance(data, dict) else []
    results = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        results.append(
            {
                "id": hit.get("project_id") or hit.get("slug") or "",
                "project_id": hit.get("project_id") or hit.get("slug") or "",
                "title": hit.get("title") or "未知项目",
                "description": hit.get("description") or "",
                "author": hit.get("author") or "",
                "downloads": int(hit.get("downloads") or 0),
                "icon_url": hit.get("icon_url") or "",
                "categories": hit.get("categories") or [],
                "versions": hit.get("versions") or [],
                "project_type": hit.get("project_type") or project_type,
            }
        )
    return results


def modrinth_versions(
    project_id: str,
    game_version: Optional[str] = None,
    loader: Optional[str] = None,
) -> List[Dict]:
    """获取某个项目的可用文件版本。"""
    if not project_id:
        raise NetworkError("缺少项目 ID")
    params = {}
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    if loader:
        params["loaders"] = json.dumps([loader.lower()])
    url = "%s/project/%s/version" % (MODRINTH_API, quote(str(project_id)))
    if params:
        url += "?" + urlencode(params)
    data = fetch_json(url)
    return data if isinstance(data, list) else []


def pick_primary_file(version: Dict) -> Optional[Dict]:
    """从版本信息中挑选主文件。"""
    files = (version or {}).get("files") or []
    if not files:
        return None
    primary = next((f for f in files if f.get("primary")), None)
    return primary or files[0]