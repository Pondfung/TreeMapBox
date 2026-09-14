# AGENTS.md — TreeMapBox

## 项目定位
Windows 磁盘占用分析工具（PyQt6 桌面应用），集成磁盘分析、重复文件筛选、缓存清理三大功能。当前版本 v0.9.6。

## 怎么跑
```bash
pip install -r requirements.txt   # PyQt6, send2trash, libfsntfs-python, pywin32
python main.py                      # 需管理员权限才能用 MFT 扫描
python build_exe.py                 # 打包成 dist/TreeMapBox.exe
```

## 技术栈
- Python 3.10+ / PyQt6
- pyfsntfs（pip 包名 libfsntfs-python，NTFS MFT 直读）/ pywin32（Windows API + USN Journal）
- SQLite（哈希缓存 + 目录大小缓存，WAL 模式）
- PyInstaller（打包）

## 目录与约定
```
main.py              # 入口，全局 excepthook 兜底
core/                # 扫描引擎层（scanner / parallel_scanner / mft_scanner / parallel_mft_scanner / cache_detector / hash_cache / usn_journal / size_cache）
ui/                  # 界面层（main_window + 3 个 tab + simple_treemap + treemap_widget）
utils/paths.py       # 路径选择：缓存目录（exe 同目录/源码 LOCALAPPDATA）+ 导出目录（build/）
utils/common.py      # UI 共享工具（无 Qt 依赖，单一来源）：safe_path / is_root_path / is_cache_like / path_in_cache_dir / get_export_path
config/software_rules.json  # 缓存识别规则库
docs/                # 用户文档
```
- 扫描器返回 `FileNode` dataclass（单一来源 `core/file_node.py`，`scanner.py`/`parallel_scanner.py` 均 re-export 保持旧导入兼容）；MFT 扫描器返回 dict，含 `frn`/`parent_frn`
- `frn`/`parent_frn` 是完整 64 位无符号 file_reference；写 SQLite（有符号 64 位）必须经 `_to_signed`/`_to_unsigned` 转换（`core/size_cache.py`），否则高位 sequence 为 1 时溢出
- UI 层 QThread 生命周期：后台线程用 `_live_scan_threads` 容器持有引用（`destroyed` 信号释放），不能在 finished 回调里过早置 None——会触发 "QThread destroyed while running"（0xc0000409 闪退）
- 崩溃日志：`%TEMP%\treemapbox_crash.log`（windowed 模式下 stderr 为 None）；C++ 层崩溃走 faulthandler 写 `%TEMP%\treemapbox_fault.log`

## 当前状态
- v0.9.6，USN 增量缓存已实现：首次全量 MFT 扫描（约 88s）写 size_cache.db，后续启动秒开 + 后台 USN 增量追平
- Git 仓库：github.com/Pondfung/TreeMapBox
- `dist/TreeMapBox.exe` 已打包（约 39MB），根目录另放一份 TreeMapBox.exe（本地用，不入库）
- 缓存位置：打包 exe → exe 同目录；源码运行 → `%LOCALAPPDATA%\TreeMapBox`；导出 JSON → `exports/`（源码）或 exe 同目录（打包，`exports/` 已 gitignore）
- 技术债：v0.9.6 已清理 `FileNode`/`format_size`/`_safe_path`/`_get_export_path`/`_is_root_path`/`_is_cache_like`/`_path_in_cache_dir` 等重复定义（统一到 `core/file_node.py`、`core/scanner.py`、`utils/common.py`），并删除死文件 `ui/batch_operations.py`、死常量 `CACHE_NAME_KEYWORDS`、死函数 `_get_latest_export_path`。当前无已知技术债。
