#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileNode 数据结构（单一来源）

scanner.py 与 parallel_scanner.py 此前各有一份同名副本（靠鸭子类型混用），
改字段要改两处、容易漏。现统一到这里，两个扫描器从本模块 import，
`from core.scanner import FileNode` 等旧导入路径保持兼容。
"""

from typing import Dict
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
