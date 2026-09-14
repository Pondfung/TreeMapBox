#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
磁盘分析 Tab - 从 MainWindow 提取的磁盘分析功能

将原有的扫描、树形视图、矩形树图、右键菜单等功能封装为独立 Tab。
"""

import sys
import os
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QSplitter,
    QFileDialog, QMessageBox, QProgressBar, QMenu,
    QAbstractItemView, QApplication, QComboBox,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QAction, QShortcut, QKeySequence

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.scanner import DiskScanner, FileNode, format_size
from core.cache_detector import CacheDetector
from core.parallel_scanner import ParallelScanner
from core.mft_scanner import MFTScanner, HybridScanner
from core.size_cache import SizeCacheManager, UsnUpdater
from ui.simple_treemap import SimpleTreemapWidget
from utils.common import (
    safe_path as _safe_path,
    is_root_path as _is_root_path,
    get_export_path as _get_export_path,
)

NODE_ROLE = Qt.ItemDataRole.UserRole + 2
LOADED_ROLE = Qt.ItemDataRole.UserRole + 3

class ScanThread(QThread):
    """扫描线程"""
    progress_signal = pyqtSignal(str, int)
    error_signal = pyqtSignal(str)

    def __init__(self, scanner, path, depth=-1):
        super().__init__()
        self.scanner = scanner
        self.path = path
        self.depth = depth
        self.result = None
        self.error = None

    def run(self):
        last = [0.0]

        def progress_callback(path, count):
            if getattr(self.scanner, '_stop_flag', False):
                return
            now = time.time()
            if now - last[0] >= 0.05:
                last[0] = now
                self.progress_signal.emit(path, count)

        try:
            self.result = self.scanner.scan(
                self.path, depth=self.depth, progress_callback=progress_callback
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error = f"{type(e).__name__}: {e}"
            self.error_signal.emit(self.error)


class MFTScanThread(QThread):
    """MFT扫描线程"""
    progress_signal = pyqtSignal(str, int)
    error_signal = pyqtSignal(str)

    def __init__(self, mft_scanner, path, mode='auto'):
        super().__init__()
        self.mft_scanner = mft_scanner
        self.path = path
        self.mode = mode
        self.files = None
        self.method = None
        self.error = None
        self.root_frn = 0  # 卷根目录完整 64 位 file_reference（增量缓存写根目录行用）

    def run(self):
        def progress_callback(message, count):
            self.progress_signal.emit(message, count)

        try:
            self.files, self.method = self.mft_scanner.scan(self.path, self.mode, progress_callback)
            self.root_frn = self._extract_root_frn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error = f"{type(e).__name__}: {e}"
            self.error_signal.emit(self.error)

    def _extract_root_frn(self):
        """从实际使用的子扫描器读取根目录 FRN。"""
        if self.method == 'mft_single':
            return getattr(self.mft_scanner.mft_single, 'last_root_frn', 0)
        return getattr(self.mft_scanner.mft_scanner, 'last_root_frn', 0)


class UsnUpdaterThread(QThread):
    """后台 USN 增量追平线程（缓存秒开后异步补齐扫描期间的变更）"""
    update_finished = pyqtSignal(int, bool)  # (applied, ok)

    def __init__(self, updater, drive):
        super().__init__()
        self.updater = updater
        self.drive = drive
        self.applied = 0
        self.ok = False

    def run(self):
        try:
            self.applied, self.ok = self.updater.run(self.drive)
        except Exception:
            import traceback
            traceback.print_exc()
            self.applied = 0
            self.ok = False
        self.update_finished.emit(self.applied, self.ok)


class CacheLoadThread(QThread):
    """后台缓存加载线程：读 SQLite + 重建目录树（纯 CPU/IO，放后台避免阻塞 UI）。

    converter 传入 _convert_mft_results_to_tree（纯 Python，不碰任何 Qt 对象），
    因此可安全地在工作线程里构建 FileNode 树，再经 loaded 信号回传主线程渲染。
    """
    loaded = pyqtSignal(object)   # FileNode 根节点（成功）；None 表示缓存为空
    failed = pyqtSignal(str)      # 错误信息

    def __init__(self, cache, path, converter):
        super().__init__()
        self.cache = cache
        self.path = path
        self.converter = converter

    def run(self):
        try:
            files = self.cache.load(self.path)
            if not files:
                self.loaded.emit(None)
                return
            root = self.converter(files, self.path)
            self.loaded.emit(root)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


class DiskAnalysisTab(QWidget):
    """磁盘分析 Tab（从 MainWindow 提取的完整功能）"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window  # 引用 MainWindow（用于状态栏更新）

        self.scanner = DiskScanner(skip_system_dirs=True)
        self.parallel_scanner = ParallelScanner(skip_system_dirs=True)
        self.use_parallel = True
        self.mft_scanner = MFTScanner()
        self.hybrid_scanner = HybridScanner()
        self.cache_detector = CacheDetector(
            str(Path(__file__).parent.parent / "config" / "software_rules.json")
        )
        self.scan_thread = None
        self._live_scan_threads = []
        self._scan_cancelled = False
        self.current_node = None
        self._scan_start = 0.0
        self._elapsed_timer = None  # 扫描计时器：每秒刷新已用时间，避免大目录扫描假死
        self._flash_item = None
        self._flash_timer = None
        self._flash_count = 0
        self._flash_state = False

        # USN 增量缓存：首次 MFT 全量扫描后持久化目录大小，二次启动秒开
        self.size_cache = SizeCacheManager()
        self.usn_updater = UsnUpdater(self.size_cache)
        self.usn_thread = None
        self.cache_load_thread = None  # 后台缓存加载线程
        self._pending_journal_snapshot = None  # 扫描开始前的 journal 游标

        self._setup_ui()
        self._setup_shortcuts()

    def _update_status(self, msg):
        """更新主窗口状态栏"""
        self.main_window.status_label.setText(msg)

    def _update_time(self, msg):
        """更新主窗口时间标签"""
        self.main_window.time_label.setText(msg)

    def _start_elapsed_timer(self):
        """启动扫描计时器：每秒更新状态栏已用时间，让大目录扫描不假死"""
        self._stop_elapsed_timer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._on_elapsed_tick)
        self._elapsed_timer.start(1000)

    def _stop_elapsed_timer(self):
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer.deleteLater()
            self._elapsed_timer = None

    def _on_elapsed_tick(self):
        """计时器每秒触发：显示已用时间"""
        if self._scan_start:
            elapsed = time.perf_counter() - self._scan_start
            self._update_status(f"扫描/加载进行中... 已用 {elapsed:.0f}s")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部控制区域
        control_layout = QHBoxLayout()
        layout.addLayout(control_layout)

        self.path_label = QLabel("扫描路径:")
        control_layout.addWidget(self.path_label)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("输入路径，如 C:\\Users")
        self.path_input.setText("C:\\")
        control_layout.addWidget(self.path_input)

        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse_path)
        control_layout.addWidget(self.browse_btn)

        self.depth_label = QLabel("扫描深度:")
        control_layout.addWidget(self.depth_label)

        self.depth_combo = QComboBox()
        self.depth_combo.addItems([
            "浅层扫描 (1层)", "标准扫描 (2层)", "深度扫描 (5层)", "完全扫描 (无限制)"
        ])
        self.depth_combo.setCurrentIndex(3)  # 默认完全扫描
        control_layout.addWidget(self.depth_combo)

        self.mode_label = QLabel("扫描模式:")
        control_layout.addWidget(self.mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["自动（推荐）", "MFT极速扫描", "普通扫描"])
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.setToolTip(
            "自动：优先使用MFT极速扫描（需管理员权限），失败则降级为普通扫描\n"
            "MFT极速：强制使用MFT扫描（10-15秒完成，需管理员权限）\n"
            "普通扫描：使用传统方式扫描（2-5分钟）"
        )
        control_layout.addWidget(self.mode_combo)

        self.view_toggle_btn = QPushButton("切换到矩形树图")
        self.view_toggle_btn.setCheckable(True)
        self.view_toggle_btn.clicked.connect(self._toggle_view)
        control_layout.addWidget(self.view_toggle_btn)
        self.view_toggle_btn.setVisible(False)

        self.back_btn = QPushButton("↑ 返回上级")
        self.back_btn.setToolTip("返回上一级目录 (Backspace)")
        self.back_btn.clicked.connect(lambda: self.treemap_widget.navigate_back())
        self.back_btn.setEnabled(False)
        control_layout.addWidget(self.back_btn)
        self.back_btn.setVisible(False)

        control_layout.addStretch()

        self.scan_btn = QPushButton("开始扫描")
        self.scan_btn.clicked.connect(self._start_scan)
        control_layout.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_scan)
        control_layout.addWidget(self.stop_btn)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 视图容器
        self.view_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.view_splitter)

        # 左侧：树形列表
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["名称", "大小", "安全评级", "路径"])
        self.result_tree.setColumnWidth(0, 250)
        self.result_tree.setColumnWidth(1, 120)
        self.result_tree.setColumnWidth(2, 100)
        self.result_tree.setColumnWidth(3, 400)
        self.result_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.result_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.result_tree.setMinimumHeight(400)
        self.result_tree.setUniformRowHeights(True)
        self.result_tree.setAnimated(False)
        self.result_tree.setSortingEnabled(True)
        self.result_tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.result_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.result_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.result_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.result_tree.setMouseTracking(True)
        self.result_tree.itemEntered.connect(self._on_tree_item_hover)
        self.result_tree.itemExpanded.connect(self._on_tree_item_expanded)
        self.result_tree.itemCollapsed.connect(self._on_tree_item_collapsed)
        self.view_splitter.addWidget(self.result_tree)

        # 右侧：矩形树图
        self.treemap_widget = SimpleTreemapWidget()
        self.treemap_widget.setMinimumHeight(400)
        self.treemap_widget.setMinimumWidth(400)
        self.treemap_widget.node_clicked.connect(self._on_treemap_node_clicked)
        self.treemap_widget.node_double_clicked.connect(self._on_treemap_node_double_clicked)
        self.treemap_widget.navigated.connect(self._on_treemap_navigated)
        self.treemap_widget.navigated_back.connect(self._on_treemap_navigated_back)
        self.treemap_widget.return_to_root.connect(self._collapse_all_expanded_nodes)
        self.treemap_widget.show_in_tree_requested.connect(self._show_node_in_tree)
        self.treemap_widget.node_hovered.connect(self._on_treemap_node_hovered)
        self.view_splitter.addWidget(self.treemap_widget)

        self.view_splitter.setSizes([600, 600])

    def _setup_shortcuts(self):
        self.shortcut_select_all = QShortcut(QKeySequence("Ctrl+A"), self)
        self.shortcut_select_all.activated.connect(self._select_all)
        self.shortcut_delete = QShortcut(QKeySequence("Delete"), self)
        self.shortcut_delete.activated.connect(self._delete_selected)

    def _select_all(self):
        self.result_tree.selectAll()

    def _delete_selected(self):
        selected_items = self.result_tree.selectedItems()
        if selected_items:
            self._batch_delete(selected_items)

    def _browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择扫描目录", self.path_input.text())
        if path:
            self.path_input.setText(path)

    def _start_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        self._scan_cancelled = False
        path = self.path_input.text().strip()
        if not path:
            QMessageBox.warning(self, "警告", "请输入扫描路径")
            return
        if not Path(path).exists():
            QMessageBox.warning(self, "警告", f"路径不存在: {path}")
            return

        # 缓存秒开：缓存有效直接加载，随后后台 USN 增量追平（跳过 JSON 复用询问与全量扫描）
        if self.size_cache.is_valid(path):
            self._load_from_size_cache(path)
            return

        # 根目录：若存在1天内生成的JSON，询问用户复用还是重新扫描
        if _is_root_path(path):
            json_path = _get_export_path(path)
            if os.path.exists(json_path):
                try:
                    age_hours = (time.time() - os.path.getmtime(json_path)) / 3600
                    if age_hours <= 24:
                        if self._ask_reuse_json(path, json_path, age_hours):
                            return  # 已走复用流程
                except Exception:
                    pass

        self._start_full_scan(path)

    def _start_full_scan(self, path):
        """启动全量扫描（MFT 或普通），MFT 前记录 journal 游标供缓存写入。"""
        # 全量重扫会重写缓存，先停掉可能还在跑的后台增量（并发互斥）
        self._stop_usn_update()

        self._scan_start = time.perf_counter()
        self.result_tree.clear()

        depth_map = {0: 1, 1: 2, 2: 5, 3: -1}
        scan_depth = depth_map[self.depth_combo.currentIndex()]
        mode_index = self.mode_combo.currentIndex()
        mode_map = {0: 'auto', 1: 'mft', 2: 'normal'}
        scan_mode = mode_map[mode_index]

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._update_status("正在扫描...")
        self._start_elapsed_timer()  # 启动计时器，扫描全程显示已用时间

        if scan_mode == 'normal':
            self._launch_scan_thread(
                ScanThread(self.parallel_scanner, path, depth=scan_depth),
                self._on_scan_finished)
        elif scan_mode == 'mft':
            if not self.mft_scanner.has_admin_rights():
                QMessageBox.warning(self, "需要管理员权限", "MFT扫描需要管理员权限。")
                self._reset_scan_ui()
                return
            if not self.mft_scanner.is_mft_library_available():
                QMessageBox.warning(self, "MFT库不可用", "MFT极速扫描不可用。")
                self._reset_scan_ui()
                return
            self._capture_journal_snapshot(path)
            self._launch_scan_thread(
                MFTScanThread(self.hybrid_scanner, path, mode='mft'),
                self._on_mft_scan_finished)
        else:
            can_use_mft = (
                self.mft_scanner.has_admin_rights() and
                self.mft_scanner.is_ntfs_drive(path) and
                self.mft_scanner.is_mft_library_available()
            )
            if can_use_mft:
                self._capture_journal_snapshot(path)
                self._launch_scan_thread(
                    MFTScanThread(self.hybrid_scanner, path, mode='auto'),
                    self._on_mft_scan_finished)
            else:
                self._launch_scan_thread(
                    ScanThread(self.parallel_scanner, path, depth=scan_depth),
                    self._on_scan_finished)

    def _capture_journal_snapshot(self, path):
        """记录扫描开始前的 USN journal 游标。

        缓存写入时用「扫描开始前」的位置作为增量起点：扫描期间发生的变更会由
        后续后台增量重放（stat 幂等），从而不漏掉扫描期间的增删改。失败返回 None
        （届时缓存不记录 journal 状态，下次启动走全量，安全降级）。
        """
        self._pending_journal_snapshot = self.size_cache.query_journal_snapshot(
            self.size_cache._drive(path))

    def _load_from_size_cache(self, path):
        """从 SQLite 缓存加载目录大小，随后后台 USN 增量追平。

        读库 + 重建目录树（122 万条目的纯 CPU/IO）放到 CacheLoadThread 后台执行，
        主线程只做轻量的列表填充与树图渲染，避免加载过程 UI 假死。
        """
        self._scan_start = time.perf_counter()
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._start_elapsed_timer()
        self.result_tree.clear()
        self.treemap_widget.clear_display()
        self.current_node = None
        self._pending_cache_path = path
        self._update_status("正在从缓存加载...")

        thread = CacheLoadThread(self.size_cache, path, self._convert_mft_results_to_tree)
        thread.loaded.connect(self._on_cache_loaded)
        thread.failed.connect(self._on_cache_load_failed)
        thread.finished.connect(thread.deleteLater)
        # 容器持有引用：防止 run() 尚未返回时 Python GC 提前析构仍在运行的 QThread，
        # 触发 "QThread: Destroyed while thread is still running" 崩溃（异常码 0xc0000409）。
        # 引用由 destroyed 信号统一释放，与 scan_thread 的既有模式保持一致。
        self._live_scan_threads.append(thread)
        thread.destroyed.connect(lambda _=None, t=thread: self._discard_scan_thread(t))
        self.cache_load_thread = thread
        thread.start()

    def _on_cache_loaded(self, root_node):
        """后台缓存加载完成：主线程填充列表 + 渲染树图，然后启动 USN 增量。"""
        # 不能在此处置 None：run() 可能尚未返回，过早解除引用会让 GC 析构仍在
        # 运行的 QThread（0xc0000409）。引用由 _live_scan_threads + destroyed 管理。
        path = getattr(self, '_pending_cache_path', None) or self.path_input.text().strip()

        if root_node is None:
            # is_valid 已挡掉空缓存，此处仅防御：回退全量扫描
            self._update_status("缓存为空，回退全量扫描")
            self._reset_scan_ui()
            self._start_full_scan(path)
            return

        try:
            self.current_node = root_node
            self._update_status("目录树重建完成，正在填充列表...")
            self._populate_tree(root_node)
            self._update_status("列表填充完成，正在渲染矩形树图...")
            self.treemap_widget.set_data(root_node)
            load_secs = time.perf_counter() - self._scan_start

            self._update_time(f"上次: 缓存加载{load_secs:.1f}s")
            self._update_status(
                f"[缓存] 加载完成 - 总大小: {format_size(root_node.size)}, "
                f"文件数: {root_node.file_count}, 目录数: {root_node.dir_count}"
            )

            # 后台 USN 增量追平（启动失败不影响已加载的缓存快照，静默降级）
            try:
                self._start_usn_update(path)
            except Exception as e:
                print(f"[增量] 启动失败: {e}", flush=True)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"处理缓存数据失败: {e}")
            self._update_status("缓存加载失败，请重新扫描")
        finally:
            self._reset_scan_ui()

    def _on_cache_load_failed(self, msg):
        """后台缓存加载失败：弹错并复位 UI（不回退全量，由用户决定是否重扫）。"""
        QMessageBox.critical(self, "加载失败", f"读取缓存失败: {msg}")
        self._update_status("缓存加载失败，请重新扫描")
        self._reset_scan_ui()

    def _start_usn_update(self, scan_path):
        """启动后台 USN 增量追平线程。"""
        drive = self.size_cache._drive(scan_path)
        self.usn_thread = UsnUpdaterThread(self.usn_updater, drive)
        self.usn_thread.update_finished.connect(self._on_usn_update_finished)
        self.usn_thread.finished.connect(self.usn_thread.deleteLater)
        # 容器持有引用，防止 GC 提前析构仍在运行的 QThread（同 CacheLoadThread）
        self._live_scan_threads.append(self.usn_thread)
        self.usn_thread.destroyed.connect(
            lambda _=None, t=self.usn_thread: self._discard_scan_thread(t))
        self.usn_thread.start()

    def _stop_usn_update(self):
        """停止后台增量线程（全量重扫前调用，避免与 save_scan 并发写库）。"""
        if self.usn_thread is not None:
            try:
                if self.usn_thread.isRunning():
                    self.usn_updater.cancel()
                    self.usn_thread.wait(3000)
            except RuntimeError:
                pass  # 线程对象已 deleteLater

    def _on_usn_update_finished(self, applied, ok):
        # 同 CacheLoadThread：不在此处置 None，引用由容器 + destroyed 管理。
        if ok:
            self._update_status(f"后台增量更新完成（{applied} 条变更）")
        else:
            self._update_status("后台增量更新未完成，下次扫描将全量刷新")

    def _ask_reuse_json(self, path, json_path, age_hours):
        """根目录扫描时询问用户是否复用1天内JSON。返回True表示已处理（复用），False表示重新扫描。"""
        reply = QMessageBox.question(
            self, "发现近期扫描结果",
            f"检测到 {path} 在 {age_hours:.1f} 小时前扫描过（{json_path}）。\n\n"
            f"复用结果：几秒加载（数据为当时快照，非实时）\n"
            f"重新扫描：MFT实时扫描（约1分钟，最新状态）\n\n"
            f"是否复用近期结果？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._load_from_json(path, json_path)
            return True
        return False

    def _load_from_json(self, path, json_path):
        """从JSON文件列表重建目录树并显示（复用近期扫描结果）"""
        import json
        self._scan_start = time.perf_counter()
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._start_elapsed_timer()
        # 清空旧树和树图，避免上一个盘的内容混入/双份显示
        self.result_tree.clear()
        self.treemap_widget.clear_display()
        self.current_node = None
        self._update_status(f"正在从JSON加载（{os.path.basename(json_path)}）...")
        QApplication.processEvents()

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            files = data.get('files', [])
            # 补 name/is_dir 字段（JSON只存 path+size），供 _convert_mft_results_to_tree 重建树
            for fitem in files:
                fitem['name'] = os.path.basename(fitem.get('path', ''))
                fitem['is_dir'] = False

            t0 = time.perf_counter()
            self._update_status(f"正在重建目录树（{len(files)} 个文件）...")
            QApplication.processEvents()
            root_node = self._convert_mft_results_to_tree(files, data.get('scan_path', path))
            if not root_node:
                self._update_status("加载失败：无法重建目录树")
                self._reset_scan_ui()
                return

            self.current_node = root_node
            self._update_status("目录树重建完成，正在填充列表...")
            QApplication.processEvents()
            t1 = time.perf_counter()
            self._populate_tree(root_node)
            self._update_status("列表填充完成，正在渲染矩形树图...")
            QApplication.processEvents()
            self.treemap_widget.set_data(root_node)
            load_secs = time.perf_counter() - t0

            self._update_time(f"上次: 复用JSON 加载{load_secs:.1f}s")
            self._update_status(
                f"[复用JSON] 加载完成 - 总大小: {format_size(root_node.size)}, "
                f"文件数: {root_node.file_count}, 目录数: {root_node.dir_count}"
            )
        except (json.JSONDecodeError, ValueError) as e:
            # JSON 损坏（多半是上次写入被中断留下半截文件）：提示并删除，建议重新扫描
            try:
                os.remove(json_path)
            except OSError:
                pass
            QMessageBox.warning(self, "扫描结果已损坏",
                f"JSON 文件损坏（{e}），已删除。\n\n"
                f"请重新扫描以生成新的结果。")
            self._update_status("扫描结果损坏，请重新扫描")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"读取JSON失败: {e}")
            self._update_status("加载失败")
        finally:
            self._reset_scan_ui()

    def _launch_scan_thread(self, thread, finished_slot):
        thread.progress_signal.connect(self._on_scan_progress)
        thread.error_signal.connect(self._on_scan_error)
        thread.finished.connect(finished_slot)
        thread.finished.connect(thread.deleteLater)
        self._live_scan_threads.append(thread)
        thread.destroyed.connect(lambda _=None, t=thread: self._discard_scan_thread(t))
        self.scan_thread = thread
        thread.start()

    def _discard_scan_thread(self, t):
        try:
            self._live_scan_threads.remove(t)
        except ValueError:
            pass
        if self.scan_thread is t:
            self.scan_thread = None
        if self.cache_load_thread is t:
            self.cache_load_thread = None
        if self.usn_thread is t:
            self.usn_thread = None

    def _stop_scan(self):
        if not (self.scan_thread and self.scan_thread.isRunning()):
            return
        self._scan_cancelled = True
        if isinstance(self.scan_thread, MFTScanThread):
            self.hybrid_scanner.cancel()
        else:
            self.parallel_scanner.stop()
        self.stop_btn.setEnabled(False)
        self._update_status("正在停止...")

    def _reset_scan_ui(self):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self._stop_elapsed_timer()

    def _export_file_list(self, auto=False):
        """导出文件列表到 JSON（按盘符区分，如 disk_scan_C.json）"""
        if not self.current_node:
            if not auto:
                QMessageBox.warning(self, "提示", "没有可导出的扫描结果")
            return

        import json
        from datetime import datetime

        scan_path = self.path_input.text().strip()
        export_path = _get_export_path(scan_path)

        # 遍历 FileNode 树收集所有文件
        files = []
        stack = [self.current_node]
        while stack:
            node = stack.pop()
            if node.is_dir:
                stack.extend(node.children.values())
            else:
                files.append({
                    'path': _safe_path(node.path),  # 代理字符安全化，避免UTF-8编码失败
                    'size': node.size,
                })

        data = {
            'scan_path': scan_path,
            'scan_time': datetime.now().isoformat(),
            'total_files': len(files),
            'files': files,
        }

        try:
            # 原子写：先写临时文件再 os.replace 替换，避免写入被中断时
            # 留下半截损坏的 JSON（此前直接 open('w') 写，中断后文件停在
            # {"path": 处，读取时 json.load 报 "expecting value"）
            tmp_path = export_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=None, separators=(',', ':'))
            os.replace(tmp_path, export_path)

            drive = os.path.splitdrive(scan_path)[0]
            if auto:
                self._update_status(
                    f"扫描完成 + 已自动导出 {drive} 盘 {len(files)} 个文件列表"
                )
            else:
                QMessageBox.information(self, "导出成功",
                    f"已导出 {len(files)} 个文件到:\n{export_path}\n\n"
                    f"重复文件筛选模块可直接导入。")
        except Exception as e:
            # 清理可能残留的 .tmp
            try:
                if os.path.exists(export_path + '.tmp'):
                    os.remove(export_path + '.tmp')
            except OSError:
                pass
            # auto 模式下也提示导出失败（此前静默吞掉，导致 JSON 不生成、
            # 用户每次都需重新扫描，却不知导出失败）
            import traceback
            err_detail = traceback.format_exc()
            print(f"[导出失败] {export_path}\n{err_detail}", flush=True)
            if auto:
                self._update_status(f"扫描完成，但导出JSON失败: {e}")
                QMessageBox.warning(self, "导出失败",
                    f"扫描结果导出失败：\n{e}\n\n"
                    f"文件列表未保存，下次扫描该盘将重新扫描。\n"
                    f"路径: {export_path}")
            else:
                QMessageBox.critical(self, "导出失败", f"导出失败: {e}")

    def _on_scan_progress(self, message: str, percent: int):
        if self._scan_cancelled:
            return
        self._update_status(message)
        if percent and percent > 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(min(percent, 100))
        else:
            self.progress_bar.setRange(0, 0)

    def _on_scan_error(self, message: str):
        self._reset_scan_ui()
        QMessageBox.critical(self, "扫描出错", f"扫描过程中发生异常：\n{message}")
        self._update_status("扫描出错")

    def cleanup(self):
        """关闭时清理线程"""
        self._stop_elapsed_timer()
        if self.scan_thread and self.scan_thread.isRunning():
            self._scan_cancelled = True
            if isinstance(self.scan_thread, MFTScanThread):
                self.hybrid_scanner.cancel()
            else:
                self.parallel_scanner.stop()
            self.scan_thread.wait(3000)
        # 停止后台增量线程：否则窗口销毁后 QThread 仍在跑，finished 信号回调
        # 访问已析构的 status_label 等 Qt 对象会段错误闪退。
        self._stop_usn_update()
        # 缓存加载线程是纯 CPU 任务无法中断，等它跑完（converter 持有 self 强引用，
        # 纯 Python 不碰 Qt，不会悬空；只影响加载耗时，不阻塞关闭正确性）。
        if self.cache_load_thread and self.cache_load_thread.isRunning():
            self.cache_load_thread.wait(10000)

    def _on_scan_finished(self):
        thread = self.scan_thread
        if thread is None:
            return
        if self._scan_cancelled:
            self._scan_cancelled = False
            self._reset_scan_ui()
            self._update_status("扫描已取消")
            return

        self._reset_scan_ui()
        root_node = thread.result
        if not root_node:
            reason = self.parallel_scanner.last_error or self.scanner.last_error or "未知原因"
            self._update_status(f"扫描失败: {reason}")
            return

        self.current_node = root_node
        scan_secs = time.perf_counter() - self._scan_start if self._scan_start else 0.0
        self._update_status(f"扫描完成（{scan_secs:.0f}s），正在填充列表与渲染树图...")
        QApplication.processEvents()
        t0 = time.perf_counter()
        self._populate_tree(root_node)
        self._update_status(f"列表填充完成，正在渲染矩形树图... 已用 {scan_secs + (time.perf_counter() - t0):.0f}s")
        QApplication.processEvents()
        self.treemap_widget.set_data(root_node)
        load_secs = time.perf_counter() - t0

        self._update_time(f"上次: 扫描{scan_secs:.1f}s 加载{load_secs:.1f}s")
        self._update_status(
            f"扫描完成 - 总大小: {format_size(root_node.size)}, "
            f"文件数: {root_node.file_count}, 目录数: {root_node.dir_count}"
        )

        # 根目录扫描时自动导出文件列表（供重复文件Tab复用）
        scan_path = self.path_input.text().strip()
        if _is_root_path(scan_path):
            self._export_file_list(auto=True)

    def _on_mft_scan_finished(self):
        thread = self.scan_thread
        if thread is None:
            return
        files = thread.files
        scan_method = thread.method

        if self._scan_cancelled:
            self._scan_cancelled = False
            self._reset_scan_ui()
            self._update_status("扫描已取消")
            return

        self._reset_scan_ui()

        if files is None or (isinstance(files, list) and len(files) == 0):
            detail = self.hybrid_scanner.last_error or ""
            reason = "无结果" if isinstance(files, list) else "失败"
            msg = f"MFT扫描{reason}，正在切换到普通扫描..."
            if detail:
                msg = f"MFT扫描{reason}（{detail}），正在切换到普通扫描..."
            self._update_status(msg)

            depth_map = {0: 1, 1: 2, 2: 5, 3: -1}
            scan_depth = depth_map[self.depth_combo.currentIndex()]
            path = self.path_input.text().strip()
            self._scan_cancelled = False
            self._launch_scan_thread(
                ScanThread(self.parallel_scanner, path, depth=scan_depth),
                self._on_scan_finished)
            return

        try:
            scan_secs = time.perf_counter() - self._scan_start if self._scan_start else 0.0
            # 构建阶段分步显示进度，避免大目录几十万文件建树/渲染时假死
            self._update_status(f"正在构建目录树（{len(files)} 个条目）... 已用 {scan_secs:.0f}s")
            QApplication.processEvents()
            t0 = time.perf_counter()
            root_node = self._convert_mft_results_to_tree(files, self.path_input.text().strip())

            if not root_node:
                self._update_status("扫描失败: 无法构建目录树")
                return

            self.current_node = root_node
            build_secs = time.perf_counter() - t0
            self._update_status(
                f"目录树构建完成（{build_secs:.0f}s），正在填充列表... 已用 {scan_secs + build_secs:.0f}s")
            QApplication.processEvents()
            t1 = time.perf_counter()
            self._populate_tree(root_node)
            tree_secs = time.perf_counter() - t1
            self._update_status(
                f"列表填充完成（{tree_secs:.0f}s），正在渲染矩形树图... 已用 {scan_secs + build_secs + tree_secs:.0f}s")
            QApplication.processEvents()
            t2 = time.perf_counter()
            self.treemap_widget.set_data(root_node)
            load_secs = time.perf_counter() - t0

            self._update_time(f"上次: 扫描{scan_secs:.1f}s 加载{load_secs:.1f}s")
            method_text = "MFT极速扫描" if scan_method == 'mft' else "普通扫描"
            self._update_status(
                f"[{method_text}] 扫描完成 - 总大小: {format_size(root_node.size)}, "
                f"文件数: {root_node.file_count}, 目录数: {root_node.dir_count}"
            )

            # 根目录扫描时自动导出文件列表（供重复文件Tab复用）
            scan_path = self.path_input.text().strip()
            if _is_root_path(scan_path):
                self._export_file_list(auto=True)

            # 写目录大小缓存 + journal 状态（供下次启动秒开；仅 MFT 扫描有 frn）
            try:
                self._save_size_cache(files, scan_path, thread.root_frn)
            except Exception as e:
                print(f"[缓存] 写入失败: {e}", flush=True)

            err_infos = getattr(self.hybrid_scanner, 'last_errors_info', [])
            if err_infos:
                lines = [f"• {loc}（{err}）" for loc, err in err_infos]
                msg = f"扫描完成，跳过了 {len(err_infos)} 个损坏的 MFT 条目：\n\n" + "\n".join(lines)
                if len(err_infos) >= 20:
                    msg += "\n\n（仅显示前 20 条）"
                QMessageBox.information(self, "损坏条目提醒", msg)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理MFT扫描结果时出错：\n{str(e)}")
            self._update_status("扫描失败")

    def _save_size_cache(self, files, scan_path, root_frn=0):
        """全量 MFT 扫描完成后写缓存，并记录「扫描开始前」的 journal 游标。

        root_frn 为卷根目录的 64 位 file_reference，写入缓存根目录行后，USN 增量
        才能解析 C:\\ 根目录下顶层文件/目录的父路径（parent_frn 指向根目录）。
        """
        self.size_cache.save_scan(files, scan_path, root_frn=root_frn)
        snap = self._pending_journal_snapshot
        if snap:
            drive = self.size_cache._drive(scan_path)
            self.size_cache.set_journal_state(
                drive, snap['journal_id'], snap['next_usn'], scan_path)
        self._pending_journal_snapshot = None

    def _convert_mft_results_to_tree(self, files, scan_path):
        """将MFT扫描结果转换为FileNode树形结构"""
        nk = os.path.normcase
        sep = os.sep
        _dirname = os.path.dirname
        _basename = os.path.basename

        root_str = os.path.normpath(str(scan_path))
        nk_root = nk(root_str)
        root_node = FileNode(name=_basename(root_str), path=root_str, is_dir=True, size=0)
        node_dict = {nk_root: root_node}

        _FileNode = FileNode
        _get = node_dict.get
        _set = node_dict.__setitem__
        _contains = node_dict.__contains__

        if nk_root.endswith(sep):
            _prefix = nk_root
            def under_root(nk_path):
                return nk_path != nk_root and nk_path.startswith(_prefix)
        else:
            _prefix = nk_root + sep
            def under_root(nk_path):
                return nk_path.startswith(_prefix)

        def ensure_ancestor(path, nk_path):
            node = _get(nk_path)
            if node is not None:
                return node
            chain = []
            cur_path, cur_nk = path, nk_path
            while cur_nk != nk_root and not _contains(cur_nk) and _dirname(cur_path) != cur_path:
                chain.append((cur_path, cur_nk))
                cur_path = _dirname(cur_path)
                cur_nk = nk(cur_path)
            parent_node = node_dict[cur_nk]
            for p, nkp in reversed(chain):
                node = _FileNode(name=_basename(p), path=p, is_dir=True, size=0)
                _set(nkp, node)
                parent_node.children[node.name] = node
                parent_node = node
            return parent_node

        for f in files:
            if f is None or not isinstance(f, dict):
                continue
            path = f.get('path')
            if not path or not f.get('name'):
                continue
            nk_path = nk(path)
            if nk_path == nk_root:
                continue
            if not under_root(nk_path):
                continue
            current_node = _get(nk_path)
            if current_node is None:
                current_node = _FileNode(name=f['name'], path=path, is_dir=f['is_dir'], size=f['size'])
                _set(nk_path, current_node)
            parent_path = _dirname(path)
            nk_parent = nk(parent_path)
            parent_node = _get(nk_parent)
            if parent_node is None:
                parent_node = ensure_ancestor(parent_path, nk_parent)
            parent_node.children[current_node.name] = current_node

        def calculate_size(root):
            stack = [(root, False)]
            while stack:
                cur, processed = stack.pop()
                if not cur.is_dir:
                    cur.file_count = 0
                    cur.dir_count = 0
                    continue
                if processed:
                    total_size = total_files = total_dirs = 0
                    for child in cur.children.values():
                        if child.is_dir:
                            total_size += child.size
                            total_files += child.file_count
                            total_dirs += child.dir_count + 1
                        else:
                            total_size += child.size
                            total_files += 1
                    cur.size = total_size
                    cur.file_count = total_files
                    cur.dir_count = total_dirs
                else:
                    stack.append((cur, True))
                    for child in cur.children.values():
                        stack.append((child, False))

        calculate_size(root_node)
        return root_node

    def _populate_tree(self, node: FileNode):
        self.result_tree.setSortingEnabled(False)
        self.result_tree.setUpdatesEnabled(False)
        try:
            sorted_children = sorted(node.children.items(), key=lambda x: x[1].size, reverse=True)
            for name, child_node in sorted_children:
                item = self._build_tree_item(child_node)
                self.result_tree.addTopLevelItem(item)
        finally:
            self.result_tree.setUpdatesEnabled(True)
            self.result_tree.setSortingEnabled(True)

    def _build_tree_item(self, node: FileNode) -> QTreeWidgetItem:
        is_cache, cache_level = self.cache_detector.detect_cache(node.path)
        cache_icon = self.cache_detector.get_cache_icon(cache_level) if is_cache else ''

        item = QTreeWidgetItem()
        item.setText(0, node.name)
        item.setText(1, format_size(node.size))
        item.setText(2, cache_icon)
        item.setText(3, node.path)

        item.setData(1, Qt.ItemDataRole.UserRole, node.size)
        if cache_level:
            level_order = {'dangerous': 0, 'cautious': 1, 'safe': 2}
            item.setData(2, Qt.ItemDataRole.UserRole, level_order.get(cache_level, 3))
        else:
            item.setData(2, Qt.ItemDataRole.UserRole, 3)

        if cache_icon:
            color_map = {'safe': QColor(76, 175, 80), 'cautious': QColor(255, 193, 7), 'dangerous': QColor(244, 67, 54)}
            item.setForeground(2, color_map.get(cache_level, QColor(0, 0, 0)))

        item.setData(0, Qt.ItemDataRole.UserRole + 1, (is_cache, cache_level))
        item.setData(0, NODE_ROLE, node)
        item.setData(0, LOADED_ROLE, False)

        if node.is_dir and node.children:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        if node.is_dir:
            item.setExpanded(False)

        return item

    def _populate_children(self, item: QTreeWidgetItem):
        if item.data(0, LOADED_ROLE):
            return
        node = item.data(0, NODE_ROLE)
        if not node:
            return
        self.result_tree.setSortingEnabled(False)
        self.result_tree.setUpdatesEnabled(False)
        try:
            sorted_children = sorted(node.children.items(), key=lambda x: x[1].size, reverse=True)
            for name, child_node in sorted_children:
                child_item = self._build_tree_item(child_node)
                item.addChild(child_item)
            item.setData(0, LOADED_ROLE, True)
        finally:
            self.result_tree.setUpdatesEnabled(True)
            self.result_tree.setSortingEnabled(True)

    def _toggle_view(self):
        pass  # 隐藏按钮，保留方法避免报错

    # ---- Treemap 联动 ----

    def _on_treemap_node_clicked(self, node: FileNode):
        self._update_status(f"选中: {node.name} ({format_size(node.size)})")

    def _on_treemap_node_double_clicked(self, node: FileNode):
        self._update_status(f"进入: {node.path}")

    def _on_treemap_navigated(self, node: FileNode):
        try:
            self._update_status(f"当前路径: {self.treemap_widget.get_navigation_path()}")
            if node:
                self._expand_tree_to_node(node.path)
        except Exception as e:
            print(f"处理矩形树图导航时出错: {e}")

    def _on_treemap_navigated_back(self, path_to_collapse: str):
        try:
            if path_to_collapse:
                self._collapse_tree_node(path_to_collapse)
        except Exception as e:
            print(f"处理矩形树图返回时出错: {e}")

    def _collapse_all_expanded_nodes(self):
        try:
            iterator = QTreeWidgetItemIterator(self.result_tree)
            while iterator.value():
                item = iterator.value()
                if item.isExpanded():
                    item.setExpanded(False)
                iterator += 1
            self.treemap_widget.show_root()
        except Exception as e:
            print(f"折叠所有节点时出错: {e}")

    def _find_child_item_by_node(self, parent_item, target_node):
        target = os.path.normcase(target_node.path)
        if parent_item is None:
            for i in range(self.result_tree.topLevelItemCount()):
                item = self.result_tree.topLevelItem(i)
                node = item.data(0, NODE_ROLE)
                if node and os.path.normcase(node.path) == target:
                    return item
        else:
            for i in range(parent_item.childCount()):
                item = parent_item.child(i)
                node = item.data(0, NODE_ROLE)
                if node and os.path.normcase(node.path) == target:
                    return item
        return None

    def _walk_to_item(self, target_path: str):
        root = self.current_node
        if not root:
            return None
        nk = os.path.normcase
        if nk(target_path) == nk(root.path):
            return None
        try:
            rel = Path(target_path).relative_to(Path(root.path))
        except ValueError:
            return None
        parts = rel.parts
        current_node = root
        current_item = None
        for part in parts:
            child_node = current_node.children.get(part)
            if not child_node:
                return None
            if current_item is not None and not current_item.data(0, LOADED_ROLE):
                self._populate_children(current_item)
            child_item = self._find_child_item_by_node(current_item, child_node)
            if not child_item:
                return None
            if child_node.is_dir and child_node.children:
                child_item.setExpanded(True)
            current_node = child_node
            current_item = child_item
        return current_item

    def _collapse_tree_node(self, target_path: str):
        try:
            item = self._walk_to_item(target_path)
            if not item:
                return False
            self._collapse_all_children(item)
            item.setExpanded(False)
            return True
        except Exception as e:
            print(f"折叠树形列表时出错: {e}")
            return False

    def _expand_tree_to_node(self, target_path: str):
        try:
            root = self.current_node
            if not root:
                return False
            if os.path.normcase(target_path) == os.path.normcase(root.path):
                return True
            item = self._walk_to_item(target_path)
            if not item:
                return False
            self.result_tree.setCurrentItem(item)
            self.result_tree.scrollToItem(item)
            return True
        except Exception as e:
            print(f"展开树形列表时出错: {e}")
            return False

    def _show_node_in_tree(self, node: FileNode):
        try:
            if self._find_and_select_tree_item(node.path):
                self._update_status(f"已在树形列表中定位: {node.name}")
            else:
                self._update_status("未在树形列表中找到该节点")
        except Exception as e:
            print(f"定位节点时出错: {e}")
            self._update_status("定位失败")

    def _find_and_select_tree_item(self, target_path: str) -> bool:
        try:
            self._clear_tree_highlight()
            item = self._walk_to_item(target_path)
            if item is None:
                return False
            self.result_tree.setCurrentItem(item)
            self.result_tree.scrollToItem(item)
            self._start_flash_effect(item)
            return True
        except Exception as e:
            print(f"搜索树形列表时出错: {e}")
            return False

    def _start_flash_effect(self, item: QTreeWidgetItem):
        self._flash_item = item
        self._flash_count = 0
        self._flash_state = True
        item.setSelected(True)
        self._flash_timer = QTimer()
        self._flash_timer.timeout.connect(self._do_flash)
        self._flash_timer.start(300)

    def _do_flash(self):
        if not self._flash_item:
            return
        self._flash_state = not self._flash_state
        self._flash_item.setSelected(self._flash_state)
        if not self._flash_state:
            self._flash_count += 1
        if self._flash_count >= 3:
            self._flash_timer.stop()
            self._flash_item.setSelected(False)
            self._flash_item = None

    def _clear_tree_highlight(self):
        try:
            self.result_tree.clearSelection()
        except Exception as e:
            print(f"清除高亮时出错: {e}")

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        path = item.text(3)
        size = item.text(1)
        self._update_status(f"选中: {path} ({size})")

    def _on_tree_item_hover(self, item: QTreeWidgetItem):
        try:
            if item:
                self._highlight_treemap_by_path(item.text(3))
        except Exception:
            pass

    def _on_tree_item_expanded(self, item: QTreeWidgetItem):
        try:
            node = item.data(0, NODE_ROLE)
            if not node:
                return
            if not item.data(0, LOADED_ROLE):
                self._populate_children(item)
            self._collapse_sibling_items(item)
            if node.children:
                self.treemap_widget.show_children_of_node(node)
                self._update_status(f"展开: {node.name}")
        except Exception as e:
            print(f"[ERROR] 展开节点时出错: {e}")

    def _collapse_sibling_items(self, item: QTreeWidgetItem):
        try:
            parent = item.parent()
            if parent:
                for i in range(parent.childCount()):
                    sibling = parent.child(i)
                    if sibling != item and sibling.isExpanded():
                        sibling.setExpanded(False)
            else:
                tree = item.treeWidget()
                for i in range(tree.topLevelItemCount()):
                    top_item = tree.topLevelItem(i)
                    if top_item != item and top_item.isExpanded():
                        top_item.setExpanded(False)
        except Exception as e:
            print(f"折叠同级节点时出错: {e}")

    def _on_tree_item_collapsed(self, item: QTreeWidgetItem):
        try:
            self._collapse_all_children(item)
            if self.treemap_widget.current_node and self.treemap_widget.current_node.path == item.text(3):
                self.treemap_widget.clear_display()
                self._update_status(f"折叠: {item.text(0)}")
        except Exception as e:
            print(f"折叠节点时出错: {e}")

    def _collapse_all_children(self, item: QTreeWidgetItem):
        try:
            for i in range(item.childCount()):
                child = item.child(i)
                if child.isExpanded():
                    child.setExpanded(False)
                self._collapse_all_children(child)
        except Exception as e:
            print(f"折叠子节点时出错: {e}")

    def _on_treemap_node_hovered(self, node):
        try:
            if node:
                self._highlight_tree_by_path(node.path)
            else:
                self._clear_tree_highlight()
        except Exception:
            pass

    def _highlight_treemap_by_path(self, path: str):
        try:
            for i, rect in enumerate(self.treemap_widget.rects):
                if rect['node'].path == path:
                    if self.treemap_widget.hovered_rect_index != i:
                        self.treemap_widget.hovered_rect_index = i
                        self.treemap_widget.update()
                    return
            if self.treemap_widget.hovered_rect_index != -1:
                self.treemap_widget.hovered_rect_index = -1
                self.treemap_widget.update()
        except Exception:
            pass

    def _highlight_tree_by_path(self, path: str):
        try:
            self._clear_tree_highlight()
            root = self.current_node
            if not root:
                return False
            if os.path.normcase(path) == os.path.normcase(root.path):
                return True
            try:
                rel = Path(path).relative_to(Path(root.path))
            except ValueError:
                return False
            parts = rel.parts
            current_node = root
            current_item = None
            for part in parts:
                child_node = current_node.children.get(part)
                if not child_node:
                    return False
                child_item = self._find_child_item_by_node(current_item, child_node)
                if not child_item:
                    return False
                current_node = child_node
                current_item = child_item
            current_item.setSelected(True)
            self.result_tree.setCurrentItem(current_item)
            return True
        except Exception as e:
            print(f"高亮树形列表时出错: {e}")
            return False

    # ---- 右键菜单 ----

    def _show_context_menu(self, position):
        item = self.result_tree.itemAt(position)
        if not item:
            return
        selected_items = self.result_tree.selectedItems()
        selected_count = len(selected_items)
        menu = QMenu(self)

        if selected_count == 1:
            open_action = QAction("打开文件夹", self)
            open_action.triggered.connect(lambda: self._open_in_explorer(item))
            menu.addAction(open_action)
            copy_action = QAction("复制路径", self)
            copy_action.triggered.connect(lambda: self._copy_path(item))
            menu.addAction(copy_action)
            menu.addSeparator()
            delete_action = QAction("删除到回收站", self)
            delete_action.triggered.connect(lambda: self._delete_to_recycle(item))
            menu.addAction(delete_action)
            menu.addSeparator()
            properties_action = QAction("属性", self)
            properties_action.triggered.connect(lambda: self._show_properties(item))
            menu.addAction(properties_action)
        else:
            count_label = menu.addAction(f"已选中 {selected_count} 项")
            count_label.setEnabled(False)
            menu.addSeparator()
            open_action = QAction("批量打开文件夹", self)
            open_action.triggered.connect(lambda: self._batch_open(selected_items))
            menu.addAction(open_action)
            copy_action = QAction("复制所有路径", self)
            copy_action.triggered.connect(lambda: self._batch_copy_paths(selected_items))
            menu.addAction(copy_action)
            menu.addSeparator()
            delete_action = QAction(f"批量删除 ({selected_count} 项)", self)
            delete_action.triggered.connect(lambda: self._batch_delete(selected_items))
            menu.addAction(delete_action)

        menu.exec(self.result_tree.viewport().mapToGlobal(position))

    def _open_in_explorer(self, item: QTreeWidgetItem):
        import subprocess
        path = item.text(3)
        if Path(path).exists():
            subprocess.run(f'explorer /select,"{Path(path).absolute()}"', shell=True)
            self._update_status(f"已打开: {path}")
        else:
            QMessageBox.warning(self, "警告", f"路径不存在: {path}")

    def _copy_path(self, item: QTreeWidgetItem):
        path = item.text(3)
        QApplication.clipboard().setText(path)
        self._update_status(f"已复制: {path}")

    def _delete_to_recycle(self, item: QTreeWidgetItem):
        try:
            import send2trash
        except ImportError:
            QMessageBox.critical(self, "错误", "缺少 send2trash 库\n请运行: pip install send2trash")
            return

        path = item.text(3)
        size = item.text(1)
        is_cache, cache_level = item.data(0, Qt.ItemDataRole.UserRole + 1)
        safety_desc = self.cache_detector.get_safety_description(cache_level) if is_cache else ''

        message = f"确定要删除以下内容吗？\n\n路径: {path}\n大小: {size}"
        if is_cache:
            message += f"\n\n缓存识别: {cache_level}\n{safety_desc}"

        reply = QMessageBox.question(self, "确认删除", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            try:
                send2trash.send2trash(path)
                parent = item.parent()
                if parent:
                    parent.removeChild(item)
                else:
                    index = self.result_tree.indexOfTopLevelItem(item)
                    self.result_tree.takeTopLevelItem(index)
                self._update_status(f"已删除: {path}")
                QMessageBox.information(self, "成功", f"已移到回收站:\n{path}")
            except Exception as e:
                msg = str(e).lower()
                if "denied" in msg or "权限" in msg or "permission" in msg:
                    hint = "删除失败：权限不足。\n\n请以管理员身份运行程序。"
                elif "being used" in msg or "occupied" in msg:
                    hint = "删除失败：文件被占用。\n\n请关闭使用该文件的程序后重试。"
                else:
                    hint = f"删除失败：{e}"
                QMessageBox.critical(self, "删除失败", f"{hint}\n\n路径: {path}")

    def _show_properties(self, item: QTreeWidgetItem):
        path = item.text(3)
        size = item.text(1)
        name = item.text(0)
        info_lines = [f"名称: {name}", f"路径: {path}", f"大小: {size}"]
        path_obj = Path(path)
        if path_obj.exists():
            try:
                stat = path_obj.stat()
                from datetime import datetime
                modified_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                info_lines.append(f"修改时间: {modified_time}")
                info_lines.append(f"类型: {'文件夹' if path_obj.is_dir() else '文件'}")
            except:
                pass
        QMessageBox.information(self, "属性", "\n".join(info_lines))

    def _batch_open(self, items):
        import subprocess
        count = 0
        for item in items:
            path = item.text(3)
            if Path(path).exists():
                subprocess.run(f'explorer /select,"{Path(path).absolute()}"', shell=True)
                count += 1
        self._update_status(f"已打开 {count} 个文件夹")

    def _batch_copy_paths(self, items):
        paths = [item.text(3) for item in items]
        QApplication.clipboard().setText("\n".join(paths))
        self._update_status(f"已复制 {len(paths)} 个路径")

    def _batch_delete(self, items):
        try:
            import send2trash
        except ImportError:
            QMessageBox.critical(self, "错误", "缺少 send2trash 库")
            return

        total_size = 0
        cache_count = 0
        paths = []
        for item in items:
            path = item.text(3)
            size_str = item.text(1)
            try:
                size_parts = size_str.split()
                size_value = float(size_parts[0])
                size_unit = size_parts[1]
                multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                total_size += size_value * multipliers.get(size_unit, 1)
            except:
                pass
            paths.append(path)
            is_cache, _ = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if is_cache:
                cache_count += 1

        total_size_str = format_size(total_size)
        message = f"确定要删除以下内容吗？\n\n选中项数: {len(paths)}\n总大小: {total_size_str}"
        if cache_count > 0:
            message += f"\n缓存文件夹: {cache_count} 个"
        if len(paths) <= 10:
            message += f"\n\n路径列表:\n" + "\n".join(paths[:10])
        else:
            message += f"\n\n路径列表（前10个）:\n" + "\n".join(paths[:10])
            message += f"\n... 还有 {len(paths) - 10} 项"

        reply = QMessageBox.question(self, "批量删除确认", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = 0
            failed_paths = []
            for i, item in enumerate(items):
                path = item.text(3)
                try:
                    send2trash.send2trash(path)
                    parent = item.parent()
                    if parent:
                        parent.removeChild(item)
                    else:
                        index = self.result_tree.indexOfTopLevelItem(item)
                        self.result_tree.takeTopLevelItem(index)
                    deleted_count += 1
                    if deleted_count % 10 == 0:
                        self._update_status(f"已删除 {deleted_count}/{len(items)} 项...")
                        QApplication.processEvents()
                except Exception as e:
                    failed_paths.append(f"{path}: {str(e)}")

            result_message = f"已删除 {deleted_count} 个项目到回收站\n总大小: {total_size_str}"
            if failed_paths:
                result_message += f"\n\n失败 {len(failed_paths)} 个:\n" + "\n".join(failed_paths[:5])
                if len(failed_paths) > 5:
                    result_message += f"\n... 还有 {len(failed_paths) - 5} 个失败"
            QMessageBox.information(self, "删除完成", result_message)
            self._update_status(f"批量删除完成 - 已删除 {deleted_count} 项")
