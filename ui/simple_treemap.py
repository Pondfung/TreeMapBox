#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的矩形树图组件 - Squarified Treemap 算法
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional
from PyQt6.QtWidgets import QWidget, QToolTip, QMenu, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QAction, QClipboard

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.scanner import FileNode, format_size


class SimpleTreemapWidget(QWidget):
    """
    矩形树图组件 - Squarified Treemap 算法
    """

    node_clicked = pyqtSignal(object)
    node_double_clicked = pyqtSignal(object)
    navigated = pyqtSignal(object)  # 导航信号，通知主窗口当前节点改变
    navigated_back = pyqtSignal(str)  # 返回上一级信号，传递要折叠的路径
    return_to_root = pyqtSignal()  # 返回根目录信号
    show_in_tree_requested = pyqtSignal(object)  # 请求在树形列表中显示节点
    node_hovered = pyqtSignal(object)  # 悬停信号，用于同步高亮

    def __init__(self):
        super().__init__()

        self.root_node: Optional[FileNode] = None
        self.current_node: Optional[FileNode] = None
        self.parent_stack: List[FileNode] = []  # 导航栈，记录父节点
        self.rects = []
        self.hovered_rect_index = -1
        self.showing_content = False  # 标记是否显示内容

        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        # 统一的蓝色系颜色方案
        self.colors = [
            QColor(100, 149, 237),   # 蓝色（Cornflower Blue）
            QColor(70, 130, 180),    # 钢蓝色
            QColor(65, 105, 225),    # 皇家蓝
            QColor(30, 144, 255),    # 道奇蓝
            QColor(0, 191, 255),     # 深天蓝
            QColor(135, 206, 250),   # 浅天蓝
            QColor(70, 130, 180),    # 钢蓝色（重复使用）
            QColor(100, 149, 237),   # 蓝色（重复使用）
        ]

    def set_data(self, node: FileNode):
        """设置数据并显示根目录子项"""
        self.root_node = node
        self.parent_stack = []
        self.show_root()  # 扫描完成即显示根目录子项（非空白）

    def show_root(self):
        """显示根目录的子项（不压导航栈，root 无父）"""
        if not self.root_node:
            self.current_node = None
            self.showing_content = False
            self.rects = []
            self.update()
            return
        self.current_node = self.root_node
        self.parent_stack = []
        self.showing_content = True
        self._calculate_layout()
        self.update()

    def show_children_of_node(self, node: FileNode, emit_signal: bool = False):
        """显示指定节点的子目录

        Args:
            node: 要显示的节点
            emit_signal: 是否发出导航信号（展开事件时为False，钻取时为True）
        """
        if node and node.children:
            # 左侧展开时，也维护导航栈（类似右侧钻取）
            if self.current_node and self.current_node != node:
                # 把当前节点添加到导航栈（只有当current_node存在且不等于node时）
                self.parent_stack.append(self.current_node)

            self.current_node = node
            self.showing_content = True
            self._calculate_layout()
            self.update()
            if emit_signal:
                self.navigated.emit(node)
        else:
            # 该节点没有子目录，清空显示
            self.current_node = None
            self.showing_content = False
            self.rects = []
            self.update()

    def clear_display(self):
        """清空显示"""
        self.current_node = None
        self.showing_content = False
        self.parent_stack = []  # 清空导航栈
        self.rects = []
        self.update()

    def navigate_back(self):
        """返回上一级"""
        if self.parent_stack:
            # 记录要折叠的节点路径（当前节点，返回前）
            path_to_collapse = self.current_node.path if self.current_node else None

            self.current_node = self.parent_stack.pop()
            self._calculate_layout()
            self.update()
            self.navigated.emit(self.current_node)

            # 发出返回信号，传递要折叠的路径
            if path_to_collapse:
                self.navigated_back.emit(path_to_collapse)
            return True
        return False

    def navigate_to_root(self):
        """返回根节点（显示根目录子项，不空白）"""
        if self.root_node and self.current_node != self.root_node:
            print(f"[DEBUG] 返回根目录")

            # 显示根目录子项
            self.show_root()

            # 发出返回根目录信号（折叠所有展开的节点）
            self.return_to_root.emit()

            # 发出导航信号
            self.navigated.emit(self.root_node)
            return True
        return False

    def get_navigation_path(self) -> str:
        """获取当前导航路径"""
        if not self.current_node:
            return ""

        parts = [node.name for node in self.parent_stack]
        parts.append(self.current_node.name)
        return " > ".join(parts[-5:])  # 最多显示5级

    def _calculate_layout(self):
        """计算矩形布局 - Squarified Treemap 算法（按排名为主，实际大小为辅）"""
        try:
            self.rects = []

            if not self.current_node or self.width() == 0 or self.height() == 0:
                return

            if not self.current_node.children:
                return

            # 按大小降序排序
            sorted_children = sorted(
                self.current_node.children.items(),
                key=lambda x: x[1].size,
                reverse=True
            )

            # 只显示前50个最大的文件/目录
            display_items = sorted_children[:50]

            if not display_items:
                return

            # 计算显示等级：排名为主（80%），实际大小为辅（20%）
            total_items = len(display_items)
            min_size = display_items[-1][1].size
            max_size = display_items[0][1].size
            size_range = max_size - min_size if max_size > min_size else 1

            adjusted_items = []

            for i, (name, node) in enumerate(display_items):
                # 计算排名等级（从15倍到1倍）
                rank_level = 15.0 - (i / (total_items - 1)) * 14.0 if total_items > 1 else 15.0

                # 计算实际大小等级（根据在最小-最大范围内的位置）
                if size_range > 0:
                    size_level = 1.0 + ((node.size - min_size) / size_range) * 14.0
                else:
                    size_level = 8.0

                # 混合：排名80% + 实际大小20%
                final_level = rank_level * 0.8 + size_level * 0.2

                adjusted_items.append((name, node, final_level))

            # 使用调整后的大小计算布局
            total_adjusted_size = sum(level for name, node, level in adjusted_items)

            # 使用 Squarified Treemap 算法
            self._squarify_adjusted(adjusted_items, 0, 0, self.width(), self.height(), total_adjusted_size)

        except Exception as e:
            print(f"[ERROR] 计算布局时出错: {e}")
            import traceback
            traceback.print_exc()

    def _squarify_adjusted(self, adjusted_items, x, y, width, height, total_size):
        """
        Squarified Treemap 算法（使用调整后的大小）
        """
        if not adjusted_items or width < 20 or height < 20 or total_size <= 0:
            return

        # 如果只有一个项目，直接显示
        if len(adjusted_items) == 1:
            name, node, adjusted_size = adjusted_items[0]
            self.rects.append({
                'x': int(x), 'y': int(y),
                'width': int(width), 'height': int(height),
                'name': name, 'size': node.size, 'node': node  # 保留原始大小用于显示
            })
            return

        # 决定分割方向
        horizontal = width >= height

        # 找到最佳的分行/分列数量
        row = []
        row_size = 0
        remaining_items = adjusted_items[:]

        # 逐个添加项目，直到宽高比最优
        for i, (name, node, adjusted_size) in enumerate(adjusted_items):
            test_row = row + [(name, node, adjusted_size)]
            test_row_size = row_size + adjusted_size

            # 计算当前行的宽高比
            current_aspect = self._worst_aspect_ratio_adjusted(row, row_size, width, height, total_size, horizontal)
            test_aspect = self._worst_aspect_ratio_adjusted(test_row, test_row_size, width, height, total_size, horizontal)

            # 如果这是第一个项目，或者宽高比在改善，继续添加
            if not row or test_aspect <= current_aspect:
                row.append((name, node, adjusted_size))
                row_size = test_row_size
                remaining_items = adjusted_items[i+1:]
            else:
                # 宽高比开始变差，停止添加
                break

        # 布局这一行
        if row:
            if horizontal:
                # 水平方向：这一行的高度
                row_height = int(height * (row_size / total_size)) if total_size > 0 else height
                self._layout_row_adjusted(row, x, y, width, row_height, row_size, True)

                # 递归处理剩余项目（在下方）
                if remaining_items:
                    remaining_size = total_size - row_size
                    self._squarify_adjusted(remaining_items, x, y + row_height, width, height - row_height, remaining_size)
            else:
                # 垂直方向：这一行的宽度
                row_width = int(width * (row_size / total_size)) if total_size > 0 else width
                self._layout_row_adjusted(row, x, y, row_width, height, row_size, False)

                # 递归处理剩余项目（在右侧）
                if remaining_items:
                    remaining_size = total_size - row_size
                    self._squarify_adjusted(remaining_items, x + row_width, y, width - row_width, height, remaining_size)

    def _worst_aspect_ratio_adjusted(self, row, row_size, width, height, total_size, horizontal):
        """计算一行矩形中最差的宽高比（使用调整后的大小）"""
        if not row or row_size <= 0:
            return float('inf')

        max_aspect = 1.0

        # 计算这一行的尺寸
        if horizontal:
            row_height = height * (row_size / total_size) if total_size > 0 else height
            row_width = width
        else:
            row_width = width * (row_size / total_size) if total_size > 0 else width
            row_height = height

        # 计算每个矩形的宽高比
        offset = 0
        for name, node, adjusted_size in row:
            if horizontal:
                rect_width = row_width * (adjusted_size / row_size) if row_size > 0 else row_width / len(row)
                rect_height = row_height
            else:
                rect_width = row_width
                rect_height = row_height * (adjusted_size / row_size) if row_size > 0 else row_height / len(row)

            # 宽高比（取 >= 1 的值）
            if rect_width > 0 and rect_height > 0:
                aspect = max(rect_width / rect_height, rect_height / rect_width)
                max_aspect = max(max_aspect, aspect)

        return max_aspect

    def _layout_row_adjusted(self, row, x, y, width, height, row_size, horizontal):
        """布局一行矩形（使用调整后的大小）"""
        offset = 0

        for name, node, adjusted_size in row:
            if horizontal:
                # 水平布局：每个矩形的高度相同，宽度按比例
                rect_width = int(width * (adjusted_size / row_size)) if row_size > 0 else int(width / len(row))
                self.rects.append({
                    'x': int(x + offset), 'y': int(y),
                    'width': rect_width, 'height': int(height),
                    'name': name, 'size': node.size, 'node': node  # 保留原始大小
                })
                offset += rect_width
            else:
                # 垂直布局：每个矩形的宽度相同，高度按比例
                rect_height = int(height * (adjusted_size / row_size)) if row_size > 0 else int(height / len(row))
                self.rects.append({
                    'x': int(x), 'y': int(y + offset),
                    'width': int(width), 'height': rect_height,
                    'name': name, 'size': node.size, 'node': node  # 保留原始大小
                })
                offset += rect_height

    def paintEvent(self, event):
        """绑定绘制"""
        try:
            from PyQt6.QtGui import QFont
            from PyQt6.QtGui import QPalette

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 使用系统默认背景色（与树形列表一致）
            palette = self.palette()
            bg_color = palette.color(QPalette.ColorRole.Window)
            painter.fillRect(self.rect(), bg_color)

            # 如果没有内容，显示提示信息
            if not self.showing_content or not self.rects:
                painter.setPen(QColor(150, 150, 150))
                painter.setFont(QFont("Arial", 12))

                # 绘制边框
                painter.setPen(QPen(QColor(200, 200, 200), 2))
                painter.drawRect(self.rect().adjusted(5, 5, -5, -5))

                # 绘制提示文本
                painter.setPen(QColor(150, 150, 150))
                text = "展开左侧目录以查看文件分布"
                text_rect = self.rect()
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
                return

            # 有内容时正常绘制
            for i, rect_data in enumerate(self.rects):
                color = self.colors[i % len(self.colors)]
                if i == self.hovered_rect_index:
                    color = color.lighter(130)

                painter.fillRect(
                    rect_data['x'], rect_data['y'],
                    rect_data['width'], rect_data['height'],
                    color
                )

                painter.setPen(QPen(QColor(0, 0, 0, 50), 1))
                painter.drawRect(
                    rect_data['x'], rect_data['y'],
                    rect_data['width'], rect_data['height']
                )

                # 根据矩形大小动态调整字体和显示内容
                if rect_data['width'] > 60 and rect_data['height'] > 40:
                    painter.setPen(Qt.GlobalColor.black)

                    # 根据矩形大小调整字体大小
                    font_size = 9
                    if rect_data['width'] > 120 and rect_data['height'] > 80:
                        font_size = 11
                    elif rect_data['width'] > 80 and rect_data['height'] > 60:
                        font_size = 10

                    font = QFont("Arial", font_size)
                    painter.setFont(font)

                    # 截断过长的文件名
                    name = rect_data['name']
                    max_chars = int(rect_data['width'] / (font_size * 0.6))
                    if len(name) > max_chars:
                        name = name[:max_chars-2] + '..'

                    painter.drawText(rect_data['x'] + 5, rect_data['y'] + 20, name)

                    # 如果空间足够，显示大小
                    if rect_data['height'] > 55:
                        painter.setFont(QFont("Arial", font_size - 1))
                        painter.setPen(QColor(80, 80, 80))
                        painter.drawText(rect_data['x'] + 5, rect_data['y'] + 38, format_size(rect_data['size']))
        except Exception as e:
            print(f"[ERROR] 绘制时出错: {e}")
            import traceback
            traceback.print_exc()

    def mouseMoveEvent(self, event):
        """鼠标移动 - 高亮并显示tooltip"""
        pos = event.position()

        # 从后往前遍历（后绘制的在上层）
        found_index = -1
        for i in range(len(self.rects) - 1, -1, -1):
            rect = self.rects[i]
            if (rect['x'] <= pos.x() < rect['x'] + rect['width'] and
                rect['y'] <= pos.y() < rect['y'] + rect['height']):
                found_index = i
                break

        # 只在悬停改变时更新
        if found_index != self.hovered_rect_index:
            self.hovered_rect_index = found_index
            self.update()

            if found_index >= 0:
                rect = self.rects[found_index]
                tooltip = f"{rect['name']}\n{format_size(rect['size'])}"
                QToolTip.showText(event.globalPosition().toPoint(), tooltip, self)

                # 发送悬停信号，同步高亮到树形列表
                self.node_hovered.emit(rect['node'])
            else:
                QToolTip.hideText()
                # 发送 None 表示鼠标离开
                self.node_hovered.emit(None)

    def mouseDoubleClickEvent(self, event):
        """双击钻取"""
        pos = event.position()
        for i in range(len(self.rects) - 1, -1, -1):
            rect = self.rects[i]
            if (rect['x'] <= pos.x() < rect['x'] + rect['width'] and
                rect['y'] <= pos.y() < rect['y'] + rect['height']):
                node = rect['node']
                if node.is_dir and node.children:
                    # 将当前节点添加到导航栈
                    if self.current_node:
                        self.parent_stack.append(self.current_node)

                    self.current_node = node
                    self._calculate_layout()
                    self.update()
                    self.node_double_clicked.emit(node)
                    self.navigated.emit(node)
                break

    def resizeEvent(self, event):
        """窗口大小改变"""
        super().resizeEvent(event)
        if self.current_node:
            self._calculate_layout()
            self.update()

    def contextMenuEvent(self, event):
        """右键菜单"""
        menu = QMenu(self)

        # 检测右键点击的矩形
        pos = event.pos()
        clicked_rect_index = -1
        clicked_node = None

        for i in range(len(self.rects) - 1, -1, -1):
            rect = self.rects[i]
            if (rect['x'] <= pos.x() < rect['x'] + rect['width'] and
                rect['y'] <= pos.y() < rect['y'] + rect['height']):
                clicked_rect_index = i
                clicked_node = rect['node']
                break

        # 如果点击了矩形，添加矩形相关操作
        if clicked_node:
            # 复制路径
            copy_path_action = QAction(f"复制路径: {clicked_node.name}", self)
            copy_path_action.triggered.connect(lambda: self._copy_path(clicked_node.path))
            menu.addAction(copy_path_action)

            # 在资源管理器打开
            open_explorer_action = QAction("在资源管理器中打开", self)
            open_explorer_action.triggered.connect(lambda: self._open_in_explorer(clicked_node.path))
            menu.addAction(open_explorer_action)

            # 在树形列表中显示
            show_in_tree_action = QAction("在树形列表中显示", self)
            show_in_tree_action.triggered.connect(lambda: self._show_in_tree(clicked_node))
            menu.addAction(show_in_tree_action)

            menu.addSeparator()

        # 导航操作
        back_action = QAction("返回上一级 (Backspace)", self)
        back_action.setEnabled(len(self.parent_stack) > 0)
        back_action.triggered.connect(self.navigate_back)
        menu.addAction(back_action)

        # 返回根节点
        root_action = QAction("返回根目录 (Home)", self)
        root_action.setEnabled(self.current_node != self.root_node)
        root_action.triggered.connect(self.navigate_to_root)
        menu.addAction(root_action)

        menu.addSeparator()

        # 显示当前路径
        path_action = QAction(f"当前路径: {self.get_navigation_path()}", self)
        path_action.setEnabled(False)
        menu.addAction(path_action)

        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        """键盘事件处理"""
        if event.key() == Qt.Key.Key_Backspace:
            # Backspace: 返回上一级
            self.navigate_back()
        elif event.key() == Qt.Key.Key_Home:
            # Home: 返回根节点
            self.navigate_to_root()
        else:
            super().keyPressEvent(event)

    def _copy_path(self, path: str):
        """复制路径到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
        # 显示提示
        QToolTip.showText(
            self.mapToGlobal(QPoint(0, 0)),
            f"已复制: {path}",
            self
        )

    def _open_in_explorer(self, path: str):
        """在资源管理器中打开"""
        import subprocess
        import platform

        try:
            if platform.system() == "Windows":
                # Windows: 使用 explorer 打开并选中文件/文件夹
                subprocess.run(['explorer', '/select,', path], check=False)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['open', '--select', path], check=False)
            else:  # Linux
                subprocess.run(['xdg-open', path], check=False)
        except Exception as e:
            QToolTip.showText(
                self.mapToGlobal(QPoint(0, 0)),
                f"打开失败: {str(e)}",
                self
            )

    def _show_in_tree(self, node: FileNode):
        """请求在树形列表中显示节点"""
        self.show_in_tree_requested.emit(node)