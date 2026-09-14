#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试返回根目录的折叠功能
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from ui.main_window import MainWindow

def main():
    """主函数"""
    # 设置日志输出
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(levelname)s] %(message)s'
    )

    app = QApplication(sys.argv)
    window = MainWindow()
    window.setWindowTitle("测试返回根目录折叠功能")
    window.resize(1400, 800)
    window.show()

    print("=" * 70)
    print("测试返回根目录折叠功能")
    print("=" * 70)
    print("\n操作步骤：")
    print("1. 扫描目录")
    print("2. 在右侧矩形树图双击钻取到第5级")
    print("3. 在右侧右键 -> 返回根目录")
    print("4. 查看控制台日志，看需要折叠多少个路径")
    print("\n关闭窗口后查看日志输出")
    print("=" * 70)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()