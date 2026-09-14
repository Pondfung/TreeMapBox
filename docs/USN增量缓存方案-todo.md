# Todos — usn-cache（对齐方案 v2）

1. [x] Task 1: core/usn_journal.py — USN Journal 引擎（含 debug_usn.py 只读验证脚本）
2. [x] Task 2: core/size_cache.py — SQLite 缓存管理 + UsnUpdater（UsnUpdaterThread 外壳归 Task 4）
3. [x] Task 3: 扫描器加 frn/parent_frn（scanner/parallel_scanner/parallel_mft_scanner/mft_scanner）
4. [x] Task 4: UI 集成 — 缓存加载 + 后台增量（disk_analysis_tab.py）
5. [x] Task 5: 测试与验证 — test_size_cache.py（4 项）+ test_usn_journal.py（6 项纯逻辑 + 真机层）+ 真机验证（扫描→改文件→重开秒开）均通过
6. [x] Task 6（可选 P2）: FileNode 去重 — 合并到 core/file_node.py 单一来源
