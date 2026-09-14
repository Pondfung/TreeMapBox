#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TreeMapBox - Windows 磁盘占用分析工具

主程序入口
"""

import sys
import os
import traceback
import datetime as _dt
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# C++ 层崩溃（段错误/访问冲突）不会走 Python excepthook，用 faulthandler 兜底，
# 把崩溃瞬间的 Python 栈 + C 栈写入文件，否则闪退无任何痕迹可查。
import faulthandler
_fault_log = os.path.join(os.environ.get('TEMP', '.'), 'treemapbox_fault.log')
_fault_file = open(_fault_log, 'a', encoding='utf-8', buffering=1)
faulthandler.enable(file=_fault_file)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

# 崩溃日志路径（写入 TEMP，--windowed 打包下也能找到）
_CRASH_LOG = os.path.join(os.environ.get('TEMP', '.'), 'treemapbox_crash.log')


def _excepthook(exc_type, exc_val, exc_tb):
    """全局异常兜底：--windowed 打包时 sys.stderr 为 None，PyQt6 默认异常处理器
    往 stderr 写会二次崩溃并 abort（表现为主窗口直接消失/闪退，无任何错误信息）。
    这里把未捕获异常写入日志文件，进程继续运行，避免级联 abort。"""
    if issubclass(exc_type, KeyboardInterrupt):
        return
    try:
        msg = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
        with open(_CRASH_LOG, 'a', encoding='utf-8') as f:
            f.write(f"\n{'=' * 60}\n[{_dt.datetime.now()}]\n{msg}\n")
    except Exception:
        pass


sys.excepthook = _excepthook


def main():
    """程序主入口"""
    # 创建应用
    app = QApplication(sys.argv)

    # 设置应用信息
    app.setApplicationName("TreeMapBox")
    app.setApplicationVersion("0.9.6")
    app.setOrganizationName("TreeMapBox")

    # 创建主窗口
    window = MainWindow()
    window.show()

    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()