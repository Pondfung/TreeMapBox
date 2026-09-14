#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试左右分栏双向同步高亮功能
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from ui.main_window import MainWindow


def test_sync_highlight():
    """测试双向同步高亮"""
    app = QApplication(sys.argv)

    window = MainWindow()
    window.setWindowTitle("左右分栏双向同步高亮测试")
    window.resize(1400, 800)

    # 显示窗口
    window.show()

    # 自动填充路径
    test_path = Path(__file__).parent
    window.path_input.setText(str(test_path))

    print("=" * 60)
    print("左右分栏双向同步高亮功能测试")
    print("=" * 60)
    print("\n新功能说明:")
    print("  - 左侧: 树形列表")
    print("  - 右侧: 矩形树图")
    print("  - 鼠标悬停任一侧，两侧同时高亮")
    print("\n测试步骤:")
    print("  1. 点击 '开始扫描' 按钮")
    print("  2. 观察左右分栏布局")
    print("  3. 鼠标悬停在左侧树形列表项上")
    print("     → 右侧矩形树图对应矩形高亮")
    print("  4. 鼠标悬停在右侧矩形上")
    print("     → 左侧树形列表对应项高亮")
    print("\n预期效果:")
    print("  OK - 左右分栏同时显示")
    print("  OK - 鼠标悬停任一侧，另一侧同步高亮")
    print("  OK - 黄色高亮显示匹配的文件/文件夹")
    print("  OK - 实时响应，无延迟")
    print("\n" + "=" * 60)

    sys.exit(app.exec())


if __name__ == "__main__":
    test_sync_highlight()