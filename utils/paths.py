#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享路径工具：缓存目录选择。

规则：打包成 exe 时放 exe 同目录（不占 C 盘），源码运行时放 LOCALAPPDATA。
exe 目录不可写（如放在 Program Files）时回退 LOCALAPPDATA。
"""

import os
import sys


def localappdata_cache_dir():
    """LOCALAPPDATA 下的缓存目录（源码运行默认，或 exe 目录不可写时的回退）。"""
    base = (os.environ.get('LOCALAPPDATA')
            or os.environ.get('USERPROFILE')
            or os.path.expanduser('~'))
    return os.path.join(base, 'TreeMapBox')


def default_cache_dir():
    """默认缓存目录：打包成 exe 时放 exe 同目录（不占 C 盘），源码运行时放 LOCALAPPDATA。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return localappdata_cache_dir()


def export_dir():
    """导出文件目录（磁盘分析结果 JSON，供重复文件 Tab 复用）。

    源码运行 → 项目根目录 exports/ 子目录（集中放置，不与根目录工程文件混杂，
    且独立于 build/，避免打包 --clean 清空导出结果）；
    打包 exe → exe 同目录。均自动建目录，失败回退 TEMP。
    """
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
    else:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'exports')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.environ.get('TEMP', '.')
    return d
