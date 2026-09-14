#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多线程扫描引擎

使用 ThreadPoolExecutor 实现并行扫描
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


@dataclass
class FileNode:
    """文件节点数据结构"""
    name: str
    path: str
    size: int = 0
    is_dir: bool = False
    children: Dict[str, 'FileNode'] = field(default_factory=dict)
    file_count: int = 0
    dir_count: int = 0
    is_cache: bool = False
    cache_level: str = ''
    frn: int = 0          # NTFS 完整 64 位 file_reference（MFT 扫描填充，普通扫描为 0）
    parent_frn: int = 0   # 父目录完整 64 位 file_reference

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


class ParallelScanner:
    """
    并行扫描器

    使用多线程并发扫描不同子目录
    """

    SKIP_DIRS = {
        '$RECYCLE.BIN',
        '$WinREAgent',
        'System Volume Information',
        'Windows',
        'Program Files',
        'Program Files (x86)',
        'ProgramData',
    }

    def __init__(self, skip_system_dirs: bool = True, max_workers: int = None):
        """
        初始化并行扫描器

        Args:
            skip_system_dirs: 是否跳过系统目录
            max_workers: 最大线程数，None 表示自动（CPU核心数）
        """
        self.skip_system_dirs = skip_system_dirs
        self.max_workers = max_workers or (os.cpu_count() or 4)
        self._stop_flag = False
        self._lock = threading.Lock()
        self.last_error = None  # 失败原因（字符串），成功时为 None

    def scan(self,
             path: str,
             depth: int = -1,
             progress_callback: Optional[Callable] = None) -> FileNode:
        """
        并行扫描指定路径

        Args:
            path: 扫描路径
            depth: 扫描深度，-1 表示无限制
            progress_callback: 进度回调函数

        Returns:
            FileNode: 文件树根节点
        """
        self._stop_flag = False
        self.last_error = None
        return self._scan_parallel(path, depth, progress_callback)

    def stop(self):
        """停止扫描"""
        self._stop_flag = True

    def _scan_parallel(self,
                       path: str,
                       depth: int,
                       progress_callback: Optional[Callable]) -> FileNode:
        """
        并行扫描实现

        策略：
        1. 先扫描顶层目录（单线程）
        2. 对顶层子目录使用线程池并行扫描
        3. 合并结果
        """
        path_obj = Path(path)
        if not path_obj.exists():
            self.last_error = f"路径不存在: {path}"
            return None

        # 创建根节点
        root_node = FileNode(
            name=path_obj.name,
            path=str(path_obj.absolute()),
            is_dir=path_obj.is_dir()
        )

        # 如果是文件，直接返回
        if not root_node.is_dir:
            try:
                root_node.size = path_obj.stat().st_size
            except (OSError, PermissionError):
                pass
            return root_node

        # 第一阶段：快速扫描顶层目录（单线程）
        top_level_items = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if self._stop_flag:
                        break

                    if self.skip_system_dirs and entry.name in self.SKIP_DIRS:
                        continue

                    top_level_items.append(entry)

                    # 进度回调（顶层）
                    if progress_callback:
                        progress_callback(entry.path, 0)
        except (PermissionError, OSError):
            pass

        if self._stop_flag or not top_level_items:
            return root_node

        # 第二阶段：并行扫描子目录
        if depth != 0:
            # 不用 with：需 cancel_futures=True 让停止时未启动的 future 立即取消
            executor = ThreadPoolExecutor(max_workers=self.max_workers)
            try:
                # 提交所有子目录扫描任务
                future_to_item = {}
                for entry in top_level_items:
                    if self._stop_flag:
                        break

                    try:
                        # reparse point（junction/symlink）：建 size=0 条目但不递归，
                        # 避免跟随链接生造重复大目录（如 All Users→ProgramData）
                        if entry.is_junction() or entry.is_symlink():
                            root_node.add_child(FileNode(
                                name=entry.name, path=entry.path, size=0, is_dir=True))
                        elif entry.is_dir() and depth != 0:
                            # 提交子目录扫描任务（不传 progress_callback 给 worker：
                            # 多线程并发 emit Qt 信号在停止时竞态 segfault，
                            # 进度只在顶层单线程阶段报告）
                            future = executor.submit(
                                self._scan_recursive,
                                entry.path,
                                depth - 1 if depth > 0 else -1,
                                None,  # worker 线程不调 progress_callback
                                1  # 当前深度
                            )
                            future_to_item[future] = entry
                        else:
                            # 文件，直接创建节点
                            try:
                                size = entry.stat().st_size
                                node = FileNode(
                                    name=entry.name,
                                    path=entry.path,
                                    size=size,
                                    is_dir=False
                                )
                                root_node.add_child(node)
                            except (OSError, PermissionError):
                                pass
                    except (PermissionError, OSError):
                        pass

                # 收集结果
                for future in as_completed(future_to_item):
                    if self._stop_flag:
                        break

                    entry = future_to_item[future]
                    try:
                        child_node = future.result()
                        if child_node:
                            root_node.add_child(child_node)
                    except Exception as e:
                        # 忽略单个任务的失败
                        pass
            finally:
                # cancel_futures=True 取消未启动的 future；正在跑的 worker
                # 因 _scan_recursive 迭代体内检查 _stop_flag 会很快退出，
                # wait=True 只阻塞极短，保证返回时无 worker 残留
                executor.shutdown(wait=True, cancel_futures=True)

        return root_node

    def _scan_recursive(self,
                        path: str,
                        depth: int,
                        progress_callback: Optional[Callable],
                        current_depth: int) -> Optional[FileNode]:
        """
        递归扫描单个子目录

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

        # 扫描子项
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
                        continue

        except (PermissionError, OSError):
            pass

        return node


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


# 测试代码
if __name__ == "__main__":
    print("测试并行扫描引擎...")

    scanner = ParallelScanner(skip_system_dirs=True, max_workers=8)

    # 测试路径
    test_path = Path(__file__).parent.parent

    def progress_callback(path, depth):
        pass  # 不打印进度

    # 并行扫描
    start_time = time.time()
    root_node = scanner.scan(str(test_path), depth=2, progress_callback=progress_callback)
    parallel_time = time.time() - start_time

    if root_node:
        print(f"\n并行扫描结果:")
        print(f"路径: {root_node.path}")
        print(f"大小: {format_size(root_node.size)}")
        print(f"文件数: {root_node.file_count}")
        print(f"目录数: {root_node.dir_count}")
        print(f"扫描时间: {parallel_time:.2f} 秒")
        print(f"使用线程数: {scanner.max_workers}")

        # 显示顶层目录
        print(f"\n子目录 (共 {len(root_node.children)} 个):")
        sorted_children = sorted(
            root_node.children.items(),
            key=lambda x: x[1].size,
            reverse=True
        )
        for name, node in sorted_children[:10]:
            print(f"  {name}: {format_size(node.size)}")