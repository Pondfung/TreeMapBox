#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存识别模块

识别系统中的缓存文件，并评估删除安全性
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional


class CacheDetector:
    """
    缓存检测器

    功能：
    - 识别常见缓存路径（temp、cache、log）
    - 评估删除安全性
    - 从软件规则库匹配
    """

    # 通用缓存模式（文件名包含这些关键词）
    CACHE_PATTERNS = [
        r'temp', r'tmp',
        r'cache', r'cached',
        r'log', r'logs',
        r'\.bak$', r'\.old$',
    ]

    # 安全删除的路径模式
    SAFE_PATTERNS = [
        r'.*\\AppData\\Local\\Temp\\.*',
        r'.*\\Windows\\Temp\\.*',
        r'.*\\AppData\\Local\\.*\\Cache\\.*',
    ]

    # 危险删除的路径模式
    DANGEROUS_PATTERNS = [
        r'.*\\Windows\\System32\\.*',
        r'.*\\Program Files\\.*\\.*\.exe$',
        r'.*\\Program Files \(x86\)\\.*\\.*\.exe$',
        r'.*\\AppData\\Roaming\\.*\\.*\.json$',
    ]

    def __init__(self, rules_path: str = None):
        """
        初始化缓存检测器

        Args:
            rules_path: 软件规则库路径
        """
        self.rules = []
        if rules_path:
            self.load_rules(rules_path)

    def load_rules(self, rules_path: str):
        """加载软件识别规则"""
        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                self.rules = json.load(f)
        except Exception as e:
            print(f"加载规则失败: {e}")

    def detect_cache(self, path: str) -> tuple[bool, str]:
        """
        检测路径是否为缓存

        Args:
            path: 文件/目录路径

        Returns:
            (is_cache, safety_level): 是否缓存，安全等级
                safety_level: 'safe', 'cautious', 'dangerous'
        """
        path_lower = path.lower()

        # 1. 检查是否为危险路径
        for pattern in self.DANGEROUS_PATTERNS:
            if re.match(pattern, path, re.IGNORECASE):
                return False, 'dangerous'

        # 2. 检查是否为安全路径（临时文件）
        for pattern in self.SAFE_PATTERNS:
            if re.match(pattern, path, re.IGNORECASE):
                return True, 'safe'

        # 3. 检查文件名是否包含缓存关键词
        path_obj = Path(path)
        name = path_obj.name.lower()

        for pattern in self.CACHE_PATTERNS:
            if re.search(pattern, name):
                # 在 AppData 下，谨慎一些
                if 'appdata' in path_lower:
                    return True, 'cautious'
                else:
                    return True, 'safe'

        # 4. 检查软件规则库
        for rule in self.rules:
            for cache_path in rule.get('cache_paths', []):
                # 将规则路径转换为正则表达式
                pattern = cache_path.replace('\\', '\\\\')
                pattern = pattern.replace('/', '\\\\')
                pattern = pattern.replace('*', '.*')

                if re.search(pattern, path, re.IGNORECASE):
                    level = rule.get('cache_level', 'cautious')
                    return True, level

        return False, ''

    def get_cache_icon(self, safety_level: str) -> str:
        """
        根据安全等级返回图标标记

        Args:
            safety_level: 安全等级

        Returns:
            图标字符串（用于显示）
        """
        icons = {
            'safe': '[SAFE]',      # 绿色
            'cautious': '[WARN]',   # 黄色
            'dangerous': '[DANGER]',  # 红色
        }
        return icons.get(safety_level, '')

    def get_safety_description(self, safety_level: str) -> str:
        """
        获取安全等级描述

        Args:
            safety_level: 安全等级

        Returns:
            描述文本
        """
        descriptions = {
            'safe': '安全删除 - 无副作用',
            'cautious': '谨慎删除 - 可能影响应用性能',
            'dangerous': '危险 - 可能导致数据丢失',
        }
        return descriptions.get(safety_level, '')


# 测试代码
if __name__ == "__main__":
    # 测试缓存检测器
    detector = CacheDetector("config/software_rules.json")

    test_paths = [
        r"C:\Users\test\AppData\Local\Temp\abc.tmp",
        r"C:\Users\test\AppData\Local\Google\Chrome\User Data\Default\Cache",
        r"C:\Users\test\AppData\Roaming\Code\Cache",
        r"C:\Windows\System32\drivers",
        r"C:\Program Files\test\app.exe",
    ]

    print("缓存识别测试：")
    print("=" * 60)

    for path in test_paths:
        is_cache, level = detector.detect_cache(path)
        icon = detector.get_cache_icon(level)
        desc = detector.get_safety_description(level)

        print(f"\n路径: {path}")
        print(f"  是否缓存: {is_cache}")
        print(f"  安全等级: {level}")
        print(f"  标记: {icon}")
        print(f"  描述: {desc}")