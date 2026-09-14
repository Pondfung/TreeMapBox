#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 层共享工具函数（无 Qt 依赖，供各 tab 复用，避免重复定义）。

历史债来源：_safe_path / _get_export_path / _is_root_path / _is_cache_like /
_path_in_cache_dir 原先在 disk_analysis_tab.py 与 duplicate_file_tab.py 各抄一份，
且缓存关键字出现过漂移（cache_cleaner_tab.py 的 CACHE_NAME_KEYWORDS 含 '.tmp'
但从未被使用）。这里统一为单一来源。
"""

import os

from utils.paths import export_dir


# cache/temp 相关关键字（子串匹配，不区分大小写）。
# 注：无需单列 '.tmp'——'tmp' 子串已覆盖所有含 ".tmp" 的名字，行为等价。
CACHE_KEYWORDS = ('cache', 'temp', 'tmp', '缓存', '临时')


def safe_path(p):
    """对路径做代理字符安全化。

    Windows 文件名是 UTF-16，损坏/特殊文件名可能含孤立代理字符（surrogate），
    json.dump(ensure_ascii=False) 写 UTF-8 会抛 UnicodeEncodeError 导致导出中断。
    用 surrogatepass 编码再 replace 解码，把孤立代理替换为 U+FFFD，保证正常写盘。
    """
    try:
        return p.encode('utf-8', 'surrogatepass').decode('utf-8', 'replace')
    except Exception:
        return p.encode('utf-8', 'replace').decode('utf-8', 'replace')


def is_root_path(path_str):
    """判断是否为磁盘根目录（如 C:\\、D:\\、E:/）"""
    p = path_str.strip().rstrip('/\\')
    return len(p) == 2 and p[1] == ':' or (len(p) == 3 and p[1] == ':' and p[2] in '/\\')


def is_cache_like(name):
    """名字是否与 cache/temp 相关（不区分大小写，子串匹配）"""
    low = name.lower()
    return any(kw in low for kw in CACHE_KEYWORDS)


def path_in_cache_dir(path):
    """路径是否位于 cache/temp 相关目录下（检查各级目录名）。

    例如 C:\\Users\\x\\.cache\\a.bin 中 .cache 匹配 → 判定在缓存目录下。
    盘符根、文件名本身不检查（只查中间各级目录名）。
    """
    parts = path.replace('/', '\\').split('\\')
    for part in parts:
        if not part or len(part) == 2 and part[1] == ':':
            continue
        if is_cache_like(part):
            return True
    return False


def get_export_path(scan_path):
    """根据扫描路径生成导出文件路径（按盘符区分，如 disk_scan_C.json）"""
    drive = os.path.splitdrive(scan_path)[0].replace(':', '') or 'unknown'
    return os.path.join(export_dir(), f'disk_scan_{drive}.json')
