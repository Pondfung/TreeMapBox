#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USN Journal 只读验证脚本（Task 1 验收用）。

用法（管理员运行更稳，普通权限通常也可读 USN）：
    python debug_usn.py C
    python debug_usn.py D

对照命令（验证解析是否对得上）：
    fsutil usn queryjournal C:
    fsutil usn enumdata 1 0 1 C:
"""

import sys

from core.usn_journal import (
    open_volume, close_volume, query_journal, read_page, catch_up, is_overflow,
    INCREMENT_REASON_MASK,
)

# 用全掩码看所有记录类型（debug 用），增量场景才用 INCREMENT_REASON_MASK
ALL_REASONS = 0xFFFFFFFF


def reason_names(reason):
    mapping = [
        (0x00000001, 'DATA_OVERWRITE'),
        (0x00000002, 'DATA_EXTEND'),
        (0x00000004, 'DATA_TRUNCATION'),
        (0x00000100, 'FILE_CREATE'),
        (0x00000200, 'FILE_DELETE'),
        (0x00001000, 'RENAME_OLD'),
        (0x00002000, 'RENAME_NEW'),
        (0x00008000, 'BASIC_INFO'),
        (0x80000000, 'CLOSE'),
    ]
    names = [n for bit, n in mapping if reason & bit]
    return ','.join(names) if names else hex(reason)


def main():
    drive = sys.argv[1] if len(sys.argv) > 1 else 'C'

    h, drive = open_volume(drive)
    try:
        info = query_journal(h)
        print('== journal info (%s:) ==' % drive)
        for k, v in info.items():
            print('  %-16s %-20s (0x%016x)' % (k, v, v))

        print()
        print('== first page (all reasons) ==')
        records, next_usn = read_page(h, info['first_usn'], info['journal_id'],
                                      reason_mask=ALL_REASONS)
        print('  next_usn = %d (0x%016x)' % (next_usn, next_usn))
        print('  records  = %d' % len(records))
        for r in records[:20]:
            print('    frn=%016x parent=%016x  %-32s  %s' % (
                r['frn'], r['parent_frn'], r['name'][:32], reason_names(r['reason'])))
        if len(records) > 20:
            print('    ... 仅显示前 20 条，共 %d 条' % len(records))

        print()
        print('== overflow check (saved==current 应 False) ==')
        print('  is_overflow(%#x, %d, current) = %s' % (
            info['journal_id'], info['next_usn'],
            is_overflow(info['journal_id'], info['next_usn'], info)))
        print('  is_overflow(0, %d, current)      = %s' % (
            info['next_usn'], is_overflow(0, info['next_usn'], info)))

        print()
        print('== catch_up 前 5 页 ==')
        all_records, end_usn = catch_up(
            h, info['first_usn'], info['journal_id'],
            reason_mask=INCREMENT_REASON_MASK, max_pages=5)
        print('  records = %d, end_usn = %d (0x%016x)' % (len(all_records), end_usn, end_usn))
    finally:
        close_volume(h)

    print()
    print('DONE')


if __name__ == '__main__':
    main()
