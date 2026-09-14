#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口 UI

实现主界面，使用 QTabWidget 管理多个功能 Tab。
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStatusBar, QLabel, QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent.parent))
from ui.disk_analysis_tab import DiskAnalysisTab
from ui.cache_cleaner_tab import CacheCleanerTab
from ui.duplicate_file_tab import DuplicateFileTab


class MainWindow(QMainWindow):
    """主窗口（Tab 容器）"""

    def __init__(self):
        super().__init__()
        self._setup_ui()
        self._setup_status_bar()
        self._check_admin_rights()

    def _setup_ui(self):
        self.setWindowTitle("TreeMapBox v0.9.5")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Tab 控件
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_widget)

        # Tab1: 磁盘分析
        self.disk_tab = DiskAnalysisTab(self)
        self.tab_widget.addTab(self.disk_tab, "📁 磁盘分析")

        # Tab2: 重复文件筛选
        self.duplicate_tab = DuplicateFileTab(self)
        self.tab_widget.addTab(self.duplicate_tab, "🔍 重复文件")

        # Tab3: 缓存清理（移到最后）
        self.cache_tab = CacheCleanerTab(self)
        self.tab_widget.addTab(self.cache_tab, "🗑️ 缓存清理")

    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.time_label = QLabel("上次: —")
        self.status_bar.addWidget(self.time_label)

        self.status_label = QLabel("就绪")
        self.status_bar.addPermanentWidget(self.status_label)

    def _check_admin_rights(self):
        """检查管理员权限（延迟到磁盘分析Tab初始化后）"""
        try:
            from core.mft_scanner import MFTScanner
            mft = MFTScanner()
            has_admin = mft.has_admin_rights()
            has_ntfs_lib = mft.is_mft_library_available()

            if not has_admin or not has_ntfs_lib:
                if not has_admin and not has_ntfs_lib:
                    self.status_label.setText("⚠️ MFT极速扫描不可用（需管理员权限 + python-ntfs库）")
                elif not has_admin:
                    self.status_label.setText("⚠️ 当前运行在普通用户模式 - MFT极速扫描不可用")
                else:
                    self.status_label.setText("⚠️ python-ntfs库不兼容 - MFT极速扫描不可用")
        except Exception:
            pass

    def _on_tab_changed(self, index):
        """Tab 切换时更新状态栏"""
        if hasattr(self, 'time_label'):
            self.time_label.setVisible(index == 0)

    def closeEvent(self, event):
        """关闭窗口时清理所有 Tab 的线程"""
        self.disk_tab.cleanup()
        self.cache_tab.cleanup()
        self.duplicate_tab.cleanup()
        super().closeEvent(event)
