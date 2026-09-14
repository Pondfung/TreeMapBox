#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并行 MFT 扫描器 - 利用多核 CPU 并行扫描根目录各级子目录
"""

import os
import sys
from typing import List, Dict, Optional, Callable


def _scan_subtree_worker(args):
    """子进程工作函数：独立打开卷，扫描指定顶层条目的子树。
    返回 (files, errors)：files 为文件列表，errors 为损坏条目信息列表（最多20条）。
    """
    entry_name, drive_letter = args
    import pyfsntfs

    files = []
    errors = []  # 损坏条目信息：[(位置, 错误类型), ...]

    def _record_err(location, exc):
        if len(errors) < 20:
            errors.append((location, type(exc).__name__))

    try:
        vol = pyfsntfs.volume()
        vol.open(f"\\\\.\\{drive_letter}:")
        root = vol.get_root_directory()

        target = None
        try:
            for e in root.sub_file_entries:
                try:
                    if e.name == entry_name:
                        target = e
                        break
                except Exception as ex:
                    _record_err(f"{drive_letter}:\\{entry_name}", ex)
                    continue
        except Exception as ex:
            _record_err(f"{drive_letter}:\\{entry_name}", ex)

        if target is None:
            vol.close()
            return files, errors

        stack = [(target, "")]
        while stack:
            entry, cur_path = stack.pop()

            # 处理条目自身（与单进程扫描逐条目处理一致）
            try:
                name = entry.name
            except Exception as ex:
                _record_err(f"{drive_letter}:\\{cur_path}" if cur_path else f"{drive_letter}:\\{entry_name}", ex)
                name = None
            if not name or name.startswith('$'):
                # 跳过系统/无效条目，但不再继续其子项
                continue

            is_dir = False
            try:
                is_dir = entry.number_of_sub_file_entries > 0
            except Exception as ex:
                _record_err(f"{drive_letter}:\\{cur_path}\\{name}" if cur_path else f"{drive_letter}:\\{name}", ex)
                is_dir = False

            size = 0
            if not is_dir:
                try:
                    size = entry.size
                except Exception as ex:
                    _record_err(f"{drive_letter}:\\{cur_path}\\{name}" if cur_path else f"{drive_letter}:\\{name}", ex)
                    size = 0

            if cur_path:
                full_path = f"{drive_letter}:\\{cur_path}\\{name}"
            else:
                full_path = f"{drive_letter}:\\{name}"

            files.append({
                'name': name,
                'path': full_path,
                'size': size,
                'is_dir': is_dir,
            })

            if is_dir:
                new_path = f"{cur_path}\\{name}" if cur_path else name
                try:
                    for sub in entry.sub_file_entries:
                        stack.append((sub, new_path))
                except Exception as ex:
                    _record_err(full_path, ex)
    except Exception as ex:
        _record_err(f"{drive_letter}:\\{entry_name}", ex)

    try:
        vol.close()
    except Exception:
        pass
    return files, errors


class ParallelMFTScanner:
    """使用 multiprocessing 并行扫描 MFT 的扫描器"""

    def __init__(self):
        self._cancelled = False
        self._pool = None
        self.last_error = None  # 失败原因（字符串），成功时为 None
        self.last_errors_info = []  # 损坏条目信息列表 [(位置, 错误类型), ...]
        try:
            import pyfsntfs
            pyfsntfs.volume  # 触发导入检查
            self._available = True
        except Exception:
            self._available = False

    @property
    def supported(self):
        return self._available

    def cancel(self):
        """取消扫描：设置标志并终止进程池"""
        self._cancelled = True
        if self._pool is not None:
            try:
                self._pool.terminate()
            except Exception:
                pass

    def scan(self, path: str, progress_callback: Optional[Callable] = None) -> Optional[List[Dict]]:
        """
        并行扫描
        """
        import multiprocessing as mp
        import time

        if not self.supported:
            return None

        self._cancelled = False
        self._pool = None
        self.last_error = None
        self.last_errors_info = []

        drive_letter = os.path.splitdrive(path)[0].rstrip(':').rstrip('\\')
        if not drive_letter:
            drive_letter = 'c'
        drive_letter = drive_letter.upper()

        # 获取根目录下的顶层条目
        top_entries = []
        try:
            import pyfsntfs
            vol = pyfsntfs.volume()
            vol.open(f"\\\\.\\{drive_letter}:")
            root = vol.get_root_directory()
            for e in root.sub_file_entries or []:
                try:
                    name = e.name
                except Exception:
                    continue
                if name and not name.startswith('$'):
                    top_entries.append(name)
            vol.close()
        except Exception as e:
            print(f"[MFT并行扫描] 获取根条目失败: {e}")
            self.last_error = f"无法读取卷根目录: {e}"
            return None

        if not top_entries:
            return None

        nproc = max(1, min(mp.cpu_count() or 1, len(top_entries), 16))
        tasks = [(name, drive_letter) for name in top_entries]
        total = len(tasks)

        print(f"[MFT并行扫描] 根条目: {len(top_entries)}, 进程数: {nproc}")
        t1 = time.time()
        all_files = []
        done = 0

        if nproc <= 1:
            for task in tasks:
                if self._cancelled:
                    break
                subtree_name = task[0]
                if progress_callback:
                    progress_callback(f"已扫描 {done}/{total}，正在扫描「{subtree_name}」...",
                                      int(done * 100 / total) if total else 0)
                part_files, part_errors = _scan_subtree_worker(task)
                all_files.extend(part_files)
                self.last_errors_info.extend(part_errors)
                done += 1
                if progress_callback:
                    progress_callback(f"已扫描 {done}/{total}", int(done * 100 / total) if total else 0)
        else:
            # 不用阻塞式 imap_unordered：Windows 下 pool.terminate() 后
            # imap 的 next() 不会可靠抛异常/返回，会永久阻塞。
            # 改用 apply_async + ready() 轮询，cancel 时 terminate() 能立即生效。
            pool = mp.Pool(nproc)
            self._pool = pool
            last_heartbeat = t1
            try:
                async_results = [pool.apply_async(_scan_subtree_worker, (task,)) for task in tasks]
                pending = list(async_results)
                while pending and not self._cancelled:
                    time.sleep(0.1)
                    ready_list = [r for r in pending if r.ready()]
                    if ready_list:
                        for r in ready_list:
                            pending.remove(r)
                            try:
                                part_files, part_errors = r.get()
                                all_files.extend(part_files)
                                self.last_errors_info.extend(part_errors)
                            except Exception:
                                pass
                            done += 1
                            if progress_callback:
                                progress_callback(f"已扫描 {done}/{total}", int(done * 100 / total) if total else 0)
                            last_heartbeat = time.time()
                    else:
                        # 无 worker 完成：每 ~1s 发心跳，显示正在扫的子树名+已等待秒数
                        now = time.time()
                        if progress_callback and now - last_heartbeat >= 1.0:
                            last_heartbeat = now
                            elapsed = int(now - t1)
                            # 按 async_results 实际状态取未完成 task 名（async_results 与 tasks 一一对应）
                            pending_names = [tasks[i][0] for i in range(total) if not async_results[i].ready()]
                            name_hint = "、".join(pending_names[:2])
                            if len(pending_names) > 2:
                                name_hint += " 等"
                            progress_callback(
                                f"已扫描 {done}/{total}，正在扫描「{name_hint}」，已等待 {elapsed}s...",
                                int(done * 100 / total) if total else 0)
                if self._cancelled:
                    pool.terminate()
            finally:
                self._pool = None
                try:
                    pool.terminate()
                except Exception:
                    pass
                pool.join()

        t2 = time.time()
        print(f"[MFT并行扫描] 完成: 文件数 {len(all_files)}, 进程数 {nproc}, 耗时 {t2-t1:.2f}s")
        return all_files if all_files else None