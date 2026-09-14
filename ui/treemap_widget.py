#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
矩形树图可视化组件

使用 QPainter 绘制交互式矩形树图
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QToolTip, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath

# 导入扫描引擎
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.scanner import FileNode, format_size

try:
    import squarify
    HAS_SQUARIFY = True
except ImportError:
    HAS_SQUARIFY = False


class TreemapRect:
    """矩形树图的一个矩形块"""

    def __init__(self, rect: QRectF, node: FileNode, color: QColor):
        self.rect = rect  # 矩形区域
        self.node = node  # 文件节点
        self.color = color  # 颜色
        self.is_hovered = False  # 是否悬停
        self.is_selected = False  # 是否选中


class TreemapWidget(QWidget):
    """
    矩形树图可视化组件

    功能：
    - 矩形大小反映文件夹大小
    - 颜色映射（大小或类型）
    - 悬停高亮和 Tooltip
    - 点击钻取进入子文件夹
    - 面包屑导航
    """

    # 信号定义
    node_clicked = pyqtSignal(object)  # FileNode
    node_double_clicked = pyqtSignal(object)  # FileNode
    navigate_back = pyqtSignal()  # 返回上一级

    def __init__(self):
        super().__init__()

        # 数据
        self.root_node: Optional[FileNode] = None
        self.current_node: Optional[FileNode] = None
        self.parent_stack: List[FileNode] = []  # 导航栈
        self.rect_items: List[TreemapRect] = []
        self._pending_data = False  # 标记是否有待处理的数据

        # 交互状态
        self.hovered_rect: Optional[TreemapRect] = None
        self.selected_rect: Optional[TreemapRect] = None

        # 设置 - 必须在初始化时立即设置
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)  # 启用鼠标跟踪

        # 添加背景色，方便调试
        self.setAutoFillBackground(True)

        # 颜色方案
        self.color_scheme = self._create_color_scheme()

        # 面包屑导航
        self._setup_breadcrumb()

    def _create_color_scheme(self) -> List[QColor]:
        """创建颜色方案（大小映射）"""
        # 从蓝到红的渐变色
        return [
            QColor(100, 181, 246),   # 浅蓝（小）
            QColor(77, 208, 225),    # 青色
            QColor(129, 199, 132),   # 浅绿
            QColor(255, 213, 79),    # 黄色
            QColor(255, 167, 38),    # 橙色
            QColor(239, 83, 80),     # 红色（大）
        ]

    def _setup_breadcrumb(self):
        """设置面包屑导航"""
        # 这将在主窗口中实现
        pass

    def set_data(self, node: FileNode):
        """设置数据并重绘"""
        self.root_node = node
        self.current_node = node
        self.parent_stack = []

        # 延迟计算布局（等待窗口有正确大小）
        if self.width() > 0 and self.height() > 0:
            self._calculate_layout()
            self.update()
        else:
            # 窗口还没有正确大小，延迟到 showEvent 或 resizeEvent
            self._pending_data = True

    def navigate_to_child(self, node: FileNode):
        """导航到子节点"""
        if self.current_node:
            self.parent_stack.append(self.current_node)
            self.current_node = node
            self._calculate_layout()
            self.update()

    def navigate_up(self):
        """返回上一级"""
        if self.parent_stack:
            self.current_node = self.parent_stack.pop()
            self._calculate_layout()
            self.update()
            return True
        return False

    def _calculate_layout(self):
        """计算矩形树图布局"""
        if not self.current_node:
            return

        # 准备数据
        values = []
        labels = []
        nodes = []

        for name, child in self.current_node.children.items():
            if child.size > 0:
                values.append(child.size)
                labels.append(name)
                nodes.append(child)

        if not values:
            return

        # 归一化到 [0, 100]
        total = sum(values)
        normalized_values = [v / total * 100 for v in values]

        # 计算矩形布局
        width = self.width()
        height = self.height()

        if HAS_SQUARIFY:
            # 使用 squarify 库
            rects = squarify.squarify(
                normalized_values,
                0, 0, width, height
            )
        else:
            # 简单的 Slice-and-Dice 算法
            rects = self._slice_and_dice(normalized_values, width, height)

        # 创建矩形对象
        self.rect_items = []
        for i, rect in enumerate(rects):
            # 计算颜色（根据大小）
            color = self._get_color_for_index(i, len(rects))

            treemap_rect = TreemapRect(
                rect=QRectF(rect['x'], rect['y'], rect['dx'], rect['dy']),
                node=nodes[i],
                color=color
            )
            self.rect_items.append(treemap_rect)

    def _slice_and_dice(self, values: List[float], width: float, height: float) -> List[Dict]:
        """简单的 Slice-and-Dice 布局算法"""
        rects = []
        x, y = 0, 0
        horizontal = True

        for i, value in enumerate(values):
            if horizontal:
                dx = (value / 100) * width
                rect = {'x': x, 'y': y, 'dx': dx, 'dy': height}
                x += dx
            else:
                dy = (value / 100) * height
                rect = {'x': x, 'y': y, 'dx': width, 'dy': dy}
                y += dy

            rects.append(rect)

        return rects

    def _get_color_for_index(self, index: int, total: int) -> QColor:
        """根据索引获取颜色（大小映射）"""
        if total <= 1:
            return self.color_scheme[0]

        # 映射到颜色方案
        position = index / (total - 1)
        color_index = int(position * (len(self.color_scheme) - 1))

        return self.color_scheme[color_index]

    def paintEvent(self, event):
        """绑定绘制事件"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制背景
        painter.fillRect(self.rect(), QColor(255, 255, 255))

        # 绘制矩形
        for treemap_rect in self.rect_items:
            self._draw_rect(painter, treemap_rect)

        # 绘制面包屑导航信息（可选）
        if self.parent_stack:
            self._draw_breadcrumb_info(painter)

    def _draw_rect(self, painter: QPainter, treemap_rect: TreemapRect):
        """绘制单个矩形"""
        rect = treemap_rect.rect
        color = treemap_rect.color

        # 悬停高亮
        if treemap_rect.is_hovered:
            color = color.lighter(120)

        # 设置画笔和画刷
        if treemap_rect.is_selected:
            painter.setPen(QPen(QColor(0, 0, 255), 3))
        else:
            painter.setPen(QPen(QColor(255, 255, 255), 1))

        painter.setBrush(QBrush(color))

        # 绘制矩形
        painter.drawRect(rect)

        # 绘制标签（如果矩形足够大）
        if rect.width() > 60 and rect.height() > 30:
            self._draw_label(painter, rect, treemap_rect.node)

    def _draw_label(self, painter: QPainter, rect: QRectF, node: FileNode):
        """绘制标签文本"""
        # 设置字体
        font = QFont("Arial", 9)
        painter.setFont(font)

        # 准备文本
        name = node.name
        size_text = format_size(node.size)

        # 根据矩形大小决定显示内容
        if rect.width() > 100 and rect.height() > 50:
            text = f"{name}\n{size_text}"
        else:
            text = name[:10]  # 截断长名称

        # 设置文本颜色（黑色或白色，根据背景）
        brightness = (node.size / self.current_node.size) if self.current_node else 0.5
        if brightness > 0.5:
            painter.setPen(Qt.GlobalColor.white)
        else:
            painter.setPen(Qt.GlobalColor.black)

        # 绘制文本
        painter.drawText(
            rect.adjusted(5, 5, -5, -5),
            Qt.TextFlag.TextWordWrap,
            text
        )

    def _draw_breadcrumb_info(self, painter: QPainter):
        """绘制导航信息"""
        painter.setPen(Qt.GlobalColor.black)
        font = QFont("Arial", 10)
        painter.setFont(font)

        path_parts = [node.name for node in self.parent_stack]
        if self.current_node:
            path_parts.append(self.current_node.name)

        path_text = " > ".join(path_parts[-5:])  # 最多显示5级
        painter.drawText(10, 20, f"路径: {path_text}")

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 悬停检测"""
        pos = event.position()

        # 检测悬停的矩形
        found_rect = None
        for treemap_rect in self.rect_items:
            if treemap_rect.rect.contains(pos):
                found_rect = treemap_rect
                break

        # 更新悬停状态
        if found_rect != self.hovered_rect:
            if self.hovered_rect:
                self.hovered_rect.is_hovered = False
            if found_rect:
                found_rect.is_hovered = True

            self.hovered_rect = found_rect
            self.update()

            # 显示 Tooltip
            if found_rect:
                tooltip_text = self._create_tooltip(found_rect.node)
                QToolTip.showText(event.globalPosition().toPoint(), tooltip_text, self)
            else:
                QToolTip.hideText()

    def _create_tooltip(self, node: FileNode) -> str:
        """创建 Tooltip 文本"""
        lines = [
            f"名称: {node.name}",
            f"大小: {format_size(node.size)}",
        ]

        if node.is_dir:
            lines.append(f"文件数: {node.file_count}")
            lines.append(f"目录数: {node.dir_count}")

        lines.append(f"\n路径: {node.path}")

        return "\n".join(lines)

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        pos = event.position()

        # 找到点击的矩形
        for treemap_rect in self.rect_items:
            if treemap_rect.rect.contains(pos):
                # 更新选中状态
                if self.selected_rect:
                    self.selected_rect.is_selected = False

                treemap_rect.is_selected = True
                self.selected_rect = treemap_rect

                # 发送信号
                self.node_clicked.emit(treemap_rect.node)

                self.update()
                break

    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件 - 钻取进入"""
        pos = event.position()

        for treemap_rect in self.rect_items:
            if treemap_rect.rect.contains(pos):
                if treemap_rect.node.is_dir and treemap_rect.node.children:
                    # 导航到子节点
                    self.navigate_to_child(treemap_rect.node)
                    self.node_double_clicked.emit(treemap_rect.node)
                break

    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)

        # 如果有待处理的数据，现在计算布局
        if self._pending_data and self.current_node:
            self._calculate_layout()
            self._pending_data = False
            self.update()
        elif self.current_node:
            # 重新计算布局以适应新大小
            self._calculate_layout()
            self.update()

    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)

        # 如果有待处理的数据，现在计算布局
        if self._pending_data and self.current_node:
            self._calculate_layout()
            self._pending_data = False
            self.update()


# 测试代码
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from core.scanner import DiskScanner

    app = QApplication(sys.argv)

    # 测试扫描
    scanner = DiskScanner(skip_system_dirs=True)
    test_path = Path(__file__).parent.parent
    root_node = scanner.scan(str(test_path), depth=1)

    if root_node:
        # 创建窗口
        widget = TreemapWidget()
        widget.set_data(root_node)
        widget.setWindowTitle("矩形树图测试")
        widget.resize(800, 600)
        widget.show()

        sys.exit(app.exec())