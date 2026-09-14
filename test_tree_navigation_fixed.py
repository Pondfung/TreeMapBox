#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的树形列表定位功能
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent))
from ui.main_window import MainWindow


def test_fixed_navigation():
    """测试修复后的导航功能"""
    app = QApplication(sys.argv)

    window = MainWindow()
    window.setWindowTitle("树形列表定位功能测试")
    window.resize(1200, 800)

    # 显示窗口
    window.show()

    # 自动扫描当前目录
    test_path = Path(__file__).parent
    window.path_edit.setText(str(test_path))

    print("=" * 50)
    print("树形列表定位功能测试")
    print("=" * 50)
    print("\n操作步骤:")
    print("1. 点击 '开始扫描' 按钮")
    print("2. 切换到 '矩形树图' 标签页")
    print("3. 右键点击任意矩形")
    print("4. 选择 '在树形列表中显示'")
    print("5. 查看是否成功切换并高亮显示")
    print("\n预期结果:")
    print("- 自动切换到树形列表视图")
    print("- 黄色高亮显示选中的节点")
    print("- 自动滚动到该节点位置")
    print("- 不会闪退")
    print("\n" + "=" * 50)

    sys.exit(app.exec())


if __name__ == "__main__":
    test_fixed_navigation()