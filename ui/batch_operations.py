#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量操作方法 - 添加到 main_window.py

将这些方法复制到 MainWindow 类中
"""

def _show_context_menu_enhanced(self, position):
    """显示右键菜单（支持多选）"""
    # 获取当前选中的项
    item = self.result_tree.itemAt(position)
    if not item:
        return

    # 获取所有选中项
    selected_items = self.result_tree.selectedItems()
    selected_count = len(selected_items)

    # 创建菜单
    menu = QMenu(self)

    # 根据选中数量调整菜单项
    if selected_count == 1:
        # 单选菜单
        open_action = QAction("打开文件夹", self)
        open_action.triggered.connect(lambda: self._open_in_explorer(item))
        menu.addAction(open_action)

        copy_action = QAction("复制路径", self)
        copy_action.triggered.connect(lambda: self._copy_path(item))
        menu.addAction(copy_action)

        menu.addSeparator()

        delete_action = QAction("删除到回收站", self)
        delete_action.triggered.connect(lambda: self._delete_to_recycle(item))
        menu.addAction(delete_action)

        menu.addSeparator()

        properties_action = QAction("属性", self)
        properties_action.triggered.connect(lambda: self._show_properties(item))
        menu.addAction(properties_action)
    else:
        # 多选菜单
        count_label = menu.addAction(f"已选中 {selected_count} 项")
        count_label.setEnabled(False)  # 标题项不可点击

        menu.addSeparator()

        open_action = QAction("批量打开文件夹", self)
        open_action.triggered.connect(lambda: self._batch_open(selected_items))
        menu.addAction(open_action)

        copy_action = QAction("复制所有路径", self)
        copy_action.triggered.connect(lambda: self._batch_copy_paths(selected_items))
        menu.addAction(copy_action)

        menu.addSeparator()

        delete_action = QAction(f"批量删除 ({selected_count} 项)", self)
        delete_action.triggered.connect(lambda: self._batch_delete(selected_items))
        menu.addAction(delete_action)

    # 显示菜单
    menu.exec(self.result_tree.viewport().mapToGlobal(position))

def _batch_open(self, items):
    """批量打开文件夹"""
    import subprocess
    count = 0
    for item in items:
        path = item.text(2)
        if Path(path).exists():
            subprocess.run(f'explorer /select,"{Path(path).absolute()}"', shell=True)
            count += 1

    self.status_label.setText(f"已打开 {count} 个文件夹")

def _batch_copy_paths(self, items):
    """批量复制路径"""
    from PyQt6.QtWidgets import QApplication

    paths = [item.text(2) for item in items]
    text = "\n".join(paths)
    QApplication.clipboard().setText(text)
    self.status_label.setText(f"已复制 {len(paths)} 个路径")

def _batch_delete(self, items):
    """批量删除"""
    try:
        import send2trash
    except ImportError:
        QMessageBox.critical(
            self,
            "错误",
            "缺少 send2trash 库\n请运行: pip install send2trash"
        )
        return

    # 统计信息
    total_size = 0
    cache_count = 0
    paths = []

    for item in items:
        path = item.text(2)
        size_str = item.text(1)

        # 提取大小（从字符串转换为字节数）
        # 假设格式是 "123.4 MB"
        try:
            size_parts = size_str.split()
            size_value = float(size_parts[0])
            size_unit = size_parts[1]
            multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
            total_size += size_value * multipliers.get(size_unit, 1)
        except:
            pass

        paths.append(path)

        # 检查缓存标记
        is_cache, _ = item.data(0, Qt.ItemDataRole.UserRole)
        if is_cache:
            cache_count += 1

    # 格式化总大小
    def format_size_simple(size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    total_size_str = format_size_simple(total_size)

    # 构建确认消息
    message = f"确定要删除以下内容吗？\n\n"
    message += f"选中项数: {len(paths)}\n"
    message += f"总大小: {total_size_str}\n"
    if cache_count > 0:
        message += f"缓存文件夹: {cache_count} 个\n"

    if len(paths) <= 10:
        message += f"\n路径列表:\n" + "\n".join(paths[:10])
    else:
        message += f"\n路径列表（前10个）:\n" + "\n".join(paths[:10])
        message += f"\n... 还有 {len(paths) - 10} 项"

    # 确认删除
    reply = QMessageBox.question(
        self,
        "批量删除确认",
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No
    )

    if reply == QMessageBox.StandardButton.Yes:
        deleted_count = 0
        failed_paths = []

        for i, item in enumerate(items):
            path = item.text(2)
            try:
                send2trash.send2trash(path)
                # 从树中移除该项
                parent = item.parent()
                if parent:
                    parent.removeChild(item)
                else:
                    index = self.result_tree.indexOfTopLevelItem(item)
                    self.result_tree.takeTopLevelItem(index)
                deleted_count += 1

                # 更新进度（每删除10个更新一次）
                if deleted_count % 10 == 0:
                    self.status_label.setText(f"已删除 {deleted_count}/{len(items)} 项...")
                    QApplication.processEvents()  # 刷新UI
            except Exception as e:
                failed_paths.append(f"{path}: {str(e)}")

        # 显示结果
        result_message = f"已删除 {deleted_count} 个项目到回收站\n总大小: {total_size_str}"
        if failed_paths:
            result_message += f"\n\n失败 {len(failed_paths)} 个:\n" + "\n".join(failed_paths[:5])
            if len(failed_paths) > 5:
                result_message += f"\n... 还有 {len(failed_paths) - 5} 个失败"

        QMessageBox.information(self, "删除完成", result_message)
        self.status_label.setText(f"批量删除完成 - 已删除 {deleted_count} 项")


# 快捷键支持 - 添加到 _setup_ui 方法
def _setup_shortcuts(self):
    """设置快捷键"""
    from PyQt6.QtGui import QShortcut, QKeySequence

    # Ctrl+A 全选
    self.shortcut_select_all = QShortcut(QKeySequence("Ctrl+A"), self)
    self.shortcut_select_all.activated.connect(self._select_all)

    # Delete 删除选中项
    self.shortcut_delete = QShortcut(QKeySequence("Delete"), self)
    self.shortcut_delete.activated.connect(self._delete_selected)

def _select_all(self):
    """全选"""
    self.result_tree.selectAll()

def _delete_selected(self):
    """删除选中项"""
    selected_items = self.result_tree.selectedItems()
    if selected_items:
        self._batch_delete(selected_items)