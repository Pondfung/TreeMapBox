#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存清理 Tab - PyQt6 版本

扫描和清理系统缓存、临时文件、浏览器缓存、开发工具缓存等。
从通用系统清理工具的 cache_cleaner.py 移植，重写 UI 为 PyQt6。
"""

import os
import time
from datetime import datetime
from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QProgressBar,
    QMenu, QMessageBox, QApplication, QAbstractItemView, QHeaderView,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QStyleOptionButton,
    QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QSize
from PyQt6.QtGui import QColor, QAction

from utils.common import is_cache_like


class CenteredCheckDelegate(QStyledItemDelegate):
    """在第 0 列居中绘制原生复选框（CheckStateRole）。

    用 QStyleOptionButton + drawControl(CE_CheckBox)——后者在所有 style 下都能
    正确画出对勾（PE_IndicatorCheckBox 在 fusion 下不画对勾）。
    index.data(CheckStateRole) 在 PyQt6 返回 int，需用 Qt.CheckState.X.value（int）
    比较，与枚举直接比较恒 False 会导致复选框不画对勾。
    """

    def paint(self, painter, option, index):
        if index.column() != 0:
            super().paint(painter, option, index)
            return
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is None:
            super().paint(painter, option, index)
            return
        style = option.widget.style() if option.widget is not None else QApplication.style()
        iw = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, option.widget)
        ih = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, None, option.widget)
        opt = QStyleOptionButton()
        opt.rect = QRect(
            option.rect.center().x() - iw // 2,
            option.rect.center().y() - ih // 2,
            iw, ih,
        )
        opt.state = QStyle.StateFlag.State_Enabled
        sval = state if isinstance(state, int) else int(getattr(state, 'value', 0))
        if sval == Qt.CheckState.Checked.value:
            opt.state |= QStyle.StateFlag.State_On
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


class CenterTextDelegate(QStyledItemDelegate):
    """文本列居中显示的 Delegate"""
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignmentFlag.AlignCenter


# ============================================
# 逻辑类（从源项目复用，无 GUI 依赖）
# ============================================

class SafetyLevel:
    SAFE = 'safe'
    CAUTION = 'caution'
    DANGER = 'danger'

    @staticmethod
    def get_level_from_date(file_date, current_date=None):
        if current_date is None:
            current_date = datetime.now()
        age_days = (current_date - file_date).days
        if age_days >= 365:
            return SafetyLevel.SAFE
        elif age_days >= 180:
            return SafetyLevel.CAUTION
        return SafetyLevel.DANGER


class Category:
    SYSTEM = '系统文件'
    BROWSER = '浏览器缓存'
    DEVELOPER = '开发工具'
    MULTIMEDIA = '多媒体'
    GAME = '游戏平台'
    GPU = '显卡驱动'
    VIRTUALIZATION = '虚拟化'
    CLOUD = '云存储'
    OTHER = '其他'


def _setup_cache_paths():
    """初始化缓存路径注册表（9大类 50+ 个路径）"""
    temp = os.environ.get('TEMP', '')
    local = os.environ.get('LOCALAPPDATA', '')
    appdata = os.environ.get('APPDATA', '')
    programdata = os.environ.get('PROGRAMDATA', '')
    user = os.environ.get('USERPROFILE', '')
    win = os.environ.get('WINDIR', 'C:\\Windows')

    paths = {}

    # 系统文件
    paths.update({
        'Windows_Temp_User': {'path': temp, 'description': '用户临时文件夹', 'category': Category.SYSTEM, 'safety': SafetyLevel.SAFE},
        'Windows_Temp_System': {'path': os.path.join(win, 'Temp'), 'description': '系统临时文件夹', 'category': Category.SYSTEM, 'safety': SafetyLevel.SAFE},
        'Windows_Prefetch': {'path': os.path.join(win, 'Prefetch'), 'description': '系统预读取文件', 'category': Category.SYSTEM, 'safety': SafetyLevel.CAUTION},
        'Windows_CrashDump': {'path': os.path.join(win, 'Minidump'), 'description': 'Windows崩溃转储', 'category': Category.SYSTEM, 'safety': SafetyLevel.CAUTION},
        'Windows_Logs': {'path': os.path.join(win, 'Logs'), 'description': 'Windows日志', 'category': Category.SYSTEM, 'safety': SafetyLevel.CAUTION},
        'Windows_Update_Cache': {'path': os.path.join(win, 'SoftwareDistribution', 'Download'), 'description': 'Windows更新缓存', 'category': Category.SYSTEM, 'safety': SafetyLevel.CAUTION},
        'Thumbnail_Cache': {'path': os.path.join(local, 'Microsoft', 'Windows', 'Explorer'), 'description': '缩略图缓存', 'category': Category.SYSTEM, 'safety': SafetyLevel.CAUTION},
        'Windows_Installer': {'path': os.path.join(win, 'Installer'), 'description': 'Windows安装缓存', 'category': Category.SYSTEM, 'safety': SafetyLevel.CAUTION},
    })

    # 浏览器缓存
    paths.update({
        'Chrome_Cache': {'path': os.path.join(local, 'Google', 'Chrome', 'User Data', 'Default', 'Cache'), 'description': 'Chrome缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Chrome_Code_Cache': {'path': os.path.join(local, 'Google', 'Chrome', 'User Data', 'Default', 'Code Cache'), 'description': 'Chrome代码缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Chrome_GPUCache': {'path': os.path.join(local, 'Google', 'Chrome', 'User Data', 'Default', 'GPUCache'), 'description': 'Chrome GPU缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Edge_Cache': {'path': os.path.join(local, 'Microsoft', 'Edge', 'User Data', 'Default', 'Cache'), 'description': 'Edge缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Edge_Code_Cache': {'path': os.path.join(local, 'Microsoft', 'Edge', 'User Data', 'Default', 'Code Cache'), 'description': 'Edge代码缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Firefox_Cache': {'path': os.path.join(local, 'Mozilla', 'Firefox', 'Profiles'), 'description': 'Firefox缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Brave_Cache': {'path': os.path.join(local, 'BraveSoftware', 'Brave-Browser', 'User Data', 'Default', 'Cache'), 'description': 'Brave缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
        'Opera_Cache': {'path': os.path.join(appdata, 'Opera Software', 'Opera Stable', 'Cache'), 'description': 'Opera缓存', 'category': Category.BROWSER, 'safety': SafetyLevel.SAFE},
    })

    # 开发工具
    paths.update({
        'npm_Cache': {'path': os.path.join(appdata, 'npm-cache'), 'description': 'npm缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'yarn_Cache': {'path': os.path.join(local, 'Yarn', 'Cache'), 'description': 'Yarn缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'pip_Cache': {'path': os.path.join(local, 'pip', 'Cache'), 'description': 'pip缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'Conda_Cache': {'path': os.path.join(user, '.conda', 'pkgs'), 'description': 'Conda包缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'NuGet_Cache': {'path': os.path.join(user, '.nuget', 'packages'), 'description': 'NuGet缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'Gradle_Cache': {'path': os.path.join(user, '.gradle', 'caches'), 'description': 'Gradle缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'Cargo_Registry': {'path': os.path.join(user, '.cargo', 'registry'), 'description': 'Cargo注册表缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'Maven_Cache': {'path': os.path.join(user, '.m2', 'repository'), 'description': 'Maven仓库缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.CAUTION},
        'Go_Mod_Cache': {'path': os.path.join(user, 'go', 'pkg', 'mod'), 'description': 'Go模块缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'VS_Code_Cache': {'path': os.path.join(appdata, 'Code', 'Cache'), 'description': 'VS Code缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'VS_Code_CPP': {'path': os.path.join(appdata, 'Code', 'CachedData'), 'description': 'VS Code缓存数据', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'VS_Component_Cache': {'path': os.path.join(local, 'Microsoft', 'VisualStudio'), 'description': 'VS组件缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'JetBrains_Cache': {'path': os.path.join(local, 'JetBrains'), 'description': 'JetBrains缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.CAUTION},
        'PyCharm_Cache': {'path': os.path.join(local, 'JetBrains', 'PyCharm'), 'description': 'PyCharm缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
        'IntelliJIdea_Cache': {'path': os.path.join(local, 'JetBrains', 'IntelliJIdea'), 'description': 'IntelliJ IDEA缓存', 'category': Category.DEVELOPER, 'safety': SafetyLevel.SAFE},
    })

    # 游戏平台
    paths.update({
        'Steam_Download': {'path': os.path.join(programdata, 'Steam', 'steamapps', 'downloading'), 'description': 'Steam下载缓存', 'category': Category.GAME, 'safety': SafetyLevel.CAUTION},
        'Steam_Depot': {'path': os.path.join(programdata, 'Steam', 'depotcache'), 'description': 'Steam仓库缓存', 'category': Category.GAME, 'safety': SafetyLevel.CAUTION},
        'Epic_Cache': {'path': os.path.join(local, 'EpicGamesLauncher', 'Saved', 'webcache'), 'description': 'Epic缓存', 'category': Category.GAME, 'safety': SafetyLevel.SAFE},
        'GOG_Galaxy_Cache': {'path': os.path.join(programdata, 'GOG.com', 'Galaxy'), 'description': 'GOG Galaxy缓存', 'category': Category.GAME, 'safety': SafetyLevel.SAFE},
        'Xbox_Cache': {'path': os.path.join(local, 'Packages', 'Microsoft.XboxApp_8wekyb3d8bbwe', 'LocalCache'), 'description': 'Xbox缓存', 'category': Category.GAME, 'safety': SafetyLevel.SAFE},
        'Origin_Cache': {'path': os.path.join(programdata, 'Origin', 'DownloadCache'), 'description': 'Origin缓存', 'category': Category.GAME, 'safety': SafetyLevel.SAFE},
        'Uplay_Cache': {'path': os.path.join(local, 'Ubisoft Game Launcher', 'cache'), 'description': 'Uplay缓存', 'category': Category.GAME, 'safety': SafetyLevel.SAFE},
    })

    # 多媒体
    paths.update({
        'Adobe_Media_Cache': {'path': os.path.join(appdata, 'Adobe', 'Common', 'Media Cache Files'), 'description': 'Adobe媒体缓存', 'category': Category.MULTIMEDIA, 'safety': SafetyLevel.SAFE},
        'Adobe_Peak': {'path': os.path.join(appdata, 'Adobe', 'Common', 'Media Cache'), 'description': 'Adobe Peak缓存', 'category': Category.MULTIMEDIA, 'safety': SafetyLevel.SAFE},
        'Spotify_Cache': {'path': os.path.join(appdata, 'Spotify', 'Storage'), 'description': 'Spotify缓存', 'category': Category.MULTIMEDIA, 'safety': SafetyLevel.SAFE},
    })

    # 显卡驱动
    paths.update({
        'NVIDIA_DXCache': {'path': os.path.join(local, 'NVIDIA', 'DXCache'), 'description': 'NVIDIA DXCache', 'category': Category.GPU, 'safety': None},
        'NVIDIA_GLCache': {'path': os.path.join(local, 'NVIDIA', 'GLCache'), 'description': 'NVIDIA GLCache', 'category': Category.GPU, 'safety': None},
        'NVIDIA_OptixCache': {'path': os.path.join(local, 'NVIDIA', 'OptixCache'), 'description': 'NVIDIA OptixCache', 'category': Category.GPU, 'safety': SafetyLevel.SAFE},
        'NVIDIA_Logs': {'path': os.path.join(programdata, 'NVIDIA Corporation'), 'description': 'NVIDIA配置和日志', 'category': Category.GPU, 'safety': SafetyLevel.CAUTION},
        'AMD_Shader_Cache': {'path': os.path.join(local, 'AMD', 'DxCache'), 'description': 'AMD Shader缓存', 'category': Category.GPU, 'safety': SafetyLevel.SAFE},
    })

    # 虚拟化
    paths.update({
        'Docker_Desktop': {'path': os.path.join(local, 'Docker', 'wsl'), 'description': 'Docker WSL数据', 'category': Category.VIRTUALIZATION, 'safety': SafetyLevel.CAUTION},
        'WSL_Distros': {'path': os.path.join(user, 'AppData', 'Local', 'Packages', 'CanonicalGroupLimited.Ubuntu'), 'description': 'WSL Ubuntu', 'category': Category.VIRTUALIZATION, 'safety': SafetyLevel.DANGER},
        'VMware_Cache': {'path': os.path.join(local, 'VMware'), 'description': 'VMware缓存', 'category': Category.VIRTUALIZATION, 'safety': SafetyLevel.SAFE},
    })

    # 云存储
    paths.update({
        'OneDrive_Cache': {'path': os.path.join(local, 'Microsoft', 'OneDrive'), 'description': 'OneDrive缓存', 'category': Category.CLOUD, 'safety': SafetyLevel.CAUTION},
        'Dropbox_Cache': {'path': os.path.join(user, 'Dropbox', '.dropbox.cache'), 'description': 'Dropbox缓存', 'category': Category.CLOUD, 'safety': SafetyLevel.CAUTION},
        'Google_Drive': {'path': os.path.join(local, 'Google', 'Drive'), 'description': 'Google Drive缓存', 'category': Category.CLOUD, 'safety': SafetyLevel.CAUTION},
    })

    # 其他
    paths.update({
        'WER_Report': {'path': os.path.join(programdata, 'Microsoft', 'Windows', 'WER'), 'description': 'Windows错误报告', 'category': Category.OTHER, 'safety': SafetyLevel.SAFE},
        'Windows_Old': {'path': os.path.join('C:\\', 'Windows.old'), 'description': '旧Windows备份', 'category': Category.OTHER, 'safety': SafetyLevel.CAUTION},
    })

    return paths


def _format_size_mb(mb):
    """格式化 MB 大小"""
    if mb < 0.001:
        return "0 B"
    if mb < 1:
        return f"{mb * 1024:.1f} KB"
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.2f} GB"


def _format_size_bytes(b):
    """格式化字节大小"""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


# ============================================
# 扫描线程
# ============================================

class CacheScanThread(QThread):
    """缓存扫描线程"""
    progress = pyqtSignal(str)           # 状态更新
    item_scanned = pyqtSignal(dict)      # 单个缓存项扫描完成
    finished = pyqtSignal(list)          # 全部完成，返回结果列表
    error = pyqtSignal(str)

    def __init__(self, cache_paths=None, custom_root=None):
        super().__init__()
        self.cache_paths = cache_paths or {}
        self.custom_root = custom_root  # 自选扫描模式：根目录路径
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cache_like(self, name):
        """名字是否与 cache/temp 相关"""
        return is_cache_like(name)

    def _discover_cache_dirs(self, root):
        """自选模式：从根目录递归发现名字含 cache/temp 的目录。
        返回 [(dir_path, description), ...]，避免重复包含（父子目录只取最外层）。"""
        found = []
        seen = set()
        try:
            for r, d, f in os.walk(root):
                if self._cancelled:
                    break
                # 检查当前目录名是否匹配
                base = os.path.basename(r)
                if r != root and self._is_cache_like(base):
                    # 避免被已选目录的子目录重复收录
                    if not any(r.startswith(s + os.sep) for s in seen):
                        found.append((r, f"自选: {base}"))
                        seen.add(r)
                        # 不再深入此目录内部找子 cache（已整体收录），但继续扫描其内容文件
                        d[:] = []  # 不下钻，整目录作为一个缓存项
                    continue
                # 同时收集名字含 cache/temp 的散落文件所在信息（按所在目录归组）
            # 收集根目录下名字含 cache/temp 的散落文件（单独成组）
        except (OSError, PermissionError):
            pass
        return found

    def _scan_dir(self, dir_path):
        """扫描单个目录"""
        files, size = [], 0
        if not os.path.exists(dir_path):
            return files, size
        try:
            for r, d, f in os.walk(dir_path):
                if self._cancelled:
                    break
                for fn in f:
                    fp = os.path.join(r, fn)
                    try:
                        st = os.stat(fp)
                        size += st.st_size / (1024 * 1024)
                        files.append({
                            'path': fp,
                            'size_mb': st.st_size / (1024 * 1024),
                            'mtime': datetime.fromtimestamp(st.st_mtime)
                        })
                    except (OSError, PermissionError):
                        pass
        except (OSError, PermissionError):
            pass
        return files, size

    def run(self):
        import time as _time
        _log_path = os.path.join(os.environ.get('TEMP', '.'), 'cache_clean_debug.log')
        def _log(msg):
            try:
                with open(_log_path, 'a', encoding='utf-8') as lf:
                    lf.write(f"[{_time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass

        _log("=== 扫描开始 ===")
        try:
            results = []

            # 自选模式：动态发现 cache/temp 目录
            if self.custom_root:
                if not os.path.isdir(self.custom_root):
                    self.error.emit("所选目录不存在")
                    return
                self.progress.emit(f"正在 {self.custom_root} 中查找 cache/temp 相关目录...")
                cache_dirs = self._discover_cache_dirs(self.custom_root)
                _log(f"自选模式: 发现 {len(cache_dirs)} 个 cache/temp 目录")
                total = len(cache_dirs)
                for idx, (dir_path, desc) in enumerate(cache_dirs, 1):
                    if self._cancelled:
                        break
                    self.progress.emit(f"扫描自选 ({idx}/{total}): {os.path.basename(dir_path)}")
                    files, size = self._scan_dir(dir_path)
                    if not files:
                        continue
                    safety = SafetyLevel.get_level_from_date(max(f['mtime'] for f in files))
                    entry = {
                        'name': f'custom_{idx}',
                        'path': dir_path,
                        'description': desc,
                        'category': Category.OTHER,
                        'safety': safety,
                        'files': files,
                        'file_count': len(files),
                        'total_size_mb': size,
                        'newest_file_date': max(f['mtime'] for f in files),
                    }
                    results.append(entry)
                    self.item_scanned.emit(entry)
            else:
                # 预设模式：扫描注册表中的固定路径
                total = len(self.cache_paths)
                scanned = 0
                for name, info in self.cache_paths.items():
                    if self._cancelled:
                        break
                    scanned += 1
                    if not os.path.exists(info['path']):
                        continue
                    self.progress.emit(f"扫描中 ({scanned}/{total}): {info['description']}")
                    scan_start = _time.time()
                    files, size = self._scan_dir(info['path'])
                    scan_elapsed = _time.time() - scan_start
                    if not files:
                        _log(f"  [{scanned}/{total}] {info['description']}: 空 ({scan_elapsed:.1f}s)")
                        continue
                    _log(f"  [{scanned}/{total}] {info['description']}: {len(files)}个文件, {size:.1f}MB ({scan_elapsed:.1f}s)")
                    safety = info['safety'] or SafetyLevel.get_level_from_date(
                        max(f['mtime'] for f in files))
                    entry = {
                        'name': name,
                        'path': info['path'],
                        'description': info['description'],
                        'category': info['category'],
                        'safety': safety,
                        'files': files,
                        'file_count': len(files),
                        'total_size_mb': size,
                        'newest_file_date': max(f['mtime'] for f in files),
                    }
                    results.append(entry)
                    self.item_scanned.emit(entry)

            _log(f"=== 扫描结束 === {len(results)} 个缓存位置")
            self.finished.emit(results)
        except Exception as e:
            _log(f"=== 扫描异常 === {e}")
            self.error.emit(str(e))


# ============================================
# 删除线程
# ============================================

class CacheDeleteThread(QThread):
    """缓存删除线程"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int, int, float)  # deleted, failed, freed_mb

    def __init__(self, caches):
        super().__init__()
        self.caches = caches
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        import time as _time
        _log_path = os.path.join(os.environ.get('TEMP', '.'), 'cache_clean_debug.log')
        def _log(msg):
            try:
                with open(_log_path, 'a', encoding='utf-8') as lf:
                    lf.write(f"[{_time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass

        try:
            import send2trash
        except ImportError:
            _log("ERROR: send2trash import failed")
            self.finished.emit(0, 0, 0)
            return

        _log(f"=== 清理开始 === 共 {sum(len(c['files']) for c in self.caches)} 个缓存项")
        del_cnt, fail_cnt, freed = 0, 0, 0
        total_files = sum(len(c['files']) for c in self.caches)
        processed = 0
        start_t = _time.time()
        last_log_t = start_t

        for c in self.caches:
            if self._cancelled:
                _log("用户取消")
                break
            _log(f"--- 处理缓存: {c['description']} ({c['file_count']} 个文件, 路径: {c['path']})")
            cache_start = _time.time()
            cache_del, cache_fail = 0, 0

            for f in c['files']:
                if self._cancelled:
                    break
                processed += 1
                try:
                    fp = f['path']
                    if not os.path.exists(fp):
                        fail_cnt += 1
                        cache_fail += 1
                        continue

                    fp_upper = fp.upper()
                    if any(p in fp_upper for p in ['SYSTEM32', 'PROGRAM FILES', 'WINDOWS\\LOGS',
                                                    'WINDOWS\\INSTALLER', 'WINDOWS\\WINSXS']):
                        fail_cnt += 1
                        cache_fail += 1
                        continue

                    # 清除只读属性
                    try:
                        import stat
                        mode = os.stat(fp).st_mode
                        if not (mode & stat.S_IWRITE):
                            os.chmod(fp, mode | stat.S_IWRITE)
                    except (OSError, PermissionError):
                        pass

                    file_start = _time.time()
                    # 缓存文件直接删除（不进回收站，速度快10倍）
                    # 大文件(>100MB)用 shutil.rmtree 处理目录
                    if os.path.isdir(fp):
                        import shutil
                        shutil.rmtree(fp, ignore_errors=True)
                    else:
                        os.remove(fp)
                    file_elapsed = _time.time() - file_start
                    del_cnt += 1
                    freed += f['size_mb']
                    cache_del += 1

                    # 记录慢文件（>1秒）
                    if file_elapsed > 1.0:
                        _log(f"  SLOW ({file_elapsed:.1f}s): {fp}")

                except (OSError, PermissionError) as e:
                    fail_cnt += 1
                    cache_fail += 1
                    _log(f"  SKIP(OSError): {fp} -> {e}")
                except Exception as e:
                    fail_cnt += 1
                    cache_fail += 1
                    _log(f"  SKIP(Exception): {fp} -> {e}")

                # 每10个文件更新进度
                if processed % 10 == 0:
                    self.progress.emit(f"清理中... {processed}/{total_files}")

                # 每30秒写一次日志
                now = _time.time()
                if now - last_log_t > 30:
                    _log(f"  进度: {processed}/{total_files}, 成功:{del_cnt}, 失败:{fail_cnt}")
                    last_log_t = now

            cache_elapsed = _time.time() - cache_start
            _log(f"  完成: {c['description']} -> 删除{cache_del}, 跳过{cache_fail}, 耗时{cache_elapsed:.1f}s")

        total_elapsed = _time.time() - start_t
        _log(f"=== 清理结束 === 删除{del_cnt}, 跳过{fail_cnt}, 释放{freed:.1f}MB, 总耗时{total_elapsed:.1f}s")
        self.finished.emit(del_cnt, fail_cnt, freed)


# ============================================
# 缓存清理 Tab UI
# ============================================

class CacheCleanerTab(QWidget):
    """缓存清理 Tab"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.cache_paths = _setup_cache_paths()
        self.cache_info = []
        self.filtered_cache_info = []
        self.scan_thread = None
        self.delete_thread = None

        self._setup_ui()

    def _update_status(self, msg):
        self.main_window.status_label.setText(msg)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # ---- 控制栏 ----
        control_row1 = QHBoxLayout()
        layout.addLayout(control_row1)

        self.scan_btn = QPushButton("🔍 扫描系统缓存")
        self.scan_btn.clicked.connect(self._start_scan)
        control_row1.addWidget(self.scan_btn)

        self.custom_scan_btn = QPushButton("📂 扫描自选目录")
        self.custom_scan_btn.setToolTip("选择一个目录，递归扫描其中的 cache/temp 相关文件夹和文件并评估")
        self.custom_scan_btn.clicked.connect(self._start_custom_scan)
        control_row1.addWidget(self.custom_scan_btn)

        self.stop_btn = QPushButton("⏹️ 停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        control_row1.addWidget(self.stop_btn)

        control_row1.addStretch()

        self.clean_safe_btn = QPushButton("✅ 清理安全文件")
        self.clean_safe_btn.setEnabled(False)
        self.clean_safe_btn.clicked.connect(self._clean_safe)
        control_row1.addWidget(self.clean_safe_btn)

        self.clean_sel_btn = QPushButton("🗑️ 清理选中项")
        self.clean_sel_btn.setEnabled(False)
        self.clean_sel_btn.clicked.connect(self._clean_selected)
        control_row1.addWidget(self.clean_sel_btn)

        # ---- 过滤栏 ----
        filter_row = QHBoxLayout()
        layout.addLayout(filter_row)

        filter_row.addWidget(QLabel("分类:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "全部", Category.SYSTEM, Category.BROWSER, Category.DEVELOPER,
            Category.MULTIMEDIA, Category.GAME, Category.GPU,
            Category.VIRTUALIZATION, Category.CLOUD, Category.OTHER
        ])
        self.category_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.category_combo)

        filter_row.addStretch()

        self.stats_label = QLabel("")
        filter_row.addWidget(self.stats_label)

        # ---- 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ---- 结果区：双树隔离（安全项 / 谨慎+危险项 各自独立排序，互不混合）----
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        # 安全项树（上方，可勾选清理）
        safe_container = QWidget()
        safe_layout = QVBoxLayout(safe_container)
        safe_layout.setContentsMargins(0, 0, 0, 0)
        safe_layout.setSpacing(2)
        self.safe_title_label = QLabel("✓ 安全（可直接删除）")
        self.safe_title_label.setStyleSheet("font-weight: bold; padding: 2px; color: #4caf50;")
        safe_layout.addWidget(self.safe_title_label)
        self.safe_tree = self._make_tree()
        safe_layout.addWidget(self.safe_tree)
        splitter.addWidget(safe_container)

        # 谨慎+危险项树（下方，移至回收站）
        caution_container = QWidget()
        caution_layout = QVBoxLayout(caution_container)
        caution_layout.setContentsMargins(0, 0, 0, 0)
        caution_layout.setSpacing(2)
        self.caution_title_label = QLabel("⚠ 谨慎 / ✗ 危险（移至回收站）")
        self.caution_title_label.setStyleSheet("font-weight: bold; padding: 2px; color: #ff9800;")
        caution_layout.addWidget(self.caution_title_label)
        self.caution_tree = self._make_tree()
        caution_layout.addWidget(self.caution_tree)
        splitter.addWidget(caution_container)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 280])

    def _make_tree(self):
        """构造一棵缓存结果树（复用配置，两棵树一致）"""
        tree = QTreeWidget()
        tree.setHeaderLabels(["✓", "名称", "分类", "安全等级", "文件数", "大小", "路径"])
        # 扁平列表：禁用树形缩进，使列0成为普通列（复选框居中不被遮挡）
        tree.setRootIsDecorated(False)
        tree.setIndentation(0)
        tree.setItemsExpandable(False)
        tree.setColumnWidth(0, 36)
        tree.setColumnWidth(1, 200)
        tree.setColumnWidth(2, 100)
        tree.setColumnWidth(3, 80)
        tree.setColumnWidth(4, 80)
        tree.setColumnWidth(5, 100)
        tree.setColumnWidth(6, 400)
        tree.header().setStretchLastSection(True)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        tree.header().setMinimumSectionSize(36)
        # 勾选列(0)用居中复选框 delegate
        tree.setItemDelegateForColumn(0, CenteredCheckDelegate(tree))
        tree.setSortingEnabled(True)
        tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._show_context_menu)
        tree.itemDoubleClicked.connect(self._on_double_click)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.header().sectionClicked.connect(self._on_header_clicked)
        # 事件过滤器：在 Qt 处理点击前保存多选状态
        tree.viewport().installEventFilter(self)
        return tree

    def eventFilter(self, obj, event):
        """在鼠标按下时保存当前多选状态（Qt会在itemClicked前清空选择）。
        分别记录是哪棵树、其选中项，供 _on_item_clicked 多选批量切换。"""
        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if obj is self.safe_tree.viewport():
                self._pre_click_tree = self.safe_tree
                self._pre_click_selection = list(self.safe_tree.selectedItems())
            elif obj is self.caution_tree.viewport():
                self._pre_click_tree = self.caution_tree
                self._pre_click_selection = list(self.caution_tree.selectedItems())
        return super().eventFilter(obj, event)

    # ---- 扫描 ----

    def _start_scan(self):
        """扫描系统预设缓存路径"""
        self._begin_scan()
        self._update_status("正在扫描系统缓存...")
        self.scan_thread = CacheScanThread(self.cache_paths)
        self._launch_scan_thread()

    def _start_custom_scan(self):
        """扫描自选目录下的 cache/temp 相关文件夹和文件"""
        from PyQt6.QtWidgets import QFileDialog
        root = QFileDialog.getExistingDirectory(self, "选择要扫描的目录")
        if not root:
            return
        self._begin_scan()
        self._update_status(f"正在 {root} 中查找 cache/temp 相关目录...")
        self.scan_thread = CacheScanThread(custom_root=root)
        self._launch_scan_thread()

    def _begin_scan(self):
        """扫描开始前的公共准备"""
        self.cache_info = []
        self.filtered_cache_info = []
        self.safe_tree.clear()
        self.caution_tree.clear()
        self._set_buttons(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

    def _launch_scan_thread(self):
        """连接信号并启动扫描线程"""
        self.scan_thread.progress.connect(self._on_scan_progress)
        self.scan_thread.item_scanned.connect(self._on_item_scanned)
        self.scan_thread.finished.connect(self._on_scan_finished)
        self.scan_thread.error.connect(self._on_scan_error)
        self.scan_thread.start()

    def _on_scan_progress(self, msg):
        self._update_status(msg)

    def _on_item_scanned(self, entry):
        """单个缓存项扫描完成，实时添加到树中"""
        self.cache_info.append(entry)
        self._add_tree_item(entry)
        self._update_tree_titles(self.cache_info)
        total = sum(c['total_size_mb'] for c in self.cache_info)
        msg = f"已发现 {len(self.cache_info)} 项 | {_format_size_mb(total)}"
        self.stats_label.setText(msg)
        self._update_status(msg)

    def _on_scan_finished(self, results):
        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        self.cache_info = results
        self.filtered_cache_info = results.copy()
        total = sum(c['total_size_mb'] for c in results)
        status_msg = f"扫描完成 - {len(results)} 个缓存位置，共 {_format_size_mb(total)}"
        self._update_status(status_msg)
        self.stats_label.setText(f"共 {len(results)} 项 | {_format_size_mb(total)}")
        self._update_tree_titles()

    def _on_scan_error(self, msg):
        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        QMessageBox.critical(self, "扫描出错", f"扫描过程中发生异常：\n{msg}")

    # ---- 树操作 ----

    def _tree_for_safety(self, safety):
        """根据安全等级返回对应树：safe → 安全树，caution/danger → 谨慎树"""
        return self.safe_tree if safety == SafetyLevel.SAFE else self.caution_tree

    def _add_tree_item(self, entry):
        """添加单条记录到对应安全等级的树"""
        safety_text = {'safe': '✓ 安全', 'caution': '⚠ 谨慎', 'danger': '✗ 危险'}[entry['safety']]

        item = QTreeWidgetItem()
        # 列0 用原生复选框（CheckStateRole，delegate 居中绘制），不再用文本 '☐'
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setText(1, entry['description'])
        item.setText(2, entry['category'])
        item.setText(3, safety_text)
        item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
        item.setText(4, f"{entry['file_count']} 个")
        item.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
        item.setText(5, _format_size_mb(entry['total_size_mb']))
        item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)
        item.setText(6, entry['path'])

        # 排序用数据（数值，避免按文本排序时 "1 个" < "10 个" < "2 个"）
        item.setData(5, Qt.ItemDataRole.UserRole, entry['total_size_mb'])
        item.setData(4, Qt.ItemDataRole.UserRole, entry['file_count'])

        # 安全等级颜色
        color_map = {
            'safe': QColor(76, 175, 80),
            'caution': QColor(255, 193, 7),
            'danger': QColor(244, 67, 54),
        }
        item.setForeground(3, color_map.get(entry['safety'], QColor(0, 0, 0)))

        # 存储完整数据
        item.setData(0, Qt.ItemDataRole.UserRole + 1, entry)

        self._tree_for_safety(entry['safety']).addTopLevelItem(item)

    def _refresh_tree(self):
        """根据过滤条件刷新两棵树"""
        self.safe_tree.clear()
        self.caution_tree.clear()
        for entry in self.filtered_cache_info:
            self._add_tree_item(entry)
        total = sum(c['total_size_mb'] for c in self.filtered_cache_info)
        self._update_tree_titles()
        self.stats_label.setText(f"共 {len(self.filtered_cache_info)} 项 | {_format_size_mb(total)}")

    def _update_tree_titles(self, items=None):
        """更新两棵树标题的项数/大小统计"""
        if items is None:
            items = self.filtered_cache_info
        safe = [c for c in items if c['safety'] == SafetyLevel.SAFE]
        caution = [c for c in items if c['safety'] != SafetyLevel.SAFE]
        safe_size = sum(c['total_size_mb'] for c in safe)
        caution_size = sum(c['total_size_mb'] for c in caution)
        self.safe_title_label.setText(
            f"✓ 安全（可直接删除）— {len(safe)} 项 | {_format_size_mb(safe_size)}")
        self.caution_title_label.setText(
            f"⚠ 谨慎 / ✗ 危险（移至回收站）— {len(caution)} 项 | {_format_size_mb(caution_size)}")

    def _apply_filter(self):
        """应用分类过滤（安全等级已由双树分区体现，不再单独筛选）"""
        cat = self.category_combo.currentText()

        self.filtered_cache_info = self.cache_info.copy()
        if cat != "全部":
            self.filtered_cache_info = [c for c in self.filtered_cache_info if c['category'] == cat]

        self._refresh_tree()

    def _on_header_clicked(self, col):
        """点击列标题：第0列对该树全选/取消全选，其他列排序"""
        tree = self.safe_tree  # 默认；sectionClicked 信号的 sender 即被点的树
        sender = self.sender()
        if isinstance(sender, QHeaderView):
            # 找到 header 所属的树
            for t in (self.safe_tree, self.caution_tree):
                if t.header() is sender:
                    tree = t
                    break
        if col == 0:
            tree.setSortingEnabled(False)
            self._toggle_select_all(tree)
            tree.setSortingEnabled(True)

    def _on_item_clicked(self, item, col):
        """点击行：第0列切换复选框（支持多选批量切换）"""
        if col != 0:
            return
        # 判断 item 属于哪棵树
        tree = self.safe_tree if self.safe_tree.indexOfTopLevelItem(item) >= 0 else self.caution_tree
        # 自行控制切换（不用 ItemIsUserCheckable 自动切换时序）
        old_state = item.checkState(0)
        new_state = (Qt.CheckState.Checked
                     if old_state == Qt.CheckState.Unchecked
                     else Qt.CheckState.Unchecked)
        item.setCheckState(0, new_state)

        # 多选：同步该树其他选中项（仅同一棵树内多选）
        pre_tree = getattr(self, '_pre_click_tree', None)
        pre_selected = getattr(self, '_pre_click_selection', [])
        if pre_tree is tree and len(pre_selected) > 1 and item in pre_selected:
            tree.setUpdatesEnabled(False)
            tree.blockSignals(True)
            for sel in pre_selected:
                if sel is item:
                    continue
                if tree.indexOfTopLevelItem(sel) >= 0:
                    sel.setCheckState(0, new_state)
            tree.blockSignals(False)
            tree.setUpdatesEnabled(True)
        self._update_check_status()

    def _toggle_select_all(self, tree):
        """对指定树全选/取消全选"""
        n = tree.topLevelItemCount()
        if n == 0:
            return
        first_state = None
        for i in range(n):
            it = tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole + 1):
                first_state = it.checkState(0)
                break
        if first_state is None:
            return
        new_state = (Qt.CheckState.Unchecked
                     if first_state == Qt.CheckState.Checked
                     else Qt.CheckState.Checked)
        tree.setSortingEnabled(False)
        tree.setUpdatesEnabled(False)
        tree.blockSignals(True)
        for i in range(n):
            it = tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole + 1):
                it.setCheckState(0, new_state)
        tree.blockSignals(False)
        tree.setUpdatesEnabled(True)
        tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        tree.setSortingEnabled(True)
        self._update_check_status()

    def _update_check_status(self):
        """统计两棵树勾选总数并显示"""
        n = 0
        for tree in (self.safe_tree, self.caution_tree):
            for i in range(tree.topLevelItemCount()):
                it = tree.topLevelItem(i)
                if (it.data(0, Qt.ItemDataRole.UserRole + 1)
                        and it.checkState(0) == Qt.CheckState.Checked):
                    n += 1
        if n:
            self._update_status(f"已勾选 {n} 项待清理")
        else:
            self._update_status("就绪")

    # ---- 右键菜单 ----

    def _show_context_menu(self, position):
        tree = self.safe_tree  # 默认
        sender = self.sender()
        if sender is self.caution_tree:
            tree = self.caution_tree
        item = tree.itemAt(position)
        if not item:
            return

        # 获取安全等级
        entry = item.data(0, Qt.ItemDataRole.UserRole + 1)
        safety = entry.get('safety', '') if entry else ''

        menu = QMenu(self)

        open_action = QAction("打开目录", self)
        open_action.triggered.connect(lambda: self._open_path(item))
        menu.addAction(open_action)

        copy_action = QAction("复制路径", self)
        copy_action.triggered.connect(lambda: self._copy_path(item))
        menu.addAction(copy_action)

        menu.addSeparator()

        if safety == SafetyLevel.SAFE:
            # 安全项：直接删除
            clean_action = QAction("直接删除", self)
            clean_action.triggered.connect(lambda: self._clean_item(item))
            menu.addAction(clean_action)
        else:
            # 谨慎/危险项：移动到回收站
            recycle_action = QAction("移动到回收站", self)
            recycle_action.triggered.connect(lambda: self._recycle_item(item))
            menu.addAction(recycle_action)

        menu.exec(tree.viewport().mapToGlobal(position))

    def _open_path(self, item):
        path = item.text(6)
        if os.path.exists(path):
            import subprocess
            subprocess.run(f'explorer /select,"{path}"', shell=True)

    def _copy_path(self, item):
        QApplication.clipboard().setText(item.text(6))
        self._update_status(f"已复制: {item.text(6)}")

    def _on_double_click(self, item, col):
        self._open_path(item)

    def _recycle_item(self, item):
        """右键：移动到回收站（用 send2trash，适用于谨慎/危险项）"""
        entry = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not entry:
            return
        reply = QMessageBox.question(self, "确认移动到回收站",
            f"将以下项目移到回收站？\n\n"
            f"{entry['description']}\n"
            f"路径: {entry['path']}\n"
            f"文件数: {entry['file_count']}\n"
            f"大小: {_format_size_mb(entry['total_size_mb'])}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            import send2trash
        except ImportError:
            QMessageBox.critical(self, "错误", "缺少 send2trash 库")
            return

        self._update_status("正在移动到回收站...")
        del_cnt, fail_cnt = 0, 0
        for f in entry['files']:
            try:
                if os.path.exists(f['path']):
                    send2trash.send2trash(f['path'])
                    del_cnt += 1
                else:
                    fail_cnt += 1
            except Exception:
                fail_cnt += 1

        msg = f"完成 - 移动 {del_cnt} 个文件到回收站"
        if fail_cnt > 0:
            msg += f"，跳过 {fail_cnt} 个"
        self._update_status(msg)
        QMessageBox.information(self, "完成", msg)
        self._start_scan()

    # ---- 清理操作 ----

    def _clean_safe(self):
        safe = [c for c in self.cache_info if c['safety'] == SafetyLevel.SAFE]
        if not safe:
            QMessageBox.information(self, "提示", "没有可安全清理的文件")
            return
        total_files = sum(c['file_count'] for c in safe)
        total_size = sum(c['total_size_mb'] for c in safe)
        reply = QMessageBox.question(self, "确认清理",
            f"清理 {len(safe)} 个安全项目？\n\n"
            f"文件数: {total_files}\n"
            f"大小: {_format_size_mb(total_size)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._do_delete(safe)

    def _clean_selected(self):
        selected = []
        for tree in (self.safe_tree, self.caution_tree):
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                if item.checkState(0) == Qt.CheckState.Checked:
                    entry = item.data(0, Qt.ItemDataRole.UserRole + 1)
                    if entry:
                        selected.append(entry)
        if not selected:
            QMessageBox.warning(self, "提示", "请先勾选要清理的项目")
            return
        total_files = sum(c['file_count'] for c in selected)
        total_size = sum(c['total_size_mb'] for c in selected)
        # 勾选可能含谨慎/危险项，提示将移至回收站
        has_caution = any(c['safety'] != SafetyLevel.SAFE for c in selected)
        hint = "\n（含谨慎/危险项，将移至回收站）" if has_caution else ""
        reply = QMessageBox.question(self, "确认清理",
            f"清理 {len(selected)} 个选中项目？\n\n"
            f"文件数: {total_files}\n"
            f"大小: {_format_size_mb(total_size)}{hint}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._do_delete(selected)

    def _clean_item(self, item):
        entry = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not entry:
            return
        reply = QMessageBox.question(self, "确认清理",
            f"清理 {entry['description']}？\n\n"
            f"文件数: {entry['file_count']}\n"
            f"大小: {_format_size_mb(entry['total_size_mb'])}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._do_delete([entry])

    def _do_delete(self, caches):
        self._set_buttons(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._update_status("正在清理...")

        self.delete_thread = CacheDeleteThread(caches)
        self.delete_thread.progress.connect(self._update_status)
        self.delete_thread.finished.connect(self._on_delete_finished)
        self.delete_thread.start()

    def _on_delete_finished(self, deleted, failed, freed):
        self.progress_bar.setVisible(False)
        self._set_buttons(True)
        msg = f"清理完成 - 删除 {deleted} 个文件，释放 {_format_size_mb(freed)}"
        if failed > 0:
            msg += f"，跳过 {failed} 个（权限不足或被占用）"
        self._update_status(msg)
        QMessageBox.information(self, "清理完成", msg)
        # 重新扫描
        self._start_scan()

    # ---- 辅助 ----

    def _set_buttons(self, enabled):
        self.scan_btn.setEnabled(enabled)
        self.custom_scan_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(not enabled)
        has_data = bool(self.cache_info)
        self.clean_safe_btn.setEnabled(enabled and has_data)
        self.clean_sel_btn.setEnabled(enabled and has_data)

    def _stop(self):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.cancel()
        if self.delete_thread and self.delete_thread.isRunning():
            self.delete_thread.cancel()
        self._update_status("正在停止...")

    def cleanup(self):
        """关闭时清理线程"""
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.cancel()
            self.scan_thread.wait(3000)
        if self.delete_thread and self.delete_thread.isRunning():
            self.delete_thread.cancel()
            self.delete_thread.wait(3000)
