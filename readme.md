# TreeMapBox v0.9.6

基于 PyQt6 的 Windows 磁盘占用分析工具（TreeMapBox），集成磁盘分析、重复文件筛选、缓存清理三大功能模块。

## 功能特性

### Tab 1: 📁 磁盘分析
- 🚀 **MFT 极速扫描**：直接读取 NTFS MFT，16 进程并行扫描全盘（~90 秒扫 106 万文件）
- 📊 **实时进度显示**：扫描计时器每秒显示已用时间，构建目录树/填充列表/渲染树图各阶段分步反馈，全程不假死
- ⏹️ **可取消扫描**：随时停止，快速终止
- 🔄 **自动降级**：MFT 失败自动切普通扫描
- 🌳 **懒加载树形视图**：百万文件不卡顿
- 🎨 **矩形树图**：Squarified Treemap 可视化
- 🔗 **双向联动**：树形列表与矩形树图互相高亮
- 📄 **自动导出文件列表**：扫描根目录时自动导出 JSON（按盘符区分，原子写），供重复文件 Tab 复用
- ♻️ **JSON 复用**：扫根目录时若存在 1 天内的盘符 JSON，弹窗询问"复用近期结果（几秒加载）"或"重新扫描（MFT 实时）"
- ⚡ **启动秒开（USN 增量缓存）**：首次 MFT 扫描后把目录大小写入 SQLite 缓存，后续启动从缓存秒级加载，后台读 USN Journal 增量追平（新建/删除/改名/改大小），无需每次全盘扫

### Tab 2: 🔍 重复文件筛选
- 🔍 **沿用磁盘分析扫描**：MFT 优先 + 失败降级普通扫描，根目录自动复用/生成盘符 JSON
- ⏭️ **跳过缓存/临时文件**：哈希比对前过滤路径各级含 cache/temp/tmp/缓存/临时 的文件，加快效率（可开关）
- 🔗 **三级渐进式比对**：大小 → 三点采样哈希(头+中+尾) → 完整哈希
- ⚡ **多线程并行哈希**：ThreadPoolExecutor 复用线程池，自动检测 CPU 核心数
- 💾 **SQLite 哈希缓存**：线程本地连接 + WAL + 批量提交，避免重复计算
- ⏰ **保留策略**：最早/最新/路径最短，一键勾选
- 🔗 **硬链接替换** / 🗑️ **删除** / 📦 **归档**（云盘/跨盘自动跳过）
- 🌳 **双树隔离显示**：重复文件与硬链接组各自独立 QTreeWidget、独立排序、互不混合
- ☑️ **原生复选框**：Qt CheckStateRole + 居中 delegate，勾选/全选/多选同步切换，单点 0ms
- 📊 **过滤统计**：`总数→大小→采样→确认`，含跳过缓存数

### Tab 3: 🗑️ 缓存清理
- 🔍 **54 个缓存路径扫描**：覆盖 9 大类（系统/浏览器/开发/游戏/显卡/虚拟化/云存储等）
- 📂 **自选目录扫描**：选择目录后递归发现 cache/temp 相关文件夹并评估安全等级
- ⚠️ **三级安全评级**：安全(直接删除) / 谨慎(移至回收站) / 危险(移至回收站)
- 🌳 **双树布局**：上方"安全"项（可直接删除），下方"谨慎/危险"项（移至回收站），各自独立排序
- ☑️ **原生复选框**：与重复文件 Tab 同款 CheckStateRole + 居中 delegate
- ✅ **一键清理安全文件** / 🗑️ **选中清理**
- 📂 **分类过滤**：按分类快速筛选

### 安全与体验
- 🧠 **智能缓存识别**：软件规则库匹配
- ⚠️ **删除安全评级**：绿/黄/红三级
- 🗑️ **安全删除**：安全项直接删除(快)，谨慎/危险项移至回收站(可恢复)
- 🛡️ **系统目录保护**：Windows/Program Files 等自动跳过
- ☁️ **云盘检测**：WPS云盘/OneDrive/Dropbox 等自动识别
- 🛡️ **崩溃兜底**：全局 excepthook 写日志（`%TEMP%\treemapbox_crash.log`），windowed 模式不静默崩溃
- ⚡ **取消响应**：扫描/哈希/路径扫描各阶段取消快速生效，不卡"正在停止"

## 安装

```bash
pip install -r requirements.txt
```

依赖：PyQt6、send2trash、libfsntfs-python（import 名 pyfsntfs，MFT 扫描）、pywin32（Windows API）。

## 使用

```bash
python main.py
```

或直接运行打包好的 `dist/TreeMapBox.exe`。

### 典型工作流
1. **Tab1 磁盘分析**：扫描根目录（如 E:\），自动导出文件列表 JSON；再次扫描同盘可选复用近期结果（几秒加载）
2. **Tab2 重复文件**：输入根目录扫描（沿用 MFT + JSON 复用），自动跳过缓存/临时文件，三级哈希比对找重复
3. 用保留策略勾选 → 执行删除/硬链接/归档
4. **Tab3 缓存清理**：扫描系统缓存或自选目录，一键清理安全项

## 项目结构

```
disk_treemap_analyzer/
├── main.py                         # 程序入口（全局异常兜底）
├── build_exe.py                    # PyInstaller 打包脚本
├── requirements.txt                # 依赖列表
├── config/
│   └── software_rules.json         # 软件缓存识别规则库
├── core/
│   ├── file_node.py                # FileNode 数据结构（单一来源）
│   ├── scanner.py                  # 基础扫描引擎
│   ├── parallel_scanner.py         # 多线程并行扫描
│   ├── mft_scanner.py              # MFT 扫描器 + 自动降级
│   ├── parallel_mft_scanner.py     # 多进程 MFT 扫描
│   ├── cache_detector.py           # 缓存识别与安全评级
│   ├── hash_cache.py               # 重复文件哈希缓存 (SQLite)
│   ├── usn_journal.py              # USN Journal 读取引擎
│   └── size_cache.py               # 目录大小缓存 + 增量更新
├── ui/
│   ├── main_window.py              # 主窗口 (QTabWidget)
│   ├── disk_analysis_tab.py        # Tab1: 磁盘分析
│   ├── duplicate_file_tab.py       # Tab2: 重复文件筛选
│   ├── cache_cleaner_tab.py        # Tab3: 缓存清理
│   ├── simple_treemap.py           # 矩形树图控件
│   └── treemap_widget.py           # 树图容器组件
├── utils/
│   ├── paths.py                    # 路径选择（缓存 + 导出目录）
│   └── common.py                   # UI 共享工具（safe_path / is_cache_like 等，单一来源）
└── dist/
    └── TreeMapBox.exe                # 打包产物（v0.9.6）
```

## 打包

```bash
python build_exe.py
```

生成 `dist/TreeMapBox.exe`（单文件，约 39MB，windowed 模式）。

> 打包后缓存文件（`size_cache.db`、哈希缓存）放 exe 同目录（不占 C 盘）；源码运行（`python main.py`）时放 `%LOCALAPPDATA%\TreeMapBox`。exe 放在只读目录（如 Program Files）时自动回退 LOCALAPPDATA。

> 提示：windowed 模式下崩溃无控制台输出，崩溃日志写入 `%TEMP%\treemapbox_crash.log`。

## 已知问题

### ✅ 已修复（v0.9.5）
- **重复文件Tab扫描大目录(17万+文件)后闪退**：`datetime.fromtimestamp` 异常未捕获 + windowed 级联崩溃、`setSortingEnabled` 排序竞态、QThread 生命周期、SQLite 并发卡死——详见版本历史
- **复选框样式/居中/勾选状态错乱**：改用 Qt 原生 CheckStateRole + CE_CheckBox 居中 delegate、禁用树形缩进、int 比较 CheckState
- **缓存清理Tab**复选框同步改造 + 双树布局（安全/谨慎危险分区）+ 自选目录扫描
- **JSON 导出失败导致每次重新扫描**：含 surrogate 代理字符路径编码失败（C盘根因）+ 导出异常被静默吞掉——原子写 + `_safe_path` 代理安全化 + 失败可见化
- **JSON 加载后树双份/切盘混入**：`_load_from_json` 重建前未清空旧树
- **扫描/哈希/路径扫描取消卡死**：各阶段循环内检查取消标志 + 取消后 emit finished 收尾
- **大目录扫描假死**：扫描计时器 + 各阶段分步反馈 + processEvents
- **`stats_label` 未定义 AttributeError**（v0.2.x 遗留）

### 🟡 已知限制
- 导出的 JSON 文件列表不包含 `mtime`（修改时间），树中显示的修改时间来自实时 `os.path.getmtime()`
- 哈希缓存批量提交（每 50 次）可能丢失每个工作线程最后不足 50 条的写入（下次扫描重算，不影响正确性）
- 跳过缓存/临时文件按路径各级目录名匹配 cache/temp/tmp/缓存/临时，路径中恰好含这些子串的合法目录也会被跳过（可取消勾选关闭）
- MFT 极速扫描需管理员权限 + pyfsntfs 库，否则降级普通扫描（较慢）

## 版本历史

- **v0.9.6**（2026-09-15）：
  - ✅ 新增 USN 增量缓存：首次 MFT 扫描后把目录大小写入 SQLite（size_cache.db），后续启动秒级加载 + 后台读 USN Journal 增量追平，消除每次启动 88 秒全盘扫描
  - ✅ 新增 `core/usn_journal.py`（FSCTL_QUERY/READ_USN_JOURNAL 封装 + USN_RECORD_V2 解析）与 `core/size_cache.py`（缓存管理 + UsnUpdater 增量）
  - ✅ 扫描器 `FileNode` 加 `frn`/`parent_frn`（完整 64 位 file_reference），MFT 扫描器暴露 `root_frn`
  - ✅ 缓存加载走后台线程（CacheLoadThread），消除百万条目加载时的 UI 假死
  - ✅ 缓存目录选择：打包 exe → exe 同目录（不占 C 盘）；源码运行 → LOCALAPPDATA；统一到 `utils/paths.py`
  - ✅ 修复 frn 溢出（64 位无符号 vs SQLite 有符号，`_to_signed`/`_to_unsigned` 转换）
  - ✅ 修复缓存加载闪退（0xc0000409：QThread destroyed while running，改用 `_live_scan_threads` 容器持有引用）
  - ✅ 修复 requirements.txt 包名（`pyfsntfs` → `libfsntfs-python`）
- **v0.9.5**（2026-08-25）：
  - ✅ 新增 Tab 框架（QTabWidget）
  - ✅ 新增缓存清理Tab（9大类54个缓存路径扫描、安全评级、分类过滤）
  - ✅ 新增重复文件筛选Tab（三级哈希、多线程并行、导入磁盘分析结果）
  - ✅ 磁盘分析Tab新增文件列表导出（按盘符区分JSON）
  - ✅ 修复重复文件扫描大目录后闪退（datetime 异常未捕获 + windowed 级联、排序竞态、QThread 生命周期、SQLite 并发卡死）
  - ✅ 重复文件Tab勾选框改造：用 Qt 原生 CheckStateRole + 居中 delegate 替换文本字符模拟（修复重复文件/硬链接组可勾选状态错乱、复选框太小不居中）
  - ✅ 勾选性能优化：单点切换 0ms（增量计数）、全选/保留策略用 setUpdatesEnabled+blockSignals 包裹消除数秒延迟、勾选列不参与排序
  - ✅ 复选框样式修复：delegate 改用 CE_CheckBox + QStyleOptionButton（PE_IndicatorCheckBox 在 fusion style 下不画对勾），并用 int 比较 CheckState（PyQt6 中 index.data 返回 int 与 Qt.CheckState 枚举比较恒 False），勾选与未勾选视觉区分清晰
  - ✅ 复选框居中修复：禁用 QTreeWidget 树形缩进（setRootIsDecorated(False)/setIndentation(0)），使列0成为普通列——此前树形 indentation 占去列0前段，导致居中复选框位置错乱、入侵"组"列、被相邻列遮挡渲染不上色
  - ✅ 缓存清理Tab复选框改造：用原生 CheckStateRole + 居中 delegate（CE_CheckBox）替代文本字符模拟，同步重复文件Tab的复选框样式与勾选逻辑
  - ✅ 缓存清理Tab双树布局：上方显示安全等级为"安全"的条目（可直接删除），下方显示"谨慎/危险"条目（移至回收站），各自独立排序、互不混合
  - ✅ 缓存清理Tab移除安全等级筛选框（双树已按安全分区，该筛选冗余）
  - ✅ 缓存清理Tab新增"扫描自选目录"：选择目录后递归发现 cache/temp/tmp/缓存/临时 相关文件夹并评估安全等级显示（按文件年龄评估，归"其他"分类）
  - ✅ 磁盘分析与重复文件扫描逻辑整合：
    - 磁盘分析Tab默认扫描深度改为"完全扫描"，去掉"导出列表"按钮（根目录扫描时自动导出对应盘符JSON）
    - 重复文件Tab扫描方式沿用磁盘分析（MFT优先，失败降级普通扫描），新增 PathScanThread 统一路径扫描
    - 重复文件Tab根目录扫描：优先复用1天内生成的盘符JSON，超过1天则MFT扫描并自动生成新JSON覆盖旧文件
  - ✅ 磁盘分析Tab扫描进度反馈：新增扫描计时器（每秒显示已用时间），MFT扫描后构建目录树/填充列表/渲染树图各阶段分步更新状态栏并 processEvents，避免大目录83秒构建期假死
  - ✅ 重复文件Tab完整哈希阶段取消修复：哈希循环内检查取消标志（大文件mmap不再阻塞数十秒），_check_scan_done 识别取消状态走 _on_scan_cancelled 正常收尾（不再卡在"正在停止"或误报异常退出）
  - ✅ 重复文件Tab MFT路径扫描取消修复：PathScanThread 取消后 emit finished 收尾（此前静默 return 导致 UI 无信号卡死），MFT取消后不再降级到 os.walk 整盘扫描；_on_path_scan_finished 识别取消显示"扫描已取消"
  - ✅ 扫描进度反馈同步：重复文件Tab与磁盘分析Tab共用扫描计时器机制（每秒显示已用时间），MFT路径扫描+三级哈希比对+结果构建各阶段分步更新状态栏并 processEvents，全程不假死
  - ✅ 磁盘分析Tab支持复用JSON：扫根目录时若存在1天内生成的盘符JSON，弹窗询问"复用近期结果（几秒加载快照）"或"重新扫描（MFT实时最新）"；复用时从扁平文件列表重建目录树渲染矩形树图
  - ✅ 导入磁盘分析结果现在统一应用最小文件大小筛选（此前导入路径绕过筛选）
  - ✅ 重复文件与硬链接组改用双 QTreeWidget 隔离（QSplitter 垂直堆叠），各自独立排序、互不混合显示
  - ✅ Tab顺序调整：磁盘分析 → 重复文件 → 缓存清理（缓存清理移到最后）；版本号升至 0.9.5
  - ✅ JSON写入原子化+读取容错：导出改为临时文件+os.replace原子写（避免中断留下半截损坏JSON）；读取处检测到损坏JSON时删除并提示重新扫描，不再报错崩溃
  - ✅ JSON导出失败可见化：auto自动导出失败不再静默吞掉（此前导致JSON不生成、用户每次重新扫描却不知原因），现在弹窗提示失败原因+状态栏提示+控制台traceback；导出失败时清理残留.tmp文件
  - ✅ 修复含surrogate代理字符路径的JSON导出失败：C盘某些损坏/特殊文件名含孤立UTF-16代理字符，json.dump(ensure_ascii=False)写UTF-8文件抛UnicodeEncodeError导致导出中断、JSON不生成（每次都重新扫描的根因）。新增_safe_path对路径做代理安全化（孤立代理替换为U+FFFD），磁盘分析Tab和重复文件Tab导出/收集时统一应用
  - ✅ 修复JSON加载后树双份/切盘混入：_load_from_json重建树前未清空旧树，导致新盘内容叠加到旧盘树项上。改为加载前 result_tree.clear()+treemap_widget.clear_display()+重置current_node
  - ✅ 重复文件Tab新增跳过缓存/临时文件：哈希比对前过滤掉路径各级目录名含 cache/temp/tmp/缓存/临时 的文件（规则与缓存清理Tab一致），不参与比对加快效率；新增"跳过缓存/临时文件"复选框控制开关，统计栏显示跳过数量
- **v0.2.1**（2026-08-17）：修复进度卡住、管理员重启、junction 问题
- **v0.2.0**（2026-08-17）：多进程 MFT、懒加载、根目录显示

## 许可证

MIT License

---

**最后更新**: 2026-09-15
