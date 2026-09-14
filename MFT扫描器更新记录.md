# MFT 扫描器更新记录

## 更新日期
2026-08-14

## 更新内容

### 1. 适配新版 pyfsntfs API (版本 20260727)

旧版 API 已废弃，更新为主要变更：

| 旧版 API | 新版 API |
|---------|---------|
| `volume.get_mft()` | 已移除 |
| `mft.get_entry(i)` | 已移除 |
| 直接遍历 `volume.file_entries` | `volume.get_root_directory()` + `sub_file_entries` |

### 2. 新版扫描方法

```python
# 正确的打开方式
volume = pyfsntfs.volume()
volume.open(r'\\.\C:')  # 注意：需要双反斜杠

# 目录遍历方式（推荐）
root = volume.get_root_directory()
for entry in root.sub_file_entries:
    name = entry.get_name()
    is_dir = entry.get_number_of_sub_file_entries() > 0
    size = entry.get_size()
    # ...
```

### 3. 更新的文件

| 文件 | 说明 |
|------|------|
| `core/mft_scanner.py` | MFT 扫描器核心代码（已更新） |
| `test_mft_scanner.py` | 测试脚本（已更新） |
| `build_exe.py` | 打包配置（已更新） |

## 测试结果

| 指标 | 数值 |
|------|------|
| MFT 总条目数 | 2,030,336 |
| 扫描到的文件/目录 | 1,057,302 |
| 扫描速度 | 约 10-15 秒（整个 C 盘） |
| 测试状态 | ✅ 通过 |

## 已知问题

1. **控制台乱码**：Windows 控制台编码问题，不影响功能
2. **需要管理员权限**：MFT 扫描需要管理员权限，否则自动降级到普通扫描

## 打包信息

| 属性 | 值 |
|------|-----|
| 输出文件 | `dist/TreeMapBox.exe` |
| 文件大小 | 约 36 MB |
| Python 版本 | 3.13.1 |
| 打包工具 | PyInstaller 6.21.0 |

## 下一步计划

1. [ ] 优化扫描性能（考虑多线程）
2. [ ] 添加扫描进度显示
3. [ ] 改进错误处理
4. [ ] 添加取消扫描功能

## 相关文档

- `docs/MFT扫描功能说明.md` - MFT 扫描功能说明
- `docs/使用说明.md` - 用户使用说明
- `docs/更新说明.md` - 版本更新说明