#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试树形列表和矩形树图的联动功能
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from ui.main_window import MainWindow


def test_linkage():
    """测试联动功能"""
    app = QApplication(sys.argv)

    window = MainWindow()
    window.setWindowTitle("树形列表与矩形树图联动测试")
    window.resize(1400, 800)

    # 显示窗口
    window.show()

    # 自动填充路径
    test_path = Path(__file__).parent
    window.path_input.setText(str(test_path))

    print("=" * 70)
    print("树形列表与矩形树图联动功能测试")
    print("=" * 70)
    print("\n功能说明:")
    print("  1. 初始状态：左侧显示根目录，右侧空白等待")
    print("  2. 左侧展开 → 右侧显示该目录的文件分布")
    print("  3. 右侧钻取 → 左侧自动展开对应目录")
    print("  4. 右侧返回 → 左侧自动折叠对应目录")
    print("\n测试步骤:")
    print("  1. 点击 '开始扫描' 按钮")
    print("  2. 观察左侧显示根目录，右侧显示提示")
    print("  3. 点击左侧根目录的展开按钮(+) ")
    print("     -> 右侧应显示该目录下的文件分布")
    print("  4. 双击右侧矩形树图中的文件夹")
    print("     -> 左侧应自动展开对应目录")
    print("  5. 在右侧矩形树图上右键 -> 返回上一级")
    print("     -> 左侧应自动折叠对应目录")
    print("\n预期效果:")
    print("  OK - 左侧展开，右侧立即响应")
    print("  OK - 右侧钻取，左侧自动展开")
    print("  OK - 右侧返回，左侧自动折叠")
    print("  OK - 状态栏显示当前路径")
    print("\n" + "=" * 70)

    sys.exit(app.exec())


if __name__ == "__main__":
    test_linkage()