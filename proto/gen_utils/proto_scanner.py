"""
Python类扫描器模块

负责扫描指定目录下的Python类，识别继承自BaseRequest/BaseResponse的类。
提取类的字段信息、类型注解等用于生成Proto文件。
"""

import os
import ast
import importlib.util
import inspect
from typing import Dict, List, Any, Optional, Type, get_type_hints
from pathlib import Path
from dataclasses import dataclass, fields, is_dataclass

from common.logger import logger
# Note: BaseRequest and BaseResponse are imported via AST parsing
# to avoid runtime dependencies during scanning


@dataclass
class ProtoFieldInfo:
    """Proto字段信息"""
    name: str           # 字段名
    type: str           # 字段类型
    number: int         # 字段编号
    comment: str        # 字段注释
    optional: bool      # 是否可选
    repeated: bool      # 是否重复


@dataclass
class ProtoClassInfo:
    """Proto类信息"""
    name: str                      # 类名
    module: str                    # 模块名
    file_path: str                 # 文件路径
    base_class: str                # 基类名 (BaseRequest/BaseResponse)
    msg_id: Optional[int]          # 消息ID
    fields: List[ProtoFieldInfo]   # 字段列表
    is_request: bool               # 是否为请求类
    is_response: bool              # 是否为响应类
    doc_string: Optional[str]      # 类文档字符串


class ProtoScanner:
    """
    Python类扫描器
    
    扫描指定目录下的Python类，识别继承自BaseRequest/BaseResponse的类
    """
    
    def __init__(self, scan_dirs: List[str] = None):
        """
        初始化扫描器
        
        Args:
            scan_dirs: 扫描目录列表，默认为['proto/class_data']
        """
        self.scan_dirs = scan_dirs or ['proto/class_data']
        self.logger = logger
        self.scanned_classes: List[ProtoClassInfo] = []
        self.message_types: Dict[int, str] = {}  # 消息ID到类名的映射
    
    def scan_directories(self) -> List[ProtoClassInfo]:
        """
        扫描目录下的所有Python类
        
        Returns:
            List[ProtoClassInfo]: 扫描到的类信息列表
        """
        self.scanned_classes.clear()
        
        try:
            self.logger.info("开始扫描Python类...")
            
            for scan_dir in self.scan_dirs:
                if not os.path.exists(scan_dir):
                    self.logger.warning(f"扫描目录不存在: {scan_dir}")
                    continue
                
                self.logger.info(f"扫描目录: {scan_dir}")
                self._scan_directory(scan_dir)
            
            self.logger.info(f"扫描完成，共找到{len(self.scanned_classes)}个类")
            return self.scanned_classes
            
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
            # 由于实际环境中可能无法导入模块，这里使用AST解析
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析AST
            tree = ast.parse(content)
            
            # 提取类定义
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_info = self._analyze_class_node(node, file_path)
                    if class_info:
                        self.scanned_classes.append(class_info)
        
        except Exception as e:
            self.logger.error(f"扫描Python文件失败: {file_path}, 错误: {str(e)}")
            raise
    
    def _analyze_class_node(self, node: ast.ClassDef, file_path: str) -> Optional[ProtoClassInfo]:
        """
        分析类AST节点
        
        Args:
            node: 类AST节点
            file_path: 文件路径
            
        Returns:
            Optional[ProtoClassInfo]: 类信息，如果不是目标类则返回None
        """
        try:
            # 检查是否继承自BaseRequest或BaseResponse
            base_class = self._get_base_class(node)
            if not base_class:
                return None
            
            # 提取类信息
            class_name = node.name
            module_name = self._get_module_name(file_path)
            doc_string = ast.get_docstring(node)
            
            # 提取字段信息
            fields_info = self._extract_class_fields(node)
            
            # 创建类信息
            class_info = ProtoClassInfo(
                name=class_name,
                module=module_name,
                file_path=file_path,
                base_class=base_class,
                msg_id=None,  # 需要从message_type.py获取
                fields=fields_info,
                is_request=base_class == 'BaseRequest',
                is_response=base_class == 'BaseResponse',
                doc_string=doc_string
            )
            
            self.logger.debug(f"找到类: {class_name} (基类: {base_class})")
            return class_info
            
        except Exception as e:
            self.logger.error(f"分析类节点失败: {node.name}, 错误: {str(e)}")
            return None
    
    def _get_base_class(self, node: ast.ClassDef) -> Optional[str]:
        """
        获取基类名
        
        Args:
            node: 类AST节点
            
        Returns:
            Optional[str]: 基类名，如果不是目标基类则返回None
        """
        for base in node.bases:
            if isinstance(base, ast.Name):
                if base.id in ['BaseRequest', 'BaseResponse']:
                    return base.id
            elif isinstance(base, ast.Attribute):
                if base.attr in ['BaseRequest', 'BaseResponse']:
                    return base.attr
        
        return None
    
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
    
    def _extract_class_fields(self, node: ast.ClassDef) -> List[ProtoFieldInfo]:
        """
        提取类字段信息
        
        Args:
            node: 类AST节点
            
        Returns:
            List[ProtoFieldInfo]: 字段信息列表
        """
        fields_info = []
        field_number = 1
        
        try:
            for item in node.body:
                # 处理变量注解
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    field_type = self._extract_type_annotation(item.annotation)
                    
                    # 跳过私有字段
                    if field_name.startswith('_'):
                        continue
                    
                    # 创建字段信息
                    field_info = ProtoFieldInfo(
                        name=field_name,
                        type=field_type,
                        number=field_number,
                        comment=f"字段: {field_name}",
                        optional=self._is_optional_type(item.annotation),
                        repeated=self._is_repeated_type(item.annotation)
                    )
                    
                    fields_info.append(field_info)
                    field_number += 1
                
                # 处理普通赋值
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            field_name = target.id
                            
                            # 跳过私有字段
                            if field_name.startswith('_'):
                                continue
                            
                            # 创建字段信息（类型推断）
                            field_info = ProtoFieldInfo(
                                name=field_name,
                                type=self._infer_type_from_value(item.value),
                                number=field_number,
                                comment=f"字段: {field_name}",
                                optional=True,
                                repeated=False
                            )
                            
                            fields_info.append(field_info)
                            field_number += 1
            
            return fields_info
            
        except Exception as e:
            self.logger.error(f"提取字段失败: {node.name}, 错误: {str(e)}")
            return []
    
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
                # 处理泛型类型，如List[str], Optional[int]
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
    
    def _is_repeated_type(self, annotation: ast.AST) -> bool:
        """
        检查是否为重复类型（List, Tuple等）
        
        Args:
            annotation: 类型注解AST节点
            
        Returns:
            bool: 是否为重复类型
        """
        if isinstance(annotation, ast.Subscript):
            if isinstance(annotation.value, ast.Name):
                return annotation.value.id in ['List', 'Tuple', 'Set']
            elif isinstance(annotation.value, ast.Attribute):
                return annotation.value.attr in ['List', 'Tuple', 'Set']
        
        return False
    
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
            return 'list'
        elif isinstance(value, ast.Dict):
            return 'dict'
        elif isinstance(value, ast.Name):
            if value.id == 'None':
                return 'Any'
        
        return 'Any'
    
    def get_request_classes(self) -> List[ProtoClassInfo]:
        """
        获取请求类列表
        
        Returns:
            List[ProtoClassInfo]: 请求类列表
        """
        return [cls for cls in self.scanned_classes if cls.is_request]
    
    def get_response_classes(self) -> List[ProtoClassInfo]:
        """
        获取响应类列表
        
        Returns:
            List[ProtoClassInfo]: 响应类列表
        """
        return [cls for cls in self.scanned_classes if cls.is_response]
    
    def load_message_types(self, message_type_file: str = None) -> Dict[int, str]:
        """
        加载消息类型映射
        
        Args:
            message_type_file: 消息类型文件路径
            
        Returns:
            Dict[int, str]: 消息ID到类名的映射
        """
        if message_type_file is None:
            # 查找message_type.py文件
            possible_paths = [
                'proto/message_type.py',
                'common/proto/message_type.py',
                'proto/class_data/message_type.py'
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    message_type_file = path
                    break
        
        if not message_type_file or not os.path.exists(message_type_file):
            self.logger.warning("未找到message_type.py文件，使用默认消息ID")
            return self._generate_default_message_types()
        
        try:
            # 解析message_type.py文件
            with open(message_type_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            message_types = {}
            
            # 提取消息ID常量
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            var_name = target.id
                            if isinstance(node.value, ast.Constant):
                                message_types[node.value.value] = var_name
            
            self.message_types = message_types
            self.logger.info(f"加载消息类型映射完成，共{len(message_types)}个")
            return message_types
            
        except Exception as e:
            self.logger.error(f"加载消息类型失败: {str(e)}")
            return self._generate_default_message_types()
    
    def _generate_default_message_types(self) -> Dict[int, str]:
        """
        生成默认消息类型映射
        
        Returns:
            Dict[int, str]: 默认消息ID映射
        """
        message_types = {}
        
        # 为请求类生成正数ID
        for i, cls in enumerate(self.get_request_classes(), start=1):
            message_types[i] = cls.name
        
        # 为响应类生成负数ID
        for i, cls in enumerate(self.get_response_classes(), start=1):
            message_types[-i] = cls.name
        
        return message_types
    
    def update_message_ids(self) -> None:
        """
        更新类信息中的消息ID
        """
        # 反向映射：类名到消息ID
        name_to_id = {name: msg_id for msg_id, name in self.message_types.items()}
        
        # 更新类信息
        for cls_info in self.scanned_classes:
            if cls_info.name in name_to_id:
                cls_info.msg_id = name_to_id[cls_info.name]
                self.logger.debug(f"更新消息ID: {cls_info.name} -> {cls_info.msg_id}")
    
    def validate_scanned_classes(self) -> bool:
        """
        验证扫描到的类
        
        Returns:
            bool: 验证是否通过
        """
        if not self.scanned_classes:
            self.logger.warning("未扫描到任何类")
            return False
        
        # 检查是否有重复的类名
        class_names = [cls.name for cls in self.scanned_classes]
        if len(class_names) != len(set(class_names)):
            self.logger.error("发现重复的类名")
            return False
        
        # 检查是否有重复的消息ID
        msg_ids = [cls.msg_id for cls in self.scanned_classes if cls.msg_id is not None]
        if len(msg_ids) != len(set(msg_ids)):
            self.logger.error("发现重复的消息ID")
            return False
        
        return True