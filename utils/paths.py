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
