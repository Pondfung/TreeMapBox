#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复版 - 正确的 TreeView 布局
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QLabel, QPushButton, QSizePolicy
)

def test_treeview():
    app = QApplication(sys.argv)

    # 创建主窗口
    window = QMainWindow()
    window.setWindowTitle("TreeView 修复版")
    window.resize(800, 600)

    # 创建中心部件
    central = QWidget()
    window.setCentralWidget(central)

    # 创建布局
    layout = QVBoxLayout()
    central.setLayout(layout)

    # 添加标签
    label = QLabel("标签 - 测试布局")
    layout.addWidget(label)

    # 创建树形视图
    tree = QTreeWidget()
    tree.setHeaderLabels(["名称", "大小"])

    # 关键：设置 size policy
    tree.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding
    )

    # 设置最小高度
    tree.setMinimumHeight(300)

    # 添加测试数据
    for i in range(10):
        item = QTreeWidgetItem()
        item.setText(0, f"文件夹 {i+1}")
        item.setText(1, f"{(i+1)*100} MB")
        tree.addTopLevelItem(item)

        # 添加子项
        child = QTreeWidgetItem()
        child.setText(0, f"子文件夹 {i+1}-1")
        child.setText(1, f"{(i+1)*10} MB")
        item.addChild(child)

    # 添加到布局（关键：使用 stretch=1）
    layout.addWidget(tree, 1)  # 1 表示 stretch factor

    # 添加底部标签
    bottom_label = QLabel("底部标签 - 如果看到我，说明 TreeView 正常")
    layout.addWidget(bottom_label)

    print(f"Tree sizePolicy: {tree.sizePolicy()}")
    print(f"Tree minimumSizeHint: {tree.minimumSizeHint()}")
    print(f"Tree sizeHint: {tree.sizeHint()}")

    # 显示窗口
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    test_treeview()