"""
Proto 基础消息类

该模块定义了 BaseRequest 和 BaseResponse 基类，提供消息的基础功能。
所有协议消息都应该继承这些基类，以获得统一的序列化/反序列化能力。
"""

import time
import json
from abc import ABC, abstractmethod
from typing import Type, TypeVar, Optional, Dict, Any, ClassVar

try:
    from google.protobuf.message import Message
    from google.protobuf.json_format import MessageToJson, Parse
    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False
    # Mock protobuf implementation
    class Message:
        def __init__(self):
            pass
        def SerializeToString(self):
            return b""
        def ParseFromString(self, data):
            pass
    
    def MessageToJson(message):
        return "{}"
    
    def Parse(text, message):
        return message

from .header import MessageHeader
from .exceptions import (
    ProtoException, EncodeException, DecodeException, 
    ValidationException, handle_proto_exception
)

T = TypeVar('T', bound='BaseMessage')


class BaseMessage(ABC):
    """
    消息基类
    
    提供所有消息的基础功能：
    - 消息头管理
    - 序列化/反序列化接口
    - 调试信息输出
    - 消息验证
    
    Attributes:
        header: 消息头信息
        _proto_class: Protocol Buffers 消息类（子类需要设置）
    """
    
    __slots__ = ('header', '_cached_data', '_dirty')
    
    # 类变量：子类需要设置对应的 protobuf 消息类
    _proto_class: ClassVar[Optional[Type[Message]]] = None
    
    def __init__(self):
        """初始化消息基类"""
        self.header: Optional[MessageHeader] = None
        self._cached_data: Optional[bytes] = None
        self._dirty: bool = True
    
    def __post_init__(self):
        """初始化后处理"""
        # 验证 protobuf 类是否已设置
        if self._proto_class is None:
            raise ValidationException(f"{self.__class__.__name__} 必须设置 _proto_class 类变量",
                                    message_class=self.__class__.__name__)
        
        # 如果有header则验证消息
        if self.header is not None:
            self._validate_message()
    
    @abstractmethod
    def _validate_message(self) -> None:
        """
        验证消息内容（子类实现）
        
        Raises:
            ValidationException: 验证失败时抛出
        """
        pass
    
    @abstractmethod
    def to_protobuf(self) -> Message:
        """
        转换为 Protocol Buffers 消息对象（子类实现）
        
        Returns:
            Message: Protocol Buffers 消息对象
        """
        pass
    
    @classmethod
    @abstractmethod
    def from_protobuf(cls: Type[T], proto_msg: Message, header: MessageHeader) -> T:
        """
        从 Protocol Buffers 消息对象创建实例（子类实现）
        
        Args:
            proto_msg: Protocol Buffers 消息对象
            header: 消息头
            
        Returns:
            T: 消息实例
        """
        pass
    
    @handle_proto_exception
    def serialize(self) -> bytes:
        """
        序列化消息为二进制数据
        
        Returns:
            bytes: 序列化后的二进制数据
            
        Raises:
            EncodeException: 序列化失败时抛出
        """
        if not self._dirty and self._cached_data is not None:
            return self._cached_data
        
        try:
            proto_msg = self.to_protobuf()
            data = proto_msg.SerializeToString()
            
            # 缓存序列化结果
            self._cached_data = data
            self._dirty = False
            
            return data
            
        except Exception as e:
            raise EncodeException(f"消息序列化失败: {e}",
                                message_type=self.__class__.__name__,
                                data=self.__dict__) from e
    
    @classmethod
    @handle_proto_exception
    def deserialize(cls: Type[T], data: bytes, header: MessageHeader) -> T:
        """
        从二进制数据反序列化消息
        
        Args:
            data: 二进制数据
            header: 消息头
            
        Returns:
            T: 反序列化后的消息实例
            
        Raises:
            DecodeException: 反序列化失败时抛出
        """
        if cls._proto_class is None:
            raise DecodeException(f"{cls.__name__} 未设置 _proto_class",
                                expected_type=cls.__name__)
        
        try:
            proto_msg = cls._proto_class()
            proto_msg.ParseFromString(data)
            
            instance = cls.from_protobuf(proto_msg, header)
            
            # 设置缓存
            instance._cached_data = data
            instance._dirty = False
            
            return instance
            
        except Exception as e:
            raise DecodeException(f"消息反序列化失败: {e}",
                                data=data,
                                expected_type=cls.__name__) from e
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式
        
        Returns:
            Dict[str, Any]: 字典格式的消息数据
        """
        try:
            proto_msg = self.to_protobuf()
            json_str = MessageToJson(proto_msg, preserving_proto_field_name=True)
            return json.loads(json_str)
        except Exception as e:
            raise EncodeException(f"转换为字典失败: {e}",
                                message_type=self.__class__.__name__) from e
    
    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any], header: MessageHeader) -> T:
        """
        从字典格式创建消息实例
        
        Args:
            data: 字典格式的消息数据
            header: 消息头
            
        Returns:
            T: 消息实例
        """
        if cls._proto_class is None:
            raise DecodeException(f"{cls.__name__} 未设置 _proto_class",
                                expected_type=cls.__name__)
        
        try:
            json_str = json.dumps(data)
            proto_msg = Parse(json_str, cls._proto_class())
            return cls.from_protobuf(proto_msg, header)
        except Exception as e:
            raise DecodeException(f"从字典创建消息失败: {e}",
                                expected_type=cls.__name__,
                                data=str(data)[:200]) from e
    
    def get_message_id(self) -> int:
        """获取消息ID"""
        return self.header.msg_id
    
    def get_unique_id(self) -> str:
        """获取唯一标识符"""
        return self.header.unique_id
    
    def get_timestamp(self) -> int:
        """获取时间戳"""
        return self.header.timestamp
    
    def get_age_ms(self) -> int:
        """获取消息年龄（毫秒）"""
        return self.header.get_age_ms()
    
    def is_expired(self, timeout_ms: int) -> bool:
        """判断消息是否已超时"""
        return self.header.is_expired(timeout_ms)
    
    def mark_dirty(self) -> None:
        """标记消息已修改，需要重新序列化"""
        self._dirty = True
        self._cached_data = None
    
    def reset(self) -> None:
        """
        重置消息状态（用于对象池复用）
        
        子类可以重写此方法来重置特定字段
        """
        self._cached_data = None
        self._dirty = True
    
    def __str__(self) -> str:
        """返回可读的字符串表示"""
        return (f"{self.__class__.__name__}("
                f"msg_id={self.header.msg_id}, "
                f"uuid={self.header.unique_id[:8]}..., "
                f"age={self.get_age_ms()}ms)")
    
    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        return (f"{self.__class__.__name__}("
                f"header={repr(self.header)}, "
                f"dirty={self._dirty})")


class BaseRequest(BaseMessage):
    """
    请求消息基类
    
    所有请求消息都应该继承此类。请求消息的 msg_id 必须为正数。
    """
    
    def __init__(self):
        """初始化请求消息"""
        super().__init__()
    
    def _validate_message(self) -> None:
        """验证请求消息内容"""
        if self.header is not None and not self.header.is_request():
            raise ValidationException("请求消息的msg_id必须为正数",
                                    field_name="msg_id",
                                    field_value=self.header.msg_id)
    
    @classmethod
    def create_request(cls: Type[T], msg_id: int, **kwargs) -> T:
        """
        创建请求消息实例
        
        Args:
            msg_id: 消息ID（正数）
            **kwargs: 其他参数
            
        Returns:
            T: 请求消息实例
        """
        header = MessageHeader.create_request(msg_id)
        
        # 创建实例时设置 header
        instance = cls()
        instance.header = header
        instance.__post_init__()  # 重新验证
        
        return instance
    
    def create_response(self, response_class: Type['BaseResponse'], **kwargs) -> 'BaseResponse':
        """
        基于当前请求创建响应消息
        
        Args:
            response_class: 响应消息类
            **kwargs: 响应消息参数
            
        Returns:
            BaseResponse: 响应消息实例
        """
        response_header = MessageHeader.create_response(self.header)
        
        response = response_class()
        response.header = response_header
        response.__post_init__()  # 重新验证
        
        return response


class BaseResponse(BaseMessage):
    """
    响应消息基类
    
    所有响应消息都应该继承此类。响应消息的 msg_id 必须为负数。
    包含通用的响应字段：错误码和错误信息。
    
    Attributes:
        code: 错误码，0表示成功，非0表示错误
        message: 错误信息或成功信息
    """
    
    __slots__ = ('code', 'message')
    
    def __init__(self, code: int = 0, message: str = ""):
        """初始化响应消息"""
        super().__init__()
        self.code = code
        self.message = message
    
    def _validate_message(self) -> None:
        """验证响应消息内容"""
        # 验证这是响应消息
        if self.header is not None and not self.header.is_response():
            raise ValidationException("响应消息的msg_id必须为负数",
                                    field_name="msg_id", 
                                    field_value=self.header.msg_id)
        
        # 验证错误码和消息
        if not isinstance(self.code, int):
            raise ValidationException("错误码必须是整数类型",
                                    field_name="code",
                                    field_value=type(self.code))
        
        if not isinstance(self.message, str):
            raise ValidationException("错误信息必须是字符串类型",
                                    field_name="message",
                                    field_value=type(self.message))
    
    @classmethod
    def create_response(cls: Type[T], request_header: MessageHeader, 
                       code: int = 0, message: str = "", **kwargs) -> T:
        """
        创建响应消息实例
        
        Args:
            request_header: 请求消息头
            code: 错误码
            message: 错误信息
            **kwargs: 其他参数
            
        Returns:
            T: 响应消息实例
        """
        header = MessageHeader.create_response(request_header)
        
        # 传递所有参数到构造函数
        instance = cls(code=code, message=message, **kwargs)
        instance.header = header
        instance.__post_init__()  # 重新验证
        
        return instance
    
    @classmethod
    def create_success(cls: Type[T], request_header: MessageHeader, 
                      message: str = "Success", **kwargs) -> T:
        """
        创建成功响应
        
        Args:
            request_header: 请求消息头
            message: 成功信息
            **kwargs: 其他参数
            
        Returns:
            T: 成功响应实例
        """
        return cls.create_response(request_header, code=0, message=message, **kwargs)
    
    @classmethod
    def create_error(cls: Type[T], request_header: MessageHeader, 
                    code: int, message: str, **kwargs) -> T:
        """
        创建错误响应
        
        Args:
            request_header: 请求消息头
            code: 错误码（非0）
            message: 错误信息
            **kwargs: 其他参数
            
        Returns:
            T: 错误响应实例
        """
        if code == 0:
            raise ValidationException("错误响应的错误码不能为0",
                                    field_name="code",
                                    field_value=code)
        
        return cls.create_response(request_header, code=code, message=message, **kwargs)
    
    def is_success(self) -> bool:
        """判断是否为成功响应"""
        return self.code == 0
    
    def is_error(self) -> bool:
        """判断是否为错误响应"""
        return self.code != 0
    
    def get_error_code(self) -> int:
        """获取错误码"""
        return self.code
    
    def get_error_message(self) -> str:
        """获取错误信息"""
        return self.message
    
    def reset(self) -> None:
        """重置响应消息状态"""
        super().reset()
        self.code = 0
        self.message = ""


# 消息工厂函数
class MessageFactory:
    """
    消息工厂类
    
    根据 msg_id 创建对应的消息实例，支持消息类型的注册和查找。
    """
    
    _message_classes: Dict[int, Type[BaseMessage]] = {}
    
    @classmethod
    def register(cls, msg_id: int, message_class: Type[BaseMessage]) -> None:
        """
        注册消息类
        
        Args:
            msg_id: 消息ID
            message_class: 消息类
            
        Raises:
            ValidationException: 注册失败时抛出
        """
        if not issubclass(message_class, BaseMessage):
            raise ValidationException("消息类必须继承自BaseMessage",
                                    field_name="message_class",
                                    field_value=message_class.__name__)
        
        if msg_id in cls._message_classes:
            existing_class = cls._message_classes[msg_id]
            if existing_class != message_class:
                raise ValidationException(f"消息ID {msg_id} 已被注册为 {existing_class.__name__}",
                                        field_name="msg_id",
                                        field_value=msg_id)
        
        cls._message_classes[msg_id] = message_class
    
    @classmethod
    def get_message_class(cls, msg_id: int) -> Type[BaseMessage]:
        """
        根据消息ID获取消息类
        
        Args:
            msg_id: 消息ID
            
        Returns:
            Type[BaseMessage]: 消息类
            
        Raises:
            ValidationException: 消息类未注册时抛出
        """
        if msg_id not in cls._message_classes:
            raise ValidationException(f"消息ID {msg_id} 未注册",
                                    field_name="msg_id",
                                    field_value=msg_id)
        
        return cls._message_classes[msg_id]
    
    @classmethod
    def create_message(cls, msg_id: int, data: bytes, header: MessageHeader) -> BaseMessage:
        """
        根据消息ID和数据创建消息实例
        
        Args:
            msg_id: 消息ID
            data: 消息数据
            header: 消息头
            
        Returns:
            BaseMessage: 消息实例
        """
        message_class = cls.get_message_class(msg_id)
        return message_class.deserialize(data, header)
    
    @classmethod
    def is_registered(cls, msg_id: int) -> bool:
        """
        检查消息ID是否已注册
        
        Args:
            msg_id: 消息ID
            
        Returns:
            bool: 是否已注册
        """
        return msg_id in cls._message_classes
    
    @classmethod
    def get_registered_ids(cls) -> list[int]:
        """
        获取所有已注册的消息ID
        
        Returns:
            list[int]: 消息ID列表
        """
        return list(cls._message_classes.keys())
    
    @classmethod
    def clear(cls) -> None:
        """清空所有注册的消息类"""
        cls._message_classes.clear()