"""
models/gen_utils 模块

数据仓库生成工具模块，提供以下功能：
- 扫描继承BaseDocument的数据模型
- 自动生成对应的Repository类
- 支持类型提示和文档字符串
- 支持自定义Repository扩展
"""

from .document_scanner import DocumentScanner
from .repository_generator import RepositoryGenerator
from .generator_main import main

__all__ = ['DocumentScanner', 'RepositoryGenerator', 'main']
