#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USN Journal 引擎回归测试。

分两层：
- 纯逻辑层（沙箱可跑，无需 pywin32 / 管理员 / 真实卷）：结构体布局、记录解析、
  溢出判断、reason 常量。CI / 快速回归走这层。
- 真机层（需 pywin32 + 可读 NTFS 卷）：query / read / catch_up 与真实 journal 对照，
  未装 pywin32 或无法打开卷时自动跳过。

用法：
    python test_usn_journal.py              # 纯逻辑 + 真机（可用则跑）
    python test_usn_journal.py --offline    # 仅纯逻辑（强制跳过真机）
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.usn_journal import (
    _parse_records, is_overflow,
    USN_RECORD_HEADER_FMT, USN_RECORD_HEADER_SIZE,
    READ_DATA_SIZE, JOURNAL_DATA_SIZE,
    USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_DATA_EXTEND, USN_REASON_DATA_TRUNCATION,
    USN_REASON_DATA_OVERWRITE, USN_REASON_CLOSE,
    INCREMENT_REASON_MASK,
)


# ---- 纯逻辑层 ----

def test_struct_sizes():
    assert USN_RECORD_HEADER_SIZE == 60, USN_RECORD_HEADER_SIZE
    assert READ_DATA_SIZE == 40, READ_DATA_SIZE
    assert JOURNAL_DATA_SIZE == 56, JOURNAL_DATA_SIZE
    # 13 字段（I HH QQQQ IIII HH）无 padding 验证
    assert struct.calcsize('<IHHQQQQIIIIHH') == 60
    print('[OK] 结构体大小: header=60, read_data=40, journal_data=56')


def _make_record(frn, parent_frn, usn, reason, name):
    """构造一条 USN_RECORD_V2 记录字节（头部 + 文件名，8 字节对齐）。"""
    name_b = name.encode('utf-16-le')
    name_len = len(name_b)
    name_offset = USN_RECORD_HEADER_SIZE
    record_length = (USN_RECORD_HEADER_SIZE + name_len + 7) & ~7
    header = struct.pack(
        USN_RECORD_HEADER_FMT,
        record_length, 2, 0, frn, parent_frn, usn, 0, reason,
        0, 0, 0, name_len, name_offset)
    record = header + name_b
    record += b'\x00' * (record_length - len(record))
    return record


def test_parse_single():
    frn = 0x0003000000001234
    parent_frn = 0x0003000000000005
    rec = _make_record(frn, parent_frn, 100, 0x100, 'test.txt')
    buf = struct.pack('<Q', 200) + rec
    records = _parse_records(buf, 8)
    assert len(records) == 1, len(records)
    r = records[0]
    assert r['frn'] == frn
    assert r['parent_frn'] == parent_frn
    assert r['usn'] == 100
    assert r['reason'] == 0x100
    assert r['name'] == 'test.txt'
    print('[OK] 单记录解析: frn=%016x parent=%016x name=%r reason=%#x' % (
        r['frn'], r['parent_frn'], r['name'], r['reason']))


def test_parse_multi_and_cn():
    n1 = '\u4e2d\u6587\u6587\u4ef6.txt'
    rec1 = _make_record(0x11, 0x05, 1, 0x200, n1)
    rec2 = _make_record(0x22, 0x05, 2, 0x100, 'plain.txt')
    buf = struct.pack('<Q', 999) + rec1 + rec2
    records = _parse_records(buf, 8)
    assert len(records) == 2, len(records)
    assert records[0]['name'] == n1 and records[0]['frn'] == 0x11 and records[0]['reason'] == 0x200
    assert records[1]['name'] == 'plain.txt' and records[1]['frn'] == 0x22
    print('[OK] 多记录 + 中文名解析')


def test_parse_truncated():
    # record_length 超出剩余缓冲区 → 安全 break，不抛异常
    rec = _make_record(0x1, 0x2, 1, 0x100, 'a.txt')
    buf = struct.pack('<Q', 100) + rec[:10]
    assert _parse_records(buf, 8) == []
    # record_length < 头部大小 → break
    bad = struct.pack('<Q', 100) + struct.pack(
        USN_RECORD_HEADER_FMT, 10, 2, 0, 1, 2, 3, 0, 0, 0, 0, 0, 0, 0)
    assert _parse_records(bad, 8) == []
    print('[OK] 截断/非法记录安全返回')


def test_is_overflow():
    current = {'journal_id': 0x1111, 'first_usn': 100, 'next_usn': 200}
    assert is_overflow(0x1111, 200, current) is False  # 一致，不重扫
    assert is_overflow(0x2222, 200, current) is True   # journal_id 变 → 重扫
    assert is_overflow(0x1111, 50, current) is True    # saved_usn < first_usn → 重扫
    print('[OK] 溢出判断: id 变 / usn 回退触发全量重扫')


def test_reason_constants():
    assert USN_REASON_FILE_CREATE == 0x100
    assert USN_REASON_FILE_DELETE == 0x200
    assert USN_REASON_RENAME_OLD_NAME == 0x1000
    assert USN_REASON_RENAME_NEW_NAME == 0x2000
    assert USN_REASON_DATA_EXTEND == 0x2
    assert USN_REASON_DATA_TRUNCATION == 0x4
    assert USN_REASON_DATA_OVERWRITE == 0x1
    assert USN_REASON_CLOSE == 0x80000000
    m = INCREMENT_REASON_MASK
    assert m & USN_REASON_FILE_CREATE
    assert m & USN_REASON_FILE_DELETE
    assert m & USN_REASON_RENAME_OLD_NAME
    assert m & USN_REASON_RENAME_NEW_NAME
    assert m & USN_REASON_DATA_EXTEND
    print('[OK] reason 常量与增量掩码')


# ---- 真机层（需 pywin32 + 可读 NTFS 卷，否则跳过）----

def _pywin32_available():
    try:
        import win32file  # noqa: F401
        return True
    except Exception:
        return False


def test_real_volume(drive='C'):
    if not _pywin32_available():
        print('[SKIP] 真机测试：未装 pywin32')
        return
    from core.usn_journal import open_volume, close_volume, query_journal, read_page, catch_up

    try:
        h, drive = open_volume(drive)
    except Exception as e:
        print('[SKIP] 真机测试：无法打开卷 %s（%s）' % (drive, e))
        return
    try:
        info = query_journal(h)
        for k in ('journal_id', 'first_usn', 'next_usn', 'max_usn'):
            assert k in info, k
        assert info['first_usn'] <= info['next_usn'] <= info['max_usn']

        records, next_usn = read_page(h, info['first_usn'], info['journal_id'])
        assert next_usn >= info['first_usn']
        for r in records:
            assert 'frn' in r and 'parent_frn' in r and 'name' in r and 'reason' in r

        all_records, end_usn = catch_up(
            h, info['first_usn'], info['journal_id'], max_pages=3)
        assert end_usn >= info['first_usn']
        print('[OK] 真机 query/read/catch_up：first=%d next=%d 首页%d条 catch_up%d条' % (
            info['first_usn'], info['next_usn'], len(records), len(all_records)))
    finally:
        close_volume(h)


if __name__ == '__main__':
    offline = '--offline' in sys.argv
    test_struct_sizes()
    test_parse_single()
    test_parse_multi_and_cn()
    test_parse_truncated()
    test_is_overflow()
    test_reason_constants()
    if not offline:
        test_real_volume()
    print('\n全部通过')
