#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目录大小缓存管理器 + USN 增量更新引擎

SQLite 持久化 MFT 扫描结果，配合 USN Journal 做增量更新，实现「启动即用」：
首次全量 MFT 扫描（约 88s）后把结果写入 size_cache.db，后续启动直接从缓存
加载（几秒），后台 UsnUpdater 读 USN Journal 追平增量，避免每次全盘扫。

缓存位置：%LOCALAPPDATA%\\TreeMapBox\\size_cache.db（不放 %TEMP%，会被系统清理）。

设计要点：
1. 只缓存「扁平条目（文件+目录）的路径/大小/frn/parent_frn」，不缓存树结构。
   目录 size 由 UI 的 _convert_mft_results_to_tree 在加载时自底向上重算，
   因此增量更新只需维护「文件行」正确，无需回算祖先目录 size（消除写放大）。
2. frn / parent_frn 为完整 64 位 file_reference，供 USN 增量时 FRN→path 解析
   （沿 parent_frn 链拼路径）。FRN 复用必须用 64 位对齐，只用 48 位会串数据。
3. 删除用软删除（deleted=1）：先保留旧行供同一轮更新内 parent_frn 链解析，
   定期物理清理。目录删除用递归 CTE 一次软删整棵子树。
4. journal_state 记录扫描范围（scan_path）与 USN 游标；scan_path 变化即失效，
   保证「单范围快照」不脏读（扫 C:\\ 后扫 C:\\Users 会强制全量重扫）。
5. 增量游标取「扫描开始前」的 journal 位置：扫描期间发生的变更会重放，
   stat 幂等，最终状态正确。
"""

import os
import stat as stat_mod
import sqlite3
import threading
import time

from core.usn_journal import (
    open_volume, close_volume, query_journal, read_page,
    UsnJournalError, is_overflow,
    USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_DATA_EXTEND, USN_REASON_DATA_TRUNCATION,
    USN_REASON_DATA_OVERWRITE,
)
from utils.paths import default_cache_dir, localappdata_cache_dir

# 数据大小变化的 reason 组合
_DATA_CHANGE_MASK = (
    USN_REASON_DATA_EXTEND | USN_REASON_DATA_TRUNCATION | USN_REASON_DATA_OVERWRITE
)

# 新建 / 改名新名都会走到「确保新路径存在」的分支
_NEW_PATH_MASK = USN_REASON_FILE_CREATE | USN_REASON_RENAME_NEW_NAME

# SQLite INTEGER 是 64 位有符号（上限 2^63-1），frn 是 64 位无符号（0~2^64-1）。
# file_reference 高位（sequence）为 1 时值会 >= 2^63，直接写库报
# "Python int too large to convert to SQLite INTEGER"，故进出库统一转换。
_U64 = 1 << 64
_S63 = 1 << 63


def _to_signed(v):
    """无符号 64 位 int -> 有符号 64 位（写库前调用）。"""
    v = int(v or 0)
    return v - _U64 if v >= _S63 else v


def _to_unsigned(v):
    """有符号 64 位 int -> 无符号 64 位（读库后恢复，与 USN/file_reference 对齐）。"""
    v = int(v or 0)
    return v + _U64 if v < 0 else v


class SizeCacheManager:
    """目录大小缓存管理器（SQLite，WAL，线程本地连接）。"""

    def __init__(self, cache_dir=None):
        if cache_dir is None:
            cache_dir = default_cache_dir()
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            # 目标目录不可写（如 exe 放在 Program Files）→ 回退 LOCALAPPDATA
            cache_dir = localappdata_cache_dir()
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except OSError:
                cache_dir = os.environ.get('TEMP', '.')
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, 'size_cache.db')
        self._local = threading.local()
        self._init_database()

    # ---- 连接管理 ----

    def _conn(self):
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self.cache_file, timeout=5.0, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA busy_timeout=2000')
            self._local.conn = conn
        return conn

    def _init_database(self):
        conn = sqlite3.connect(self.cache_file, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS size_cache (
                path TEXT PRIMARY KEY COLLATE NOCASE,
                name TEXT,
                frn INTEGER,
                parent_frn INTEGER,
                size INTEGER,
                is_dir INTEGER,
                mtime REAL,
                deleted INTEGER DEFAULT 0,
                scan_time REAL
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_frn ON size_cache(frn)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_parent_frn ON size_cache(parent_frn)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_deleted ON size_cache(deleted)')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS journal_state (
                drive TEXT PRIMARY KEY,
                journal_id INTEGER,
                next_usn INTEGER,
                scan_path TEXT,
                last_update REAL
            )
        ''')
        conn.commit()
        conn.close()

    # ---- 工具 ----

    @staticmethod
    def _drive(scan_path):
        d = os.path.splitdrive(scan_path)[0]
        d = d.rstrip(':').rstrip('\\').upper()
        return d or 'C'

    @staticmethod
    def _like_pattern(path_prefix):
        """把路径前缀转成 SQL LIKE 模式（转义 \\ % _），供 path LIKE ? ESCAPE '\\'。"""
        p = os.path.normpath(path_prefix).rstrip('\\') + '\\'
        p = p.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return p + '%'

    def _drive_like(self, drive):
        return self._like_pattern(drive + ':\\')

    @staticmethod
    def _norm_scan(scan_path):
        return os.path.normcase(os.path.normpath(scan_path))

    # ---- 读写 ----

    def save_scan(self, files, scan_path, root_frn=0):
        """全量扫描后写入缓存：清空本盘旧数据，再批量插入新结果。

        root_frn 为卷根目录的 64 位 file_reference（可选）：提供后会把根目录
        作为一行写入缓存，USN 增量时顶层目录改名/新建才能正确解析父路径。
        """
        drive = self._drive(scan_path)
        conn = self._conn()
        now = time.time()
        conn.execute("DELETE FROM size_cache WHERE path LIKE ? ESCAPE '\\'",
                     (self._drive_like(drive),))
        rows = []
        if root_frn:
            rows.append((scan_path, os.path.basename(os.path.normpath(scan_path)),
                         _to_signed(root_frn), 0, 0, 1, 0.0, 0, now))
        for f in files:
            if not f:
                continue
            path = f.get('path')
            if not path:
                continue
            name = f.get('name') or os.path.basename(path)
            frn = _to_signed(f.get('frn') or 0)
            parent_frn = _to_signed(f.get('parent_frn') or 0)
            size = f.get('size') or 0
            is_dir = 1 if f.get('is_dir') else 0
            rows.append((path, name, frn, parent_frn, size, is_dir, 0.0, 0, now))
        conn.executemany(
            'INSERT OR REPLACE INTO size_cache '
            '(path, name, frn, parent_frn, size, is_dir, mtime, deleted, scan_time) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
        conn.commit()
        return len(rows)

    def load(self, scan_path):
        """返回缓存中 scan_path 下的条目 dict 列表（可直接喂给 _convert_mft_results_to_tree）。"""
        conn = self._conn()
        rows = conn.execute(
            "SELECT path, name, size, is_dir, frn, parent_frn "
            "FROM size_cache WHERE deleted=0 AND path LIKE ? ESCAPE '\\'",
            (self._like_pattern(scan_path),)).fetchall()
        return [
            {'path': r[0], 'name': r[1], 'size': r[2], 'is_dir': bool(r[3]),
             'frn': _to_unsigned(r[4]), 'parent_frn': _to_unsigned(r[5])}
            for r in rows
        ]

    def _row_count(self, scan_path):
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM size_cache WHERE deleted=0 AND path LIKE ? ESCAPE '\\'",
            (self._like_pattern(scan_path),)).fetchone()
        return row[0] if row else 0

    # ---- journal 状态 ----

    def get_journal_state(self, drive):
        conn = self._conn()
        row = conn.execute(
            'SELECT journal_id, next_usn, scan_path, last_update '
            'FROM journal_state WHERE drive=?', (drive,)).fetchone()
        if not row:
            return None
        return {'journal_id': row[0], 'next_usn': row[1],
                'scan_path': row[2], 'last_update': row[3]}

    def set_journal_state(self, drive, journal_id, next_usn, scan_path=None):
        conn = self._conn()
        if scan_path is None:
            row = conn.execute('SELECT scan_path FROM journal_state WHERE drive=?',
                               (drive,)).fetchone()
            scan_path = row[0] if row else ''
        conn.execute(
            'INSERT OR REPLACE INTO journal_state '
            '(drive, journal_id, next_usn, scan_path, last_update) VALUES (?,?,?,?,?)',
            (drive, journal_id, next_usn, scan_path, time.time()))
        conn.commit()

    def query_journal_snapshot(self, drive):
        """读当前 journal 的 (journal_id, next_usn)，失败返回 None。"""
        drive = drive.rstrip(':').upper()
        h = None
        try:
            h, _ = open_volume(drive)
            info = query_journal(h)
            return {'journal_id': info['journal_id'], 'next_usn': info['next_usn']}
        except Exception:
            return None
        finally:
            if h is not None:
                try:
                    close_volume(h)
                except Exception:
                    pass

    def is_valid(self, scan_path):
        """缓存是否可复用。任一条件不满足即返回 False（走全量扫描）。"""
        drive = self._drive(scan_path)
        h = None
        try:
            h, _ = open_volume(drive)
            info = query_journal(h)
        except Exception:
            return False
        finally:
            if h is not None:
                try:
                    close_volume(h)
                except Exception:
                    pass

        state = self.get_journal_state(drive)
        if not state:
            return False
        if is_overflow(state['journal_id'], state['next_usn'], info):
            return False
        if self._norm_scan(state.get('scan_path') or '') != self._norm_scan(scan_path):
            return False
        if self._row_count(scan_path) == 0:
            return False
        return True


class UsnUpdater:
    """USN 增量更新：query -> 分页 catch_up -> 分类应用 -> 推进 next_usn。

    run() 走真实卷流程（需 pywin32，通常在后台 QThread 里调用）；
    apply() 是纯记录应用入口，供单元测试在无 pywin32 环境验证分类逻辑。
    """

    def __init__(self, cache):
        self.cache = cache
        self._pending_rename = {}
        self._cancelled = False

    def cancel(self):
        """请求停止增量（全量重扫前调用，避免与 save_scan 并发写库）。"""
        self._cancelled = True

    def run(self, drive, progress_callback=None):
        """对 drive 执行一次增量追平。返回 (applied, ok)。失败返回 (0, False)。"""
        drive = drive.rstrip(':').upper()
        h = None
        applied = 0
        self._cancelled = False
        try:
            h, _ = open_volume(drive)
            info = query_journal(h)
            state = self.cache.get_journal_state(drive)
            if not state:
                return 0, False
            start_usn = state['next_usn']
            if is_overflow(state['journal_id'], start_usn, info):
                return 0, False

            frn2path = self._build_frn_map(drive)
            frn2isdir = self._build_frn_isdir(drive)
            self._pending_rename = {}
            conn = self.cache._conn()

            usn = start_usn
            jid = info['journal_id']
            pages = 0
            while True:
                if self._cancelled:
                    # 丢弃未提交变更，不推进 next_usn；全量重扫会重建缓存
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    return applied, False
                records, next_usn = read_page(h, usn, jid)
                if records:
                    applied += self._apply(records, drive, frn2path, frn2isdir, conn)
                pages += 1
                if next_usn <= usn:
                    break
                usn = next_usn
                if progress_callback and pages % 20 == 0:
                    progress_callback(applied, usn)

            conn.commit()
            self.cache.set_journal_state(drive, jid, usn)
            return applied, True
        except Exception:
            return applied, False
        finally:
            if h is not None:
                try:
                    close_volume(h)
                except Exception:
                    pass

    def apply(self, records, drive):
        """单批应用（测试/单测入口）：重建映射后应用，返回成功条数。"""
        drive = drive.rstrip(':').upper()
        frn2path = self._build_frn_map(drive)
        frn2isdir = self._build_frn_isdir(drive)
        self._pending_rename = {}
        conn = self.cache._conn()
        applied = self._apply(records, drive, frn2path, frn2isdir, conn)
        conn.commit()
        return applied

    # ---- 内部 ----

    def _build_frn_map(self, drive):
        conn = self.cache._conn()
        pattern = self.cache._drive_like(drive)
        m = {}
        for frn, path in conn.execute(
                "SELECT frn, path FROM size_cache "
                "WHERE deleted=0 AND frn != 0 AND path LIKE ? ESCAPE '\\'",
                (pattern,)):
            m[_to_unsigned(frn)] = path
        return m

    def _build_frn_isdir(self, drive):
        conn = self.cache._conn()
        pattern = self.cache._drive_like(drive)
        m = {}
        for frn, is_dir in conn.execute(
                "SELECT frn, is_dir FROM size_cache "
                "WHERE deleted=0 AND frn != 0 AND path LIKE ? ESCAPE '\\'",
                (pattern,)):
            m[_to_unsigned(frn)] = bool(is_dir)
        return m

    def _apply(self, records, drive, frn2path, frn2isdir, conn):
        applied = 0
        for rec in records:
            if self._apply_one(rec, frn2path, frn2isdir, conn):
                applied += 1
        return applied

    def _apply_one(self, rec, frn2path, frn2isdir, conn):
        reason = rec.get('reason', 0)
        frn = rec.get('frn', 0)
        name = rec.get('name', '')
        parent_frn = rec.get('parent_frn', 0)
        if not frn or not name:
            return False

        # 1. 删除：软删该行；若为目录，递归 CTE 软删整棵子树
        if reason & USN_REASON_FILE_DELETE:
            old_path = frn2path.pop(frn, None)
            self._pending_rename.pop(frn, None)
            if not old_path:
                return False
            if frn2isdir.get(frn):
                self._soft_delete_tree(conn, frn)
            else:
                conn.execute('UPDATE size_cache SET deleted=1 WHERE frn=?', (_to_signed(frn),))
            frn2isdir.pop(frn, None)
            return True

        # 2. 改名（旧名）：记住旧路径，等 NEW_NAME 记录来移动
        if reason & USN_REASON_RENAME_OLD_NAME:
            old_path = frn2path.get(frn)
            if old_path:
                self._pending_rename[frn] = old_path
            return bool(old_path)

        # 3. 新建 / 改名（新名）：确保新路径存在
        if reason & _NEW_PATH_MASK:
            parent_path = frn2path.get(parent_frn)
            if parent_path is None:
                # 父目录不在缓存（子目录扫描或缓存缺失）→ 跳过，下次全量修复
                return False
            new_path = os.path.join(parent_path, name)
            old_path = self._pending_rename.pop(frn, None)
            if old_path and os.path.normcase(old_path) != os.path.normcase(new_path):
                # 移动/改名：按 frn 更新 path/name/parent_frn，保留原 size/is_dir
                conn.execute(
                    'UPDATE size_cache SET path=?, name=?, parent_frn=?, deleted=0 '
                    'WHERE frn=? AND deleted=0',
                    (new_path, name, _to_signed(parent_frn), _to_signed(frn)))
                frn2path[frn] = new_path
                if frn2isdir.get(frn):
                    self._rewrite_tree(conn, frn, old_path, new_path, frn2path)
                return True
            # 纯新建
            size, is_dir, ok = self._stat(new_path)
            if not ok:
                return False
            conn.execute(
                'INSERT OR REPLACE INTO size_cache '
                '(path, name, frn, parent_frn, size, is_dir, mtime, deleted, scan_time) '
                'VALUES (?,?,?,?,?,?,0,0,?)',
                (new_path, name, _to_signed(frn), _to_signed(parent_frn), size, is_dir, time.time()))
            frn2path[frn] = new_path
            frn2isdir[frn] = is_dir
            return True

        # 4. 数据变更（大小变化）
        if reason & _DATA_CHANGE_MASK:
            path = frn2path.get(frn)
            if path is None:
                return False
            size, is_dir, ok = self._stat(path)
            if not ok:
                return False
            conn.execute('UPDATE size_cache SET size=?, is_dir=? WHERE path=?',
                         (size, is_dir, path))
            frn2isdir[frn] = is_dir
            return True

        return False

    @staticmethod
    def _stat(path):
        try:
            st = os.stat(path)
        except OSError:
            return 0, False, False
        is_dir = stat_mod.S_ISDIR(st.st_mode)
        size = 0 if is_dir else st.st_size
        return size, is_dir, True

    def _soft_delete_tree(self, conn, dir_frn):
        conn.execute(
            'WITH RECURSIVE sub(frn) AS ('
            '  SELECT frn FROM size_cache WHERE frn=? AND deleted=0 '
            '  UNION ALL '
            '  SELECT s.frn FROM size_cache s JOIN sub ON s.parent_frn=sub.frn AND s.deleted=0'
            ') UPDATE size_cache SET deleted=1 WHERE frn IN (SELECT frn FROM sub)',
            (_to_signed(dir_frn),))

    def _rewrite_tree(self, conn, dir_frn, old_dir_path, new_dir_path, frn2path):
        rows = conn.execute(
            'WITH RECURSIVE sub(frn) AS ('
            '  SELECT frn FROM size_cache WHERE parent_frn=? AND deleted=0 '
            '  UNION ALL '
            '  SELECT s.frn FROM size_cache s JOIN sub ON s.parent_frn=sub.frn AND s.deleted=0'
            ') SELECT frn, path FROM size_cache WHERE frn IN (SELECT frn FROM sub)',
            (_to_signed(dir_frn),)).fetchall()
        old_prefix = old_dir_path + os.sep
        nk_old_prefix = os.path.normcase(old_prefix)
        for frn, path in rows:
            if not path:
                continue
            if os.path.normcase(path).startswith(nk_old_prefix):
                new_path = new_dir_path + path[len(old_dir_path):]
                conn.execute('UPDATE size_cache SET path=? WHERE frn=?', (new_path, frn))
                frn2path[_to_unsigned(frn)] = new_path
