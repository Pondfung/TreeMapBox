# AGENTS.md — TreeMapBox

## 项目定位
Windows 磁盘占用分析工具（PyQt6 桌面应用），集成磁盘分析、重复文件筛选、缓存清理三大功能。当前版本 v0.9.5。

## 怎么跑
```bash
pip install -r requirements.txt   # PyQt6, send2trash, pyfsntfs, pywin32
python main.py                      # 需管理员权限才能用 MFT 扫描
python build_exe.py                 # 打包成 dist/TreeMapBox.exe
```

## 技术栈
- Python 3.12+ / PyQt6
- pyfsntfs（NTFS MFT 直读）/ pywin32（Windows API）
- SQLite（哈希缓存，WAL 模式）
- PyInstaller（打包）

## 目录与约定
```
main.py              # 入口，全局 excepthook 兜底
core/                # 扫描引擎层（scanner / parallel_scanner / mft_scanner / parallel_mft_scanner / cache_detector / hash_cache）
ui/                  # 界面层（main_window + 3 个 tab + simple_treemap + treemap_widget）
config/software_rules.json  # 缓存识别规则库
docs/                # 用户文档
```
- 扫描器返回 `FileNode` dataclass（`core/scanner.py` 定义，`parallel_scanner.py` 有同名副本，靠鸭子类型混用——改字段时两处都要改）
- UI 层用 QThread + `finished.connect(deleteLater)` 管理扫描线程生命周期，停止扫描时不能直接 deleteLater（会 segfault）
- 崩溃日志：`%TEMP%\treemapbox_crash.log`（windowed 模式下 stderr 为 None）

## 当前状态
- v0.9.5，三大 Tab 功能完整
- Git 仓库：github.com/Pondfung/TreeMapBox
- `dist/` 空（需重新打包）、`resources/icons/` 空
- 已知技术债：`FileNode` 重复定义、`_safe_path` 在两个 tab 文件各抄一份
