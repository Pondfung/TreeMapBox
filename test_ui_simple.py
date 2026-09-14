#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版主窗口 - 用于测试
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QStatusBar, QProgressBar, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

sys.path.insert(0, str(Path(__file__).parent))
from core.parallel_scanner import ParallelScanner
from core.scanner import format_size


class ScanThread(QThread):
    progress_signal = pyqtSignal(str, int)
    finished_signal = pyqtSignal(object)

    def __init__(self, scanner, path, depth=-1):
        super().__init__()
        self.scanner = scanner
        self.path = path
        self.depth = depth

    def run(self):
        def progress_callback(path, count):
            self.progress_signal.emit(path, count)

        result = self.scanner.scan(
            self.path,
            depth=self.depth,
            progress_callback=progress_callback
        )
        self.finished_signal.emit(result)


class SimpleWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.scanner = ParallelScanner(skip_system_dirs=True)
        self.scan_thread = None

        self.setWindowTitle("简化版 - 磁盘扫描")
        self.setMinimumSize(800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # 控制区域
        control_layout = QHBoxLayout()
        layout.addLayout(control_layout)

        self.path_input = QLineEdit()
        self.path_input.setText("C:\\")
        control_layout.addWidget(self.path_input)

        scan_btn = QPushButton("扫描")
        scan_btn.clicked.connect(self._start_scan)
        control_layout.addWidget(scan_btn)

        # 结果树
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["名称", "大小", "路径"])
        layout.addWidget(self.result_tree)

        # 状态栏
        self.status_label = QLabel("就绪")
        self.statusBar().addPermanentWidget(self.status_label)

    def _start_scan(self):
        path = self.path_input.text().strip()
        if not path:
            return

        self.result_tree.clear()
        self.status_label.setText("扫描中...")

        self.scan_thread = ScanThread(self.scanner, path, depth=1)
        self.scan_thread.finished_signal.connect(self._on_finished)
        self.scan_thread.start()

    def _on_finished(self, root_node):
        if not root_node:
            self.status_label.setText("扫描失败")
            return

        self._populate_tree(root_node)
        self.status_label.setText(f"完成 - 大小: {format_size(root_node.size)}")

    def _populate_tree(self, node, parent_item=None):
        item = QTreeWidgetItem()
        item.setText(0, node.name)
        item.setText(1, format_size(node.size))
        item.setText(2, node.path)

        if parent_item:
            parent_item.addChild(item)
        else:
            self.result_tree.addTopLevelItem(item)

        for name, child in node.children.items():
            self._populate_tree(child, item)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimpleWindow()
    window.show()
    sys.exit(app.exec())