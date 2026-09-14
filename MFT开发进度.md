# MFT 扫描功能开发进度

## 项目信息
- **项目路径**: C:/Users/fengyutang/disk_treemap_analyzer
- **当前状态**: ✅ v0.2.1（v0.2.0 全部功能 + 心跳进度/双实例修复/junction 不跟随）已打包
- **版本**: 0.2.1
- **EXE 路径**: C:/Users/fengyutang/disk_treemap_analyzer/dist/TreeMapBox.exe

---

## 最近更新 (2026-08-17)

### ✅ 多进程 MFT 扫描调试完成

1. **修复 `core/parallel_mft_scanner.py`**
   - 修正 `scan()` 方法 try 块缩进错乱（IndentationError，模块无法导入）
   - worker 改用正确的 pyfsntfs API `get_root_directory()`（原误用不存在的 `get_root_directory_entry()`）

2. **修复 `core/mft_scanner.py`**
   - 顶层导入改相对导入 `from .parallel_mft_scanner import`
   - `HybridScanner` 改用 `self.mft_single.is_ntfs_drive()`（`ParallelMFTScanner` 无此方法）
   - `HybridScanner` 调用 `scan()`（原误调不存在的 `scan_parallel()`）

3. **修复 multiprocessing spawn 递归**
   - smoke 脚本加 `if __name__ == '__main__'` 保护 + `freeze_support()`
   - `main.py` 加 `freeze_support()`（打包后多进程必需）

4. **实测结果（C 盘 / 16 进程）**
   - 文件数：1,064,471
   - 耗时：86.87 秒
   - 对比单进程基准（1,057,644 文件 / 203 秒）→ 加速约 2.3 倍

5. **已知限制**
   - 并行度受顶层条目数限制（C:\ 下 28 个），子树大小不均导致加速比 < 进程数
   - 每个进程独立打开卷有开销
   - 文件数与单进程略有差异（+0.6%），属路径覆盖范围不同，可接受

### ✅ UI 进度显示与取消功能完成

1. **进度显示**（`core/parallel_mft_scanner.py` / `core/mft_scanner.py` / `ui/main_window.py`）
   - MFT 扫描进度回调改为真实百分比 `已扫描 n/28`，进度条 0%→100%
   - 单进程 MFT 用 `get_number_of_file_entries()` 估算总量（失败走 busy）
   - 普通扫描无总量保持 busy 模式 + 状态栏路径文本（ScanThread 50ms 节流防数百万次回调卡 UI）

2. **取消功能**
   - 三个扫描器加 `cancel()`：MFT 多进程用 `pool.terminate()` 杀子进程，单进程用 `_cancelled` 标志
   - **关键修复**：Windows 下 `imap_unordered` 在 `pool.terminate()` 后永久阻塞，改用 `apply_async`+`ready()` 轮询（0.1s 检查 `_cancelled`），取消响应 0.10s（原方案卡死 30s）
   - `HybridScanner` 加自身 `_cancelled` 门控防误降级（取消并行 MFT 不再触发单进程全盘重扫）
   - UI `_stop_scan` 重写：按线程类型分派 cancel（MFTScanThread→hybrid.cancel，ScanThread→parallel.stop），不再 `wait()` 阻塞，依赖 finished 信号清理；取消后丢弃部分结果显示"已取消"

3. **验证结果**
   - 正常扫描：1,064,952 文件 / 88.18s（与改前一致，apply_async 轮询开销可忽略）
   - 取消：2s 后调 cancel，0.10s 终止、无异常、子进程被回收
   - offscreen MainWindow 实例化正常，初始状态（_scan_cancelled=False/按钮禁用/进度条隐藏）正确

---

## 最近更新 (2026-08-14)

### ✅ 已完成

1. **优化 MFT 扫描器** (`core/mft_scanner.py`)
   - 迭代式栈遍历替代递归（避免 Python 递归开销）
   - 移除 50 万条目限制
   - 移除 `modification_time` 读取（减少 1M 次 C 调用）
   - 用 `entry.name` 属性替代 `get_name()` 函数调用
   - 进度回调间隔从 5000 提升到 20000
   - 损坏 MFT 条目自动跳过，不影响整体扫描

2. **性能测试结果**
   - C 盘扫描：1,057,644 个文件，203 秒完成
   - 路径完整性：99.99%
   - 错误处理：2 个损坏目录自动跳过

3. **已知限制**
   - C 盘有损坏 MFT 条目（704976 号），`volume.file_entries` 直接遍历不可用
   - `file_attribute_flags` 返回非标准值，无法替代 `number_of_sub_file_entries`
   - 瓶颈在 pyfsntfs C 库调用开销，Python 层面已无优化空间

4. **打包完成**
   - 输出文件：`dist/TreeMapBox.exe`
   - 已启用控制台模式（可查看扫描日志）

---

## 关键文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| **MFT 扫描器** | `core/mft_scanner.py` | MFT 扫描核心逻辑（已优化） |
| 主窗口 | `ui/main_window.py` | UI 和扫描线程 |
| 打包配置 | `build_exe.py` | PyInstaller 打包配置 |
| 测试脚本 | `test_mft_scanner.py` | MFT 扫描测试 |

---

## 下次继续调试

### 方式 1：运行测试脚本
```bash
cd C:/Users/fengyutang/disk_treemap_analyzer
python test_mft_scanner.py
```

### 方式 2：运行打包的 EXE
```bash
# 直接运行
C:/Users/fengyutang/disk_treemap_analyzer/dist/TreeMapBox.exe

# 或以管理员身份运行（启用 MFT 极速扫描）
# 右键 -> 以管理员身份运行
```

### 方式 3：重新打包
```bash
cd C:/Users/fengyutang/disk_treemap_analyzer
python build_exe.py
```

---

## 下一步计划

1. [x] 关闭控制台模式，重新打包正式版 — ✅ 2026-08-17 重新打包，无控制台黑窗，bootloader=runw.exe
2. [x] 多进程扫描（利用多核 CPU）— ✅ 16 进程 86.87s（单进程 203s，加速 ~2.3x）
3. [x] 添加扫描进度显示到 UI — ✅ MFT 百分比 0→100%，普通 busy+节流
4. [x] 添加取消扫描功能 — ✅ 多进程 0.10s 终止，防误降级
5. [x] 改进错误处理和用户提示 — ✅ 见下方"错误处理改进"

---

## 最近更新 (2026-08-17 · 错误处理改进）

### ✅ 改进错误处理和用户提示（仅严重项）

1. **扫描线程异常捕获（修复 UI 卡死）**
   - `ScanThread`/`MFTScanThread` 的 `run()` 加 try/except + `error_signal`
   - scan() 抛异常时不再永久卡在"正在扫描..."，改为弹"扫描出错"对话框 + 恢复按钮状态 + 清理线程
   - 5 处启动线程处均连接 `error_signal → _on_scan_error`

2. **扫描失败显示具体原因**
   - 各扫描器加 `self.last_error` 属性（DiskScanner/ParallelScanner/ParallelMFTScanner/MFTScanner/HybridScanner）
   - 失败路径写原因（"路径不存在: X"/"需要管理员权限"/"缺少 libfsntfs-python 库"/"无法访问磁盘"/"扫描异常: ..."），成功置 None
   - `HybridScanner._sync_last_error()` 转存子扫描器原因
   - UI `_on_scan_finished`/`_on_mft_scan_finished` 读 `last_error` 显示"扫描失败: {具体原因}"，不再笼统"扫描失败"

3. **删除失败加解决指引**
   - `_delete_to_recycle` 按异常类型给指引：权限不足→"请以管理员身份运行"/文件被占用→"请关闭占用程序"，而非直接抛 `str(e)`

4. **修复裸 except 隐患**
   - `parallel_scanner.py` 行 182 裸 `except:` → `except (OSError, PermissionError):`（不再吞 KeyboardInterrupt 等）

### 验证结果（offscreen 自动化）
- 场景1：扫描不存在路径 → last_error="路径不存在: ..."，UI 显示具体原因 ✅
- 场景2：扫描线程抛 RuntimeError → error_signal 触发，状态"扫描出错"、按钮恢复、线程清理、弹窗 ✅（此前会 UI 永久卡死）
- 5 文件 py_compile 通过，MainWindow 实例化正常

### ✅ 修复 MFT 扫描结果为空（0文件0目录）

1. **根因**：`_convert_mft_results_to_tree` 的 `node_dict` key 大小写不匹配
   - UI 输入 `C:\` → root key `'C:\\'`（大写）；MFT 扫描器返回 `c:\AMD`（小写盘符，`drive_letter.lower()` 强制）
   - `node_dict.get('c:\\')` 匹配不到 `'C:\\'` → 顶层文件挂到孤立节点而非 root → root.children 空 → 0文件0目录0大小
2. **修复**
   - `core/parallel_mft_scanner.py` + `core/mft_scanner.py`：盘符 `.lower()` → `.upper()`，路径源头规范化
   - `ui/main_window.py _convert_mft_results_to_tree`：`node_dict` key 全用 `os.path.normcase` 防御大小写/分隔符差异
   - **附带修复隐藏 bug**：`calculate_size` 递归 `child.file_count, child.dir_count = calculate_size(child)` 把返回的 int 当元组解包 → TypeError（空树时不触发，修复大小写后 children 非空才暴露）；重写为自洽的 `(size, file_count, dir_count)` 返回
3. **验证**
   - 转换单元测试 PASS：大写 scan_path + 小写盘符文件 → root.children 非空、file_count=2、dir_count=3、size=1536（修复前 0/0/0）
   - 扫描器盘符 PASS：1534 文件全 `C:\` 大写，0 小写
   - 注：缓存功能用户决定暂不做（pickle 技术验证 ~158MB，`get_serial_number` 可用于失效检测，后续需要可再做）

### ✅ 重新打包正式版（无控制台）

1. **关闭控制台模式**
   - `build_exe.py` 去掉冲突的 `--console`（原与 `--windowed` 同时存在，后者被覆盖），正式版无控制台黑窗
   - spec 文件 `console=True → False`，bootloader 由 `run.exe` 改为 `runw.exe`
2. **打包结果**
   - `dist/TreeMapBox.exe`（37.7MB，2026-08-17 11:40）
   - PyInstaller 6.21.0 + Python 3.13.1，exit code 0
   - 含 `pyi_rth_multiprocessing.py` 运行时钩子（多进程打包支持）
3. **验证**
   - 启动 EXE：进程稳定、主窗口标题"TreeMapBox v0.1.0"正常显示
   - 无 conhost 控制台窗口（符合 --windowed 预期）
   - 多进程 MFT 扫描的 GUI 交互（进度/取消/错误弹窗）需手动以管理员身份运行确认

### ✅ 重新打包（含 MFT 结果修复，2026-08-17 12:13）

- 修复 MFT 扫描结果为空 bug 后重新打包
- `dist/TreeMapBox.exe`（36.0MB，2026-08-17 12:13），bootloader=runw.exe 无控制台
- 启动验证：进程稳定存活、无控制台黑窗

### ✅ 左下角固定显示扫描/加载时间

- **背景**：MFT 扫描完成后转树+渲染（`_convert_mft_results_to_tree`+`_populate_tree`+`set_data`）对百万节点是 CPU 密集同步操作，期间软件"未响应"。用户希望量化显示耗时供参考
- **实现**（`ui/main_window.py`）：
  - 状态栏左侧加固定 `time_label`（`addWidget`，非 permanent），显示"上次: 扫描X.Xs 加载Y.Ys"
  - `_start_scan` 记录 `_scan_start = time.perf_counter()`
  - `_on_scan_finished`/`_on_mft_scan_finished` 成功路径分阶段计时：扫描耗时（到拿到结果）+ 加载耗时（转树+渲染），更新 time_label
  - time_label 不主动清空，下次扫描前保留上次值（供参考）；取消/失败不更新
- **验证**：offscreen 扫项目目录，time_label 从"上次: —"更新为"上次: 扫描0.0s 加载0.0s"格式正确，与右侧 status_label 不互相覆盖
- 注：MFT 全盘会显示真实扫描~88s + 加载耗时，用户可据此判断卡顿程度

### ✅ 懒加载根治 UI 未响应卡顿

- **根因**：`_populate_tree` 递归对 106 万节点同步建 QTreeWidgetItem（每节点 setText×4+setData+detect_cache 14 正则+addChild），且 `setSortingEnabled(True)` 每次插入重排序 → 数十秒"未响应"
- **方案**（懒加载，仅改 `ui/main_window.py`）：
  - `_populate_tree` 只建顶层 ~28 项（瞬间完成），子项展开时按需建
  - `_build_tree_item`：建项 + `setData(NODE_ROLE=FileNode, LOADED_ROLE=False)` + `setChildIndicatorPolicy(ShowIndicator)` 强制显示展开箭头
  - `_populate_children`：展开时建子项，标记已加载，`setSorting/UpdatesEnabled(False)` 包裹
  - `_walk_to_item`：沿 FileNode 按路径段逐层走（`children.get(part)` O(1)），边走边建+展开，替代 5 个 `QTreeWidgetItemIterator` 全树遍历
  - `_expand_tree_to_node`/`_find_and_select_tree_item`/`_collapse_tree_node` 改调 `_walk_to_item`
  - `_highlight_tree_by_path` 不建项（hover 高频），未展开路径返回 False
  - `_on_tree_item_expanded` 用 `item.data(NODE_ROLE)` O(1) 取节点（删 `_find_node_by_path` O(N) 递归）
  - `calculate_size` 改迭代后序遍历（防深目录 RecursionError）
  - `setUniformRowHeights(True)` + `setAnimated(False)` 性能优化
- **验证**（offscreen 13/13 PASS）：顶层只建5项/子项0/未加载/箭头显示、展开建5子项/已加载/不重复、路径定位找到/祖先展开/选中、高亮已展开True未展开False、全折叠、calculate_size深树不爆栈
- **重新打包**（2026-08-17 12:38）：`dist/TreeMapBox.exe`（36.0MB，runw.exe 无控制台），启动验证进程稳定

### ✅ 折叠时显示根目录 + 优化加载耗时（28s→2.8s）

1. **始终显示根目录子项**（`ui/simple_treemap.py`）
   - 新增 `show_root()`：显示根目录 children（不压导航栈）
   - `set_data` 末尾调 `show_root()`（扫描完成即显示，非空白）
   - `navigate_to_root` 改调 `show_root()`（不清空）
   - `main_window._collapse_all_expanded_nodes` 末尾调 `show_root()`（折叠全部后树图回根）
2. **优化 `_convert_mft_results_to_tree`**（`ui/main_window.py`）
   - 去 `sorted`（106万次count+排序）→ 单遍 + `ensure_ancestor` 祖先链向上补齐多层（替代排序保证父先建，修复原"只补一层"孤立丢数据）
   - 字符串替代 `Path` 构造（`os.path.dirname`/`normcase`/`startswith`），修盘根边界 bug（`C:\` 的 `startswith(nk_root+sep)` 会误过滤全盘 → 分支处理）
   - `calculate_size` 去 `child_results` dict，直接读子节点字段累加（`dir_count` +1 放父累加子目录时）
   - 局部绑定热函数减属性查找
3. **验证**（offscreen 5/5 PASS）：等价性(size/fc/dc/结构一致)、C:\A vs C:\AB 不混淆、子目录 scan_path 过滤、深路径30层无RecursionError、show_root(显示根+折叠回根)、**计时106万 2.83s（原28s，降幅~90%）**
4. **重新打包**（2026-08-17 13:00）：`dist/TreeMapBox.exe`（36.0MB，runw.exe 无控制台），启动验证进程稳定

### ✅ 修复普通扫描停止闪退（QThread 析构竞态）

- **现象**：普通扫描中途按停止，约 1/3 概率 segfault（无 Python traceback，C++ 层崩溃）
- **根因**：QThread 析构竞态。`ScanThread.run` 在内部最后一行 emit 自定义 `finished_signal`（早于 run 返回、早于内置 finished、早于 OS 线程退出）。槽 `_on_scan_finished` 里 `self.scan_thread = None` 触发 sip 析构 C++ QThread，而此刻 OS 线程还在 `QThreadPrivate::finish()` 收尾 → use-after-free → segfault。间歇性 = 析构 vs 线程退出的时序竞态。`ThreadPoolExecutor.shutdown(wait=True)` 排空 ~2s 把竞态窗口推到"停止后 ~2s"
- **验证根因**：纯 Python（无 Qt）停止 3 次全不崩 → 排除 ParallelScanner/ThreadPoolExecutor 本身；Qt 环境 1/3 崩 → 确认 QThread 交互
- **修复**（Qt 官方 QThread 生命周期管理）：
  - ScanThread/MFTScanThread 去掉自定义 `finished_signal`，结果存 `self.result/files/method/error` 属性，用 QThread 内置 `finished`
  - `_launch_scan_thread` 统一：`finished.connect(槽)` + `finished.connect(deleteLater)`（延迟 C++ 析构到线程已退出）+ `_live_scan_threads` 强引用保活（防 sip 先于 deleteLater GC）+ `destroyed.connect(_discard_scan_thread)`（析构后才置 scan_thread=None）
  - `_on_scan_finished`/`_on_mft_scan_finished`/`_on_scan_error` 改无参从线程属性读结果，不在槽里置 `scan_thread=None`
  - `ParallelScanner`：`with ThreadPoolExecutor` 改手动 + `finally shutdown(wait=True, cancel_futures=True)`（取消未启动 future，停止毫秒级）
  - `closeEvent` 加 `scan_thread.wait(3000)`（防退出时 destroyed while running）
- **验证**：真实 GUI 连续 30 次"启动-1.5s-停止"，**OK=30 CRASH=0**（修复前约 10 次崩）✓
- **重新打包**（2026-08-17 13:58）：`dist/TreeMapBox.exe`（36.0MB，runw.exe 无控制台），启动验证进程稳定

### ✅ 版本号升级 0.1.0 → 0.2.0

- 本次会话功能性大升级（多进程MFT扫描、进度显示、取消功能、错误处理、懒加载根治未响应、加载耗时28s→2.8s、根目录显示、停止闪退修复），minor 版本升级
- `main.py` `setApplicationVersion("0.2.0")`、`ui/main_window.py` 窗口标题 "v0.2.0"
- 需重新打包使版本号生效
- **重新打包 v0.2.0**（2026-08-17 14:03）：`dist/TreeMapBox.exe`（36.0MB，runw.exe 无控制台），窗口标题"v0.2.0"，启动验证进程稳定

### ✅ 完善 README 说明文档

- README.md 重写到 v0.2.0，反映本次全部改进
- 功能特性：MFT 极速扫描/进度显示/取消/懒加载/根目录显示/错误处理/双视图联动
- 性能数据表：MFT 88s、加载 2.8s（原28s）、扫描完成瞬间显示
- 项目结构：补全 core（4 扫描器）/ ui（4 文件）/ config / dist
- 使用说明：源码运行 + 打包 EXE + 管理员运行 MFT + 操作流程
- 已知限制：NTFS/管理员、并行度受限、超大目录展开、无结果缓存

### ✅ 修复顶层条目少时进度卡住无反馈（心跳进度）

- **现象**：扫 K 盘卡在"已扫描 1/2"很久，程序未响应但无显示，不知卡死还是加载中
- **根因**：K 盘顶层仅 2 条目（`b_jx3_released_dev_2026-06-29` + `System Volume Information`），进度粒度=顶层完成数，只 0/50/100 三点；大子树单 worker 扫时无任何反馈
- **跨进程进度方案不可行**（实测）：mp.Value/Queue/Manager.Queue/shared_memory 在 Windows 管理员 spawn 环境均因句柄复制失败（PermissionError/Synchronized 限制）
- **修复**（纯主进程侧心跳，零跨进程风险）：`parallel_mft_scanner.py` scan 轮询循环每 ~1s 即使无 worker 完成也调 progress_callback，文案含 `done/total` + 正在扫的子树名（按 async_results 实际 ready 状态取未完成 task 名）+ 已等待秒数；单进程分支扫前也回调子树名
- **验证**：真实扫 K 盘，状态栏显示 `已扫描 1/2，正在扫描「b_jx3_released_dev_2026-06-29」，已等待 59s...`，秒数持续增长（证明没卡死），心跳文案数 59 ✓
- 文案示例：`已扫描 1/2，正在扫描「b_jx3_released_dev_2026-06-29」，已等待 15s...` — 用户看到子树名+等待秒数增长即知在加载中
- **重新打包**（2026-08-17 14:35）：`dist/TreeMapBox.exe`（36.0MB，runw.exe 无控制台），含心跳进度修复

### ✅ 修复双实例 + All Users junction 跟随

- **问题1（双实例）**：`_restart_as_admin` 在 `__init__` 中调用，`ShellExecuteW` 后 `QApplication.quit()` 只设标志但 `app.exec()` 未启动，构造函数继续→`window.show()`→两实例共存。改为 `sys.exit(0)`（SystemExit 穿透构造函数立即终止）+ ShellExecuteW 返回值检查（<=32 失败如 UAC 拒绝则不退出、提示用户）
- **问题3（All Users 生造大目录）**：`C:\Users\All Users` 是 symlink→ProgramData，`Default User` 是 junction→Users。普通扫描 `is_dir()` 默认 follow_symlinks=True 跟随→递归扫目标→生造重复大目录（ProgramData 镜像）。MFT 读元数据不跟随故无此问题。修复：`parallel_scanner.py`/`scanner.py` scandir 循环加 `entry.is_junction() or entry.is_symlink()` 检测（实测：单用任一会漏另一类，必须组合），reparse 建 size=0 条目不递归
- **问题2（范围差异）**：MFT 扫全卷含系统目录（极速优势），普通扫描跳系统目录（速度+权限），用户决策保持各自策略，修 junction 后 All Users 重复消除，剩系统目录策略差异属设计
- **验证**：普通扫描 C:\Users，All Users/Default User 显示为 size=0 空条目无子项（修复前是 GB 级 ProgramData 镜像）✓
- **重新打包**（2026-08-17 15:23）：`dist/TreeMapBox.exe`（36.0MB，runw.exe 无控制台），含 junction+双实例修复

### ✅ 损坏 MFT 条目弹窗提醒

- MFT 扫描碰到损坏条目时本就跳过继续出结果（局部 try/except 容错），但用户无感知
- 改进：worker 收集损坏条目信息（位置 + 错误类型，限前 20 条）随结果返回 → scan 汇总到 `last_errors_info` → HybridScanner 转存 → UI `_on_mft_scan_finished` 完成后若非空弹"损坏条目提醒"information 对话框，列出跳过的损坏条目位置+错误类型（仅告知，无其他功能）
- 4 层容错保持不变（name/is_dir/size/sub_file_entries 各自 try/except 跳过继续），仅增加信息上报
- **验证**：8/8 接线完整 PASS（worker 返回(files,errors)→scan 收集→HybridScanner 汇总→UI 弹窗限20条含错误类型）