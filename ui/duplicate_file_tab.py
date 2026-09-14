#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重复文件筛选 Tab - PyQt6 版本

三级渐进式比对（大小 → 采样哈希 → 完整哈希）
支持导入磁盘分析结果、哈希缓存、硬链接检测、保留策略
从通用系统清理工具的 duplicate_file_scanner.py 移植。
"""

import os
import sys
import hashlib
import mmap
import json
import stat
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QProgressBar,
    QMenu, QMessageBox, QApplication, QAbstractItemView,
    QLineEdit, QFileDialog, QCheckBox, QHeaderView,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QSplitter,
    QStyleOptionButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QRect, QSize
from PyQt6.QtGui import QColor, QAction
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.hash_cache import HashCacheManager
from core.mft_scanner import MFTScanner, HybridScanner

# 导出文件目录
EXPORT_DIR = os.environ.get('TEMP', '.')


def _safe_path(p):
    """对路径做代理字符安全化（与磁盘分析Tab一致）。

    Windows 文件名是 UTF-16，某些损坏/特殊文件名含孤立代理字符（surrogate），
    json.dump(ensure_ascii=False) 写 UTF-8 文件会抛 UnicodeEncodeError 导致导出
    中断。用 surrogatepass 编码再 replace 解码，把孤立代理替换为 U+FFFD。
    """
    try:
        return p.encode('utf-8', 'surrogatepass').decode('utf-8', 'replace')
    except Exception:
        return p.encode('utf-8', 'replace').decode('utf-8', 'replace')


# cache/temp 相关关键字（与缓存清理Tab _is_cache_like 一致）
_CACHE_KEYWORDS = ('cache', 'temp', 'tmp', '缓存', '临时')


def _is_cache_like(name):
    """名字是否与 cache/temp 相关（不区分大小写，与缓存清理Tab同规则）"""
    low = name.lower()
    return any(kw in low for kw in _CACHE_KEYWORDS)


def _path_in_cache_dir(path):
    """路径是否位于 cache/temp 相关目录下（检查各级目录名）。

    例如 C:\\Users\\x\\.cache\\a.bin 中 .cache 匹配 → 跳过该文件。
    盘根、文件名本身不检查（只查中间各级目录名）。
    """
    # 拆分路径各级，跳过盘符根，检查每个目录名
    parts = path.replace('/', '\\').split('\\')
    # 去掉空段和盘符段（如 'C:'）
    for part in parts:
        if not part or len(part) == 2 and part[1] == ':':
            continue
        if _is_cache_like(part):
            return True
    return False


def _get_export_path(scan_path):
    """根据扫描路径生成导出文件路径（按盘符区分，如 disk_scan_C.json）"""
    drive = os.path.splitdrive(scan_path)[0].replace(':', '') or 'unknown'
    return os.path.join(EXPORT_DIR, f'disk_scan_{drive}.json')


def _is_root_path(path_str):
    """判断是否为磁盘根目录（如 C:\、D:\、E:/）"""
    p = path_str.strip().rstrip('/\\')
    return len(p) == 2 and p[1] == ':' or (len(p) == 3 and p[1] == ':' and p[2] in '/\\')


class CenteredCheckDelegate(QStyledItemDelegate):
    """在第 0 列居中绘制原生复选框。

    替代用文本字符 '☐'/'☑' 模拟复选框的旧方案——后者字符太小、对齐不可控、
    且改文本会触发排序/重绘导致延迟。改用 Qt.CheckStateRole 后，复选框外观与
    大小由 style 统一管理（直观、可点击），本 delegate 只负责把它居中绘制。
    对没有 CheckStateRole 数据的行（硬链接树显示 '🔗'）按默认方式绘制其文本。

    注意：用 QStyleOptionButton + drawControl(CE_CheckBox) 而非
    drawPrimitive(PE_IndicatorCheckBox)——后者在 fusion style 下勾选与未勾选
    渲染完全相同（不画对勾），导致「点选后复选框无变化」；CE_CheckBox 在所有
    style 下都能正确画出对勾。
    """

    def paint(self, painter, option, index):
        if index.column() != 0:
            super().paint(painter, option, index)
            return
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is None:
            # 非勾选项（硬链接树显示 '🔗'）：按默认方式绘制其文本
            super().paint(painter, option, index)
            return
        style = option.widget.style() if option.widget is not None else QApplication.style()
        iw = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, option.widget)
        ih = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, None, option.widget)
        # 构造按钮风格选项并居中
        opt = QStyleOptionButton()
        opt.rect = QRect(
            option.rect.center().x() - iw // 2,
            option.rect.center().y() - ih // 2,
            iw, ih,
        )
        # 清除选中高亮（避免 indicator 被选区色淹没），保留 enabled
        opt.state = QStyle.StateFlag.State_Enabled
        # ⚠️ index.data(CheckStateRole) 在 PyQt6 返回 int（如 2），与 Qt.CheckState
        # 枚举直接比较恒为 False，会导致勾选状态被误判为未勾选、复选框不画对勾。
        # 这里用 .value 取 int 比较。
        sval = state if isinstance(state, int) else int(getattr(state, 'value', 0))
        if sval == Qt.CheckState.Checked.value:
            opt.state |= QStyle.StateFlag.State_On
        elif sval == Qt.CheckState.PartiallyChecked.value:
            opt.state |= QStyle.StateFlag.State_NoChange
        else:
            opt.state |= QStyle.StateFlag.State_Off
        style.drawControl(QStyle.ControlElement.CE_CheckBox, opt, painter, option.widget)

    def sizeHint(self, option, index):
        if index.column() != 0:
            return super().sizeHint(option, index)
        style = option.widget.style() if option.widget is not None else QApplication.style()
        iw = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, option.widget)
        ih = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, None, option.widget)
        return QSize(iw + 8, ih + 8)


def _get_latest_export_path():
    """获取最新修改的导出文件"""
    import glob
    files = glob.glob(os.path.join(EXPORT_DIR, 'disk_scan_*.json'))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _format_size(b):
    """格式化字节大小"""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


# ============================================
# 云盘/保护路径检测
# ============================================

CLOUD_MARKERS = [
    'WPS企业云盘', 'WPS Cloud', 'OneDrive', 'Dropbox',
    'Google Drive', 'iCloud', '坚果云', '百度网盘', '阿里云盘', '腾讯微云',
]

PROTECTED_PATHS = [
    os.environ.get('SystemRoot', r'C:\Windows'),
    os.environ.get('ProgramFiles', r'C:\Program Files'),
    os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
]


def _is_cloud_synced(path):
    p = path.upper()
    return any(m.upper() in p for m in CLOUD_MARKERS)


def _is_protected(path):
    try:
        norm = os.path.normpath(os.path.abspath(path))
        for d in PROTECTED_PATHS:
            if d and os.path.exists(d):
                if norm.lower().startswith(os.path.normpath(os.path.abspath(d)).lower()):
                    return True
        if hasattr(sys, 'executable'):
            prog_dir = os.path.normpath(os.path.abspath(os.path.dirname(sys.executable)))
            if norm.lower().startswith(prog_dir.lower()):
                return True
    except Exception:
        return True
    return False


def _clear_readonly(path):
    try:
        mode = os.stat(path).st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(path, mode | stat.S_IWRITE)
            return True
    except (OSError, PermissionError):
        pass
    return False


# ============================================
# 扫描线程
# ============================================

class PathScanThread(QThread):
    """路径扫描线程 - 沿用磁盘分析Tab的扫描办法（MFT优先，失败降级普通扫描）。

    得到扁平文件列表 [{'path','size'}, ...]，供 DuplicateScanThread 做三级哈希比对。
    若扫描根目录，完成后自动导出对应盘符 JSON（覆盖旧文件），供下次复用。
    """
    progress = pyqtSignal(str, int)
    error = pyqtSignal(str)
    finished = pyqtSignal(list)  # file_list: [{'path','size'}, ...]

    def __init__(self, path, auto_export=False):
        super().__init__()
        self.path = path
        self.auto_export = auto_export  # 根目录扫描时自动导出 JSON
        self.hybrid_scanner = HybridScanner()
        self.mft_scanner = MFTScanner()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.hybrid_scanner.cancel()

    def run(self):
        import time as _time
        try:
            self.progress.emit("正在扫描文件列表（MFT优先）...", 0)
            mode = 'auto'  # 自动：MFT优先，失败降级普通扫描
            # MFT 不可用时直接普通扫描
            can_use_mft = (
                self.mft_scanner.has_admin_rights() and
                self.mft_scanner.is_mft_library_available() and
                self.mft_scanner.is_ntfs_drive(self.path)
            )
            if not can_use_mft:
                mode = 'normal'

            files = None
            method = None
            if mode == 'auto':
                def cb(msg, count):
                    if self._cancelled:
                        return
                    self.progress.emit(msg, count)
                files, method = self.hybrid_scanner.scan(self.path, 'auto', cb)
                if self._cancelled:
                    # 取消后不降级、不继续，直接收尾 emit finished（空列表）
                    self.finished.emit([])
                    return
                # MFT 自然失败（非取消）才降级到普通扫描
                if files is None:
                    self.progress.emit("MFT扫描失败，降级为普通扫描...", 0)
                    files, method = self._scan_normal(), 'normal'

            if mode == 'normal' and files is None:
                files = self._scan_normal()
                method = 'normal'

            if self._cancelled:
                self.finished.emit([])
                return

            # 转为重复文件所需格式，过滤目录、只留文件
            file_list = []
            for f in (files or []):
                if f is None or not isinstance(f, dict):
                    continue
                if f.get('is_dir'):
                    continue
                p = f.get('path')
                if not p:
                    continue
                file_list.append({'path': _safe_path(p), 'size': f.get('size', 0)})

            self.progress.emit(f"扫描完成：{len(file_list)} 个文件（{method}）", 0)

            # 根目录自动导出 JSON（覆盖旧文件）
            if self.auto_export and _is_root_path(self.path):
                self._export_json(file_list)

            self.finished.emit(file_list)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(f"路径扫描异常: {e}")

    def _scan_normal(self):
        """普通扫描兜底：os.walk 收集文件"""
        files = []
        try:
            for root, dirs, fns in os.walk(self.path):
                if self._cancelled:
                    break
                for fn in fns:
                    if self._cancelled:
                        break
                    fp = os.path.join(root, fn)
                    try:
                        st = os.stat(fp)
                        files.append({'path': fp, 'name': fn, 'is_dir': False,
                                      'size': st.st_size})
                    except (OSError, PermissionError):
                        pass
        except (OSError, PermissionError):
            pass
        return files

    def _export_json(self, file_list):
        """导出文件列表到 JSON（按盘符区分，原子覆盖旧文件）"""
        import json
        from datetime import datetime
        export_path = _get_export_path(self.path)
        data = {
            'scan_path': self.path,
            'scan_time': datetime.now().isoformat(),
            'total_files': len(file_list),
            'files': [{'path': _safe_path(f['path']), 'size': f['size']} for f in file_list],
        }
        try:
            # 原子写：临时文件 + os.replace，避免中断留下半截损坏 JSON
            tmp_path = export_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=None,
                          separators=(',', ':'))
            os.replace(tmp_path, export_path)
            drive = os.path.splitdrive(self.path)[0]
            self.progress.emit(f"已自动导出 {drive} 盘文件列表（{len(file_list)} 个）", 0)
        except Exception:
            pass


class DuplicateScanThread(QThread):
    """重复文件扫描线程 - 三级渐进式比对（多线程并行）"""
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    SAMPLE_SIZE = 4096
    MAX_WORKERS = 16

    def __init__(self, file_list, use_cache=True):
        super().__init__()
        self.file_list = file_list
        self.use_cache = use_cache
        self._cancelled = False
        self.cache_manager = HashCacheManager()
        self.result_dup = []
        self.result_hl = []
        self.result_stats = {}
        self.is_done = False

    def cancel(self):
        self._cancelled = True

    def _calc_sample_hash(self, path, size):
        hasher = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                if size <= self.SAMPLE_SIZE * 3:
                    hasher.update(f.read())
                else:
                    hasher.update(f.read(self.SAMPLE_SIZE))
                    mid = size // 2 - self.SAMPLE_SIZE // 2
                    f.seek(max(0, mid))
                    hasher.update(f.read(self.SAMPLE_SIZE))
                    f.seek(size - self.SAMPLE_SIZE)
                    hasher.update(f.read(self.SAMPLE_SIZE))
            return hasher.hexdigest() if not self._cancelled else None
        except (OSError, PermissionError):
            return None

    def _calc_full_hash(self, path, size):
        hasher = hashlib.sha256()
        try:
            if size > 100 * 1024 * 1024:
                with open(path, 'rb') as f:
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        for offset in range(0, size, 8192):
                            # 大文件哈希循环内检查取消，避免按停止后
                            # 在单个大文件上阻塞数十秒无法退出
                            if self._cancelled:
                                return None
                            end = min(offset + 8192, size)
                            hasher.update(mm[offset:end])
            else:
                with open(path, 'rb') as f:
                    while True:
                        if self._cancelled:
                            return None
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        hasher.update(chunk)
            return hasher.hexdigest() if not self._cancelled else None
        except (OSError, PermissionError):
            return None

    def _detect_hardlinks(self, file_list):
        inode_map = {}
        for fp in file_list:
            try:
                st = os.stat(fp)
                key = (st.st_dev, st.st_ino)
                inode_map.setdefault(key, []).append(fp)
            except OSError:
                pass
        if len(inode_map) == 1:
            first_key = list(inode_map.keys())[0]
            if len(inode_map[first_key]) >= 2:
                return True, inode_map[first_key]
        return False, file_list

    def _hash_one_file(self, fp, size, mode='sample'):
        """单文件哈希计算（线程池 worker）"""
        try:
            # 尝试从缓存获取
            if self.use_cache:
                mtime = os.path.getmtime(fp)
                cs, cf = self.cache_manager.get_cached_hash(fp, size, mtime)
                if mode == 'sample' and cs:
                    return fp, cs, 'cached'
                if mode == 'full' and cf:
                    return fp, cf, 'cached'

            if mode == 'sample':
                h = self._calc_sample_hash(fp, size)
            else:
                h = self._calc_full_hash(fp, size)

            if h and self.use_cache:
                mtime = os.path.getmtime(fp)
                if mode == 'sample':
                    self.cache_manager.save_hash(fp, size, mtime, sample_hash=h)
                else:
                    self.cache_manager.save_hash(fp, size, mtime, full_hash=h)

            return fp, h, 'computed'
        except Exception:
            return fp, None, 'error'

    def run(self):
        try:
            import os as _os
            cpu_count = _os.cpu_count() or 4
            workers = min(self.MAX_WORKERS, max(4, cpu_count))

            stats = {
                'total_files': len(self.file_list),
                'size_groups': 0, 'size_filtered': 0,
                'sample_groups': 0, 'sample_filtered': 0,
                'full_groups': 0, 'full_filtered': 0,
                'cached_hits': 0,
            }

            # ===== 第一级：大小分组 =====
            self.progress.emit(f"第一级：按大小分组 ({stats['total_files']} 个文件)")
            size_groups = defaultdict(list)
            for f in self.file_list:
                if self._cancelled:
                    return
                size_groups[f['size']].append(f['path'])

            dup_by_size = {s: p for s, p in size_groups.items() if len(p) > 1}
            stats['size_groups'] = len(dup_by_size)
            stats['size_filtered'] = sum(len(p) for p in dup_by_size.values())

            if not dup_by_size:
                self.result_dup = []
                self.result_hl = []
                self.result_stats = stats
                self.is_done = True
                return

            self.progress.emit(f"第一级：{stats['total_files']} → {stats['size_filtered']} ({stats['size_groups']} 组)")

            # ===== 第二级 + 第三级：复用同一个线程池 =====
            # 之前每批 500 条都新建/销毁一个 ThreadPoolExecutor，17 万文件会产生
            # ~680 次构造/shutdown/线程销毁，抬高内存峰值与资源句柄压力，放大
            # QThread 拆除时序窗口。这里全程共用一个池，仅在大循环末尾 shutdown 一次。
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # ----- 第二级：采样哈希（分批并行） -----
                self.progress.emit(f"第二级：采样哈希 ({workers} 线程并行)...")
                sample_groups = defaultdict(list)
                all_sample_tasks = []
                for size, paths in dup_by_size.items():
                    for fp in paths:
                        all_sample_tasks.append((fp, size))

                processed = 0
                total = len(all_sample_tasks)
                batch_size = 500

                for batch_start in range(0, total, batch_size):
                    if self._cancelled:
                        return
                    batch = all_sample_tasks[batch_start:batch_start + batch_size]
                    try:
                        results = list(pool.map(
                            lambda args: self._hash_one_file(args[0], args[1], 'sample'),
                            batch
                        ))
                    except Exception:
                        continue

                    for idx, (fp, h, status) in enumerate(results):
                        processed += 1
                        if h:
                            sz = batch[idx][1]
                            sample_groups[(sz, h)].append(fp)
                            if status == 'cached':
                                stats['cached_hits'] += 1

                    if processed % 1000 == 0:
                        self.progress.emit(f"采样哈希: {processed}/{total}")
                    del results

                dup_by_sample = {k: p for k, p in sample_groups.items() if len(p) > 1}
                stats['sample_groups'] = len(dup_by_sample)
                stats['sample_filtered'] = sum(len(p) for p in dup_by_sample.values())

                if not dup_by_sample:
                    self.result_dup = []
                    self.result_hl = []
                    self.result_stats = stats
                    self.is_done = True
                    return

                self.progress.emit(f"第二级：{stats['size_filtered']} → {stats['sample_filtered']} ({stats['sample_groups']} 组)")

                # ----- 第三级：完整哈希（分批并行） -----
                self.progress.emit(f"第三级：完整哈希 ({workers} 线程并行)...")
                hash_groups = defaultdict(list)
                all_full_tasks = []
                sample_hash_map = {}
                for (size, sh), paths in dup_by_sample.items():
                    for fp in paths:
                        all_full_tasks.append((fp, size))
                        sample_hash_map[fp] = sh

                processed = 0
                total = len(all_full_tasks)
                batch_size = 500

                for batch_start in range(0, total, batch_size):
                    if self._cancelled:
                        return
                    batch = all_full_tasks[batch_start:batch_start + batch_size]
                    try:
                        results = list(pool.map(
                            lambda args: self._hash_one_file(args[0], args[1], 'full'),
                            batch
                        ))
                    except Exception:
                        continue

                    for idx, (fp, h, status) in enumerate(results):
                        processed += 1
                        if h:
                            sz = batch[idx][1]  # 从 batch 取 size
                            hash_groups[(sz, h)].append(fp)
                            if status == 'cached':
                                stats['cached_hits'] += 1

                    self.progress.emit(f"完整哈希: {processed}/{total}")
                    del results

            raw_groups = [p for (s, h), p in hash_groups.items() if len(p) > 1]
            stats['full_groups'] = len(raw_groups)
            stats['full_filtered'] = sum(len(p) for p in raw_groups)

            # 区分硬链接组和普通重复组
            dup_groups = []
            hl_groups = []
            for group in raw_groups:
                is_hl, result = self._detect_hardlinks(group)
                if is_hl:
                    hl_groups.append(group)
                else:
                    dup_groups.append(group)

            self.progress.emit(f"扫描完成：{len(dup_groups)} 组重复，{len(hl_groups)} 组硬链接")
            self.result_dup = dup_groups
            self.result_hl = hl_groups
            self.result_stats = stats
            self.is_done = True

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(f"扫描异常: {e}")


# ============================================
# 操作线程（删除/硬链接/归档）
# ============================================

class ActionThread(QThread):
    """通用操作线程"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int, int, str)  # success, failed, message

    def __init__(self, action, files, **kwargs):
        super().__init__()
        self.action = action
        self.files = files
        self.kwargs = kwargs
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self.action == 'delete':
                self._do_delete()
            elif self.action == 'hardlink':
                self._do_hardlink()
            elif self.action == 'archive':
                self._do_archive()
        except Exception as e:
            self.finished.emit(0, 0, f"操作失败: {e}")

    def _do_delete(self):
        ok, fail = 0, 0
        total = len(self.files)
        for i, fp in enumerate(self.files):
            if self._cancelled:
                break
            try:
                if os.path.exists(fp):
                    _clear_readonly(fp)
                    os.remove(fp)
                    ok += 1
                else:
                    fail += 1
            except (OSError, PermissionError):
                fail += 1
            if i % 10 == 0:
                self.progress.emit(f"删除中... {i}/{total}")
        self.finished.emit(ok, fail, f"删除完成：成功 {ok}，跳过 {fail}")

    def _do_hardlink(self):
        source = self.kwargs.get('source')
        if not source:
            self.finished.emit(0, 0, "未指定源文件")
            return
        ok, fail = 0, 0
        source_drive = os.path.splitdrive(source)[0]
        for fp in self.files:
            if self._cancelled:
                break
            try:
                if _is_cloud_synced(fp):
                    fail += 1
                    continue
                if os.path.splitdrive(fp)[0] != source_drive:
                    fail += 1
                    continue
                _clear_readonly(fp)
                os.remove(fp)
                os.link(source, fp)
                ok += 1
            except (OSError, PermissionError):
                fail += 1
        self.finished.emit(ok, fail, f"硬链接替换完成：成功 {ok}，失败 {fail}")

    def _do_archive(self):
        archive_dir = self.kwargs.get('archive_dir', '')
        if not archive_dir:
            self.finished.emit(0, 0, "未选择归档目录")
            return
        import shutil
        date_str = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        subdir = os.path.join(archive_dir, f"duplicate_archive_{date_str}")
        os.makedirs(subdir, exist_ok=True)
        ok, fail = 0, 0
        for fp in self.files:
            if self._cancelled:
                break
            try:
                if not os.path.exists(fp):
                    fail += 1
                    continue
                fn = os.path.basename(fp)
                target = os.path.join(subdir, fn)
                c = 1
                while os.path.exists(target):
                    name, ext = os.path.splitext(fn)
                    target = os.path.join(subdir, f"{name}_{c}{ext}")
                    c += 1
                shutil.move(fp, target)
                ok += 1
            except Exception:
                fail += 1
        self.finished.emit(ok, fail, f"归档完成：成功 {ok}，失败 {fail}，目录: {subdir}")


# ============================================
# 重复文件筛选 Tab
# ============================================

class DuplicateFileTab(QWidget):
    """重复文件筛选 Tab"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.duplicate_groups = []
        self.hardlink_groups = []
        self.scan_thread = None
        self.action_thread = None
        self.path_scan_thread = None  # 路径扫描线程（MFT，得到文件列表）
        self.total_wasted = 0
        # 扫描计时器：每秒刷新已用时间，避免大目录扫描/比对假死（与磁盘分析Tab同步）
        self._elapsed_timer = None
        self._scan_start = 0.0
        # 记录用户上一次选择的排序列（非勾选列），全选后据此恢复排序
        self._last_sort_col = 2
        self._last_sort_order = Qt.SortOrder.AscendingOrder
        # 当前勾选数（增量维护，避免单点切换时全表遍历造成延迟）
        self._checked_count = 0
        # 结果数据与分批加载状态
        self._all_items = []
        self._hl_items = []
        self._displayed_count = 0
        self._load_gen = 0

        self._setup_ui()

    def _update_status(self, msg):
        self.main_window.status_label.setText(msg)

    def _start_elapsed_timer(self):
        """启动扫描计时器：每秒更新状态栏已用时间，避免大目录扫描/比对假死。
        与磁盘分析Tab同步的机制。扫描线程的 progress 信号会覆盖此显示，
        但在无进度心跳的阶段（如单进程MFT、os.walk、哈希批次间隙）计时器兜底。"""
        self._stop_elapsed_timer()
        self._scan_start = time.perf_counter()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._on_elapsed_tick)
        self._elapsed_timer.start(1000)

    def _stop_elapsed_timer(self):
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer.deleteLater()
            self._elapsed_timer = None

    def _on_elapsed_tick(self):
        """计时器每秒触发：显示已用时间（仅在扫描进行中且无新进度时兜底）"""
        if self._scan_start:
            elapsed = time.perf_counter() - self._scan_start
            self._update_status(f"扫描/比对进行中... 已用 {elapsed:.0f}s")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # ---- 控制面板 ----
        ctrl = QHBoxLayout()
        layout.addLayout(ctrl)

        ctrl.addWidget(QLabel("扫描路径:"))
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("添加路径后点扫描，或点导入磁盘分析结果")
        ctrl.addWidget(self.path_input)

        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._browse)
        ctrl.addWidget(browse_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self.path_input.clear())
        ctrl.addWidget(clear_btn)

        # ---- 选项行 ----
        opt_row = QHBoxLayout()
        layout.addLayout(opt_row)

        opt_row.addWidget(QLabel("最小文件大小:"))
        self.min_size_combo = QComboBox()
        self.min_size_combo.addItems(["100 KiB", "1 MiB", "10 MiB", "100 MiB", "1 GiB"])
        self.min_size_combo.setCurrentIndex(1)
        opt_row.addWidget(self.min_size_combo)

        self.include_sub_cb = QCheckBox("包含子目录")
        self.include_sub_cb.setChecked(True)
        opt_row.addWidget(self.include_sub_cb)

        self.use_cache_cb = QCheckBox("使用缓存")
        self.use_cache_cb.setChecked(True)
        opt_row.addWidget(self.use_cache_cb)

        self.skip_cache_cb = QCheckBox("跳过缓存/临时文件")
        self.skip_cache_cb.setChecked(True)
        self.skip_cache_cb.setToolTip("跳过路径中含 cache/temp/tmp/缓存/临时 的文件，不参与哈希比对（加快速度）")
        opt_row.addWidget(self.skip_cache_cb)

        opt_row.addStretch()

        # ---- 按钮行1：开始干活 ----
        btn_row1 = QHBoxLayout()
        layout.addLayout(btn_row1)

        btn_row1.addWidget(QLabel("开始干活:"))

        self.scan_btn = QPushButton("🔍 开始扫描")
        self.scan_btn.setToolTip("扫描指定路径，三级渐进式比对查找重复文件")
        self.scan_btn.clicked.connect(self._start_scan)
        btn_row1.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setToolTip("停止当前扫描或操作")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row1.addWidget(self.stop_btn)

        self.import_btn = QPushButton("📥 导入磁盘分析结果")
        self.import_btn.setToolTip("导入磁盘分析Tab导出的文件列表，跳过目录遍历直接开始比对")
        self.import_btn.clicked.connect(self._import_list)
        btn_row1.addWidget(self.import_btn)

        self.export_btn = QPushButton("📄 导出清单")
        self.export_btn.setToolTip("将重复文件清单导出为JSON文件")
        self.export_btn.setEnabled(False)
        btn_row1.addWidget(self.export_btn)

        btn_row1.addStretch()

        # ---- 按钮行2：保留策略 ----
        btn_row2 = QHBoxLayout()
        layout.addLayout(btn_row2)

        btn_row2.addWidget(QLabel("保留策略:"))

        self.keep_old_btn = QPushButton("⏰ 最早")
        self.keep_old_btn.setToolTip("每组保留创建时间最早的文件，勾选其余文件待删除")
        self.keep_old_btn.clicked.connect(lambda: self._apply_retention('oldest'))
        btn_row2.addWidget(self.keep_old_btn)

        self.keep_new_btn = QPushButton("🆕 最新")
        self.keep_new_btn.setToolTip("每组保留修改时间最新的文件，勾选其余文件待删除")
        self.keep_new_btn.clicked.connect(lambda: self._apply_retention('newest'))
        btn_row2.addWidget(self.keep_new_btn)

        self.keep_short_btn = QPushButton("📁 路径最短")
        self.keep_short_btn.setToolTip("每组保留路径最短的文件，勾选其余文件待删除")
        self.keep_short_btn.clicked.connect(lambda: self._apply_retention('shortest'))
        btn_row2.addWidget(self.keep_short_btn)

        hint = QLabel("（划重点：打勾的才是不要的！）")
        hint.setStyleSheet("color: #cc0000;")
        btn_row2.addWidget(hint)

        btn_row2.addStretch()

        # ---- 按钮行3：文件操作 ----
        btn_row3 = QHBoxLayout()
        layout.addLayout(btn_row3)

        btn_row3.addWidget(QLabel("文件操作:"))

        self.hl_btn = QPushButton("🔗 硬链接替换")
        self.hl_btn.setToolTip("将勾选的文件替换为硬链接（指向未勾选的源文件），需在同一分区")
        self.hl_btn.setEnabled(False)
        self.hl_btn.clicked.connect(self._hardlink_replace)
        btn_row3.addWidget(self.hl_btn)

        self.del_btn = QPushButton("🗑️ 删除选中")
        self.del_btn.setToolTip("直接删除勾选的文件（不可恢复）")
        self.del_btn.setEnabled(False)
        self.del_btn.clicked.connect(self._delete_selected)
        btn_row3.addWidget(self.del_btn)

        self.archive_btn = QPushButton("📦 移动到归档")
        self.archive_btn.setToolTip("将勾选的文件移动到指定归档目录")
        self.archive_btn.setEnabled(False)
        self.archive_btn.clicked.connect(self._archive_selected)
        btn_row3.addWidget(self.archive_btn)

        btn_row3.addStretch()

        # ---- 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ---- 结果区：双树隔离（重复文件 / 硬链接组 各自独立排序，互不混合）----
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        # 重复文件树（可勾选、可操作）
        dup_container = QWidget()
        dup_layout = QVBoxLayout(dup_container)
        dup_layout.setContentsMargins(0, 0, 0, 0)
        dup_layout.setSpacing(2)
        dup_title = QLabel("重复文件（可勾选 → 打勾的是不要的）")
        dup_title.setStyleSheet("font-weight: bold; padding: 2px;")
        dup_layout.addWidget(dup_title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["✓", "组", "文件名", "大小", "修改时间", "路径"])
        # 扁平列表：禁用树形缩进/展开箭头，使列0成为普通列——否则树形 indentation
        # 会占去列0前段，导致居中复选框位置错乱、入侵相邻列、被遮挡渲染不上色。
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setItemsExpandable(False)
        self.tree.setColumnWidth(0, 36)
        self.tree.setColumnWidth(1, 50)
        self.tree.setColumnWidth(2, 250)
        self.tree.setColumnWidth(3, 100)
        self.tree.setColumnWidth(4, 150)
        self.tree.setColumnWidth(5, 400)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        # 勾选列(0)用居中复选框 delegate，替代文本 '☐'/'☑' 模拟
        self.tree.setItemDelegateForColumn(0, CenteredCheckDelegate(self.tree))
        self.tree.setSortingEnabled(True)
        # 初始按文件名(列2)排序，避免勾选列参与排序——勾选不应改变行顺序
        self.tree.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.header().sectionClicked.connect(self._on_header_clicked)
        # 事件过滤器：在Qt处理点击前保存多选状态
        self._pre_click_selection = []
        self.tree.viewport().installEventFilter(self)
        dup_layout.addWidget(self.tree)
        splitter.addWidget(dup_container)

        # 硬链接组树（只读展示，不可勾选）
        hl_container = QWidget()
        hl_layout = QVBoxLayout(hl_container)
        hl_layout.setContentsMargins(0, 0, 0, 0)
        hl_layout.setSpacing(2)
        self.hl_title_label = QLabel("硬链接组（只读，不可操作）")
        self.hl_title_label.setStyleSheet("font-weight: bold; padding: 2px; color: #0066cc;")
        hl_layout.addWidget(self.hl_title_label)
        self.hl_tree = QTreeWidget()
        self.hl_tree.setHeaderLabels(["", "组", "文件名", "大小", "修改时间", "路径"])
        # 同重复文件树：扁平列表，禁用树形缩进
        self.hl_tree.setRootIsDecorated(False)
        self.hl_tree.setIndentation(0)
        self.hl_tree.setItemsExpandable(False)
        self.hl_tree.setColumnWidth(0, 36)
        self.hl_tree.setColumnWidth(1, 50)
        self.hl_tree.setColumnWidth(2, 250)
        self.hl_tree.setColumnWidth(3, 100)
        self.hl_tree.setColumnWidth(4, 150)
        self.hl_tree.setColumnWidth(5, 400)
        self.hl_tree.header().setStretchLastSection(True)
        self.hl_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.hl_tree.setSortingEnabled(True)
        self.hl_tree.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.hl_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.hl_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hl_tree.customContextMenuRequested.connect(self._show_hl_context_menu)
        # 列0 显示 '🔗' 标记，居中
        self.hl_tree.setItemDelegateForColumn(0, CenteredCheckDelegate(self.hl_tree))
        hl_layout.addWidget(self.hl_tree)
        splitter.addWidget(hl_container)

        # 初始比例：重复文件区占大部分，硬链接区较小
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 200])

        # ---- 统计栏 ----
        stats_row = QHBoxLayout()
        layout.addLayout(stats_row)
        self.stats_label = QLabel("")
        stats_row.addWidget(self.stats_label)

    def eventFilter(self, obj, event):
        """在鼠标按下时保存当前多选状态"""
        if obj is self.tree.viewport() and event.type() == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._pre_click_selection = [item for item in self.tree.selectedItems()]
        return super().eventFilter(obj, event)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "选择扫描路径")
        if path:
            current = self.path_input.text().strip()
            if current:
                self.path_input.setText(f"{current}; {path}")
            else:
                self.path_input.setText(path)

    # ---- 导入 ----

    def _import_list(self):
        """导入磁盘分析结果 - 直接打开文件对话框"""
        # 列出所有可用的 JSON 文件
        import glob
        available = glob.glob(os.path.join(EXPORT_DIR, 'disk_scan_*.json'))

        if available:
            # 显示可用文件列表
            names = [os.path.basename(f) for f in sorted(available, key=os.path.getmtime, reverse=True)]
            QMessageBox.information(self, "可用的文件列表",
                f"在 {EXPORT_DIR} 中找到以下文件：\n\n" + "\n".join(names) +
                "\n\n接下来请选择要导入的文件")

        file_path = QFileDialog.getOpenFileName(
            self, "选择磁盘分析导出的文件列表",
            EXPORT_DIR, "JSON文件 (disk_scan_*.json)")[0]

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if 'files' not in data:
                QMessageBox.warning(self, "格式错误", "JSON文件格式不正确")
                return

            file_list = data['files']
            scan_path = data.get('scan_path', '')
            self.path_input.setText(scan_path)

            self._update_status(f"已导入 {len(file_list)} 个文件 ({scan_path})，开始扫描...")

            # 直接开始扫描
            self._start_scan_with_list(file_list)

        except (json.JSONDecodeError, ValueError) as e:
            QMessageBox.critical(self, "导入失败",
                f"JSON 文件损坏（{e}）。\n\n"
                f"该扫描结果可能在上次写入时被中断，请在磁盘分析Tab重新扫描对应盘符后再导入。")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    # ---- 扫描 ----

    def _parse_min_size(self):
        """解析最小文件大小"""
        text = self.min_size_combo.currentText().strip().upper()
        units = [
            ('GIB', 1024**3), ('GB', 1024**3),
            ('MIB', 1024**2), ('MB', 1024**2),
            ('KIB', 1024), ('KB', 1024),
            ('B', 1),
        ]
        for unit, mult in units:
            if text.endswith(unit):
                try:
                    return float(text[:-len(unit)].strip()) * mult
                except ValueError:
                    return 0
        return 0

    def _start_scan(self):
        """从路径开始扫描"""
        paths_text = self.path_input.text().strip()
        if not paths_text:
            QMessageBox.warning(self, "提示", "请先添加扫描路径，或导入磁盘分析结果")
            return

        paths = [p.strip() for p in paths_text.split(';') if p.strip()]
        for p in paths:
            if not os.path.exists(p):
                QMessageBox.warning(self, "提示", f"路径不存在: {p}")
                return

        # 启动扫描计时器（贯穿路径扫描+三级哈希比对全程，与磁盘分析Tab同步）
        self._start_elapsed_timer()

        # 单一路径：根目录走 JSON 缓存复用逻辑（需求5）
        if len(paths) == 1 and _is_root_path(paths[0]):
            self._start_root_scan_with_cache(paths[0])
            return

        # 多路径或非根目录：沿用磁盘分析扫描办法（MFT优先+降级）逐路径扫描
        self._scan_paths_with_mft(paths)

    def _start_root_scan_with_cache(self, root_path):
        """根目录扫描：优先复用1天内生成的JSON，否则MFT扫描并生成新JSON（需求5）"""
        import json
        import time as _time
        export_path = _get_export_path(root_path)
        if os.path.exists(export_path):
            try:
                age_hours = (_time.time() - os.path.getmtime(export_path)) / 3600
                if age_hours <= 24:
                    with open(export_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    file_list = data.get('files', [])
                    self.path_input.setText(data.get('scan_path', root_path))
                    self._update_status(
                        f"复用 {age_hours:.1f} 小时前的扫描结果（{len(file_list)} 个文件），"
                        f"开始重复文件比对..."
                    )
                    self._start_scan_with_list(file_list)
                    return
            except (json.JSONDecodeError, ValueError):
                # JSON 损坏（上次写入被中断留下半截）：删除损坏文件，继续重新扫描
                try:
                    os.remove(export_path)
                except OSError:
                    pass
                self._update_status("扫描结果损坏，已删除，将重新扫描...")
            except Exception:
                pass  # 其他异常也重新扫描

        # JSON 不存在、超过1天或损坏：正常启动 MFT 扫描，完成后自动导出新 JSON 覆盖旧文件
        self._update_status(f"扫描 {root_path}（MFT优先，结果将自动保存）...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._set_buttons(False)

        self.path_scan_thread = PathScanThread(root_path, auto_export=True)
        self.path_scan_thread.progress.connect(self._on_path_scan_progress)
        self.path_scan_thread.finished.connect(self._on_path_scan_finished)
        self.path_scan_thread.error.connect(self._on_path_scan_error)
        self.path_scan_thread.start()

    def _scan_paths_with_mft(self, paths):
        """非根目录：用MFT/普通扫描收集文件列表（沿用磁盘分析扫描办法，需求4）"""
        self._update_status("正在扫描文件列表（MFT优先）...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._set_buttons(False)
        self._pending_paths = list(paths)
        self._collected_files = []
        self._scan_next_path()

    def _scan_next_path(self):
        """扫描下一个待处理路径（多路径时逐个扫描合并）"""
        if not self._pending_paths:
            # 全部路径扫描完，合并文件列表
            file_list = self._collected_files
            self._collected_files = []
            if not file_list:
                self._update_status("未找到文件")
                self.progress_bar.setVisible(False)
                self._set_buttons(True)
                self._stop_elapsed_timer()
                return
            self._start_scan_with_list(file_list)
            return

        path = self._pending_paths.pop(0)
        self.path_scan_thread = PathScanThread(path, auto_export=False)
        self.path_scan_thread.progress.connect(self._on_path_scan_progress)
        self.path_scan_thread.finished.connect(
            lambda fl, p=path: self._on_multi_path_scan_finished(fl, p))
        self.path_scan_thread.error.connect(self._on_path_scan_error)
        self.path_scan_thread.start()

    def _on_multi_path_scan_finished(self, file_list, path):
        """单个路径扫描完成（多路径模式）"""
        thread = self.path_scan_thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self.path_scan_thread = None
        # 取消则停止多路径扫描
        if file_list and not (thread is not None and getattr(thread, '_cancelled', False)):
            self._collected_files.extend(file_list)
        if thread is not None and getattr(thread, '_cancelled', False):
            self._collected_files = []
            self.progress_bar.setVisible(False)
            self._set_buttons(True)
            self._stop_elapsed_timer()
            self._update_status("扫描已取消")
            return
        self._update_status(f"已扫描 {path}：{len(file_list)} 个文件，继续下一路径...")
        self._scan_next_path()

    def _on_path_scan_progress(self, msg, count):
        self._update_status(msg)

    def _on_path_scan_finished(self, file_list):
        """根目录扫描完成（含自动导出JSON）"""
        # 识别取消：取消时 emit 空列表，显示"已取消"而非"未找到文件"
        thread = self.path_scan_thread
        if thread is not None and getattr(thread, '_cancelled', False):
            if thread is not None:
                thread.wait()
                thread.deleteLater()
            self.path_scan_thread = None
            self.progress_bar.setVisible(False)
            self._set_buttons(True)
            self._stop_elapsed_timer()
            self._update_status("扫描已取消")
            return
        if not file_list:
            self._update_status("未找到文件")
            self.progress_bar.setVisible(False)
            self._set_buttons(True)
            self._stop_elapsed_timer()
            return
        # 正常完成：释放扫描线程引用
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self.path_scan_thread = None
        self._update_status(f"扫描完成：{len(file_list)} 个文件，开始重复文件比对...")
        self._start_scan_with_list(file_list)  # 计时器继续，贯穿比对阶段

    def _on_path_scan_error(self, msg):
        if self.path_scan_thread is not None:
            self.path_scan_thread.wait()
            self.path_scan_thread.deleteLater()
            self.path_scan_thread = None
        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        self._stop_elapsed_timer()
        QMessageBox.critical(self, "扫描出错", msg)

    def _start_scan_with_list(self, file_list):
        """用给定的文件列表开始扫描"""
        # 递增加载代际：使上一轮未完成的分批加载回调立即失效，
        # 避免扫描重置后旧 singleShot 仍往树里写入过期数据（数据错乱/崩溃）。
        self._load_gen = getattr(self, '_load_gen', 0) + 1
        self.tree.clear()
        self.hl_tree.clear()
        self.duplicate_groups = []
        self.hardlink_groups = []
        self._checked_count = 0
        self._set_buttons(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        # 若计时器未启动（如导入JSON路径），在此启动，贯穿比对全程
        if self._elapsed_timer is None:
            self._start_elapsed_timer()

        # 最小文件大小筛选：无论从路径扫描还是导入磁盘分析结果，都统一在此生效
        # （之前 _import_list 直接用导入的列表，绕过了该筛选）。
        min_size = self._parse_min_size()
        if min_size > 0:
            before = len(file_list)
            file_list = [f for f in file_list if f.get('size', 0) >= min_size]
            filtered = before - len(file_list)
            if filtered > 0:
                self._update_status(f"最小文件大小筛选：{before} → {len(file_list)}（过滤 {filtered} 个）")

        # 跳过 cache/temp 相关文件：不参与哈希比对，加快效率
        # 规则与缓存清理Tab _is_cache_like 一致（路径各级目录名含 cache/temp/tmp/缓存/临时）
        self._skipped_cache = 0
        if self.skip_cache_cb.isChecked():
            before = len(file_list)
            file_list = [f for f in file_list if not _path_in_cache_dir(f.get('path', ''))]
            self._skipped_cache = before - len(file_list)
            if self._skipped_cache > 0:
                self._update_status(f"跳过缓存/临时文件：{self._skipped_cache} 个，剩余 {len(file_list)} 个参与比对")

        if not file_list:
            self._update_status("筛选后无文件可扫描")
            self.progress_bar.setVisible(False)
            self._set_buttons(True)
            self._stop_elapsed_timer()
            return

        self._update_status(f"开始扫描 ({len(file_list)} 个文件)...")

        self.scan_thread = DuplicateScanThread(file_list, use_cache=self.use_cache_cb.isChecked())
        self.scan_thread.progress.connect(self._update_status)
        self.scan_thread.error.connect(self._on_scan_error)
        self.scan_thread.start()

        # 用 QTimer 轮询线程完成状态（避免 finished 信号竞态导致崩溃）
        # 复用同一 timer，避免重复扫描时旧 timer 对象被回收引发 use-after-free
        if not getattr(self, '_poll_timer', None):
            self._poll_timer = QTimer()
            self._poll_timer.timeout.connect(self._check_scan_done)
        self._poll_timer.start(500)

    def _check_scan_done(self):
        """轮询检查扫描线程是否完成"""
        if not self.scan_thread:
            return
        if self.scan_thread.is_done:
            self._poll_timer.stop()
            self._on_scan_finished()
        elif self.scan_thread._cancelled:
            # 用户取消：线程退出后正常收尾，不当作错误
            self._poll_timer.stop()
            self._on_scan_cancelled()
        elif not self.scan_thread.isRunning():
            self._poll_timer.stop()
            if not self.scan_thread.is_done:
                self._on_scan_error("扫描线程异常退出")

    def _on_scan_cancelled(self):
        """用户取消扫描后的收尾（非错误）"""
        thread = self.scan_thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self.scan_thread = None
        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        self._stop_elapsed_timer()
        self._update_status("扫描已取消")

    def _on_scan_finished(self):
        thread = self.scan_thread
        if thread is None:
            return
        dup_groups = thread.result_dup
        hl_groups = thread.result_hl
        stats = thread.result_stats

        # ⚠️ 安全释放扫描线程：必须先 wait() 确保底层 C++ 线程完全退出
        # （run() 返回 + finished 信号 + 线程清理完成），再让 Qt 延迟销毁对象。
        # 之前直接 `self.scan_thread = None` 会立即触发 Python 析构 QThread，
        # 若此时 C++ 线程尚未完全退出（run() 刚返回，finished 信号/线程清理
        # 仍在进行），Qt 会 abort："QThread: Destroyed while thread is still
        # running"，表现为「扫描完成→结果列表加载前闪退」（文件越多越易触发）。
        thread.wait()
        thread.deleteLater()
        self.scan_thread = None
        del thread  # 尽早释放 QThread 持有的 file_list/cache_manager，降低大目录内存峰值

        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        self._stop_elapsed_timer()  # 比对完成，停止计时器
        self.duplicate_groups = dup_groups
        self.hardlink_groups = hl_groups

        # 计算浪费空间
        self.total_wasted = 0
        for g in dup_groups:
            if g:
                try:
                    sz = os.path.getsize(g[0])
                    self.total_wasted += sz * (len(g) - 1)
                except OSError:
                    pass

        # 准备所有数据项（不直接插入树）
        # 重复文件项与硬链接项分离：分别加载到两棵独立的树，各自排序、互不混合。
        # 大目录重复组多时，构建数据项可能数秒，分阶段反馈避免假死（与磁盘分析Tab同步）。
        QApplication.processEvents()
        self._update_status(f"正在构建结果数据（{len(dup_groups)} 组重复 + {len(hl_groups)} 组硬链接）...")
        self._all_items = []
        self._hl_items = []
        for idx, group in enumerate(dup_groups, 1):
            try:
                file_size = os.path.getsize(group[0])
            except OSError:
                file_size = 0
            for fp in group:
                fn = os.path.basename(fp)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M:%S')
                except (OSError, OverflowError, ValueError):
                    mtime = ""
                self._all_items.append({
                    'values': ['', f"#{idx}", fn, _format_size(file_size), mtime, fp],
                    'data': {'group': idx, 'path': fp, 'size': file_size},
                    'type': 'duplicate', 'checked': False
                })

        # 硬链接组（单独加载到硬链接树）
        for idx, group in enumerate(hl_groups, 1):
            try:
                file_size = os.path.getsize(group[0])
            except OSError:
                file_size = 0
            for fp in group:
                fn = os.path.basename(fp)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M:%S')
                except (OSError, OverflowError, ValueError):
                    mtime = ""
                self._hl_items.append({
                    'values': ['🔗', f"H#{idx}", fn, _format_size(file_size), mtime, fp],
                    'data': None, 'type': 'hardlink'
                })

        self._update_status(f"数据构建完成，正在加载结果列表（{len(self._all_items)} 项）...")
        QApplication.processEvents()
        # 分页显示：重复文件树先加载前500条
        self._displayed_count = 0
        self._load_more_items(500)
        # 硬链接树一次性加载（通常较少）
        self._load_hl_items()

        # 硬链接标题显示数量
        self.hl_title_label.setText(
            f"硬链接组（只读，不可操作）— {len(hl_groups)} 组 / {len(self._hl_items)} 个文件"
            if hl_groups else "硬链接组（无）"
        )

        # 统计
        skipped_cache = getattr(self, '_skipped_cache', 0)
        skip_info = f" | 跳过缓存/临时: {skipped_cache}" if skipped_cache else ""
        filter_info = (
            f"过滤: {stats['total_files']}→"
            f"{stats['size_filtered']}(大小)→"
            f"{stats['sample_filtered']}(采样)→"
            f"{stats['full_filtered']}(确认)"
        )
        self.stats_label.setText(
            f"重复组: {len(dup_groups)} | "
            f"可释放: {_format_size(self.total_wasted)} | "
            f"缓存命中: {stats['cached_hits']}{skip_info}\n{filter_info}"
        )
        self._update_status(f"扫描完成 - {len(dup_groups)} 组重复，可释放 {_format_size(self.total_wasted)}")
        self._enable_result_buttons(True)

    def _load_more_items(self, count=500, gen=None):
        """分批加载重复文件结果到 self.tree"""
        if gen is None:
            gen = getattr(self, '_load_gen', 0)
        # 已被新一轮扫描取代（_load_gen 递增）→ 停止加载旧数据
        if gen != getattr(self, '_load_gen', 0):
            return
        remaining = self._all_items[self._displayed_count:]
        batch = remaining[:count]

        if not batch:
            return
        # 加载期间关闭排序：setSortingEnabled(True) 时逐条 addTopLevelItem 会触发
        # 全模型排序（O(n²)）并使视图持久索引与模型失同步 → 访问已释放 item 段错误。
        # 全部加载完再统一开排序。
        self.tree.setSortingEnabled(False)
        self.tree.setUpdatesEnabled(False)
        for item_data in batch:
            # 仅 duplicate 类型（硬链接已分离到独立树）
            item = QTreeWidgetItem(item_data['values'])
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                0, Qt.CheckState.Checked if item_data.get('checked') else Qt.CheckState.Unchecked
            )
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, item_data['data'])
            self.tree.addTopLevelItem(item)
        self.tree.setUpdatesEnabled(True)
        self._displayed_count += len(batch)

        if self._displayed_count >= len(self._all_items):
            self.tree.setSortingEnabled(True)  # 全部加载完再开排序

        if self._displayed_count < len(self._all_items):
            self._update_status(f"已显示 {self._displayed_count}/{len(self._all_items)}，双击底部加载更多")
            # 延迟加载剩余项（携带当前加载代际，新一轮扫描后回调自动失效）
            QTimer.singleShot(100, lambda: self._load_more_items(500, gen))
        else:
            self._update_status(f"全部 {len(self._all_items)} 条结果已加载")

    def _load_hl_items(self):
        """一次性加载硬链接组到独立的 self.hl_tree（通常数量较少）。
        与重复文件树隔离，各自独立排序、互不混合。"""
        self.hl_tree.clear()
        if not self._hl_items:
            return
        self.hl_tree.setSortingEnabled(False)
        self.hl_tree.setUpdatesEnabled(False)
        for item_data in self._hl_items:
            item = QTreeWidgetItem(item_data['values'])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
            item.setForeground(2, QColor(0, 102, 204))
            self.hl_tree.addTopLevelItem(item)
        self.hl_tree.setUpdatesEnabled(True)
        self.hl_tree.setSortingEnabled(True)
        self.hl_tree.sortByColumn(2, Qt.SortOrder.AscendingOrder)

    def _on_scan_error(self, msg):
        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        self._stop_elapsed_timer()
        QMessageBox.critical(self, "扫描出错", msg)

    # ---- 复选框 ----

    def _on_header_clicked(self, col):
        if col == 0:
            self._toggle_all_checks()
        else:
            # 记录用户选择的排序列（非勾选列），供全选后恢复
            self._last_sort_col = col
            self._last_sort_order = self.tree.header().sortIndicatorOrder()

    def _toggle_all_checks(self):
        """点勾选列表头：全选/全不选所有可勾选项（重复文件）。"""
        n = self.tree.topLevelItemCount()
        if n == 0:
            return
        # 取第一个可勾选项的当前状态，取反作为目标
        first_state = None
        for i in range(n):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole + 1):
                first_state = it.checkState(0)
                break
        if first_state is None:
            return
        new_state = (Qt.CheckState.Unchecked
                     if first_state == Qt.CheckState.Checked
                     else Qt.CheckState.Checked)
        # 批量更新：关闭排序/绘制/信号，避免万次 setCheckState 触发逐条
        # 重绘与按勾选列重排造成的数秒延迟。
        self.tree.setSortingEnabled(False)
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        for i in range(n):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole + 1):
                it.setCheckState(0, new_state)
        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)
        # 恢复到全选前的排序列（避免按勾选状态排序打乱顺序）
        self.tree.sortByColumn(self._last_sort_col, self._last_sort_order)
        self.tree.setSortingEnabled(True)
        self._update_check_status()

    def _on_item_clicked(self, item, col):
        if col != 0:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not data:
            # 硬链接组/分隔行不可勾选（无 CheckStateRole）
            return
        # 自行控制切换（不依赖 ItemIsUserCheckable 的自动切换时序）
        old_state = item.checkState(0)
        new_state = (Qt.CheckState.Checked
                     if old_state == Qt.CheckState.Unchecked
                     else Qt.CheckState.Unchecked)
        item.setCheckState(0, new_state)
        pre_selected = getattr(self, '_pre_click_selection', [])
        if len(pre_selected) > 1 and item in pre_selected:
            # 多选：把其他选中项同步为相同状态，之后全遍历校准计数
            self.tree.setUpdatesEnabled(False)
            self.tree.blockSignals(True)
            for sel in pre_selected:
                if sel is item:
                    continue
                if sel.data(0, Qt.ItemDataRole.UserRole + 1):
                    sel.setCheckState(0, new_state)
            self.tree.blockSignals(False)
            self.tree.setUpdatesEnabled(True)
            self._update_check_status()
        else:
            # 单选：增量更新计数（避免全表遍历），即时反馈
            self._checked_count = max(0, self._checked_count + (1 if new_state == Qt.CheckState.Checked else -1))
            self._update_status(
                f"已勾选 {self._checked_count} 个文件待处理" if self._checked_count else "就绪"
            )

    def _update_check_status(self):
        """全遍历校准勾选计数并显示（批量操作后调用）。"""
        n = 0
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if (it.data(0, Qt.ItemDataRole.UserRole + 1)
                    and it.checkState(0) == Qt.CheckState.Checked):
                n += 1
        self._checked_count = n
        self._update_status(f"已勾选 {n} 个文件待处理" if n else "就绪")

    # ---- 保留策略 ----

    def _apply_retention(self, policy):
        if not self.duplicate_groups:
            QMessageBox.warning(self, "提示", "没有扫描结果")
            return

        # 清空所有勾选 + 建立路径→item 映射（一次遍历）
        path_to_item = {}
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if data:
                item.setCheckState(0, Qt.CheckState.Unchecked)
                path_to_item[data['path']] = item
        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)

        kept = 0
        checked = 0
        # 计算各组要勾选的文件，再批量 setCheckState
        to_check = []
        for group in self.duplicate_groups:
            if not group:
                continue
            if policy == 'oldest':
                def key(fp):
                    try:
                        return os.path.getctime(fp)
                    except OSError:
                        return float('inf')
                keep = min(group, key=key)
            elif policy == 'newest':
                def key(fp):
                    try:
                        return os.path.getmtime(fp)
                    except OSError:
                        return 0
                keep = max(group, key=key)
            else:  # shortest
                keep = min(group, key=len)

            kept += 1
            for fp in group:
                if fp != keep and fp in path_to_item:
                    to_check.append(path_to_item[fp])
                    checked += 1

        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        for item in to_check:
            item.setCheckState(0, Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)

        self._update_status(f"保留策略完成：保留 {kept} 个，勾选 {checked} 个待删除")

    # ---- 右键菜单 ----

    def _show_context_menu(self, position):
        """重复文件树右键菜单"""
        item = self.tree.itemAt(position)
        if not item or not item.data(0, Qt.ItemDataRole.UserRole + 1):
            return

        menu = QMenu(self)
        open_act = QAction("在资源管理器中打开", self)
        open_act.triggered.connect(lambda: self._open_in_explorer(item))
        menu.addAction(open_act)

        copy_act = QAction("复制路径", self)
        copy_act.triggered.connect(lambda: QApplication.clipboard().setText(item.text(5)))
        menu.addAction(copy_act)

        menu.addSeparator()
        del_act = QAction("移动到回收站", self)
        del_act.triggered.connect(lambda: self._recycle_single(item))
        menu.addAction(del_act)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _show_hl_context_menu(self, position):
        """硬链接树右键菜单（只读：打开/复制，不可删除）"""
        item = self.hl_tree.itemAt(position)
        if not item:
            return

        menu = QMenu(self)
        open_act = QAction("在资源管理器中打开", self)
        open_act.triggered.connect(lambda: self._open_in_explorer(item))
        menu.addAction(open_act)

        copy_act = QAction("复制路径", self)
        copy_act.triggered.connect(lambda: QApplication.clipboard().setText(item.text(5)))
        menu.addAction(copy_act)

        menu.exec(self.hl_tree.viewport().mapToGlobal(position))

    def _open_in_explorer(self, item):
        fp = item.text(5)
        if os.path.exists(fp):
            import subprocess
            subprocess.run(f'explorer /select,"{fp}"', shell=True)

    def _recycle_single(self, item):
        fp = item.text(5)
        try:
            import send2trash
            send2trash.send2trash(fp)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
            self._update_status(f"已移到回收站: {os.path.basename(fp)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    # ---- 批量操作 ----

    def _get_checked_files(self):
        """获取所有勾选的文件"""
        files = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                data = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if data:
                    files.append(data['path'])
        return files

    def _delete_selected(self):
        files = self._get_checked_files()
        if not files:
            QMessageBox.warning(self, "提示", "请先勾选要删除的文件")
            return

        reply = QMessageBox.question(self, "确认删除",
            f"确定删除 {len(files)} 个文件？\n\n文件将直接删除（不进回收站）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._run_action('delete', files)

    def _hardlink_replace(self):
        files = self._get_checked_files()
        if not files:
            QMessageBox.warning(self, "提示", "请先勾选要替换的文件")
            return

        # 找到源文件（未勾选的同组文件）
        checked_set = set(files)
        sources = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Unchecked:
                data = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if data:
                    sources[data['group']] = data['path']

        if not sources:
            QMessageBox.warning(self, "提示", "每组需要保留至少一个文件（不勾选）作为源")
            return

        reply = QMessageBox.question(self, "确认硬链接替换",
            f"将 {len(files)} 个文件替换为硬链接\n\n注意：必须在同一分区",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 按组分组执行
        source = list(sources.values())[0]
        self._run_action('hardlink', files, source=source)

    def _archive_selected(self):
        files = self._get_checked_files()
        if not files:
            QMessageBox.warning(self, "提示", "请先勾选要归档的文件")
            return

        archive_dir = QFileDialog.getExistingDirectory(self, "选择归档目录")
        if not archive_dir:
            return

        self._run_action('archive', files, archive_dir=archive_dir)

    def _run_action(self, action, files, **kwargs):
        self._set_buttons(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        start = time.time()

        self.action_thread = ActionThread(action, files, **kwargs)
        self.action_thread.progress.connect(self._update_status)

        def on_finished(ok, fail, msg):
            elapsed = time.time() - start
            self.progress_bar.setVisible(False)
            self._set_buttons(True)
            full_msg = f"{msg}\n用时: {elapsed:.1f} 秒"
            self._update_status(full_msg)
            # 安全释放操作线程（同扫描线程：wait() 等 C++ 线程退出，再延迟删除）
            if self.action_thread is not None:
                self.action_thread.wait()
                self.action_thread.deleteLater()
                self.action_thread = None
            QMessageBox.information(self, "操作完成", full_msg)
            # 刷新列表
            self._refresh_tree()

        self.action_thread.finished.connect(on_finished)
        self.action_thread.start()

    def _refresh_tree(self):
        """刷新结果列表（移除已删除的文件）"""
        new_groups = []
        for group in self.duplicate_groups:
            existing = [f for f in group if os.path.exists(f)]
            if len(existing) >= 2:
                new_groups.append(existing)
        self.duplicate_groups = new_groups
        self._checked_count = 0  # 重建后归零

        self.total_wasted = 0
        for g in new_groups:
            try:
                self.total_wasted += os.path.getsize(g[0]) * (len(g) - 1)
            except OSError:
                pass

        if not new_groups:
            self.tree.clear()
            self.stats_label.setText("无重复文件")
            self._update_status("所有重复文件已处理完成")
            self._enable_result_buttons(False)
        else:
            # 重新显示
            self.tree.clear()
            # 批量插入期间关闭排序，避免逐条 addTopLevelItem 触发 O(n²) 排序与索引失同步
            self.tree.setSortingEnabled(False)
            self.tree.setUpdatesEnabled(False)
            for idx, group in enumerate(new_groups, 1):
                try:
                    file_size = os.path.getsize(group[0])
                except OSError:
                    file_size = 0
                for fp in group:
                    fn = os.path.basename(fp)
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M:%S')
                    except (OSError, OverflowError, ValueError):
                        mtime = ""
                    item = QTreeWidgetItem(['', f"#{idx}", fn, _format_size(file_size), mtime, fp])
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    )
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, {'group': idx, 'path': fp, 'size': file_size})
                    self.tree.addTopLevelItem(item)
            self.tree.setUpdatesEnabled(True)
            self.tree.sortByColumn(self._last_sort_col, self._last_sort_order)
            self.tree.setSortingEnabled(True)

            self.stats_label.setText(f"剩余 {len(new_groups)} 组，可释放 {_format_size(self.total_wasted)}")
            self._update_status(f"刷新完成，剩余 {len(new_groups)} 组")

    def _stop(self):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.cancel()
        if self.path_scan_thread and self.path_scan_thread.isRunning():
            self.path_scan_thread.cancel()
        if self.action_thread and self.action_thread.isRunning():
            self.action_thread.cancel()
        self._update_status("正在停止...")

    def _set_buttons(self, enabled):
        self.scan_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(not enabled)
        self.import_btn.setEnabled(enabled)

    def _enable_result_buttons(self, enabled):
        self.hl_btn.setEnabled(enabled)
        self.del_btn.setEnabled(enabled)
        self.archive_btn.setEnabled(enabled)

    def cleanup(self):
        # 作废所有未完成的分批加载回调，避免关闭后 singleShot 仍访问已销毁的 tree
        self._load_gen = getattr(self, '_load_gen', 0) + 1
        self._stop_elapsed_timer()
        timer = getattr(self, '_poll_timer', None)
        if timer is not None:
            timer.stop()
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.cancel()
            self.scan_thread.wait(3000)
        if self.path_scan_thread and self.path_scan_thread.isRunning():
            self.path_scan_thread.cancel()
            self.path_scan_thread.wait(3000)
        if self.action_thread and self.action_thread.isRunning():
            self.action_thread.cancel()
            self.action_thread.wait(3000)
