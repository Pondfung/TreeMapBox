#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最简单的 TreeView 测试
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
)

app = QApplication(sys.argv)

# 创建主窗口
window = QMainWindow()
window.setWindowTitle("TreeView 测试")
window.resize(800, 600)

# 创建中心部件
central = QWidget()
window.setCentralWidget(central)

# 创建布局
layout = QVBoxLayout()
central.setLayout(layout)

# 创建树形视图
tree = QTreeWidget()
tree.setHeaderLabels(["名称", "大小"])

# 添加一些测试数据
for i in range(5):
    item = QTreeWidgetItem()
    item.setText(0, f"文件夹 {i+1}")
    item.setText(1, f"{(i+1)*100} MB")
    tree.addTopLevelItem(item)

# 添加到布局
layout.addWidget(tree)

# 显示窗口
window.show()

print("TreeView 已创建，请检查窗口")
print(f"Tree 控件: {tree}")
print(f"Tree 父级: {tree.parent()}")
print(f"Tree 可见: {tree.isVisible()}")
print(f"Tree 大小: {tree.size()}")

sys.exit(app.exec())