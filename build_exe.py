#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller打包配置
"""

# PyInstaller打包命令
# 在项目根目录运行：
# python build_exe.py

import PyInstaller.__main__
import sys
from pathlib import Path

# 获取项目根目录
project_root = Path(__file__).parent

# 打包参数
PyInstaller.__main__.run([
    'main.py',                           # 主程序入口
    '--name=TreeMapBox',                  # 程序名称
    '--onefile',                         # 打包成单个exe文件
    '--windowed',                        # 窗口模式（不显示控制台）
    '--clean',                           # 清理临时文件
    '--noconfirm',                       # 不询问确认

    # 添加数据文件
    '--add-data=config;config',          # 配置文件目录
    '--add-data=core;core',              # 核心模块
    '--add-data=ui;ui',                  # UI模块

    # 隐藏导入（PyInstaller可能检测不到的模块）
    '--hidden-import=PyQt6',
    '--hidden-import=PyQt6.QtCore',
    '--hidden-import=PyQt6.QtGui',
    '--hidden-import=PyQt6.QtWidgets',
    '--hidden-import=send2trash',
    '--hidden-import=pyfsntfs',          # MFT扫描依赖（新版）
    '--hidden-import=win32file',         # Windows API
    '--hidden-import=pywintypes',

    # 排除不需要的模块
    '--exclude-module=tkinter',
    '--exclude-module=matplotlib',
    '--exclude-module=numpy',

    # 输出目录
    f'--distpath={project_root / "dist"}',
    f'--workpath={project_root / "build"}',
    f'--specpath={project_root}',

    # 图标（如果有的话）
    # '--icon=resources/icon.ico',        # 如果有的话
])

print("\n" + "="*70)
print("打包完成！")
print("="*70)
print(f"可执行文件位置: {project_root / 'dist' / 'TreeMapBox.exe'}")
print("="*70)