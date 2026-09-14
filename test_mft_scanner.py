#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试MFT扫描功能 - 优化版
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.mft_scanner import MFTScanner, HybridScanner


def test_mft_scanner():
    """测试MFT扫描器（优化版 MFT 直接模式）"""
    print("=" * 70)
    print("测试MFT扫描器（优化版）")
    print("=" * 70)

    scanner = MFTScanner()

    # 检查支持情况
    print(f"\n支持MFT扫描: {scanner.supported}")
    print(f"管理员权限: {scanner.has_admin_rights()}")
    print(f"状态: {scanner.get_scan_speed_description()}")

    if not scanner.supported:
        print("\nMFT扫描不可用")
        if not scanner.has_admin_rights():
            print("提示: 请以管理员身份运行")
        return

    # 测试扫描C盘
    test_path = "C:/"
    print(f"\n开始扫描: {test_path}")

    progress_log = []
    def progress_callback(message, count):
        progress_log.append((time.time(), message, count))
        if count % 10 == 0 or count <= 50:
            print(f"  进度: {message} ({count}%)")

    t_start = time.time()
    files = scanner.scan(test_path, progress_callback)
    t_end = time.time()

    if files:
        print(f"\n{'='*70}")
        print(f"扫描成功!")
        print(f"总耗时: {t_end - t_start:.2f} 秒")
        print(f"找到 {len(files)} 个文件/目录")

        # 统计目录和文件
        dirs = sum(1 for f in files if f.get('is_dir'))
        regular_files = len(files) - dirs
        print(f"目录: {dirs} 个")
        print(f"文件: {regular_files} 个")

        # 显示前20个文件
        print("\n前20个项目:")
        for i, file in enumerate(files[:20]):
            file_type = "目录" if file.get('is_dir') else "文件"
            size_str = f"{file['size']:,} bytes" if file['size'] else ""
            print(f"  {i+1}. [{file_type}] {file['path']} {size_str}")

        # 检查路径完整性
        no_path = sum(1 for f in files if not f.get('path') or f['path'].count('\\') < 2)
        print(f"\n路径完整性: {len(files) - no_path}/{len(files)} 有完整路径")
    else:
        print(f"\n扫描失败 (耗时 {t_end - t_start:.2f}s)")


if __name__ == "__main__":
    print("MFT扫描器测试（优化版）\n")
    test_mft_scanner()