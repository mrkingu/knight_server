"""
JSON工具模块

该模块提供高性能JSON序列化/反序列化功能，支持自定义类型、
循环引用检测和压缩JSON等功能。
"""

import json
import gzip
import zlib
import pickle
import base64
import datetime
import decimal
import uuid
from typing import Any, Dict, List, Optional, Union, Type, Callable, Set
from dataclasses import dataclass, is_dataclass, asdict
from enum import Enum
import weakref
from loguru import logger


class JSONError(Exception):
    """JSON相关异常"""
    pass


class CompressionType(Enum):
    """压缩类型枚举"""
    NONE = "none"
    GZIP = "gzip"
    ZLIB = "zlib"


@dataclass
class SerializationStats:
    """序列化统计信息"""
    original_size: int
    compressed_size: int
    compression_ratio: float
    serialization_time: float
    deserialization_time: float


class CustomJSONEncoder(json.JSONEncoder):
    """
    自定义JSON编码器
    
    支持更多Python类型的序列化。
    """
    
    def __init__(self, *args, **kwargs):
        """初始化编码器"""
        self.circular_refs: Set[int] = set()
        super().__init__(*args, **kwargs)
    
    def default(self, obj: Any) -> Any:
        """
        处理默认不支持的类型
        
        Args:
            obj: 要序列化的对象
            
        Returns:
            Any: 可序列化的对象
        """
        # 检查循环引用
        obj_id = id(obj)
        if obj_id in self.circular_refs:
            return {"__circular_ref__": True, "__type__": type(obj).__name__}
        
        # 添加到引用集合
        if hasattr(obj, '__dict__') or isinstance(obj, (list, dict, tuple)):
            self.circular_refs.add(obj_id)
        
        try:
            # 处理各种类型
            if isinstance(obj, datetime.datetime):
                return {
                    "__type__": "datetime",
                    "__value__": obj.isoformat()
                }
            elif isinstance(obj, datetime.date):
                return {
                    "__type__": "date",
                    "__value__": obj.isoformat()
                }
            elif isinstance(obj, datetime.time):
                return {
                    "__type__": "time",
                    "__value__": obj.isoformat()
                }
            elif isinstance(obj, decimal.Decimal):
                return {
                    "__type__": "Decimal",
                    "__value__": str(obj)
                }
            elif isinstance(obj, uuid.UUID):
                return {
                    "__type__": "UUID",
                    "__value__": str(obj)
                }
            elif isinstance(obj, bytes):
                return {
                    "__type__": "bytes",
                    "__value__": base64.b64encode(obj).decode('utf-8')
                }
            elif isinstance(obj, set):
                return {
                    "__type__": "set",
                    "__value__": list(obj)
                }
            elif isinstance(obj, frozenset):
                return {
                    "__type__": "frozenset",
                    "__value__": list(obj)
                }
            elif isinstance(obj, complex):
                return {
                    "__type__": "complex",
                    "__value__": [obj.real, obj.imag]
                }
            elif isinstance(obj, range):
                return {
                    "__type__": "range",
                    "__value__": [obj.start, obj.stop, obj.step]
                }
            elif isinstance(obj, Enum):
                return {
                    "__type__": "Enum",
                    "__class__": f"{obj.__class__.__module__}.{obj.__class__.__name__}",
                    "__value__": obj.value
                }
            elif is_dataclass(obj):
                return {
                    "__type__": "dataclass",
                    "__class__": f"{obj.__class__.__module__}.{obj.__class__.__name__}",
                    "__value__": asdict(obj)
                }
            elif hasattr(obj, '__dict__'):
                # 自定义类对象
                return {
                    "__type__": "object",
                    "__class__": f"{obj.__class__.__module__}.{obj.__class__.__name__}",
                    "__value__": obj.__dict__
                }
            else:
                # 尝试使用pickle序列化
                try:
                    pickled = pickle.dumps(obj)
                    return {
                        "__type__": "pickle",
                        "__value__": base64.b64encode(pickled).decode('utf-8')
                    }
                except Exception:
                    return {
                        "__type__": "unserializable",
                        "__value__": str(obj),
                        "__class__": type(obj).__name__
                    }
        
        finally:
            # 移除引用
            if obj_id in self.circular_refs:
                self.circular_refs.remove(obj_id)


def custom_json_decoder(dct: Dict[str, Any]) -> Any:
    """
    自定义JSON解码器
    
    Args:
        dct: 字典对象
        
    Returns:
        Any: 反序列化的对象
    """
    if "__type__" not in dct:
        return dct
    
    obj_type = dct["__type__"]
    
    try:
        if obj_type == "datetime":
            return datetime.datetime.fromisoformat(dct["__value__"])
        elif obj_type == "date":
            return datetime.date.fromisoformat(dct["__value__"])
        elif obj_type == "time":
            return datetime.time.fromisoformat(dct["__value__"])
        elif obj_type == "Decimal":
            return decimal.Decimal(dct["__value__"])
        elif obj_type == "UUID":
            return uuid.UUID(dct["__value__"])
        elif obj_type == "bytes":
            return base64.b64decode(dct["__value__"].encode('utf-8'))
        elif obj_type == "set":
            return set(dct["__value__"])
        elif obj_type == "frozenset":
            return frozenset(dct["__value__"])
        elif obj_type == "complex":
            real, imag = dct["__value__"]
            return complex(real, imag)
        elif obj_type == "range":
            start, stop, step = dct["__value__"]
            return range(start, stop, step)
        elif obj_type == "Enum":
            # 注意：这需要枚举类在当前环境中可用
            class_path = dct["__class__"]
            module_name, class_name = class_path.rsplit('.', 1)
            try:
                module = __import__(module_name, fromlist=[class_name])
                enum_class = getattr(module, class_name)
                return enum_class(dct["__value__"])
            except (ImportError, AttributeError):
                logger.warning(f"无法导入枚举类: {class_path}")
                return dct["__value__"]
        elif obj_type == "dataclass":
            # 注意：这需要数据类在当前环境中可用
            class_path = dct["__class__"]
            module_name, class_name = class_path.rsplit('.', 1)
            try:
                module = __import__(module_name, fromlist=[class_name])
                dataclass_class = getattr(module, class_name)
                return dataclass_class(**dct["__value__"])
            except (ImportError, AttributeError):
                logger.warning(f"无法导入数据类: {class_path}")
                return dct["__value__"]
        elif obj_type == "object":
            # 自定义类对象（返回字典形式）
            return dct["__value__"]
        elif obj_type == "pickle":
            pickled_data = base64.b64decode(dct["__value__"].encode('utf-8'))
            return pickle.loads(pickled_data)
        elif obj_type == "circular_ref":
            return f"<CircularReference: {dct.get('__class__', 'Unknown')}>"
        elif obj_type == "unserializable":
            return f"<Unserializable: {dct['__class__']}({dct['__value__']})>"
        else:
            logger.warning(f"未知类型: {obj_type}")
            return dct
    
    except Exception as e:
        logger.error(f"反序列化失败: {obj_type}, {e}")
        return dct


class JSONUtils:
    """
    JSON工具类
    
    提供高性能的JSON序列化和反序列化功能。
    """
    
    @staticmethod
    def dumps(obj: Any, indent: Optional[int] = None, 
             ensure_ascii: bool = False, sort_keys: bool = False,
             compression: CompressionType = CompressionType.NONE,
             custom_encoder: bool = True) -> Union[str, bytes]:
        """
        序列化对象为JSON字符串
        
        Args:
            obj: 要序列化的对象
            indent: 缩进空格数
            ensure_ascii: 是否确保ASCII编码
            sort_keys: 是否排序键
            compression: 压缩类型
            custom_encoder: 是否使用自定义编码器
            
        Returns:
            Union[str, bytes]: JSON字符串或压缩后的字节数据
        """
        try:
            # 选择编码器
            if custom_encoder:
                encoder_cls = CustomJSONEncoder
            else:
                encoder_cls = None
            
            # 序列化
            json_str = json.dumps(
                obj,
                indent=indent,
                ensure_ascii=ensure_ascii,
                sort_keys=sort_keys,
                cls=encoder_cls
            )
            
            # 压缩
            if compression == CompressionType.GZIP:
                return gzip.compress(json_str.encode('utf-8'))
            elif compression == CompressionType.ZLIB:
                return zlib.compress(json_str.encode('utf-8'))
            else:
                return json_str
        
        except Exception as e:
            raise JSONError(f"JSON序列化失败: {e}")
    
    @staticmethod
    def loads(data: Union[str, bytes], 
             compression: CompressionType = CompressionType.NONE,
             custom_decoder: bool = True) -> Any:
        """
        反序列化JSON字符串为对象
        
        Args:
            data: JSON字符串或压缩数据
            compression: 压缩类型
            custom_decoder: 是否使用自定义解码器
            
        Returns:
            Any: 反序列化的对象
        """
        try:
            # 解压缩
            if compression == CompressionType.GZIP:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                json_str = gzip.decompress(data).decode('utf-8')
            elif compression == CompressionType.ZLIB:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                json_str = zlib.decompress(data).decode('utf-8')
            else:
                json_str = data if isinstance(data, str) else data.decode('utf-8')
            
            # 反序列化
            if custom_decoder:
                return json.loads(json_str, object_hook=custom_json_decoder)
            else:
                return json.loads(json_str)
        
        except Exception as e:
            raise JSONError(f"JSON反序列化失败: {e}")
    
    @staticmethod
    def load_file(file_path: str, 
                 compression: CompressionType = CompressionType.NONE,
                 encoding: str = 'utf-8') -> Any:
        """
        从文件加载JSON数据
        
        Args:
            file_path: 文件路径
            compression: 压缩类型
            encoding: 文件编码
            
        Returns:
            Any: 加载的数据
        """
        try:
            if compression == CompressionType.GZIP:
                with gzip.open(file_path, 'rt', encoding=encoding) as f:
                    return json.load(f, object_hook=custom_json_decoder)
            else:
                with open(file_path, 'r', encoding=encoding) as f:
                    return json.load(f, object_hook=custom_json_decoder)
        
        except Exception as e:
            raise JSONError(f"从文件加载JSON失败: {e}")
    
    @staticmethod
    def save_file(obj: Any, file_path: str, 
                 indent: Optional[int] = 2,
                 compression: CompressionType = CompressionType.NONE,
                 encoding: str = 'utf-8') -> None:
        """
        保存数据到JSON文件
        
        Args:
            obj: 要保存的对象
            file_path: 文件路径
            indent: 缩进空格数
            compression: 压缩类型
            encoding: 文件编码
        """
        try:
            if compression == CompressionType.GZIP:
                with gzip.open(file_path, 'wt', encoding=encoding) as f:
                    json.dump(obj, f, indent=indent, ensure_ascii=False, cls=CustomJSONEncoder)
            else:
                with open(file_path, 'w', encoding=encoding) as f:
                    json.dump(obj, f, indent=indent, ensure_ascii=False, cls=CustomJSONEncoder)
        
        except Exception as e:
            raise JSONError(f"保存JSON到文件失败: {e}")
    
    @staticmethod
    def pretty_print(obj: Any, max_depth: int = 10) -> str:
        """
        美化打印JSON
        
        Args:
            obj: 要打印的对象
            max_depth: 最大深度
            
        Returns:
            str: 美化后的JSON字符串
        """
        try:
            return json.dumps(
                obj, 
                indent=2, 
                ensure_ascii=False, 
                cls=CustomJSONEncoder
            )
        except Exception as e:
            return f"无法序列化对象: {e}"
    
    @staticmethod
    def minify(json_str: str) -> str:
        """
        压缩JSON字符串（移除空白字符）
        
        Args:
            json_str: JSON字符串
            
        Returns:
            str: 压缩后的JSON字符串
        """
        try:
            obj = json.loads(json_str)
            return json.dumps(obj, separators=(',', ':'))
        except Exception as e:
            raise JSONError(f"JSON压缩失败: {e}")
    
    @staticmethod
    def validate(json_str: str) -> bool:
        """
        验证JSON字符串是否有效
        
        Args:
            json_str: JSON字符串
            
        Returns:
            bool: 是否有效
        """
        try:
            json.loads(json_str)
            return True
        except Exception:
            return False
    
    @staticmethod
    def get_size_info(obj: Any, compression: CompressionType = CompressionType.NONE) -> Dict[str, int]:
        """
        获取对象序列化后的大小信息
        
        Args:
            obj: 对象
            compression: 压缩类型
            
        Returns:
            Dict[str, int]: 大小信息
        """
        # 原始JSON大小
        json_str = JSONUtils.dumps(obj, custom_encoder=True)
        original_size = len(json_str.encode('utf-8')) if isinstance(json_str, str) else len(json_str)
        
        # 压缩后大小
        if compression != CompressionType.NONE:
            compressed_data = JSONUtils.dumps(obj, compression=compression, custom_encoder=True)
            compressed_size = len(compressed_data)
        else:
            compressed_size = original_size
        
        return {
            'original_size': original_size,
            'compressed_size': compressed_size,
            'compression_ratio': compressed_size / original_size if original_size > 0 else 0,
            'savings': original_size - compressed_size
        }


class JSONCache:
    """
    JSON缓存
    
    提供JSON数据的内存缓存功能。
    """
    
    def __init__(self, max_size: int = 1000):
        """
        初始化缓存
        
        Args:
            max_size: 最大缓存条目数
        """
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._access_order: List[str] = []
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[Any]: 缓存数据
        """
        if key in self._cache:
            # 更新访问顺序
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        """
        设置缓存数据
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        if key in self._cache:
            # 更新现有条目
            self._access_order.remove(key)
        elif len(self._cache) >= self.max_size:
            # 删除最久未访问的条目
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]
        
        self._cache[key] = value
        self._access_order.append(key)
    
    def remove(self, key: str) -> bool:
        """
        删除缓存条目
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 是否成功删除
        """
        if key in self._cache:
            del self._cache[key]
            self._access_order.remove(key)
            return True
        return False
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._access_order.clear()
    
    def size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)
    
    def keys(self) -> List[str]:
        """获取所有缓存键"""
        return list(self._cache.keys())


class JSONSchema:
    """
    简单的JSON模式验证器
    """
    
    @staticmethod
    def validate_structure(data: Any, schema: Dict[str, Any]) -> bool:
        """
        验证数据结构是否符合模式
        
        Args:
            data: 要验证的数据
            schema: 模式定义
            
        Returns:
            bool: 是否符合模式
        """
        try:
            return JSONSchema._validate_recursive(data, schema)
        except Exception:
            return False
    
    @staticmethod
    def _validate_recursive(data: Any, schema: Dict[str, Any]) -> bool:
        """递归验证数据结构"""
        # 检查类型
        if 'type' in schema:
            expected_type = schema['type']
            if expected_type == 'object' and not isinstance(data, dict):
                return False
            elif expected_type == 'array' and not isinstance(data, list):
                return False
            elif expected_type == 'string' and not isinstance(data, str):
                return False
            elif expected_type == 'number' and not isinstance(data, (int, float)):
                return False
            elif expected_type == 'boolean' and not isinstance(data, bool):
                return False
            elif expected_type == 'null' and data is not None:
                return False
        
        # 检查对象属性
        if isinstance(data, dict) and 'properties' in schema:
            properties = schema['properties']
            required = schema.get('required', [])
            
            # 检查必需属性
            for req_prop in required:
                if req_prop not in data:
                    return False
            
            # 检查属性类型
            for prop, prop_schema in properties.items():
                if prop in data:
                    if not JSONSchema._validate_recursive(data[prop], prop_schema):
                        return False
        
        # 检查数组元素
        if isinstance(data, list) and 'items' in schema:
            item_schema = schema['items']
            for item in data:
                if not JSONSchema._validate_recursive(item, item_schema):
                    return False
        
        return True


# 全局JSON缓存实例
json_cache = JSONCache()

# 便捷函数
def dumps(obj: Any, **kwargs) -> Union[str, bytes]:
    """序列化对象的便捷函数"""
    return JSONUtils.dumps(obj, **kwargs)

def loads(data: Union[str, bytes], **kwargs) -> Any:
    """反序列化对象的便捷函数"""
    return JSONUtils.loads(data, **kwargs)

def load_file(file_path: str, **kwargs) -> Any:
    """从文件加载JSON的便捷函数"""
    return JSONUtils.load_file(file_path, **kwargs)

def save_file(obj: Any, file_path: str, **kwargs) -> None:
    """保存JSON到文件的便捷函数"""
    return JSONUtils.save_file(obj, file_path, **kwargs)

def pretty_print(obj: Any) -> str:
    """美化打印的便捷函数"""
    return JSONUtils.pretty_print(obj)


if __name__ == "__main__":
    # 测试代码
    def test_json_utils():
        """测试JSON工具"""
        
        # 测试数据
        test_data = {
            'string': 'Hello, 世界!',
            'number': 42,
            'float': 3.14159,
            'boolean': True,
            'null': None,
            'list': [1, 2, 3, 'test'],
            'dict': {'nested': 'value'},
            'datetime': datetime.datetime.now(),
            'date': datetime.date.today(),
            'decimal': decimal.Decimal('123.456'),
            'uuid': uuid.uuid4(),
            'bytes': b'binary data',
            'set': {1, 2, 3, 4, 5},
            'complex': complex(1, 2)
        }
        
        print("原始数据:")
        print(pretty_print(test_data))
        
        # 测试序列化和反序列化
        print("\n测试序列化和反序列化:")
        json_str = dumps(test_data, indent=2)
        print(f"JSON大小: {len(json_str)} 字符")
        
        restored_data = loads(json_str)
        print("反序列化成功")
        
        # 测试压缩
        print("\n测试压缩:")
        compressed_data = dumps(test_data, compression=CompressionType.GZIP)
        print(f"压缩后大小: {len(compressed_data)} 字节")
        
        decompressed_data = loads(compressed_data, compression=CompressionType.GZIP)
        print("解压缩成功")
        
        # 测试大小信息
        print("\n大小信息:")
        size_info = JSONUtils.get_size_info(test_data, CompressionType.GZIP)
        print(f"原始大小: {size_info['original_size']} 字节")
        print(f"压缩后大小: {size_info['compressed_size']} 字节")
        print(f"压缩比: {size_info['compression_ratio']:.2%}")
        print(f"节省空间: {size_info['savings']} 字节")
        
        # 测试缓存
        print("\n测试缓存:")
        json_cache.set("test_data", test_data)
        cached_data = json_cache.get("test_data")
        print(f"缓存命中: {cached_data is not None}")
        print(f"缓存大小: {json_cache.size()}")
        
        # 测试模式验证
        print("\n测试模式验证:")
        schema = {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'age': {'type': 'number'},
                'active': {'type': 'boolean'}
            },
            'required': ['name', 'age']
        }
        
        valid_data = {'name': 'John', 'age': 30, 'active': True}
        invalid_data = {'name': 'John', 'active': 'yes'}
        
        print(f"有效数据验证: {JSONSchema.validate_structure(valid_data, schema)}")
        print(f"无效数据验证: {JSONSchema.validate_structure(invalid_data, schema)}")
    
    test_json_utils()