#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MFT扫描器 - 直接读取NTFS MFT实现极速扫描
使用 libfsntfs-python 库（兼容 Python 3）

API 版本: 20260727+
"""

import os
import sys
from typing import List, Dict, Optional, Callable
from pathlib import Path


class MFTScanner:
    """
    MFT扫描器 - 通过直接读取NTFS MFT实现极速扫描

    使用 libfsntfs-python 库（兼容 Python 3）

    优点：速度极快（10秒扫描整个系统盘）
    缺点：需要管理员权限，仅支持Windows NTFS
    """

    def __init__(self):
        self.supported = self._check_support()
        self._libfsntfs_available = self._check_libfsntfs()
        self._cancelled = False
        self.last_error = None  # 失败原因（字符串），成功时为 None
        self.last_errors_info = []  # 损坏条目信息列表 [(位置, 错误类型), ...]
        self.last_root_frn = 0  # 卷根目录完整 64 位 file_reference（增量缓存写根目录行用）

    def cancel(self):
        """取消扫描"""
        self._cancelled = True

    def _check_support(self) -> bool:
        """检查是否支持MFT扫描"""
        # 仅支持Windows
        if sys.platform != 'win32':
            return False

        # 检查是否有管理员权限
        return self.has_admin_rights()

    def _check_libfsntfs(self) -> bool:
        """检查 libfsntfs-python 库是否可用"""
        try:
            import pyfsntfs
            return True
        except ImportError:
            print("[MFT扫描] libfsntfs-python 库未安装")
            print("[MFT扫描] 请安装: pip install libfsntfs-python")
            return False

    def is_mft_library_available(self) -> bool:
        """返回 MFT 库是否可用"""
        return self._libfsntfs_available

    @staticmethod
    def has_admin_rights() -> bool:
        """检查是否有管理员权限"""
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    @staticmethod
    def is_ntfs_drive(path: str) -> bool:
        """检查指定路径是否在NTFS驱动器上"""
        try:
            import win32file
            drive = os.path.splitdrive(path)[0]
            if not drive:
                drive = os.path.splitdrive(os.getcwd())[0]

            # 获取文件系统类型
            _, _, _, _, fs_type = win32file.GetVolumeInformation(drive + "\\")
            return fs_type == 'NTFS'
        except:
            # 如果无法确定，假设是NTFS
            return True

    def scan(self, path: str, progress_callback: Optional[Callable] = None) -> Optional[List[Dict]]:
        """
        使用MFT扫描指定路径

        Args:
            path: 扫描路径
            progress_callback: 进度回调函数

        Returns:
            文件列表，失败返回None
        """
        print(f"[MFT扫描] 开始扫描: {path}")
        print(f"[MFT扫描] supported={self.supported}, libfsntfs_available={self._libfsntfs_available}")

        self._cancelled = False
        self.last_error = None
        self.last_errors_info = []

        if not self.supported:
            print("[MFT扫描] 不支持MFT扫描（可能缺少管理员权限）")
            self.last_error = "MFT扫描不可用：可能缺少管理员权限"
            return None

        try:
            # 使用 libfsntfs-python 库
            print("[MFT扫描] 调用 _scan_with_libfsntfs...")
            result = self._scan_with_libfsntfs(path, progress_callback)
            print(f"[MFT扫描] 扫描完成，返回 {len(result) if result else 0} 条记录")
            return result
        except ImportError as e:
            print(f"[MFT扫描] 缺少依赖: {e}")
            print("[MFT扫描] 请安装: pip install libfsntfs-python")
            self.last_error = "缺少 libfsntfs-python 库（请安装：pip install libfsntfs-python）"
            if progress_callback:
                progress_callback("缺少libfsntfs-python库，无法使用MFT扫描", 0)
            return None
        except PermissionError as e:
            print(f"[MFT扫描] 权限不足: {e}")
            self.last_error = "需要管理员权限才能使用MFT扫描"
            if progress_callback:
                progress_callback("需要管理员权限才能使用MFT扫描", 0)
            return None
        except OSError as e:
            print(f"[MFT扫描] 打开卷失败: {e}")
            self.last_error = f"无法访问磁盘：{e}（请以管理员身份运行）"
            if progress_callback:
                progress_callback("无法访问磁盘，请以管理员身份运行", 0)
            return None
        except Exception as e:
            print(f"[MFT扫描失败] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            self.last_error = f"扫描异常: {type(e).__name__}: {e}"
            return None

    def _scan_with_libfsntfs(self, path: str, progress_callback: Optional[Callable]) -> Optional[List[Dict]]:
        """
        使用 libfsntfs-python 库扫描（优化版）

        使用迭代式栈遍历目录树（避免 Python 递归开销）

        依赖：pip install libfsntfs-python
        """
        import pyfsntfs
        import time

        # 获取驱动器号
        drive_letter = os.path.splitdrive(path)[0]
        if not drive_letter:
            drive_letter = 'C'
        else:
            drive_letter = drive_letter.rstrip(':')
        drive_letter = drive_letter.upper()

        device_path = f"\\\\.\\{drive_letter}:"
        print(f"[MFT扫描] device_path = {device_path}")

        if progress_callback:
            progress_callback(f"正在打开 {drive_letter} 盘...", 0)

        # 打开卷
        volume = pyfsntfs.volume()
        volume.open(device_path)
        print(f"[MFT扫描] 卷打开成功")

        # 获取根目录
        root = volume.get_root_directory()
        root_name = root.get_name() or ""
        total_sub = root.get_number_of_sub_file_entries()
        print(f"[MFT扫描] 根目录: {root_name or '(空)'}, 子条目数: {total_sub}")

        # MFT 条目总数（用于进度百分比，失败则 0 走 busy 模式）
        try:
            total_entries = volume.get_number_of_file_entries()
        except Exception:
            total_entries = 0

        if progress_callback:
            progress_callback("正在扫描目录结构...", 0)

        # ===== 迭代式栈遍历 =====
        t1 = time.time()
        files = []
        # 根目录 FRN（作为顶层条目的 parent_frn）
        try:
            root_frn = root.file_reference
        except Exception:
            root_frn = 0
        self.last_root_frn = root_frn
        # 栈元素: (directory_entry, current_path, parent_frn)
        stack = [(root, "", root_frn)]
        count = 0
        errors = 0

        while stack:
            if self._cancelled:
                break
            directory, current_path, parent_frn = stack.pop()
            try:
                for entry in directory.sub_file_entries:
                    try:
                        name = entry.name
                        if not name or name.startswith('$'):
                            continue

                        # 完整 64 位 file_reference（含 sequence），供 USN 增量映射
                        try:
                            frn = entry.file_reference
                        except Exception:
                            frn = 0

                        # 判断目录
                        try:
                            is_dir = entry.number_of_sub_file_entries > 0
                        except:
                            is_dir = False

                        # 获取大小（仅文件）
                        size = 0
                        if not is_dir:
                            try:
                                size = entry.size
                            except:
                                size = 0

                        # 构建完整路径
                        if current_path:
                            full_path = f"{drive_letter}:\\{current_path}\\{name}"
                        else:
                            full_path = f"{drive_letter}:\\{name}"

                        files.append({
                            'name': name,
                            'path': full_path,
                            'size': size,
                            'is_dir': is_dir,
                            'frn': frn,
                            'parent_frn': parent_frn,
                        })

                        count += 1

                        # 目录压栈
                        if is_dir:
                            new_path = f"{current_path}\\{name}" if current_path else name
                            stack.append((entry, new_path, frn))

                    except Exception as e:
                        errors += 1
                        if errors <= 5:
                            print(f"[MFT扫描] 条目处理错误: {type(e).__name__}: {e}")
                        if len(self.last_errors_info) < 20:
                            loc = f"{drive_letter}:\\{current_path}" if current_path else f"{drive_letter}:\\"
                            self.last_errors_info.append((loc, type(e).__name__))

            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"[MFT扫描] 目录遍历错误: {type(e).__name__}: {e}")
                if len(self.last_errors_info) < 20:
                    loc = f"{drive_letter}:\\{current_path}" if current_path else f"{drive_letter}:\\"
                    self.last_errors_info.append((loc, type(e).__name__))

            # 进度回调（加大间隔减少开销）
            if count % 20000 == 0 and count > 0 and progress_callback:
                pct = int(count * 100 / total_entries) if total_entries > 0 else 0
                progress_callback(f"已扫描 {count} 文件", pct)

        # 关闭卷
        volume.close()

        t2 = time.time()
        print(f"[MFT扫描] 扫描完成: {count} 个文件, {errors} 个错误, 耗时 {t2-t1:.2f}s")

        return files if files else None

    def get_scan_speed_description(self) -> str:
        """获取扫描速度描述"""
        if not self.supported:
            if sys.platform != 'win32':
                return "MFT扫描仅支持Windows"
            return "需要管理员权限才能使用MFT扫描"

        return "极速扫描（预计1-3分钟）"


from .parallel_mft_scanner import ParallelMFTScanner


class HybridScanner:
    """
    混合扫描器：自动选择最佳扫描方式

    优先级：
    1. MFT扫描（并行 · 需管理员权限 + NTFS）
    2. 普通扫描（兜底）
    """

    def __init__(self):
        self.mft_scanner = ParallelMFTScanner()
        self.mft_single = MFTScanner()
        self._cancelled = False
        self.last_error = None  # 失败原因（字符串），成功时为 None
        self.last_errors_info = []  # 损坏条目信息列表 [(位置, 错误类型), ...]

    def cancel(self):
        """取消扫描：转发给子扫描器"""
        self._cancelled = True
        self.mft_scanner.cancel()
        self.mft_single.cancel()

    def _sync_last_error(self):
        """从子扫描器转存失败原因"""
        self.last_error = self.mft_scanner.last_error or self.mft_single.last_error
        self.last_errors_info = self.mft_scanner.last_errors_info or self.mft_single.last_errors_info

    def scan(self, path: str, mode: str = 'auto', progress_callback: Optional[Callable] = None):
        """
        扫描指定路径

        Args:
            path: 扫描路径
            mode: 扫描模式
                - 'auto': 自动选择（MFT优先，普通扫描兜底）
                - 'mft': 强制MFT扫描（失败返回None）
                - 'normal': 强制普通扫描
            progress_callback: 进度回调

        Returns:
            (files_list, scan_method)
        """
        self._cancelled = False
        self.last_error = None

        if mode == 'normal':
            return None, 'normal'

        if mode == 'mft':
            # 强制MFT扫描
            if not self.mft_scanner.supported:
                self.last_error = "MFT并行扫描不可用（可能缺少管理员权限或 pyfsntfs 库）"
                return None, 'mft_unsupported'

            files = self.mft_scanner.scan(path, progress_callback)
            if self._cancelled:
                return None, 'cancelled'
            if files:
                return files, 'mft'
            self._sync_last_error()
            return None, 'mft'

        # mode == 'auto'
        # 自动选择：优先MFT，失败则降级
        if self.mft_scanner.supported and self.mft_single.is_ntfs_drive(path):
            if progress_callback:
                progress_callback("尝试使用MFT并行极速扫描...", 0)

            files = self.mft_scanner.scan(path, progress_callback)

            if self._cancelled:
                return None, 'cancelled'

            if files:
                return files, 'mft'

            # 并行扫描失败，退回单进程MFT
            print("[HybridScanner] 并行MFT扫描失败，退回单进程...")
            files = self.mft_single.scan(path, progress_callback)

            if self._cancelled:
                return None, 'cancelled'

            if files:
                return files, 'mft_single'

            self._sync_last_error()

        # 降级到普通扫描
        return None, 'normal'