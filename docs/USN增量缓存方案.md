# USN Journal 增量缓存 — 启动即用方案

## 项目概述
为 TreeMapBox v0.9.5 增加"目录大小持久化缓存 + USN Journal 增量更新"层，实现启动即用（秒开树图），无需每次全盘扫描。首次扫描 88s 后，后续启动从 SQLite 缓存秒级加载，后台 USN 线程追平增量变更。

## 技术选型
- **缓存存储**：SQLite（复用 hash_cache.py 的 WAL + 线程本地连接模式）
- **增量来源**：USN Journal（FSCTL_READ_USN_JOURNAL，pywin32 win32file）
- **FRN 映射**：pyfsntfs entry.file_reference.value，扫描时顺带采集
- **全量扫描**：保留现有 pyfsntfs MFT 多进程扫描（88s/106万文件）

## 架构设计

### 新增模块
```
core/
├── usn_journal.py     # USN 常量/结构体/query/read/catch_up/溢出检测
├── size_cache.py      # SizeCacheManager(SQLite) + UsnUpdaterThread(QThread)
└── scanner.py         # FileNode 加 frn/parent_frn 字段（现有文件改）
```

### 数据模型
```sql
-- size_cache.db（%TEMP%/treemapbox_size_cache.db）
CREATE TABLE size_cache (
  path TEXT PRIMARY KEY, name TEXT, frn INTEGER,
  parent_frn INTEGER, size INTEGER, is_dir INTEGER,
  mtime REAL, scan_time REAL
);
CREATE INDEX idx_frn ON size_cache(frn);
CREATE TABLE journal_state (
  volume_serial TEXT PRIMARY KEY, journal_id INTEGER,
  next_usn INTEGER, last_update REAL
);
```

### 启动流程（_start_scan 插入点：disk_analysis_tab.py:344 之前）
```
_start_scan(path)
  ├─ size_cache.is_valid(path)? ─────── 是 → _load_from_size_cache → 后台USN增量 → 完成
  ├─ JSON 24h 复用（现有逻辑，兜底）── 是 → 加载
  └─ 全量MFT扫描 → 写JSON + size_cache + journal_state
```

### USN 增量更新逻辑
1. 启动时 query_journal → 比对 saved journal_id/next_usn
2. journal_id 不匹配或 next_usn < first_usn → 全量重扫
3. 否则 catch_up 读记录 → 按 FRN 合并 → 路径解析 → stat 新大小 → 沿 parent_frn 链回算祖先 delta

## 实施步骤

### Phase 1: core/usn_journal.py — USN Journal 引擎 (P0)
**目标**: 封装 FSCTL_QUERY/READ_USN_JOURNAL，提供 query/read/catch_up/溢出检测
1. 定义常量（FSCTL_*、Reason 掩码、结构体格式串）
2. `_open_volume(drive)` 打开卷句柄（FILE_SHARE_READ|WRITE）
3. `query_journal(h)` → {journal_id, first_usn, next_usn, max_usn}
4. `read_page(h, start_usn, jid, mask)` → (records, next_usn)
5. `catch_up(h, start_usn, jid, mask)` → (all_records, next_usn)
6. `is_overflow(saved, current)` → bool（journal_id 变或 next_usn < first_usn）
**交付物**: core/usn_journal.py
**acceptance**: 能 query C 盘 journal、read 一页记录、解析出 frn/parent_frn/name/reason

### Phase 2: core/size_cache.py — SQLite 缓存管理 (P0)
**目标**: SizeCacheManager 复用 hash_cache 模式，UsnUpdaterThread 后台增量
1. SizeCacheManager: 建表、save_scan(files, scan_path)、load(path)→List[dict]、is_valid(path)
2. is_valid: 查 journal_state，比对当前 journal_id/next_usn 是否可增量
3. UsnUpdaterThread(QThread): query→catch_up→路径解析→stat→回算祖先→写库
4. 路径解析: 沿 parent_frn 链查 SQLite 拼路径，未知父入 pending 队列
5. 祖先回算: delta 沿 parent_frn 链批量 UPDATE 目录 size
**交付物**: core/size_cache.py
**acceptance**: 全量扫描后能 save_scan；is_valid 返回 True；UsnUpdater 能追平增量并更新 size

### Phase 3: 扫描器加 FRN 字段 (P0)
**目标**: MFT 扫描结果带 frn/parent_frn，供缓存建立 FRN→path 映射
1. core/scanner.py FileNode 加 frn=0, parent_frn=0 字段
2. core/parallel_mft_scanner.py:96 files.append 加 frn/parent_frn（try 包裹）
3. core/mft_scanner.py:227 同上
**交付物**: 改动的 3 个文件
**acceptance**: MFT 扫描结果 dict 含 frn/parent_frn 非零值；现有功能不回归

### Phase 4: UI 集成 — 缓存加载 + 后台增量 (P0)
**目标**: _start_scan 优先走缓存，扫描完成写缓存
1. disk_analysis_tab.py __init__ 初始化 SizeCacheManager
2. _start_scan:344 前插入 size_cache.is_valid 分支 → _load_from_size_cache
3. _load_from_size_cache: 读行→转 dict→_convert_mft_results_to_tree→_populate_tree→set_data
4. _on_mft_scan_finished:721 旁加 size_cache.save_scan + journal_state 记录
5. 加载完成后启动 UsnUpdaterThread，finished 后可选刷新树
**交付物**: disk_analysis_tab.py 改动
**acceptance**: 首次扫描后第二次启动秒开；新建/删除文件后缓存 size 正确更新

### Phase 5: 测试与验证 (P1)
**目标**: 验证增量正确性 + 回归测试
1. test_usn_journal.py: mock/真实 query+read C 盘
2. test_size_cache.py: save/load/is_valid/增量回算
3. 手动验证: 扫描→关→改文件→重开→size 正确
4. 回归: 现有 15 个 test_*.py 全过
**交付物**: 2 个测试文件
**acceptance**: 增量回算正确；无回归

## 风险与注意事项
- USN 记录无文件大小 → 增量必须 stat 路径，FRN→path 映射是硬依赖
- FILE_DELETE 无法 stat → 用缓存旧 size 从祖先减去
- 目录改名 → 子孙路径全错，v1 沿 parent_frn 链重建路径（缓存存 name 列）
- journal 溢出 → 无条件全量重扫，宁慢勿错
- 需管理员权限（与 MFT 扫描同一上下文，无额外要求）
- UsnUpdaterThread 生命周期管理复用现有 QThread+deleteLater 模式

## 验证方式
- `python main.py` 手动验证首次扫描→关→重开秒开
- 新建/删除/修改文件后缓存 size 正确
- `python -m pytest test_*.py` 无回归
- USN 增量: 扫描后 touch 新文件 → 重开 → 树图含新文件且 size 正确

## 关键文件清单
| File path | Description |
|-----------|-------------|
| core/usn_journal.py | USN Journal 引擎（新增） |
| core/size_cache.py | SQLite 缓存 + UsnUpdaterThread（新增） |
| core/scanner.py | FileNode 加 frn/parent_frn（改） |
| core/parallel_mft_scanner.py | 扫描结果加 FRN（改） |
| core/mft_scanner.py | 扫描结果加 FRN（改） |
| ui/disk_analysis_tab.py | 缓存加载/写入集成（改） |
| test_usn_journal.py | USN 引擎测试（新增） |
| test_size_cache.py | 缓存测试（新增） |