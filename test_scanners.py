#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试扫描和数据填充
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.scanner import DiskScanner
from core.parallel_scanner import ParallelScanner

# 测试单线程扫描
print("测试单线程扫描...")
scanner = DiskScanner(skip_system_dirs=True)
root1 = scanner.scan(str(Path(__file__).parent), depth=1)
if root1:
    print(f"单线程成功: {root1.name}, 大小: {root1.size}, 子项数: {len(root1.children)}")
else:
    print("单线程失败")

# 测试并行扫描
print("\n测试并行扫描...")
parallel_scanner = ParallelScanner(skip_system_dirs=True)
root2 = parallel_scanner.scan(str(Path(__file__).parent), depth=1)
if root2:
    print(f"并行扫描成功: {root2.name}, 大小: {root2.size}, 子项数: {len(root2.children)}")
else:
    print("并行扫描失败")

# 对比子项
if root1 and root2:
    print("\n子项对比:")
    print(f"单线程子项: {list(root1.children.keys())[:5]}")
    print(f"并行扫描子项: {list(root2.children.keys())[:5]}")