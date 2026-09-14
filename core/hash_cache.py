#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
哈希缓存管理器 - SQLite 存储已计算的文件哈希

从通用系统清理工具的 duplicate_file_scanner.py 提取，
用于重复文件筛选模块的增量扫描优化。
"""

import os
import sqlite3
import threading
from datetime import datetime

from utils.paths import default_cache_dir, localappdata_cache_dir


class HashCacheManager:
    """哈希缓存管理器 - 使用SQLite存储已计算的哈希"""

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
        self.cache_file = os.path.join(cache_dir, 'duplicate_scanner_cache.db')
        # 每线程复用一个连接：避免 16 线程并发时每次操作都新建/销毁连接，
        # 也避免 sqlite3 默认 5 秒 busy 等待 × 大量写锁冲突导致扫描卡死。
        self._local = threading.local()
        self._init_database()

    def _conn(self):
        """返回当前线程专属连接（复用）。启用 WAL + busy_timeout，
        显著降低多线程并发写的锁冲突与等待。"""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self.cache_file, timeout=5.0, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')  # WAL 下安全且快，避免每次 commit 都 fsync
            conn.execute('PRAGMA busy_timeout=2000')
            self._local.conn = conn
        return conn

    def _init_database(self):
        conn = sqlite3.connect(self.cache_file, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA busy_timeout=2000')
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hash_cache (
                file_path TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sample_hash TEXT,
                full_hash TEXT,
                scan_time REAL NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deletion_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_hash TEXT,
                deleted_time REAL NOT NULL,
                restored INTEGER DEFAULT 0,
                restored_time REAL
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_deletion_time
            ON deletion_log(deleted_time DESC)
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_size ON hash_cache(file_size)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mtime ON hash_cache(mtime)')

        conn.commit()
        conn.close()

    def get_cached_hash(self, file_path, file_size, mtime):
        """从缓存获取哈希（如果文件未修改）"""
        try:
            conn = self._conn()
            cur = conn.execute('''
                SELECT sample_hash, full_hash, file_size, mtime
                FROM hash_cache WHERE file_path = ?
            ''', (file_path,))
            row = cur.fetchone()

            if row:
                cached_sample, cached_full, cached_size, cached_mtime = row
                if cached_size == file_size and abs(cached_mtime - mtime) < 1.0:
                    return cached_sample, cached_full
            return None, None
        except Exception:
            return None, None

    def save_hash(self, file_path, file_size, mtime, sample_hash=None, full_hash=None):
        """保存哈希到缓存（每 50 次批量提交一次，减少 WAL 写/事务次数）"""
        try:
            conn = self._conn()
            conn.execute('''
                INSERT OR REPLACE INTO hash_cache
                (file_path, file_size, mtime, sample_hash, full_hash, scan_time)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (file_path, file_size, mtime, sample_hash, full_hash, datetime.now().timestamp()))
            n = getattr(self._local, 'n', 0) + 1
            self._local.n = n
            if n % 50 == 0:
                conn.commit()
        except Exception:
            pass

    def flush(self):
        """提交当前线程尚未写入的缓存（扫描结束/退出时对各线程调用）。"""
        try:
            conn = getattr(self._local, 'conn', None)
            if conn is not None:
                conn.commit()
                self._local.n = 0
        except Exception:
            pass

    def clear_old_entries(self, days=30):
        """清理超过指定天数的旧缓存"""
        try:
            conn = self._conn()
            cutoff_time = datetime.now().timestamp() - days * 86400
            conn.execute('DELETE FROM hash_cache WHERE scan_time < ?', (cutoff_time,))
            conn.commit()
        except Exception:
            pass
