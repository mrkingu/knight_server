"""
文档模型扫描器模块

负责扫描指定目录下的Python文档模型，识别继承自BaseDocument的类。
提取模型的字段信息、类型注解等用于生成Repository类。
"""

import os
import ast
import importlib.util
import inspect
from typing import Dict, List, Any, Optional, Type, get_type_hints
from pathlib import Path
from dataclasses import dataclass, fields, is_dataclass

from common.logger import logger
# Note: BaseDocument is imported via AST parsing
# to avoid runtime dependencies during scanning


@dataclass
class DocumentFieldInfo:
    """文档字段信息"""
    name: str           # 字段名
    type: str           # 字段类型
    comment: str        # 字段注释
    optional: bool      # 是否可选
    default_value: Any  # 默认值


@dataclass
class DocumentClassInfo:
    """文档类信息"""
    name: str                         # 类名
    module: str                       # 模块名
    file_path: str                    # 文件路径
    collection_name: Optional[str]    # 集合名称
    fields: List[DocumentFieldInfo]   # 字段列表
    doc_string: Optional[str]         # 类文档字符串
    base_fields: List[str]            # 基类字段列表
    custom_methods: List[str]         # 自定义方法列表


class DocumentScanner:
    """
    文档模型扫描器
    
    扫描指定目录下的Python文档模型，识别继承自BaseDocument的类
    """
    
    def __init__(self, scan_dirs: List[str] = None):
        """
        初始化扫描器
        
        Args:
            scan_dirs: 扫描目录列表，默认为['models/document']
        """
        self.scan_dirs = scan_dirs or ['models/document']
        self.logger = logger
        self.scanned_documents: List[DocumentClassInfo] = []
        
        # BaseDocument的基础字段
        self.base_fields = [
            '_id', 'created_at', 'updated_at', 'version', 'is_deleted'
        ]
    
    def scan_directories(self) -> List[DocumentClassInfo]:
        """
        扫描目录下的所有文档模型
        
        Returns:
            List[DocumentClassInfo]: 扫描到的文档类信息列表
        """
        self.scanned_documents.clear()
        
        try:
            self.logger.info("开始扫描文档模型...")
            
            for scan_dir in self.scan_dirs:
                if not os.path.exists(scan_dir):
                    self.logger.warning(f"扫描目录不存在: {scan_dir}")
                    continue
                
                self.logger.info(f"扫描目录: {scan_dir}")
                self._scan_directory(scan_dir)
            
            self.logger.info(f"扫描完成，共找到{len(self.scanned_documents)}个文档模型")
            return self.scanned_documents
            
        except Exception as e:
            self.logger.error(f"扫描目录失败: {str(e)}")
            raise
    
    def _scan_directory(self, directory: str) -> None:
        """
        扫描单个目录
        
        Args:
            directory: 目录路径
        """
        try:
            # 查找所有Python文件
            python_files = []
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith('.py') and not file.startswith('__'):
                        python_files.append(os.path.join(root, file))
            
            self.logger.info(f"在目录{directory}中找到{len(python_files)}个Python文件")
            
            # 扫描每个Python文件
            for python_file in python_files:
                try:
                    self._scan_python_file(python_file)
                except Exception as e:
                    self.logger.error(f"扫描文件失败: {python_file}, 错误: {str(e)}")
                    continue
        
        except Exception as e:
            self.logger.error(f"扫描目录失败: {directory}, 错误: {str(e)}")
            raise
    
    def _scan_python_file(self, file_path: str) -> None:
        """
        扫描单个Python文件
        
        Args:
            file_path: 文件路径
        """
        try:
            # 使用AST解析文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析AST
            tree = ast.parse(content)
            
            # 提取类定义
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    doc_info = self._analyze_document_class(node, file_path)
                    if doc_info:
                        self.scanned_documents.append(doc_info)
        
        except Exception as e:
            self.logger.error(f"扫描Python文件失败: {file_path}, 错误: {str(e)}")
            raise
    
    def _analyze_document_class(self, node: ast.ClassDef, file_path: str) -> Optional[DocumentClassInfo]:
        """
        分析文档类AST节点
        
        Args:
            node: 类AST节点
            file_path: 文件路径
            
        Returns:
            Optional[DocumentClassInfo]: 文档类信息，如果不是目标类则返回None
        """
        try:
            # 检查是否继承自BaseDocument
            if not self._is_base_document_subclass(node):
                return None
            
            # 提取类信息
            class_name = node.name
            module_name = self._get_module_name(file_path)
            doc_string = ast.get_docstring(node)
            
            # 提取集合名称
            collection_name = self._extract_collection_name(node, class_name)
            
            # 提取字段信息
            fields_info = self._extract_document_fields(node)
            
            # 提取自定义方法
            custom_methods = self._extract_custom_methods(node)
            
            # 创建文档类信息
            doc_info = DocumentClassInfo(
                name=class_name,
                module=module_name,
                file_path=file_path,
                collection_name=collection_name,
                fields=fields_info,
                doc_string=doc_string,
                base_fields=self.base_fields.copy(),
                custom_methods=custom_methods
            )
            
            self.logger.debug(f"找到文档模型: {class_name}")
            return doc_info
            
        except Exception as e:
            self.logger.error(f"分析文档类失败: {node.name}, 错误: {str(e)}")
            return None
    
    def _is_base_document_subclass(self, node: ast.ClassDef) -> bool:
        """
        检查是否为BaseDocument的子类
        
        Args:
            node: 类AST节点
            
        Returns:
            bool: 是否为BaseDocument的子类
        """
        for base in node.bases:
            if isinstance(base, ast.Name):
                if base.id == 'BaseDocument':
                    return True
            elif isinstance(base, ast.Attribute):
                if base.attr == 'BaseDocument':
                    return True
        
        return False
    
    def _get_module_name(self, file_path: str) -> str:
        """
        从文件路径获取模块名
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 模块名
        """
        # 转换为相对路径
        relative_path = os.path.relpath(file_path)
        
        # 移除.py扩展名
        module_path = relative_path[:-3] if relative_path.endswith('.py') else relative_path
        
        # 转换为模块名
        module_name = module_path.replace(os.sep, '.')
        
        return module_name
    
    def _extract_collection_name(self, node: ast.ClassDef, class_name: str) -> Optional[str]:
        """
        提取集合名称
        
        Args:
            node: 类AST节点
            class_name: 类名
            
        Returns:
            Optional[str]: 集合名称
        """
        # 查找get_collection_name方法
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == 'get_collection_name':
                # 尝试提取返回值
                for stmt in item.body:
                    if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
                        return stmt.value.value
        
        # 默认集合名称（类名转换为snake_case）
        return self._to_snake_case(class_name)
    
    def _extract_document_fields(self, node: ast.ClassDef) -> List[DocumentFieldInfo]:
        """
        提取文档字段信息
        
        Args:
            node: 类AST节点
            
        Returns:
            List[DocumentFieldInfo]: 字段信息列表
        """
        fields_info = []
        
        try:
            for item in node.body:
                # 处理变量注解
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    
                    # 跳过私有字段和基类字段
                    if field_name.startswith('_') or field_name in self.base_fields:
                        continue
                    
                    field_type = self._extract_type_annotation(item.annotation)
                    field_comment = f"文档字段: {field_name}"
                    field_optional = self._is_optional_type(item.annotation)
                    field_default = self._extract_default_value(item.value) if item.value else None
                    
                    # 创建字段信息
                    field_info = DocumentFieldInfo(
                        name=field_name,
                        type=field_type,
                        comment=field_comment,
                        optional=field_optional,
                        default_value=field_default
                    )
                    
                    fields_info.append(field_info)
                
                # 处理普通赋值
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            field_name = target.id
                            
                            # 跳过私有字段和基类字段
                            if field_name.startswith('_') or field_name in self.base_fields:
                                continue
                            
                            field_type = self._infer_type_from_value(item.value)
                            field_comment = f"文档字段: {field_name}"
                            field_default = self._extract_default_value(item.value)
                            
                            # 创建字段信息
                            field_info = DocumentFieldInfo(
                                name=field_name,
                                type=field_type,
                                comment=field_comment,
                                optional=True,
                                default_value=field_default
                            )
                            
                            fields_info.append(field_info)
            
            return fields_info
            
        except Exception as e:
            self.logger.error(f"提取文档字段失败: {node.name}, 错误: {str(e)}")
            return []
    
    def _extract_custom_methods(self, node: ast.ClassDef) -> List[str]:
        """
        提取自定义方法列表
        
        Args:
            node: 类AST节点
            
        Returns:
            List[str]: 自定义方法名列表
        """
        custom_methods = []
        
        # BaseDocument的标准方法
        base_methods = {
            '__init__', '__post_init__', 'get_collection_name', 'get_field_names',
            'get_field_types', 'validate', 'update_timestamp', 'increment_version',
            'is_new', 'is_modified', 'get_age', 'get_last_modified_age',
            '__str__', '__repr__', '__eq__', '__hash__'
        }
        
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_name = item.name
                
                # 跳过私有方法和基类方法
                if not method_name.startswith('_') and method_name not in base_methods:
                    custom_methods.append(method_name)
        
        return custom_methods
    
    def _extract_type_annotation(self, annotation: ast.AST) -> str:
        """
        提取类型注解
        
        Args:
            annotation: 类型注解AST节点
            
        Returns:
            str: 类型字符串
        """
        try:
            if isinstance(annotation, ast.Name):
                return annotation.id
            elif isinstance(annotation, ast.Attribute):
                return annotation.attr
            elif isinstance(annotation, ast.Subscript):
                # 处理泛型类型
                if isinstance(annotation.value, ast.Name):
                    return annotation.value.id
                elif isinstance(annotation.value, ast.Attribute):
                    return annotation.value.attr
            elif isinstance(annotation, ast.Constant):
                return str(annotation.value)
            
            return 'Any'
            
        except Exception as e:
            self.logger.warning(f"提取类型注解失败: {annotation}, 错误: {str(e)}")
            return 'Any'
    
    def _is_optional_type(self, annotation: ast.AST) -> bool:
        """
        检查是否为Optional类型
        
        Args:
            annotation: 类型注解AST节点
            
        Returns:
            bool: 是否为Optional类型
        """
        if isinstance(annotation, ast.Subscript):
            if isinstance(annotation.value, ast.Name):
                return annotation.value.id in ['Optional', 'Union']
            elif isinstance(annotation.value, ast.Attribute):
                return annotation.value.attr in ['Optional', 'Union']
        
        return False
    
    def _extract_default_value(self, value: ast.AST) -> Any:
        """
        提取默认值
        
        Args:
            value: 值AST节点
            
        Returns:
            Any: 默认值
        """
        if value is None:
            return None
        
        try:
            if isinstance(value, ast.Constant):
                return value.value
            elif isinstance(value, ast.Name):
                if value.id == 'None':
                    return None
                elif value.id in ['True', 'False']:
                    return value.id == 'True'
            elif isinstance(value, ast.List):
                return []
            elif isinstance(value, ast.Dict):
                return {}
            
            return None
            
        except Exception as e:
            self.logger.warning(f"提取默认值失败: {value}, 错误: {str(e)}")
            return None
    
    def _infer_type_from_value(self, value: ast.AST) -> str:
        """
        从值推断类型
        
        Args:
            value: 值AST节点
            
        Returns:
            str: 推断的类型
        """
        if isinstance(value, ast.Constant):
            if isinstance(value.value, int):
                return 'int'
            elif isinstance(value.value, float):
                return 'float'
            elif isinstance(value.value, str):
                return 'str'
            elif isinstance(value.value, bool):
                return 'bool'
        elif isinstance(value, ast.List):
            return 'List'
        elif isinstance(value, ast.Dict):
            return 'Dict'
        elif isinstance(value, ast.Name):
            if value.id == 'None':
                return 'Any'
        
        return 'Any'
    
    def _to_snake_case(self, name: str) -> str:
        """
        转换为snake_case
        
        Args:
            name: 原始名称
            
        Returns:
            str: snake_case名称
        """
        import re
        
        # 在大写字母前插入下划线
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        snake_case = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        # 移除Document后缀
        if snake_case.endswith('_document'):
            snake_case = snake_case[:-9]
        
        return snake_case
    
    def get_documents_by_module(self) -> Dict[str, List[DocumentClassInfo]]:
        """
        按模块分组获取文档列表
        
        Returns:
            Dict[str, List[DocumentClassInfo]]: 模块到文档列表的映射
        """
        module_docs = {}
        
        for doc in self.scanned_documents:
            module = doc.module
            if module not in module_docs:
                module_docs[module] = []
            module_docs[module].append(doc)
        
        return module_docs
    
    def validate_scanned_documents(self) -> bool:
        """
        验证扫描到的文档模型
        
        Returns:
            bool: 验证是否通过
        """
        if not self.scanned_documents:
            self.logger.warning("未扫描到任何文档模型")
            return False
        
        # 检查是否有重复的类名
        class_names = [doc.name for doc in self.scanned_documents]
        if len(class_names) != len(set(class_names)):
            self.logger.error("发现重复的文档类名")
            return False
        
        # 检查是否有重复的集合名
        collection_names = [doc.collection_name for doc in self.scanned_documents if doc.collection_name]
        if len(collection_names) != len(set(collection_names)):
            self.logger.error("发现重复的集合名")
            return False
        
        return True