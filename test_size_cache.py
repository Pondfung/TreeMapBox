#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
size_cache 本地单测（不依赖 pywin32 / 管理员 / 真实 USN Journal）

覆盖：save_scan/load 往返、is_valid 降级、UsnUpdater.apply 的
建/删/改/改名（文件+目录）四类记录处理。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.size_cache import SizeCacheManager, UsnUpdater
from core.usn_journal import (
    USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_DATA_EXTEND,
)


def _rec(frn, parent_frn, name, reason):
    return {'frn': frn, 'parent_frn': parent_frn, 'name': name, 'reason': reason}


def _mkfile(path, size):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)


def test_roundtrip():
    tmp = tempfile.mkdtemp(prefix='tmb_cache_')
    cache = SizeCacheManager(cache_dir=os.path.join(tmp, 'cache'))
    scan_path = 'C:\\'
    files = [
        {'name': 'Users', 'path': 'C:\\Users', 'size': 0, 'is_dir': True, 'frn': 10, 'parent_frn': 5},
        {'name': 'a.txt', 'path': 'C:\\Users\\a.txt', 'size': 100, 'is_dir': False, 'frn': 11, 'parent_frn': 10},
        {'name': 'b.txt', 'path': 'C:\\Users\\b.txt', 'size': 200, 'is_dir': False, 'frn': 12, 'parent_frn': 10},
        {'name': 'Windows', 'path': 'C:\\Windows', 'size': 0, 'is_dir': True, 'frn': 20, 'parent_frn': 5},
    ]
    n = cache.save_scan(files, scan_path)
    assert n == 4, n
    loaded = cache.load(scan_path)
    assert len(loaded) == 4, len(loaded)
    bypath = {f['path']: f for f in loaded}
    assert bypath['C:\\Users\\a.txt']['size'] == 100
    assert bypath['C:\\Users\\a.txt']['frn'] == 11
    assert bypath['C:\\Users']['is_dir'] is True
    print('[OK] roundtrip: save_scan/load 往返一致')


def test_is_valid_degrades():
    tmp = tempfile.mkdtemp(prefix='tmb_valid_')
    cache = SizeCacheManager(cache_dir=os.path.join(tmp, 'cache'))
    # 无 pywin32 / 无真实 journal → is_valid 应返回 False（降级全量扫描），且不抛异常
    result = cache.is_valid('C:\\')
    assert result is False, result
    print('[OK] is_valid: 无 journal 时降级为全量扫描，不抛异常')


def test_apply_crud():
    tmp = tempfile.mkdtemp(prefix='tmb_apply_')
    cache = SizeCacheManager(cache_dir=os.path.join(tmp, 'cache'))
    drive = os.path.splitdrive(tmp)[0].rstrip(':').upper()

    root = os.path.join(tmp, 'root')
    d1 = os.path.join(root, 'd1')
    f1 = os.path.join(d1, 'f1.txt')
    _mkfile(f1, 100)
    files = [
        {'name': 'd1', 'path': d1, 'size': 0, 'is_dir': True, 'frn': 100, 'parent_frn': 1},
        {'name': 'f1.txt', 'path': f1, 'size': 100, 'is_dir': False, 'frn': 101, 'parent_frn': 100},
    ]
    cache.save_scan(files, root)
    updater = UsnUpdater(cache)

    # 1. 新建文件 f2.txt（frn 102，父 d1=100）
    f2 = os.path.join(d1, 'f2.txt')
    _mkfile(f2, 300)
    updater.apply([_rec(102, 100, 'f2.txt', USN_REASON_FILE_CREATE)], drive)
    loaded = {f['path']: f for f in cache.load(root)}
    assert f2 in loaded and loaded[f2]['size'] == 300 and loaded[f2]['frn'] == 102

    # 2. 修改 f1.txt 大小（DATA_EXTEND，100 -> 500）
    with open(f1, 'ab') as fh:
        fh.write(b'y' * 400)
    updater.apply([_rec(101, 100, 'f1.txt', USN_REASON_DATA_EXTEND)], drive)
    loaded = {f['path']: f for f in cache.load(root)}
    assert loaded[f1]['size'] == 500, loaded[f1]['size']

    # 3. 删除 f2.txt
    os.remove(f2)
    updater.apply([_rec(102, 100, 'f2.txt', USN_REASON_FILE_DELETE)], drive)
    loaded = {f['path']: f for f in cache.load(root)}
    assert f2 not in loaded

    # 4. 改名 f1.txt -> f1_renamed.txt（同目录）
    f1r = os.path.join(d1, 'f1_renamed.txt')
    os.rename(f1, f1r)
    updater.apply([
        _rec(101, 100, 'f1.txt', USN_REASON_RENAME_OLD_NAME),
        _rec(101, 100, 'f1_renamed.txt', USN_REASON_RENAME_NEW_NAME),
    ], drive)
    loaded = {f['path']: f for f in cache.load(root)}
    assert f1 not in loaded and f1r in loaded
    assert loaded[f1r]['size'] == 500
    print('[OK] apply CRUD: 新建/改大小/删除/改名 四类记录处理正确')


def test_apply_dir_rename():
    tmp = tempfile.mkdtemp(prefix='tmb_ren_')
    cache = SizeCacheManager(cache_dir=os.path.join(tmp, 'cache'))
    drive = os.path.splitdrive(tmp)[0].rstrip(':').upper()

    root = os.path.join(tmp, 'root')
    d1 = os.path.join(root, 'd1')
    d2 = os.path.join(d1, 'd2')
    f1 = os.path.join(d2, 'f1.txt')
    files = [
        {'name': 'd1', 'path': d1, 'size': 0, 'is_dir': True, 'frn': 100, 'parent_frn': 1},
        {'name': 'd2', 'path': d2, 'size': 0, 'is_dir': True, 'frn': 110, 'parent_frn': 100},
        {'name': 'f1.txt', 'path': f1, 'size': 100, 'is_dir': False, 'frn': 111, 'parent_frn': 110},
    ]
    cache.save_scan(files, root)
    updater = UsnUpdater(cache)

    # 目录 d2 改名为 d2x（父 d1=100 在缓存内，可解析）
    d2x = os.path.join(d1, 'd2x')
    f1x = os.path.join(d2x, 'f1.txt')
    updater.apply([
        _rec(110, 100, 'd2', USN_REASON_RENAME_OLD_NAME),
        _rec(110, 100, 'd2x', USN_REASON_RENAME_NEW_NAME),
    ], drive)
    loaded = {f['path']: f for f in cache.load(root)}
    assert d2 not in loaded and d2x in loaded
    assert f1 not in loaded and f1x in loaded, list(loaded.keys())
    assert loaded[f1x]['size'] == 100
    print('[OK] apply dir rename: 目录改名后整棵子树路径重写正确')


if __name__ == '__main__':
    test_roundtrip()
    test_is_valid_degrades()
    test_apply_crud()
    test_apply_dir_rename()
    print('\n全部通过')
