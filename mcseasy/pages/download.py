# coding=utf-8
# Copyright (C) 2024-2025 HOE Team.
"""下载中心：服务端核心、模组与插件。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import SERVER_TYPES, default_server_root
from ..dialogs import InstallerDialog, VersionPickerDialog
from ..model import Instance
from ..services import DownloadSpec
from ..theme import Theme
from ..utils import human_size, open_path
from ..widgets import Card, EmptyState, LoadingOverlay, ProjectCard
from ..workers import (
    DownloadWorker,
    ModrinthSearchWorker,
    ResolveDownloadWorker,
    VersionsWorker,
    cancel_worker,
    is_running,
)

logger = logging.getLogger(__name__)

MOD_LOADER_OPTIONS = ["全部", "fabric", "forge", "neoforge", "quilt"]
PLUGIN_LOADER_OPTIONS = ["全部", "paper", "spigot", "bukkit", "purpur", "folia", "velocity"]
ALL_VERSIONS_LABEL = "全部版本"
COMMON_VERSIONS = [ALL_VERSIONS_LABEL, "1.21.8", "1.21.4", "1.21.1", "1.20.6", "1.20.1", "1.19.4", "1.18.2", "1.16.5"]


class DownloadPage(QWidget):
    """下载中心。"""

    def __init__(self, app, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.app = app
        self._versions_worker: Optional[VersionsWorker] = None
        self._resolve_worker: Optional[ResolveDownloadWorker] = None
        self._server_download: Optional[DownloadWorker] = None
        self._project_downloads: Dict[bool, Optional[DownloadWorker]] = {True: None, False: None}
        self._search_workers: Dict[bool, Optional[ModrinthSearchWorker]] = {True: None, False: None}
        self._featured_loaded: Dict[bool, bool] = {True: False, False: False}
        self._cards: Dict[bool, List[ProjectCard]] = {True: [], False: []}
        self._versions_requested = False
        self.return_to_workspace = False
        self._search_edits: Dict[bool, QLineEdit] = {}
        self._version_combos: Dict[bool, QComboBox] = {}
        self._loader_combos: Dict[bool, QComboBox] = {}
        self._sort_combos: Dict[bool, QComboBox] = {}
        self._cards_layouts: Dict[bool, QVBoxLayout] = {}
        self._empties: Dict[bool, EmptyState] = {}
        self._progress_bars: Dict[bool, QProgressBar] = {}
        self._overlays: Dict[bool, LoadingOverlay] = {}
        self._result_labels: Dict[bool, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 20)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_server_tab(), "服务端核心")
        self.tabs.addTab(self._build_project_tab(True), "模组 (Mods)")
        self.tabs.addTab(self._build_project_tab(False), "插件 (Plugins)")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

    # ==================== 服务端核心 ====================
    def _build_server_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(12)

        target_card = Card("下载到")
        target_row = QHBoxLayout()
        target_row.setSpacing(8)
        self.target_label = QLabel("未选择实例")
        self.target_label.setObjectName("value")
        self.target_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        target_row.addWidget(self.target_label, 1)
        self.target_open_button = QPushButton("打开目录")
        self.target_open_button.clicked.connect(self._open_target)
        target_row.addWidget(self.target_open_button)
        target_card.add(target_row)
        layout.addWidget(target_card)

        settings_card = Card("选择版本")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("服务端"))
        self.server_type_combo = QComboBox()
        self.server_type_combo.addItems(SERVER_TYPES)
        self.server_type_combo.setMinimumWidth(120)
        self.server_type_combo.currentTextChanged.connect(self._on_server_type_changed)
        row.addWidget(self.server_type_combo)

        row.addWidget(QLabel("游戏版本"))
        self.version_combo = QComboBox()
        self.version_combo.setEditable(True)
        self.version_combo.setMinimumWidth(160)
        self.version_combo.setPlaceholderText("选择或输入版本号")
        row.addWidget(self.version_combo, 1)

        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.clicked.connect(self.refresh_versions)
        row.addWidget(self.refresh_button)
        settings_card.add(row)

        self.source_hint = QLabel("")
        self.source_hint.setObjectName("muted")
        self.source_hint.setWordWrap(True)
        settings_card.add(self.source_hint)
        layout.addWidget(settings_card)

        action_card = Card("下载")
        action_row = QHBoxLayout()
        action_row.setSpacing(14)
        self.download_button = QPushButton("开始下载")
        self.download_button.setObjectName("primary")
        self.download_button.setMinimumHeight(38)
        self.download_button.setFixedWidth(168)
        self.download_button.setCursor(Qt.PointingHandCursor)
        self.download_button.clicked.connect(self._start_server_download)
        action_row.addWidget(self.download_button)

        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.hide()
        action_row.addWidget(self.download_progress, 1)
        action_row.addStretch(1)
        action_card.add(action_row)

        self.download_status = QLabel("")
        self.download_status.setObjectName("muted")
        self.download_status.setWordWrap(True)
        action_card.add(self.download_status)
        layout.addWidget(action_card)

        tips = Card("说明")
        tips_text = QLabel(
            "• 下载前会自动把 eula.txt 写成 eula=true（这是启动 Minecraft 服务端的必要步骤）。\n"
            "• Forge / NeoForge 下载的是安装器，下载完成后可以一键运行安装，首次安装需要联网拉取依赖。\n"
            "• 实例还没有目录时，程序会询问是否在「数据目录 / servers」下自动创建。"
        )
        tips_text.setObjectName("hint")
        tips_text.setWordWrap(True)
        tips.add(tips_text)
        layout.addWidget(tips)
        layout.addStretch(1)

        self._update_source_hint()
        return page

    def on_show(self) -> None:
        """页面显示时刷新目标实例，并在首次进入时加载版本列表。"""
        self.update_target()
        if not self._versions_requested:
            self._versions_requested = True
            self.refresh_versions()

    def update_target(self) -> None:
        instance = self.app.current_instance()
        if instance is None:
            self.target_label.setText("未选择实例")
            return
        if instance.path:
            self.target_label.setText("%s  ·  %s" % (instance.display_name(), instance.path))
        else:
            self.target_label.setText("%s  ·  尚未设置目录，下载时会自动创建" % instance.display_name())

    def _open_target(self) -> None:
        instance = self.app.current_instance()
        if instance is None or not instance.path or not os.path.isdir(instance.path):
            self.app.notify("当前实例还没有可打开的目录", "error")
            return
        if not open_path(instance.path):
            self.app.notify("无法打开目录", "error")

    def _on_server_type_changed(self, _text: str) -> None:
        self._update_source_hint()
        self.refresh_versions()

    def _update_source_hint(self) -> None:
        server_type = self.server_type_combo.currentText()
        sources = {
            "Vanilla": "下载源：Mojang 官方 piston-meta",
            "Paper": "下载源：PaperMC Fill API",
            "Fabric": "下载源：FabricMC Meta（含服务端启动器）",
            "Forge": "下载源：BMCLAPI 版本索引 + Forge 官方 Maven（下载后需运行安装器）",
            "NeoForge": "下载源：NeoForged Maven（下载后需运行安装器）",
        }
        self.source_hint.setText(sources.get(server_type, ""))

    # ---- 版本列表 ----
    def refresh_versions(self) -> None:
        server_type = self.server_type_combo.currentText()
        self.version_combo.clear()
        self.version_combo.addItem("正在获取…")
        self.version_combo.setCurrentIndex(0)
        self.version_combo.setEnabled(False)
        self.download_button.setEnabled(False)
        self.download_status.setText("正在获取 %s 的版本列表…" % server_type)

        if is_running(self._versions_worker):
            cancel_worker(self._versions_worker)

        worker = VersionsWorker(server_type)
        worker.fetched.connect(self._on_versions_fetched)
        worker.error.connect(self._on_versions_error)
        self._versions_worker = worker
        self.app.workers.start(worker)

    def _on_versions_fetched(self, versions: list) -> None:
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.setEnabled(True)
        if not versions:
            self.version_combo.addItem("没有可用版本")
            self.version_combo.setCurrentIndex(0)
            self.version_combo.blockSignals(False)
            self.download_status.setText("没有获取到可用版本，请稍后重试。")
            return

        self.version_combo.addItems([str(v) for v in versions])
        self.version_combo.setCurrentIndex(0)
        self.version_combo.blockSignals(False)

        instance = self.app.current_instance()
        preferred = ""
        if instance is not None:
            preferred = instance.mc_version or ""
            if not preferred and instance.path:
                from ..model import detect_server

                _, detected = detect_server(instance.path)
                preferred = detected
        if preferred:
            index = self.version_combo.findText(preferred)
            if index >= 0:
                self.version_combo.setCurrentIndex(index)
        else:
            self.version_combo.setCurrentIndex(0)
        self.download_button.setEnabled(True)
        self.download_status.setText("已获取 %d 个版本。" % len(versions))

    def _on_versions_error(self, message: str) -> None:
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItem("获取失败")
        self.version_combo.setCurrentIndex(0)
        self.version_combo.setEnabled(True)
        self.version_combo.blockSignals(False)
        self.download_button.setEnabled(False)
        self.download_status.setText("获取版本失败：%s" % message)
        self.app.notify("获取版本失败：%s" % message, "error")

    # ---- 下载 ----
    def _start_server_download(self) -> None:
        instance = self.app.current_instance()
        if instance is None:
            self.app.notify("请先创建一个实例", "error")
            return
        if is_running(self._server_download):
            self.app.notify("已有服务端正在下载，请稍候", "error")
            return

        server_type = self.server_type_combo.currentText()
        mc_version = self.version_combo.currentText().strip()
        if not mc_version or mc_version in {"正在获取…", "获取失败", "没有可用版本"}:
            self.app.notify("请选择有效的游戏版本", "error")
            return

        if not instance.path:
            suggested = default_server_root() / ("%s-%s" % (server_type, mc_version))
            if (
                QMessageBox.question(
                    self,
                    "创建服务器目录",
                    "当前实例还没有目录。\n是否在下面的位置创建目录并下载？\n\n%s" % suggested,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                != QMessageBox.Yes
            ):
                return
            try:
                suggested.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self.app.notify("无法创建目录：%s" % error, "error")
                return
            self.app.set_instance_path(instance.id, str(suggested))
            instance = self.app.current_instance() or instance

        if not instance.path:
            return

        self.download_button.setEnabled(False)
        self.download_progress.setValue(0)
        self.download_progress.show()
        self.download_status.setText("正在解析 %s %s 的下载地址…" % (server_type, mc_version))

        worker = ResolveDownloadWorker(server_type, mc_version)
        worker.resolved.connect(lambda spec: self._on_resolved(spec, instance))
        worker.error.connect(self._on_download_error)
        self._resolve_worker = worker
        self.app.workers.start(worker)

    def _on_resolved(self, spec: DownloadSpec, instance: Instance) -> None:
        if spec is None:
            return
        instance = self.app.find_instance(instance.id) or instance
        if not instance.path:
            self._on_download_error("实例目录已失效")
            return

        self.download_status.setText(
            "正在下载 %s（%s）…" % (spec.name, human_size(spec.size) if spec.size else "大小未知")
        )
        self._pending_spec = spec
        self._pending_instance_id = instance.id

        worker = DownloadWorker(spec.url, instance.path, spec.name, spec.size)
        worker.progress.connect(self._on_download_progress)
        worker.succeeded.connect(self._on_server_downloaded)
        worker.error.connect(self._on_download_error)
        self._server_download = worker
        self.app.workers.start(worker)

    def _on_download_progress(self, percent: int, detail: str) -> None:
        self.download_progress.setValue(percent)
        self.download_status.setText("正在下载… %d%%  (%s)" % (percent, detail))

    def _on_server_downloaded(self, path: str) -> None:
        spec: Optional[DownloadSpec] = getattr(self, "_pending_spec", None)
        instance_id = getattr(self, "_pending_instance_id", "")
        self.download_progress.setValue(100)
        self.download_button.setEnabled(True)

        instance = self.app.find_instance(instance_id)
        if instance is not None and spec is not None:
            instance.loader = spec.server_type
            instance.mc_version = spec.mc_version
            self.app.persist_instances()
            self.app.refresh_instances()

        self.app.notify("服务端核心已下载完成", "success")
        self.download_status.setText("已保存到：%s" % path)

        if spec is not None and spec.requires_install:
            self._offer_install(instance, path)
        else:
            self.download_progress.hide()

        if self.return_to_workspace and instance is not None:
            self.return_to_workspace = False
            self.app.open_workspace(instance.id)

    def _offer_install(self, instance: Optional[Instance], installer_path: str) -> None:
        if instance is None or not instance.path:
            self.download_progress.hide()
            return
        java_info = self.app.java_info
        if not java_info.ok:
            self.app.notify("需要可用的 Java 才能运行安装器，请先在设置中配置", "error")
            return
        answer = QMessageBox.question(
            self,
            "运行安装器",
            "这个服务端需要先运行安装器才能启动。\n现在就运行安装吗？（可能需要几分钟）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            self.download_status.setText("已下载安装器，请稍后手动安装。")
            return

        dialog = InstallerDialog(
            self.app.theme,
            self.app.workers,
            java_info.path,
            installer_path,
            instance.path,
            self,
        )
        accepted = bool(dialog.exec())
        if accepted:
            self.app.refresh_instances()
            self.app.notify("安装完成，现在可以启动服务器了", "success")
            self.download_status.setText("安装完成。")
            if self.return_to_workspace and instance is not None:
                self.return_to_workspace = False
                self.app.open_workspace(instance.id)
        else:
            self.download_status.setText("安装未完成，可以稍后重新运行安装器。")
        self.download_progress.hide()

    def _on_download_error(self, message: str) -> None:
        self.download_progress.hide()
        self.download_button.setEnabled(True)
        self.download_status.setText("下载失败：%s" % message)
        self.app.notify("下载失败：%s" % message, "error")

    # ==================== 模组 / 插件 ====================
    def _build_project_tab(self, is_mod: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索%s名称、关键词…" % ("模组" if is_mod else "插件"))
        search_edit.returnPressed.connect(lambda: self._do_search(is_mod))
        search_row.addWidget(search_edit, 1)

        version_combo = QComboBox()
        version_combo.setEditable(True)
        version_combo.setMinimumWidth(120)
        version_combo.addItems(COMMON_VERSIONS)
        version_combo.setPlaceholderText("游戏版本")
        search_row.addWidget(version_combo)

        loader_combo = QComboBox()
        loader_combo.addItems(MOD_LOADER_OPTIONS if is_mod else PLUGIN_LOADER_OPTIONS)
        search_row.addWidget(loader_combo)

        sort_combo = QComboBox()
        sort_combo.addItems(["按相关度", "按下载量"])
        search_row.addWidget(sort_combo)

        search_button = QPushButton("搜索")
        search_button.setObjectName("primary")
        search_button.clicked.connect(lambda: self._do_search(is_mod))
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        result_header = QHBoxLayout()
        self._result_labels[is_mod] = QLabel("热门%s" % ("模组" if is_mod else "插件"))
        label = self._result_labels[is_mod]
        label.setObjectName("cardTitle")
        result_header.addWidget(label)
        result_header.addStretch(1)
        source = QLabel("数据来源：Modrinth")
        source.setObjectName("muted")
        result_header.addWidget(source)
        layout.addLayout(result_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("cardContainer")
        cards_layout = QVBoxLayout(container)
        cards_layout.setContentsMargins(2, 2, 2, 2)
        cards_layout.setSpacing(6)
        cards_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        empty = EmptyState(
            self.app.theme,
            "package" if is_mod else "plugin-and-mod",
            "还没有搜索结果",
            "输入关键词后点击「搜索」，或稍等片刻查看热门%s。" % ("模组" if is_mod else "插件"),
        )
        cards_layout.insertWidget(0, empty)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.hide()
        layout.addWidget(progress)

        overlay = LoadingOverlay(page, self.app.theme, "正在加载…")
        page.installEventFilter(overlay)

        self._search_edits[is_mod] = search_edit
        self._version_combos[is_mod] = version_combo
        self._loader_combos[is_mod] = loader_combo
        self._sort_combos[is_mod] = sort_combo
        self._cards_layouts[is_mod] = cards_layout
        self._empties[is_mod] = empty
        self._progress_bars[is_mod] = progress
        self._overlays[is_mod] = overlay
        return page

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self.on_show()
            return
        is_mod = index == 1
        self._prefill_filters(is_mod)
        if not self._featured_loaded[is_mod]:
            self._featured_loaded[is_mod] = True
            self._load_featured(is_mod)

    def _prefill_filters(self, is_mod: bool) -> None:
        instance = self.app.current_instance()
        if instance is None:
            return
        version = instance.mc_version
        if not version and instance.path:
            from ..model import detect_server

            _, version = detect_server(instance.path)
        if version:
            combo = self._version_combos[is_mod]
            if not combo.currentText() or combo.currentText() == ALL_VERSIONS_LABEL:
                index = combo.findText(version)
                if index >= 0:
                    combo.setCurrentIndex(index)
                else:
                    combo.setEditText(version)

        loader = (instance.loader or "").lower()
        if loader:
            combo = self._loader_combos[is_mod]
            index = combo.findText(loader, Qt.MatchFixedString)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _load_featured(self, is_mod: bool) -> None:
        self._run_search(is_mod, query="", sort_by_downloads=True, featured=True)

    def _do_search(self, is_mod: bool) -> None:
        query = self._search_edits[is_mod].text().strip()
        sort_by_downloads = self._sort_combos[is_mod].currentIndex() == 1
        self._run_search(is_mod, query=query, sort_by_downloads=sort_by_downloads)

    def _run_search(
        self,
        is_mod: bool,
        query: str,
        sort_by_downloads: bool = False,
        featured: bool = False,
    ) -> None:
        previous = self._search_workers[is_mod]
        if is_running(previous):
            cancel_worker(previous)

        self._clear_cards(is_mod)
        self._empties[is_mod].hide()
        self._overlays[is_mod].start("正在搜索…")
        self._result_labels[is_mod].setText(
            ("热门%s" if featured else "搜索结果") % ("模组" if is_mod else "插件")
        )

        version = self._version_combos[is_mod].currentText().strip()
        if version == ALL_VERSIONS_LABEL:
            version = None
        loader = self._loader_combos[is_mod].currentText()
        loader = None if loader == "全部" else loader

        worker = ModrinthSearchWorker(
            query=query,
            project_type="mod" if is_mod else "plugin",
            game_version=version,
            loader=loader,
            limit=24,
            sort_by_downloads=sort_by_downloads,
        )
        worker.results.connect(lambda results, m=is_mod: self._on_search_results(m, results))
        worker.error.connect(lambda message, m=is_mod: self._on_search_error(m, message))
        self._search_workers[is_mod] = worker
        self.app.workers.start(worker)

    def _on_search_results(self, is_mod: bool, results: list) -> None:
        self._overlays[is_mod].stop()
        self._clear_cards(is_mod)
        if not results:
            self._empties[is_mod].show()
            self._result_labels[is_mod].setText("没有找到结果")
            return
        self._empties[is_mod].hide()
        for data in results:
            card = ProjectCard(data, self.app.theme, self.app.icons.load)
            card.clicked.connect(lambda payload, m=is_mod: self._open_picker(m, payload))
            card.download_requested.connect(lambda payload, m=is_mod: self._open_picker(m, payload))
            self._cards_layouts[is_mod].insertWidget(
                self._cards_layouts[is_mod].count() - 1, card
            )
            self._cards[is_mod].append(card)
        self._result_labels[is_mod].setText(
            "找到 %d 个结果" % len(results)
        )

    def _on_search_error(self, is_mod: bool, message: str) -> None:
        self._overlays[is_mod].stop()
        self._result_labels[is_mod].setText("搜索失败")
        self._empties[is_mod].show()
        self.app.notify("搜索失败：%s" % message, "error")

    def _clear_cards(self, is_mod: bool) -> None:
        for card in self._cards[is_mod]:
            card.setParent(None)
            card.deleteLater()
        self._cards[is_mod].clear()

    def _open_picker(self, is_mod: bool, data: dict) -> None:
        instance = self.app.current_instance()
        if instance is None or not instance.path:
            self.app.notify("请先为当前实例选择服务器目录", "error")
            return

        dialog = VersionPickerDialog(
            self.app.theme,
            self.app.workers,
            data,
            game_version=instance.mc_version or None,
            loader=instance.loader.lower() or None,
            parent=self,
        )
        if dialog.exec() != dialog.Accepted:
            return
        file_info = dialog.selected_file()
        if not file_info:
            return
        self._download_project_file(is_mod, file_info)

    def _download_project_file(self, is_mod: bool, file_info: dict) -> None:
        instance = self.app.current_instance()
        if instance is None or not instance.path:
            return
        if is_running(self._project_downloads[is_mod]):
            self.app.notify("已有文件正在下载，请稍候", "error")
            return

        subfolder = "mods" if is_mod else "plugins"
        target = Path(instance.path) / subfolder
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.app.notify("无法创建目录：%s" % error, "error")
            return

        progress = self._progress_bars[is_mod]
        progress.setValue(0)
        progress.show()

        worker = DownloadWorker(
            file_info["url"], str(target), file_info.get("filename") or "download.jar"
        )
        worker.progress.connect(lambda percent, _detail, p=progress: p.setValue(percent))
        worker.succeeded.connect(
            lambda path, m=is_mod: self._on_project_downloaded(m, path)
        )
        worker.error.connect(lambda message: self._on_project_download_error(message))
        self._project_downloads[is_mod] = worker
        self.app.workers.start(worker)

    def _on_project_downloaded(self, is_mod: bool, path: str) -> None:
        self._progress_bars[is_mod].hide()
        name = os.path.basename(path)
        self.app.notify("已下载 %s 到 %s" % (name, os.path.dirname(path)), "success")

    def _on_project_download_error(self, message: str) -> None:
        for bar in self._progress_bars.values():
            bar.hide()
        self.app.notify("下载失败：%s" % message, "error")

    # ==================== 主题 ====================
    def restyle(self, theme: Theme) -> None:
        for is_mod, empty in self._empties.items():
            empty.set_theme(theme, "package" if is_mod else "plugin-and-mod")
        for overlay in self._overlays.values():
            overlay.set_theme(theme)