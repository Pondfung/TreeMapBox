#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调试 MFT 扫描"""

import os
import sys
import ctypes

print("=" * 50)
print("MFT 扫描诊断")
print("=" * 50)

# 1. 检查管理员权限
has_admin = ctypes.windll.shell32.IsUserAnAdmin()
print(f"\n[1] 管理员权限: {has_admin}")

# 2. 检查 libfsntfs 库
try:
    import pyfsntfs
    print(f"[2] libfsntfs 版本: {pyfsntfs.get_version()}")
except ImportError as e:
    print(f"[2] libfsntfs 导入失败: {e}")
    sys.exit(1)

# 3. 尝试打开 C: 盘
print("\n[3] 尝试打开 C: 盘...")
device_path = r"\\.\C:"
print(f"    设备路径: {device_path}")

try:
    volume = pyfsntfs.volume()
    volume.open(device_path)
    print("    成功打开!")

    # 4. 获取根目录
    print("\n[4] 获取根目录...")
    root = volume.get_root_directory()
    root_name = root.get_name() or "(空)"
    num_sub_entries = root.get_number_of_sub_file_entries()
    print(f"    根目录: {root_name}")
    print(f"    子条目数: {num_sub_entries}")

    # 5. 尝试读取前20个条目
    print("\n[5] 读取前 20 个条目:")
    count = 0
    for entry in root.sub_file_entries:
        if count >= 20:
            break
        try:
            name = entry.get_name() if hasattr(entry, 'get_name') else 'N/A'
            is_dir = entry.get_number_of_sub_file_entries() > 0 if hasattr(entry, 'get_number_of_sub_file_entries') else False
            try:
                size = entry.get_size() if hasattr(entry, 'get_size') and not is_dir else 0
            except:
                size = 0
            print(f"    {count}: {name} (dir={is_dir}, size={size})")
            count += 1
        except Exception as e:
            print(f"    {count}: 错误 - {type(e).__name__}")
            count += 1

    volume.close()
    print("\n[OK] 测试成功!")

except PermissionError as e:
    print(f"    权限错误: {e}")
    print("\n[ERROR] 需要以管理员身份运行!")

except Exception as e:
    print(f"    错误: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)