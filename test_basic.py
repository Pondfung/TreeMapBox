#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试 - 检查基本功能是否正常
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow

sys.path.insert(0, str(Path(__file__).parent))

print("开始测试...")

try:
    print("1. 测试导入 MainWindow...")
    from ui.main_window import MainWindow
    print("   成功")
except Exception as e:
    print(f"   失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("2. 测试创建 QApplication...")
    app = QApplication(sys.argv)
    print("   成功")
except Exception as e:
    print(f"   失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("3. 测试创建 MainWindow...")
    window = MainWindow()
    print("   成功")
except Exception as e:
    print(f"   失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("4. 测试显示窗口...")
    window.show()
    print("   成功")
except Exception as e:
    print(f"   失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n所有测试通过！")
print("程序已启动，请手动测试...")

sys.exit(app.exec())
