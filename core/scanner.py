#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高性能磁盘扫描引擎

使用 os.scandir() 实现快速文件扫描
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class FileNode:
    """文件节点数据结构"""
    name: str
    path: str
    size: int = 0
    is_dir: bool = False
    children: Dict[str, 'FileNode'] = field(default_factory=dict)
    file_count: int = 0  # 包含的文件数
    dir_count: int = 0   # 包含的目录数
    is_cache: bool = False
    cache_level: str = ''  # safe, cautious, dangerous

    def add_child(self, node: 'FileNode'):
        """添加子节点"""
        self.children[node.name] = node
        self.size += node.size
        if node.is_dir:
            self.dir_count += 1
            self.file_count += node.file_count
            self.dir_count += node.dir_count
        else:
            self.file_count += 1


class DiskScanner:
    """
    高性能磁盘扫描器

    特性：
    - 使用 os.scandir() 快速遍历
    - 支持进度回调
    - 自动跳过权限受限目录
    """

    # 需要跳过的系统目录
    SKIP_DIRS = {
        '$RECYCLE.BIN',
        '$WinREAgent',
        'System Volume Information',
        'Windows',
        'Program Files',
        'Program Files (x86)',
        'ProgramData',
    }

    def __init__(self, skip_system_dirs: bool = True):
        """
        初始化扫描器

        Args:
            skip_system_dirs: 是否跳过系统目录
        """
        self.skip_system_dirs = skip_system_dirs
        self._stop_flag = False
        self.last_error = None  # 失败原因（字符串），成功时为 None

    def scan(self,
             path: str,
             depth: int = -1,
             progress_callback: Optional[Callable] = None) -> FileNode:
        """
        扫描指定路径

        Args:
            path: 扫描路径
            depth: 扫描深度，-1 表示无限制
            progress_callback: 进度回调函数 (current_path, scanned_count)

        Returns:
            FileNode: 文件树根节点
        """
        self._stop_flag = False
        self.last_error = None
        return self._scan_recursive(path, depth, progress_callback)

    def stop(self):
        """停止扫描"""
        self._stop_flag = True

    def _scan_recursive(self,
                        path: str,
                        depth: int,
                        progress_callback: Optional[Callable],
                        current_depth: int = 0) -> FileNode:
        """
        递归扫描目录

        Args:
            path: 当前扫描路径
            depth: 剩余扫描深度
            progress_callback: 进度回调
            current_depth: 当前深度
        """
        if self._stop_flag:
            return None

        path_obj = Path(path)
        if not path_obj.exists():
            self.last_error = f"路径不存在: {path}"
            return None

        # 创建节点
        node = FileNode(
            name=path_obj.name,
            path=str(path_obj.absolute()),
            is_dir=path_obj.is_dir()
        )

        # 如果是文件，直接返回
        if not node.is_dir:
            try:
                node.size = path_obj.stat().st_size
            except (OSError, PermissionError):
                pass
            return node

        # 如果是目录，扫描子项
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if self._stop_flag:
                        break

                    # 跳过系统目录
                    if self.skip_system_dirs and entry.name in self.SKIP_DIRS:
                        continue

                    # 进度回调
                    if progress_callback:
                        progress_callback(entry.path, 0)

                    # 检查深度限制
                    if depth == 0:
                        continue

                    # reparse point（junction/symlink）：建 size=0 条目但不递归
                    if entry.is_junction() or entry.is_symlink():
                        node.add_child(FileNode(
                            name=entry.name, path=entry.path, size=0, is_dir=True))
                        continue

                    # 递归扫描
                    try:
                        child_node = self._scan_recursive(
                            entry.path,
                            depth - 1 if depth > 0 else -1,
                            progress_callback,
                            current_depth + 1
                        )
                        if child_node:
                            node.add_child(child_node)
                    except (PermissionError, OSError):
                        # 跳过权限受限目录
                        continue

        except (PermissionError, OSError):
            pass

        return node


def format_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        str: 格式化后的字符串（如 "1.2 GB"）
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


# 测试代码
if __name__ == "__main__":
    import sys

    print("测试扫描引擎...")
    scanner = DiskScanner(skip_system_dirs=True)

    # 扫描当前目录
    test_path = Path(__file__).parent.parent

    def progress_callback(path, count):
        pass  # 不打印进度

    start_time = time.time()
    root_node = scanner.scan(str(test_path), depth=2, progress_callback=progress_callback)
    scan_time = time.time() - start_time

    if root_node:
        print(f"\n扫描结果:")
        print(f"路径: {root_node.path}")
        print(f"大小: {format_size(root_node.size)}")
        print(f"文件数: {root_node.file_count}")
        print(f"目录数: {root_node.dir_count}")
        print(f"扫描时间: {scan_time:.2f} 秒")

        # 显示顶层目录
        print(f"\n子目录 (共 {len(root_node.children)} 个):")
        sorted_children = sorted(
            root_node.children.items(),
            key=lambda x: x[1].size,
            reverse=True
        )
        for name, node in sorted_children[:10]:  # 显示前 10 个
            print(f"  {name}: {format_size(node.size)}")