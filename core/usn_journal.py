#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USN Journal 引擎 — 封装 NTFS USN Change Journal 的查询与读取

用 pywin32 的 win32file.DeviceIoControl 直接读卷（FSCTL_QUERY/READ_USN_JOURNAL）。
仅 Windows + NTFS。读 USN Journal 通常普通权限即可；配合 MFT 扫描（需管理员）
使用时无额外要求。

参考（已核对结构体布局）：
- FSCTL_QUERY_USN_JOURNAL / FSCTL_READ_USN_JOURNAL（winioctl.h）
- USN_RECORD_V2 / USN_JOURNAL_DATA_V0 / READ_USN_JOURNAL_DATA_V0

注意：win32file 延迟导入，保证无 pywin32 环境也能 import 本模块做纯逻辑单测。
"""

import struct

# ---- 控制码（winioctl.h）----
FSCTL_QUERY_USN_JOURNAL = 0x000900F4
FSCTL_READ_USN_JOURNAL = 0x000900BB
FSCTL_ENUM_USN_DATA = 0x000900B3
FSCTL_CREATE_USN_JOURNAL = 0x000900E7
FSCTL_DELETE_USN_JOURNAL = 0x000900F8

# ---- USN Reason 掩码 ----
USN_REASON_DATA_OVERWRITE = 0x00000001
USN_REASON_DATA_EXTEND = 0x00000002
USN_REASON_DATA_TRUNCATION = 0x00000004
USN_REASON_NAMED_DATA_OVERWRITE = 0x00000010
USN_REASON_NAMED_DATA_EXTEND = 0x00000020
USN_REASON_NAMED_DATA_TRUNCATION = 0x00000040
USN_REASON_FILE_CREATE = 0x00000100
USN_REASON_FILE_DELETE = 0x00000200
USN_REASON_EA_CHANGE = 0x00000400
USN_REASON_SECURITY_CHANGE = 0x00000800
USN_REASON_RENAME_OLD_NAME = 0x00001000
USN_REASON_RENAME_NEW_NAME = 0x00002000
USN_REASON_INDEXABLE_CHANGE = 0x00004000
USN_REASON_BASIC_INFO_CHANGE = 0x00008000
USN_REASON_HARD_LINK_CHANGE = 0x00010000
USN_REASON_COMPRESSION_CHANGE = 0x00020000
USN_REASON_ENCRYPTION_CHANGE = 0x00040000
USN_REASON_OBJECT_ID_CHANGE = 0x00080000
USN_REASON_REPARSE_POINT_CHANGE = 0x00100000
USN_REASON_STREAM_CHANGE = 0x00200000
USN_REASON_TRANSACTED_CHANGE = 0x00400000
USN_REASON_INTEGRITY_CHANGE = 0x00800000
USN_REASON_CLOSE = 0x80000000

# 增量更新关心的掩码（过滤其它噪音，减少读到的记录量）
INCREMENT_REASON_MASK = (
    USN_REASON_FILE_CREATE | USN_REASON_FILE_DELETE
    | USN_REASON_RENAME_OLD_NAME | USN_REASON_RENAME_NEW_NAME
    | USN_REASON_DATA_EXTEND | USN_REASON_DATA_TRUNCATION
    | USN_REASON_DATA_OVERWRITE
)

# ---- 结构体格式串（< 表示 little-endian 且无对齐 padding）----

# USN_JOURNAL_DATA_V0：7 个 QWORD，共 56 字节
JOURNAL_DATA_FMT = '<QQQQQQQ'
JOURNAL_DATA_SIZE = struct.calcsize(JOURNAL_DATA_FMT)

# READ_USN_JOURNAL_DATA_V0：StartUsn, ReasonMask, ReturnOnlyOnClose,
#   Timeout, BytesToWaitFor, UsnJournalID —— 40 字节
READ_DATA_FMT = '<QIIQQQ'
READ_DATA_SIZE = struct.calcsize(READ_DATA_FMT)

# USN_RECORD_V2 头部固定部分（不含 FileName）：
#   RecordLength(I) MajorVersion(H) MinorVersion(H)
#   FileReferenceNumber(Q) ParentFileReferenceNumber(Q) Usn(Q) TimeStamp(Q)
#   Reason(I) SourceInfo(I) SecurityId(I) FileAttributes(I)
#   FileNameLength(H) FileNameOffset(H) —— 共 60 字节（13 个字段）
# 字段顺序按 MSDN 逐字节排列，8 字节字段天然落在 8 字节边界，无 padding。
USN_RECORD_HEADER_FMT = '<IHHQQQQIIIIHH'
USN_RECORD_HEADER_SIZE = struct.calcsize(USN_RECORD_HEADER_FMT)


class UsnJournalError(Exception):
    """USN Journal 操作失败。"""


def open_volume(drive):
    """打开卷句柄。drive 形如 'C' 或 'C:'。返回 (handle, drive_letter)。"""
    import win32file

    drive = drive.rstrip(':').upper()
    path = '\\\\.\\%s:' % drive
    h = win32file.CreateFile(
        path,
        win32file.GENERIC_READ,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    if h == win32file.INVALID_HANDLE_VALUE:
        raise UsnJournalError('无法打开卷 %s' % drive)
    return h, drive


def close_volume(h):
    """关闭卷句柄。"""
    import win32file

    try:
        win32file.CloseHandle(h)
    except Exception:
        pass


def query_journal(h):
    """查询 journal 信息，返回 dict。journal 未开启时抛 UsnJournalError。"""
    import win32file

    try:
        buf = win32file.DeviceIoControl(
            h, FSCTL_QUERY_USN_JOURNAL, None, JOURNAL_DATA_SIZE, None)
    except Exception as e:
        # 常见：卷未开启 Change Journal，报 ERROR_INVALID_FUNCTION
        raise UsnJournalError('FSCTL_QUERY_USN_JOURNAL 失败（卷可能未开启 journal）: %s' % e)

    (journal_id, first_usn, next_usn, lowest_valid_usn,
     max_usn, maximum_size, allocation_delta) = struct.unpack(JOURNAL_DATA_FMT, buf)
    return {
        'journal_id': journal_id,
        'first_usn': first_usn,
        'next_usn': next_usn,
        'lowest_valid_usn': lowest_valid_usn,
        'max_usn': max_usn,
        'maximum_size': maximum_size,
        'allocation_delta': allocation_delta,
    }


def read_page(h, start_usn, journal_id, reason_mask=INCREMENT_REASON_MASK,
              bytes_to_wait=0x10000, timeout=1):
    """读一页记录，返回 (records, next_usn)。records 为 dict 列表。

    BytesToWaitFor=64KB 表示"攒够 64KB 数据再返回"；若 journal 末尾剩余不足 64KB
    且 Timeout=0（无限等待），DeviceIoControl 会一直阻塞，增量线程的 cancel 标志
    无法生效、关闭时线程悬空。Timeout=1 秒保证最多等 1 秒即返回现有数据，避免卡死。
    """
    import win32file

    input_buf = struct.pack(
        READ_DATA_FMT, start_usn, reason_mask, 0, timeout, bytes_to_wait, journal_id)
    try:
        out = win32file.DeviceIoControl(
            h, FSCTL_READ_USN_JOURNAL, input_buf, bytes_to_wait, None)
    except Exception as e:
        raise UsnJournalError('FSCTL_READ_USN_JOURNAL 失败: %s' % e)

    if len(out) < 8:
        return [], start_usn
    next_usn = struct.unpack('<Q', out[:8])[0]
    records = _parse_records(out, 8)
    return records, next_usn


def catch_up(h, start_usn, journal_id, reason_mask=INCREMENT_REASON_MASK,
             max_pages=None):
    """从 start_usn 起连续读到 journal 末尾，返回 (records, next_usn)。"""
    records = []
    usn = start_usn
    pages = 0
    while True:
        page, next_usn = read_page(h, usn, journal_id, reason_mask)
        records.extend(page)
        pages += 1
        # next_usn 不再推进即到末尾；异常回退也终止
        if next_usn <= usn:
            break
        usn = next_usn
        if max_pages is not None and pages >= max_pages:
            break
    return records, usn


def _parse_records(buf, offset):
    """从缓冲区 offset 起解析 USN_RECORD_V2 序列。"""
    records = []
    n = len(buf)
    pos = offset
    while pos + USN_RECORD_HEADER_SIZE <= n:
        (record_length, major, minor, frn, parent_frn, usn, timestamp,
         reason, source_info, security_id, file_attributes,
         name_length, name_offset) = struct.unpack_from(USN_RECORD_HEADER_FMT, buf, pos)

        if record_length < USN_RECORD_HEADER_SIZE:
            break
        if pos + record_length > n:
            break

        # FileNameOffset 是相对「本记录起点（pos）」的偏移，UTF-16 编码
        name = ''
        if name_length > 0 and name_offset >= USN_RECORD_HEADER_SIZE:
            start = pos + name_offset
            end = start + name_length
            if end <= n:
                try:
                    name = buf[start:end].decode('utf-16-le', errors='replace')
                except Exception:
                    name = ''

        records.append({
            'frn': frn,
            'parent_frn': parent_frn,
            'usn': usn,
            'timestamp': timestamp,
            'reason': reason,
            'source_info': source_info,
            'security_id': security_id,
            'file_attributes': file_attributes,
            'name': name,
            'major': major,
            'minor': minor,
        })
        pos += record_length
    return records


def is_overflow(saved_id, saved_usn, current):
    """判断 journal 是否溢出/重建，需要全量重扫。current 为 query_journal 返回值。"""
    if saved_id != current['journal_id']:
        return True
    if saved_usn < current['first_usn']:
        return True
    return False
