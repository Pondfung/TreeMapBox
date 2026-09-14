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
utils/paths.py       # 缓存目录选择（打包 exe 同目录，源码运行 LOCALAPPDATA）
config/software_rules.json  # 缓存识别规则库
docs/                # 用户文档
```
- 扫描器返回 `FileNode` dataclass（`core/scanner.py` 定义，`parallel_scanner.py` 有同名副本，靠鸭子类型混用——改字段时两处都要改）；MFT 扫描器返回 dict，含 `frn`/`parent_frn`
- `frn`/`parent_frn` 是完整 64 位无符号 file_reference；写 SQLite（有符号 64 位）必须经 `_to_signed`/`_to_unsigned` 转换（`core/size_cache.py`），否则高位 sequence 为 1 时溢出
- UI 层 QThread 生命周期：后台线程用 `_live_scan_threads` 容器持有引用（`destroyed` 信号释放），不能在 finished 回调里过早置 None——会触发 "QThread destroyed while running"（0xc0000409 闪退）
- 崩溃日志：`%TEMP%\treemapbox_crash.log`（windowed 模式下 stderr 为 None）；C++ 层崩溃走 faulthandler 写 `%TEMP%\treemapbox_fault.log`

## 当前状态
- v0.9.6，USN 增量缓存已实现：首次全量 MFT 扫描（约 88s）写 size_cache.db，后续启动秒开 + 后台 USN 增量追平
- Git 仓库：github.com/Pondfung/TreeMapBox
- `dist/TreeMapBox.exe` 已打包（约 39MB），根目录另放一份 TreeMapBox.exe（本地用，不入库）
- 缓存位置：打包 exe → exe 同目录；源码运行 → `%LOCALAPPDATA%\TreeMapBox`
- 已知技术债：`FileNode` 重复定义（scanner.py / parallel_scanner.py 两处）、`_safe_path` 在两个 tab 文件各抄一份
