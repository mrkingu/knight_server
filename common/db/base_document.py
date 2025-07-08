"""
基础文档类

该模块提供MongoDB文档的基础类，包含以下功能：
- 标准字段定义（_id, created_at, updated_at, version, is_deleted）
- 字段验证
- 序列化/反序列化
- 版本控制（乐观锁）
- 软删除支持
- 时间戳自动管理
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional, Type, TypeVar, get_type_hints, Union
from dataclasses import dataclass, field, fields, asdict
from abc import ABC, abstractmethod

from common.logger import logger
from common.utils.id_generator import generate_id


T = TypeVar('T', bound='BaseDocument')


class DocumentError(Exception):
    """文档相关异常"""
    pass


class ValidationError(DocumentError):
    """字段验证异常"""
    pass


class SerializationError(DocumentError):
    """序列化异常"""
    pass


def current_timestamp() -> datetime:
    """获取当前时间戳"""
    return datetime.utcnow()


@dataclass
class BaseDocument(ABC):
    """
    基础文档类
    
    所有MongoDB文档的基类，提供标准字段和通用功能。
    """
    
    # 基础字段
    _id: Optional[str] = field(default=None)
    created_at: datetime = field(default_factory=current_timestamp)
    updated_at: datetime = field(default_factory=current_timestamp) 
    version: int = field(default=1)
    is_deleted: bool = field(default=False)
    
    def __post_init__(self):
        """初始化后处理"""
        # 生成ID（如果未提供）
        if self._id is None:
            self._id = str(generate_id())
        
        # 验证字段
        self.validate()
    
    @classmethod
    def get_collection_name(cls) -> str:
        """
        获取集合名称
        
        默认使用类名的小写形式，子类可以重写此方法自定义集合名称。
        
        Returns:
            集合名称
        """
        return cls.__name__.lower()
    
    @classmethod
    def get_field_names(cls) -> list[str]:
        """
        获取所有字段名
        
        Returns:
            字段名列表
        """
        return [f.name for f in fields(cls)]
    
    @classmethod
    def get_field_types(cls) -> Dict[str, Type]:
        """
        获取字段类型映射
        
        Returns:
            字段名到类型的映射
        """
        return get_type_hints(cls)
    
    def validate(self) -> None:
        """
        验证文档字段
        
        子类可以重写此方法实现自定义验证逻辑。
        
        Raises:
            ValidationError: 验证失败时抛出
        """
        # 基础字段验证
        if self._id is not None and not isinstance(self._id, str):
            raise ValidationError("_id必须是字符串类型")
        
        if not isinstance(self.created_at, datetime):
            raise ValidationError("created_at必须是datetime类型")
        
        if not isinstance(self.updated_at, datetime):
            raise ValidationError("updated_at必须是datetime类型")
        
        if not isinstance(self.version, int) or self.version < 1:
            raise ValidationError("version必须是正整数")
        
        if not isinstance(self.is_deleted, bool):
            raise ValidationError("is_deleted必须是布尔类型")
        
        # 时间逻辑验证
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at不能早于created_at")
    
    def update_timestamp(self) -> None:
        """更新时间戳"""
        self.updated_at = current_timestamp()
    
    def increment_version(self) -> None:
        """增加版本号（用于乐观锁）"""
        self.version += 1
        self.update_timestamp()
    
    def soft_delete(self) -> None:
        """软删除"""
        self.is_deleted = True
        self.update_timestamp()
    
    def restore(self) -> None:
        """恢复软删除"""
        self.is_deleted = False
        self.update_timestamp()
    
    def to_dict(self, include_private: bool = True, exclude_none: bool = False) -> Dict[str, Any]:
        """
        转换为字典
        
        Args:
            include_private: 是否包含私有字段（以_开头）
            exclude_none: 是否排除None值
            
        Returns:
            字典表示
        """
        try:
            data = asdict(self)
            
            # 处理私有字段
            if not include_private:
                data = {k: v for k, v in data.items() if not k.startswith('_')}
            
            # 处理None值
            if exclude_none:
                data = {k: v for k, v in data.items() if v is not None}
            
            # 处理特殊类型
            for key, value in data.items():
                if isinstance(value, datetime):
                    data[key] = value.isoformat()
            
            return data
            
        except Exception as e:
            raise SerializationError(f"序列化失败: {e}")
    
    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """
        从字典创建实例
        
        Args:
            data: 字典数据
            
        Returns:
            文档实例
            
        Raises:
            SerializationError: 反序列化失败时抛出
        """
        try:
            # 复制数据避免修改原数据
            data_copy = data.copy()
            
            # 获取字段类型
            field_types = cls.get_field_types()
            
            # 处理特殊类型转换
            for field_name, field_type in field_types.items():
                if field_name in data_copy:
                    value = data_copy[field_name]
                    
                    # datetime类型转换
                    if field_type == datetime and isinstance(value, str):
                        try:
                            data_copy[field_name] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError:
                            # 尝试其他常见格式
                            try:
                                from datetime import datetime as dt
                                data_copy[field_name] = dt.strptime(value, '%Y-%m-%dT%H:%M:%S.%f')
                            except ValueError:
                                data_copy[field_name] = dt.strptime(value, '%Y-%m-%dT%H:%M:%S')
                    
                    # Optional类型处理
                    elif hasattr(field_type, '__origin__') and field_type.__origin__ is Union:
                        # 处理Optional[T]类型
                        args = field_type.__args__
                        if len(args) == 2 and type(None) in args:
                            actual_type = args[0] if args[1] is type(None) else args[1]
                            if actual_type == datetime and isinstance(value, str):
                                try:
                                    data_copy[field_name] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                except ValueError:
                                    try:
                                        from datetime import datetime as dt
                                        data_copy[field_name] = dt.strptime(value, '%Y-%m-%dT%H:%M:%S.%f')
                                    except ValueError:
                                        data_copy[field_name] = dt.strptime(value, '%Y-%m-%dT%H:%M:%S')
            
            # 创建实例
            return cls(**data_copy)
            
        except TypeError as e:
            raise SerializationError(f"反序列化失败，字段不匹配: {e}")
        except Exception as e:
            raise SerializationError(f"反序列化失败: {e}")
    
    def to_json(self, indent: Optional[int] = None, ensure_ascii: bool = False) -> str:
        """
        转换为JSON字符串
        
        Args:
            indent: 缩进级别
            ensure_ascii: 是否确保ASCII编码
            
        Returns:
            JSON字符串
        """
        try:
            data = self.to_dict()
            return json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=str)
        except Exception as e:
            raise SerializationError(f"JSON序列化失败: {e}")
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """
        从JSON字符串创建实例
        
        Args:
            json_str: JSON字符串
            
        Returns:
            文档实例
        """
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            raise SerializationError(f"JSON解析失败: {e}")
        except Exception as e:
            raise SerializationError(f"从JSON创建实例失败: {e}")
    
    def clone(self: T, **updates) -> T:
        """
        克隆文档实例
        
        Args:
            **updates: 要更新的字段
            
        Returns:
            新的文档实例
        """
        data = self.to_dict()
        data.update(updates)
        
        # 生成新的ID和时间戳
        data['_id'] = str(generate_id())
        data['created_at'] = current_timestamp()
        data['updated_at'] = current_timestamp()
        data['version'] = 1
        
        return self.__class__.from_dict(data)
    
    def update_fields(self, **updates) -> None:
        """
        更新字段值
        
        Args:
            **updates: 要更新的字段
        """
        for key, value in updates.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        self.update_timestamp()
        self.validate()
    
    def get_changes(self, other: 'BaseDocument') -> Dict[str, Dict[str, Any]]:
        """
        获取与另一个文档的差异
        
        Args:
            other: 另一个文档实例
            
        Returns:
            差异字典，格式为 {field: {'old': old_value, 'new': new_value}}
        """
        if not isinstance(other, self.__class__):
            raise ValueError("只能比较相同类型的文档")
        
        changes = {}
        self_dict = self.to_dict()
        other_dict = other.to_dict()
        
        all_keys = set(self_dict.keys()) | set(other_dict.keys())
        
        for key in all_keys:
            self_value = self_dict.get(key)
            other_value = other_dict.get(key)
            
            if self_value != other_value:
                changes[key] = {
                    'old': other_value,
                    'new': self_value
                }
        
        return changes
    
    def is_new(self) -> bool:
        """
        判断是否为新文档（版本号为1且创建时间等于更新时间）
        
        Returns:
            是否为新文档
        """
        return (self.version == 1 and 
                self.created_at == self.updated_at)
    
    def is_modified(self) -> bool:
        """
        判断是否已修改（版本号大于1或更新时间晚于创建时间）
        
        Returns:
            是否已修改
        """
        return (self.version > 1 or 
                self.updated_at > self.created_at)
    
    def get_age(self) -> float:
        """
        获取文档年龄（秒）
        
        Returns:
            文档年龄
        """
        now = current_timestamp()
        return (now - self.created_at).total_seconds()
    
    def get_last_modified_age(self) -> float:
        """
        获取最后修改时间的年龄（秒）
        
        Returns:
            最后修改年龄
        """
        now = current_timestamp()
        return (now - self.updated_at).total_seconds()
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"{self.__class__.__name__}(id={self._id}, version={self.version})"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        return f"{self.__class__.__name__}({self.to_dict()})"
    
    def __eq__(self, other) -> bool:
        """相等比较（基于ID）"""
        if not isinstance(other, self.__class__):
            return False
        return self._id == other._id
    
    def __hash__(self) -> int:
        """哈希值（基于ID）"""
        return hash(self._id) if self._id else hash(id(self))


class DocumentRegistry:
    """
    文档注册表
    
    用于管理所有文档类的注册和元数据。
    """
    
    def __init__(self):
        self._documents: Dict[str, Type[BaseDocument]] = {}
        self._collection_mapping: Dict[str, Type[BaseDocument]] = {}
    
    def register(self, document_class: Type[BaseDocument]) -> None:
        """
        注册文档类
        
        Args:
            document_class: 文档类
        """
        if not issubclass(document_class, BaseDocument):
            raise ValueError(f"{document_class} 必须继承自 BaseDocument")
        
        class_name = document_class.__name__
        collection_name = document_class.get_collection_name()
        
        if class_name in self._documents:
            logger.warning(f"文档类 {class_name} 已存在，将被覆盖")
        
        if collection_name in self._collection_mapping:
            existing_class = self._collection_mapping[collection_name]
            if existing_class != document_class:
                logger.warning(f"集合 {collection_name} 已被 {existing_class} 使用")
        
        self._documents[class_name] = document_class
        self._collection_mapping[collection_name] = document_class
        
        logger.info(f"注册文档类: {class_name} -> {collection_name}")
    
    def get_document_class(self, class_name: str) -> Optional[Type[BaseDocument]]:
        """
        根据类名获取文档类
        
        Args:
            class_name: 类名
            
        Returns:
            文档类或None
        """
        return self._documents.get(class_name)
    
    def get_document_class_by_collection(self, collection_name: str) -> Optional[Type[BaseDocument]]:
        """
        根据集合名获取文档类
        
        Args:
            collection_name: 集合名
            
        Returns:
            文档类或None
        """
        return self._collection_mapping.get(collection_name)
    
    def list_documents(self) -> list[str]:
        """
        列出所有注册的文档类名
        
        Returns:
            文档类名列表
        """
        return list(self._documents.keys())
    
    def list_collections(self) -> list[str]:
        """
        列出所有集合名
        
        Returns:
            集合名列表
        """
        return list(self._collection_mapping.keys())
    
    def get_document_info(self, class_name: str) -> Optional[Dict[str, Any]]:
        """
        获取文档类信息
        
        Args:
            class_name: 类名
            
        Returns:
            文档类信息
        """
        document_class = self._documents.get(class_name)
        if not document_class:
            return None
        
        return {
            'class_name': class_name,
            'collection_name': document_class.get_collection_name(),
            'fields': document_class.get_field_names(),
            'field_types': {k: str(v) for k, v in document_class.get_field_types().items()},
            'module': document_class.__module__
        }
    
    def clear(self) -> None:
        """清空注册表"""
        self._documents.clear()
        self._collection_mapping.clear()
        logger.info("文档注册表已清空")


# 全局文档注册表
document_registry = DocumentRegistry()


def register_document(document_class: Type[BaseDocument]) -> Type[BaseDocument]:
    """
    注册文档类的装饰器
    
    Args:
        document_class: 文档类
        
    Returns:
        文档类
    """
    document_registry.register(document_class)
    return document_class


# 示例文档类
@register_document
@dataclass
class User(BaseDocument):
    """用户文档示例"""
    
    user_id: str = ""
    username: str = ""
    email: str = ""
    phone: Optional[str] = None
    avatar: Optional[str] = None
    status: str = "active"  # active, inactive, banned
    last_login_at: Optional[datetime] = None
    
    @classmethod
    def get_collection_name(cls) -> str:
        return "users"
    
    def validate(self) -> None:
        """自定义验证"""
        super().validate()
        
        if not self.user_id:
            raise ValidationError("user_id不能为空")
        
        if not self.username:
            raise ValidationError("username不能为空")
        
        if not self.email:
            raise ValidationError("email不能为空")
        
        if self.status not in ['active', 'inactive', 'banned']:
            raise ValidationError("status必须是 active, inactive 或 banned")
    
    def is_active(self) -> bool:
        """判断用户是否活跃"""
        return self.status == "active" and not self.is_deleted
    
    def ban(self) -> None:
        """封禁用户"""
        self.status = "banned"
        self.update_timestamp()
    
    def activate(self) -> None:
        """激活用户"""
        self.status = "active"
        self.update_timestamp()


@register_document  
@dataclass
class GameRecord(BaseDocument):
    """游戏记录文档示例"""
    
    user_id: str = ""
    game_type: str = ""
    score: int = 0
    duration: int = 0  # 游戏时长（秒）
    result: str = "unknown"  # win, lose, draw, unknown
    metadata: Optional[Dict[str, Any]] = None
    
    @classmethod
    def get_collection_name(cls) -> str:
        return "game_records"
    
    def validate(self) -> None:
        """自定义验证"""
        super().validate()
        
        if not self.user_id:
            raise ValidationError("user_id不能为空")
        
        if not self.game_type:
            raise ValidationError("game_type不能为空")
        
        if self.score < 0:
            raise ValidationError("score不能为负数")
        
        if self.duration < 0:
            raise ValidationError("duration不能为负数")
        
        if self.result not in ['win', 'lose', 'draw', 'unknown']:
            raise ValidationError("result必须是 win, lose, draw 或 unknown")
    
    def is_victory(self) -> bool:
        """判断是否胜利"""
        return self.result == "win"
    
    def get_score_per_second(self) -> float:
        """获取每秒得分"""
        if self.duration <= 0:
            return 0.0
        return self.score / self.duration


# 便捷函数
def get_document_class(class_name: str) -> Optional[Type[BaseDocument]]:
    """获取文档类的便捷函数"""
    return document_registry.get_document_class(class_name)


def get_document_class_by_collection(collection_name: str) -> Optional[Type[BaseDocument]]:
    """根据集合名获取文档类的便捷函数"""
    return document_registry.get_document_class_by_collection(collection_name)


def list_registered_documents() -> list[str]:
    """列出所有注册文档的便捷函数"""
    return document_registry.list_documents()


def create_document_from_dict(collection_name: str, data: Dict[str, Any]) -> Optional[BaseDocument]:
    """从字典创建文档实例的便捷函数"""
    document_class = get_document_class_by_collection(collection_name)
    if document_class:
        return document_class.from_dict(data)
    return None