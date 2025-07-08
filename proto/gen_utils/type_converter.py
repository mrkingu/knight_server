"""
Python类型到Proto类型转换器

负责将Python类型转换为Protocol Buffers类型定义。
支持基本类型、集合类型和自定义类型的转换。
"""

from typing import Dict, Any, Optional, List, Type, get_type_hints, Union
import inspect
import re

from common.logger import logger


class TypeConverter:
    """
    Python类型到Proto类型转换器
    
    负责将Python类型转换为Protocol Buffers类型定义
    """
    
    def __init__(self):
        """初始化转换器"""
        self.logger = logger
        
        # Python类型到Proto类型的映射
        self.type_mapping = {
            'int': 'int32',
            'float': 'float',
            'str': 'string',
            'bool': 'bool',
            'bytes': 'bytes',
            'datetime': 'string',  # 转换为ISO格式字符串
            'date': 'string',
            'time': 'string',
            'dict': 'string',     # 序列化为JSON字符串
            'list': 'repeated',   # 特殊处理，需要获取元素类型
            'tuple': 'repeated',  # 特殊处理，需要获取元素类型
            'set': 'repeated',    # 特殊处理，需要获取元素类型
        }
        
        # 复杂类型的默认处理
        self.default_proto_type = 'string'
    
    def convert_python_type_to_proto(self, python_type: Any) -> str:
        """
        将Python类型转换为Proto类型
        
        Args:
            python_type: Python类型
            
        Returns:
            str: Proto类型字符串
        """
        try:
            # 处理None类型
            if python_type is None or python_type is type(None):
                return 'string'
            
            # 处理字符串类型名
            if isinstance(python_type, str):
                return self._convert_string_type(python_type)
            
            # 处理type对象
            if isinstance(python_type, type):
                return self._convert_type_object(python_type)
            
            # 处理typing模块的类型
            if hasattr(python_type, '__origin__'):
                return self._convert_typing_type(python_type)
            
            # 默认处理
            return self.default_proto_type
            
        except Exception as e:
            self.logger.warning(f"类型转换失败: {python_type}, 错误: {str(e)}")
            return self.default_proto_type
    
    def _convert_string_type(self, type_str: str) -> str:
        """
        转换字符串类型名
        
        Args:
            type_str: 类型字符串
            
        Returns:
            str: Proto类型
        """
        # 清理类型字符串
        type_str = type_str.strip()
        
        # 处理Optional类型
        if type_str.startswith('Optional[') and type_str.endswith(']'):
            inner_type = type_str[9:-1]
            return self._convert_string_type(inner_type)
        
        # 处理List类型
        if type_str.startswith('List[') and type_str.endswith(']'):
            inner_type = type_str[5:-1]
            inner_proto_type = self._convert_string_type(inner_type)
            return f'repeated {inner_proto_type}'
        
        # 处理Dict类型
        if type_str.startswith('Dict[') and type_str.endswith(']'):
            # Proto3不直接支持map，转换为string
            return 'string'
        
        # 处理Union类型
        if type_str.startswith('Union[') and type_str.endswith(']'):
            # 取第一个类型
            inner_types = type_str[6:-1].split(',')
            if inner_types:
                first_type = inner_types[0].strip()
                return self._convert_string_type(first_type)
        
        # 基本类型映射
        return self.type_mapping.get(type_str, self.default_proto_type)
    
    def _convert_type_object(self, type_obj: type) -> str:
        """
        转换type对象
        
        Args:
            type_obj: type对象
            
        Returns:
            str: Proto类型
        """
        type_name = type_obj.__name__
        
        # 检查是否为基本类型
        if type_name in self.type_mapping:
            return self.type_mapping[type_name]
        
        # 检查是否为自定义类
        if hasattr(type_obj, '__module__'):
            # 自定义类通常转换为string（序列化后）
            return 'string'
        
        return self.default_proto_type
    
    def _convert_typing_type(self, typing_type: Any) -> str:
        """
        转换typing模块的类型
        
        Args:
            typing_type: typing类型
            
        Returns:
            str: Proto类型
        """
        origin = getattr(typing_type, '__origin__', None)
        args = getattr(typing_type, '__args__', ())
        
        if origin is None:
            return self.default_proto_type
        
        # 处理Optional类型
        if origin is Union:
            # 检查是否为Optional (Union[T, None])
            if len(args) == 2 and type(None) in args:
                non_none_type = args[0] if args[1] is type(None) else args[1]
                return self.convert_python_type_to_proto(non_none_type)
            else:
                # 普通Union，取第一个类型
                return self.convert_python_type_to_proto(args[0])
        
        # 处理List类型
        if origin is list:
            if args:
                inner_type = self.convert_python_type_to_proto(args[0])
                return f'repeated {inner_type}'
            else:
                return 'repeated string'
        
        # 处理Dict类型
        if origin is dict:
            # Proto3的map需要特殊处理，这里简化为string
            return 'string'
        
        # 处理Tuple类型
        if origin is tuple:
            # 转换为repeated类型
            if args:
                inner_type = self.convert_python_type_to_proto(args[0])
                return f'repeated {inner_type}'
            else:
                return 'repeated string'
        
        return self.default_proto_type
    
    def extract_field_type_from_annotation(self, annotation: Any) -> str:
        """
        从类型注解提取字段类型
        
        Args:
            annotation: 类型注解
            
        Returns:
            str: Proto字段类型
        """
        try:
            return self.convert_python_type_to_proto(annotation)
        except Exception as e:
            self.logger.warning(f"提取字段类型失败: {annotation}, 错误: {str(e)}")
            return self.default_proto_type
    
    def get_proto_field_definition(self, field_name: str, field_type: str, 
                                  field_number: int) -> str:
        """
        生成Proto字段定义
        
        Args:
            field_name: 字段名
            field_type: 字段类型
            field_number: 字段编号
            
        Returns:
            str: Proto字段定义
        """
        # 清理字段名
        clean_name = self._clean_field_name(field_name)
        
        # 处理repeated类型
        if field_type.startswith('repeated '):
            base_type = field_type[9:]  # 去掉'repeated '
            return f"    repeated {base_type} {clean_name} = {field_number};"
        
        # 普通字段
        return f"    {field_type} {clean_name} = {field_number};"
    
    def _clean_field_name(self, field_name: str) -> str:
        """
        清理字段名，确保符合Proto命名规范
        
        Args:
            field_name: 原始字段名
            
        Returns:
            str: 清理后的字段名
        """
        # 移除前导下划线
        clean_name = field_name.lstrip('_')
        
        # 确保字段名不为空
        if not clean_name:
            clean_name = 'field'
        
        # 转换为snake_case
        clean_name = self._to_snake_case(clean_name)
        
        # 确保以字母开头
        if not clean_name[0].isalpha():
            clean_name = 'field_' + clean_name
        
        return clean_name
    
    def _to_snake_case(self, name: str) -> str:
        """
        转换为snake_case
        
        Args:
            name: 原始名称
            
        Returns:
            str: snake_case名称
        """
        # 在大写字母前插入下划线
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    def is_proto_reserved_word(self, word: str) -> bool:
        """
        检查是否为Proto保留字
        
        Args:
            word: 待检查的词
            
        Returns:
            bool: 是否为保留字
        """
        proto_reserved_words = {
            'message', 'enum', 'service', 'rpc', 'returns', 'option',
            'import', 'package', 'syntax', 'extend', 'extensions',
            'reserved', 'oneof', 'map', 'repeated', 'optional', 'required',
            'double', 'float', 'int32', 'int64', 'uint32', 'uint64',
            'sint32', 'sint64', 'fixed32', 'fixed64', 'sfixed32', 'sfixed64',
            'bool', 'string', 'bytes'
        }
        
        return word.lower() in proto_reserved_words
    
    def get_safe_field_name(self, field_name: str) -> str:
        """
        获取安全的字段名（避免保留字冲突）
        
        Args:
            field_name: 原始字段名
            
        Returns:
            str: 安全的字段名
        """
        clean_name = self._clean_field_name(field_name)
        
        if self.is_proto_reserved_word(clean_name):
            clean_name = f"{clean_name}_field"
        
        return clean_name
    
    def validate_proto_type(self, proto_type: str) -> bool:
        """
        验证Proto类型是否有效
        
        Args:
            proto_type: Proto类型
            
        Returns:
            bool: 是否有效
        """
        valid_types = {
            'double', 'float', 'int32', 'int64', 'uint32', 'uint64',
            'sint32', 'sint64', 'fixed32', 'fixed64', 'sfixed32', 'sfixed64',
            'bool', 'string', 'bytes'
        }
        
        # 处理repeated类型
        if proto_type.startswith('repeated '):
            base_type = proto_type[9:]
            return base_type in valid_types
        
        return proto_type in valid_types