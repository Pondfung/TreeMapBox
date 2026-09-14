# USN Journal 增量缓存 — 启动即用方案（细化版 v2）

> v0.9.6 升级计划。目标：给 TreeMapBox 加「目录大小持久化缓存 + USN Journal 增量更新」，
> 首次全量扫描 88s 后，后续启动从 SQLite 缓存秒级加载，后台 USN 线程追平增量。
> 本版已并入 API 实测修正、盲点与风险清单、细化的任务拆分。

## 一、技术选型（已确认）

| 项 | 选择 | 说明 |
|---|---|---|
| 缓存存储 | SQLite | 复用 hash_cache.py 的 WAL + 线程本地连接模式 |
| 增量来源 | USN Journal | `FSCTL_QUERY/READ_USN_JOURNAL`，pywin32 `win32file.DeviceIoControl` |
| FRN 映射 | pyfsntfs `entry.file_reference` | **完整 64 位**，含 16 位 sequence number |
| 全量扫描 | 保留现有 pyfsntfs MFT 并行扫描 | 88s / 106 万文件 |

### 关键 API 修正（相对 v1 方案）
1. `entry.file_reference` 是 **int 属性**，不是 `entry.file_reference.value`（v1 写错了）。
2. 完整 64 位 file_reference 格式 = `[16 位 sequence][48 位 MFT entry 号]`。
   - 与 USN_RECORD 的 `FileReferenceNumber` **同构**，直接按 64 位对齐即可。
   - `& 0xffffffffffff` 只在需要「MFT 条目号」时用（调试/取 entry），映射用全 64 位，避免 entry 号复用串数据。
3. parent_frn 在 MFT 遍历时从 stack 传递，**不调 `get_parent_file_reference()`**（该方法要读 $FILE_NAME attribute，百万文件下开销不可接受）。

---

## 二、USN API 参考（Phase 1 直接照抄）

### 打开卷句柄
```python
import win32file
h = win32file.CreateFile(
    r'\\.\C:',                       # 卷路径
    win32file.GENERIC_READ,
    win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
    None, win32file.OPEN_EXISTING, 0, None)
```

### 查询 journal 信息（FSCTL_QUERY_USN_JOURNAL）
输出 `USN_JOURNAL_DATA_V0`，56 字节，`struct.unpack('QQQQQQQ', buf)`：
```
UsnJournalID, FirstUsn, NextUsn, LowestValidUsn, MaxUsn, MaximumSize, AllocationDelta
```

### 读取记录（FSCTL_READ_USN_JOURNAL）
输入 `READ_USN_JOURNAL_DATA_V0`，40 字节，`struct.pack('QIIQQQ', ...)`：
```
StartUsn(Q), ReasonMask(I), ReturnOnlyOnClose(I), Timeout(Q), BytesToWaitFor(Q), UsnJournalID(Q)
```
- `Timeout=0`（立即返回当前可用记录）、`BytesToWaitFor` 给一个缓冲大小。
- 输出缓冲：**前 8 字节是 next USN**，之后是 0..N 条 `USN_RECORD_V2`，按 `RecordLength` 步进。

### USN_RECORD_V2 布局
```
I  RecordLength          I  SourceInfo
H  MajorVersion          I  SecurityId
H  MinorVersion          I  FileAttributes
Q  FileReferenceNumber   H  FileNameLength
Q  ParentFileReferenceNumber  H  FileNameOffset
Q  Usn                   WCHAR FileName[1]  (UTF-16, FileNameOffset 从记录起点算)
Q  TimeStamp
I  Reason
```
解析循环：`pos = 8`（跳过 next USN），每条 `RecordLength` 决定下一条偏移；`FileName` 从 `offset_in_buffer + FileNameOffset` 取 `FileNameLength` 字节，UTF-16 解码。

### 关心的 Reason 掩码
```
FILE_CREATE=0x100, FILE_DELETE=0x200,
RENAME_OLD_NAME=0x1000, RENAME_NEW_NAME=0x2000,
DATA_EXTEND=0x02, DATA_TRUNCATION=0x04, DATA_OVERWRITE=0x01
```
改名/移动会产生**两条**记录（OLD_NAME + NEW_NAME，父子不同）。这是路径重建的入口。

---

## 三、数据模型（调整）

```sql
-- 位置：打包成 exe 时放 exe 同目录（不占 C 盘）；源码运行时放 %LOCALAPPDATA%\TreeMapBox\size_cache.db（不再放 %TEMP%，会被清理）
CREATE TABLE size_cache (
  path TEXT PRIMARY KEY,        -- 大小写规范化后的全路径
  name TEXT,                    -- 文件名（改名重建路径用）
  frn INTEGER,                  -- 完整 64 位 file_reference
  parent_frn INTEGER,           -- 完整 64 位
  size INTEGER,
  is_dir INTEGER,
  mtime REAL,
  deleted INTEGER DEFAULT 0,    -- 软删除标记：物理删行前保留旧 size 供反减
  scan_time REAL
);
CREATE INDEX idx_frn ON size_cache(frn);
CREATE INDEX idx_parent_frn ON size_cache(parent_frn);
CREATE TABLE journal_state (
  volume_serial TEXT PRIMARY KEY,
  journal_id INTEGER,
  next_usn INTEGER,
  last_update REAL
);
```

---

## 四、启动流程

```
_start_scan(path)
  ├─ size_cache.is_valid(path)? ──是 → _load_from_size_cache → 后台 UsnUpdater → 完成
  ├─ JSON 24h 复用（现有逻辑）──是 → 加载
  └─ 全量 MFT 扫描 → 写 JSON + size_cache + journal_state
```

`is_valid` 判定（并入降级路径）：
1. 卷句柄能打开，且 `FSCTL_QUERY_USN_JOURNAL` 成功（**失败 = 卷未开 journal，返回 False 走全量扫描**，不报错）；
2. `journal_state.journal_id == 当前 UsnJournalID`；
3. `next_usn >= FirstUsn`（否则溢出）；
4. 缓存行数与体积合理（可选：行数 > 0）。

---

## 五、USN 增量更新逻辑（细化）

1. 启动 query → 比对 journal_id / next_usn，不匹配或溢出 → 全量重扫。
2. `catch_up(start_usn)` 分页读记录，逐条按 reason 分类：
   - **FILE_CREATE / RENAME_NEW_NAME**：stat 路径拿 size，UPSERT 进 size_cache，delta = 新 size。
   - **FILE_DELETE / RENAME_OLD_NAME**：缓存里查旧 size，delta = -旧 size，行打 `deleted=1`（不物理删）。
   - **DATA_EXTEND/TRUNCATION/OVERWRITE**：stat 新 size，delta = 新 size - 旧 size。
3. 每条记录沿 `parent_frn` 链回算祖先目录的 size 增量（批量事务，每 N 条 commit）。
4. 物理清理：定期把 `deleted=1` 且超过阈值时间的行删除（反减已完成，可安全删）。
5. 追平后更新 `journal_state.next_usn`。

---

## 六、盲点与风险（v2 扩充）

1. **缓存位置**：`%TEMP%` 会被系统清理 → 改 `%LOCALAPPDATA%\TreeMapBox\`。
2. **journal 未开启/被删**：query 报 `ERROR_INVALID_FUNCTION`。is_valid 直接降级全量扫描；可选 `FSCTL_CREATE_USN_JOURNAL` 重建。
3. **journal 溢出**：journal_id 变 或 `next_usn < first_usn` → 无条件全量重扫，宁慢勿错。
4. **删除无法 stat**：删除记录反减依赖缓存里的旧 size → 行必须软删除，先反减再物理删。
5. **目录改名**：RENAME 双记录；子目录树路径全错 → v1 沿 parent_frn 链 + 缓存 name 列重建路径。
6. **FRN 复用**：MFT entry 号会复用（seq number 变化）。必须用完整 64 位 file_reference 对齐，只用 48 位会串数据。
7. **回算写放大**：删一个大目录 = 数万条记录 × 各自祖先链 UPDATE。v1 按 parent_frn 聚合 delta 后再批量 UPDATE，控制事务数。
8. **并发写库**：后台 UsnUpdater 与用户手动重扫会同时写 size_cache → 重扫前先停止/等待 updater。
9. **权限**：读 USN journal 通常普通权限即可，但本项目 MFT 扫描已在管理员上下文，无额外要求。
10. **结构体解析**：`FileNameOffset` 是相对记录起点偏移，不是相对缓冲区起点——解析时用「缓冲区位置 + FileNameOffset」。

---

## 七、实施步骤（任务拆分）

### Task 1 — core/usn_journal.py：USN Journal 引擎 (P0)
1. 常量：FSCTL_*、USN_REASON_*、V2 结构体 struct 格式串。
2. `open_volume(drive) -> handle`（GENERIC_READ + share）。
3. `query_journal(h) -> dict(journal_id, first_usn, next_usn, ...)`。
4. `read_page(h, start_usn, jid, mask) -> (records, next_usn)`，解析 V2 记录。
5. `catch_up(h, start_usn, jid, mask) -> (records, next_usn)` 分页循环。
6. `is_overflow(saved_id, saved_usn, current) -> bool`。
7. **只读验证脚本 `debug_usn.py`**（用户环境管理员跑）：query C 盘、read 一页、打印 frn/parent_frn/name/reason。
**验收**：能解析出 frn/parent_frn/name/reason 且与 `fsutil usn enumdata` 对得上。

### Task 2 — core/size_cache.py：SQLite 缓存 + UsnUpdaterThread (P0)
1. `SizeCacheManager`：建表（含 deleted 列）、`save_scan(files, scan_path)`、`load(path)`、`is_valid(path)`。
2. `load` 返回能直接喂给 `_convert_mft_results_to_tree` 的 dict 列表（补 name/is_dir/frn/parent_frn）。
3. `UsnUpdaterThread(QThread)`：query → catch_up → 分类 → stat → 祖先回算 → 写库 → 更新 next_usn。
4. FRN→path 解析：沿 parent_frn 链查 SQLite 拼路径，未知父进 pending 队列（改名场景）。
5. 回算：按 parent_frn 聚合 delta，批量 UPDATE，每 500 条 commit。
**验收**：全量扫描后 save_scan 成功；is_valid 返回 True；touch 新文件后 UsnUpdater 能更新 size。

### Task 3 — 扫描器加 frn/parent_frn 字段 (P0)
1. `core/scanner.py` 与 `core/parallel_scanner.py` 的 FileNode 各加 `frn=0, parent_frn=0`（两处，鸭子类型混用）。
2. `core/parallel_mft_scanner.py`：`_scan_subtree_worker` 的 stack 改为 `(entry, path, parent_frn)`，files.append 加 `frn`/`parent_frn`（try 包裹）。
3. `core/mft_scanner.py`：同样改 stack 结构 + append。
**验收**：MFT 扫描 dict 含非零 frn/parent_frn；现有 15 个测试不回归。

### Task 4 — UI 集成 (P0)
1. `disk_analysis_tab.py __init__` 初始化 SizeCacheManager。
2. `_start_scan`（现 328 行）在 JSON 判断前插入 `size_cache.is_valid` 分支 → `_load_from_size_cache`。
3. `_load_from_size_cache`：load → `_convert_mft_results_to_tree` → `_populate_tree` → `set_data`。
4. `_on_mft_scan_finished`（现 652 行）加 `save_scan` + journal_state 记录。
5. 加载完成后启动 UsnUpdaterThread；重扫前先停止 updater（并发互斥）。
**验收**：首次扫描后第二次启动秒开；新建/删除文件后缓存 size 正确更新。

### Task 5 — 测试与验证 (P1)
1. `test_usn_journal.py`：真实 query/read C 盘（用户环境跑）。
2. `test_size_cache.py`：save/load/is_valid/增量回算/改名重建。
3. 手动验证：扫描 → 关 → 改文件 → 重开 → size 正确。
4. 回归：现有 test_*.py 全过。

### Task 6 — FileNode 去重（可选，P2，独立于主链路）
合并 scanner.py / parallel_scanner.py 的同名 FileNode，消除「改字段要改两处」的技术债。不阻塞主线。

---

## 八、验证方式
- `python debug_usn.py`：只读验证 USN 能读、FRN 对得上 fsutil。
- `python main.py`：首次扫描 → 关 → 重开秒开。
- `python -m pytest test_*.py`：无回归。

## 九、关键文件清单
| 文件 | 变更 |
|---|---|
| core/usn_journal.py | 新增：USN 引擎 |
| core/size_cache.py | 新增：缓存 + UsnUpdaterThread |
| core/scanner.py | 改：FileNode 加 frn/parent_frn |
| core/parallel_scanner.py | 改：FileNode 加 frn/parent_frn（副本） |
| core/parallel_mft_scanner.py | 改：stack 传 parent_frn + append |
| core/mft_scanner.py | 改：stack 传 parent_frn + append |
| ui/disk_analysis_tab.py | 改：缓存加载/写入集成 |
| debug_usn.py | 新增：只读验证脚本 |
| test_usn_journal.py / test_size_cache.py | 新增：测试 |
