"""
协议装饰器模块

该模块提供协议相关的装饰器，用于绑定消息类型和协议号。
支持请求/响应协议绑定、消息类型标记和自动序列化。

主要功能：
- @proto_message: 绑定消息类型和协议号
- @request_proto: 标记请求协议
- @response_proto: 标记响应协议
- 自动协议号管理
- 消息序列化/反序列化
"""

import functools
import inspect
import time
from typing import Callable, Any, Dict, Optional, Type, Union, get_type_hints
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger


class ProtoType(Enum):
    """协议类型枚举"""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    EVENT = "event"


@dataclass
class ProtoMessageInfo:
    """协议消息信息"""
    message_id: int
    message_type: ProtoType
    message_class: Type
    message_name: str
    version: str = "1.0"
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProtoBindingInfo:
    """协议绑定信息"""
    request_proto: Optional[ProtoMessageInfo] = None
    response_proto: Optional[ProtoMessageInfo] = None
    handler_name: str = ""
    timeout: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProtoRegistry:
    """协议注册表"""
    
    def __init__(self):
        self._messages: Dict[int, ProtoMessageInfo] = {}
        self._message_types: Dict[Type, ProtoMessageInfo] = {}
        self._bindings: Dict[str, ProtoBindingInfo] = {}
        self._next_message_id = 1000
    
    def register_message(self, message_info: ProtoMessageInfo):
        """注册协议消息"""
        # 检查消息ID是否重复
        if message_info.message_id in self._messages:
            existing = self._messages[message_info.message_id]
            logger.warning("协议消息ID重复",
                         message_id=message_info.message_id,
                         existing_type=existing.message_class.__name__,
                         new_type=message_info.message_class.__name__)
        
        self._messages[message_info.message_id] = message_info
        self._message_types[message_info.message_class] = message_info
        
        logger.info("协议消息注册成功",
                   message_id=message_info.message_id,
                   message_type=message_info.message_type.value,
                   message_class=message_info.message_class.__name__)
    
    def get_message_by_id(self, message_id: int) -> Optional[ProtoMessageInfo]:
        """根据ID获取协议消息"""
        return self._messages.get(message_id)
    
    def get_message_by_type(self, message_type: Type) -> Optional[ProtoMessageInfo]:
        """根据类型获取协议消息"""
        return self._message_types.get(message_type)
    
    def register_binding(self, handler_name: str, binding_info: ProtoBindingInfo):
        """注册协议绑定"""
        self._bindings[handler_name] = binding_info
        logger.info("协议绑定注册成功", handler_name=handler_name)
    
    def get_binding(self, handler_name: str) -> Optional[ProtoBindingInfo]:
        """获取协议绑定"""
        return self._bindings.get(handler_name)
    
    def generate_message_id(self) -> int:
        """生成新的消息ID"""
        message_id = self._next_message_id
        self._next_message_id += 1
        return message_id
    
    def list_messages(self) -> Dict[int, ProtoMessageInfo]:
        """列出所有注册的消息"""
        return self._messages.copy()


# 全局协议注册表
_proto_registry = ProtoRegistry()


def proto_message(message_id: Optional[int] = None,
                 message_type: ProtoType = ProtoType.REQUEST,
                 version: str = "1.0",
                 description: str = "",
                 **kwargs) -> Callable:
    """
    绑定消息类型和协议号的装饰器
    
    Args:
        message_id: 消息ID，如果为None则自动生成
        message_type: 消息类型
        version: 协议版本
        description: 消息描述
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @proto_message(message_id=1001, message_type=ProtoType.REQUEST)
    class LoginRequest:
        username: str
        password: str
    
    @proto_message(message_id=1002, message_type=ProtoType.RESPONSE)
    class LoginResponse:
        success: bool
        token: str
    ```
    """
    def decorator(cls: Type) -> Type:
        # 生成或使用指定的消息ID
        msg_id = message_id if message_id is not None else _proto_registry.generate_message_id()
        
        # 创建消息信息
        message_info = ProtoMessageInfo(
            message_id=msg_id,
            message_type=message_type,
            message_class=cls,
            message_name=cls.__name__,
            version=version,
            description=description,
            metadata=kwargs
        )
        
        # 注册消息
        _proto_registry.register_message(message_info)
        
        # 在类上添加消息信息
        cls._proto_message_info = message_info
        
        # 添加序列化/反序列化方法
        cls.serialize = _create_serialize_method(message_info)
        cls.deserialize = _create_deserialize_method(message_info)
        
        # 添加获取消息ID的方法
        cls.get_message_id = lambda: msg_id
        cls.get_message_type = lambda: message_type
        
        logger.info("协议消息装饰完成",
                   message_id=msg_id,
                   message_type=message_type.value,
                   class_name=cls.__name__)
        
        return cls
    
    return decorator


def request_proto(message_id: Optional[int] = None,
                 version: str = "1.0",
                 description: str = "",
                 **kwargs) -> Callable:
    """
    标记请求协议的装饰器
    
    Args:
        message_id: 消息ID
        version: 协议版本
        description: 消息描述
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @request_proto(message_id=1001)
    class LoginRequest:
        username: str
        password: str
    ```
    """
    return proto_message(
        message_id=message_id,
        message_type=ProtoType.REQUEST,
        version=version,
        description=description,
        **kwargs
    )


def response_proto(message_id: Optional[int] = None,
                  version: str = "1.0",
                  description: str = "",
                  **kwargs) -> Callable:
    """
    标记响应协议的装饰器
    
    Args:
        message_id: 消息ID
        version: 协议版本
        description: 消息描述
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @response_proto(message_id=1002)
    class LoginResponse:
        success: bool
        token: str
    ```
    """
    return proto_message(
        message_id=message_id,
        message_type=ProtoType.RESPONSE,
        version=version,
        description=description,
        **kwargs
    )


def notification_proto(message_id: Optional[int] = None,
                      version: str = "1.0",
                      description: str = "",
                      **kwargs) -> Callable:
    """
    标记通知协议的装饰器
    
    Args:
        message_id: 消息ID
        version: 协议版本
        description: 消息描述
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @notification_proto(message_id=2001)
    class SystemNotification:
        message: str
        timestamp: int
    ```
    """
    return proto_message(
        message_id=message_id,
        message_type=ProtoType.NOTIFICATION,
        version=version,
        description=description,
        **kwargs
    )


def event_proto(message_id: Optional[int] = None,
               version: str = "1.0",
               description: str = "",
               **kwargs) -> Callable:
    """
    标记事件协议的装饰器
    
    Args:
        message_id: 消息ID
        version: 协议版本
        description: 消息描述
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @event_proto(message_id=3001)
    class UserLoginEvent:
        user_id: str
        login_time: int
    ```
    """
    return proto_message(
        message_id=message_id,
        message_type=ProtoType.EVENT,
        version=version,
        description=description,
        **kwargs
    )


def proto_binding(request_proto_class: Optional[Type] = None,
                 response_proto_class: Optional[Type] = None,
                 timeout: float = 30.0,
                 **kwargs) -> Callable:
    """
    协议绑定装饰器，用于绑定请求和响应协议
    
    Args:
        request_proto_class: 请求协议类
        response_proto_class: 响应协议类
        timeout: 超时时间(秒)
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @proto_binding(
        request_proto_class=LoginRequest,
        response_proto_class=LoginResponse,
        timeout=10.0
    )
    async def handle_login(request: LoginRequest) -> LoginResponse:
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        # 获取协议信息
        request_proto = None
        response_proto = None
        
        if request_proto_class:
            request_proto = _proto_registry.get_message_by_type(request_proto_class)
        
        if response_proto_class:
            response_proto = _proto_registry.get_message_by_type(response_proto_class)
        
        # 创建绑定信息
        binding_info = ProtoBindingInfo(
            request_proto=request_proto,
            response_proto=response_proto,
            handler_name=func.__name__,
            timeout=timeout,
            metadata=kwargs
        )
        
        # 注册绑定
        _proto_registry.register_binding(func.__name__, binding_info)
        
        # 在函数上添加绑定信息
        func._proto_binding_info = binding_info
        
        # 包装函数以添加协议处理功能
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                # 检查和转换参数
                processed_args, processed_kwargs = _process_proto_args(
                    func, args, kwargs, binding_info
                )
                
                # 调用原始函数
                result = await func(*processed_args, **processed_kwargs)
                
                # 处理返回值
                processed_result = _process_proto_result(result, binding_info)
                
                # 记录成功调用
                latency = time.time() - start_time
                logger.debug("协议绑定方法调用成功",
                           method=func.__name__,
                           latency=latency)
                
                return processed_result
                
            except Exception as e:
                # 记录错误调用
                latency = time.time() - start_time
                logger.error("协议绑定方法调用失败",
                           method=func.__name__,
                           error=str(e),
                           latency=latency)
                raise
        
        return wrapper
    
    return decorator


def _create_serialize_method(message_info: ProtoMessageInfo) -> Callable:
    """创建序列化方法"""
    def serialize(self) -> bytes:
        """序列化消息对象"""
        try:
            # 这里应该根据实际的协议实现序列化
            # 暂时使用JSON序列化
            import json
            from dataclasses import asdict, is_dataclass
            
            if is_dataclass(self):
                data = asdict(self)
            elif hasattr(self, '__dict__'):
                data = self.__dict__
            else:
                data = {"value": self}
            
            # 添加消息头信息
            message_packet = {
                "message_id": message_info.message_id,
                "message_type": message_info.message_type.value,
                "version": message_info.version,
                "data": data,
                "timestamp": int(time.time() * 1000)
            }
            
            return json.dumps(message_packet).encode('utf-8')
            
        except Exception as e:
            logger.error("消息序列化失败",
                        message_id=message_info.message_id,
                        error=str(e))
            raise
    
    return serialize


def _create_deserialize_method(message_info: ProtoMessageInfo) -> Callable:
    """创建反序列化方法"""
    @classmethod
    def deserialize(cls, data: bytes) -> Any:
        """反序列化消息对象"""
        try:
            # 这里应该根据实际的协议实现反序列化
            # 暂时使用JSON反序列化
            import json
            
            packet = json.loads(data.decode('utf-8'))
            
            # 验证消息ID
            if packet.get("message_id") != message_info.message_id:
                raise ValueError(f"消息ID不匹配: 期望{message_info.message_id}, 实际{packet.get('message_id')}")
            
            # 提取数据
            message_data = packet.get("data", {})
            
            # 创建对象实例
            if hasattr(cls, '__init__'):
                try:
                    # 尝试使用构造函数创建实例
                    instance = cls(**message_data)
                except TypeError:
                    # 如果构造函数参数不匹配，创建空实例并设置属性
                    instance = cls()
                    for key, value in message_data.items():
                        setattr(instance, key, value)
            else:
                instance = cls()
                for key, value in message_data.items():
                    setattr(instance, key, value)
            
            return instance
            
        except Exception as e:
            logger.error("消息反序列化失败",
                        message_id=message_info.message_id,
                        error=str(e))
            raise
    
    return deserialize


def _process_proto_args(func: Callable, args: tuple, kwargs: dict, 
                       binding_info: ProtoBindingInfo) -> tuple:
    """处理协议参数"""
    # 这里可以添加参数验证和转换逻辑
    # 暂时直接返回原始参数
    return args, kwargs


def _process_proto_result(result: Any, binding_info: ProtoBindingInfo) -> Any:
    """处理协议返回值"""
    # 这里可以添加返回值验证和转换逻辑
    # 暂时直接返回原始结果
    return result


def get_proto_registry() -> ProtoRegistry:
    """获取协议注册表"""
    return _proto_registry


def get_message_info(message_id: int) -> Optional[ProtoMessageInfo]:
    """根据消息ID获取消息信息"""
    return _proto_registry.get_message_by_id(message_id)


def get_message_info_by_type(message_type: Type) -> Optional[ProtoMessageInfo]:
    """根据消息类型获取消息信息"""
    return _proto_registry.get_message_by_type(message_type)


def list_proto_messages() -> Dict[int, ProtoMessageInfo]:
    """列出所有协议消息"""
    return _proto_registry.list_messages()


def register_proto_message(message_class: Type, message_id: int, 
                          message_type: ProtoType = ProtoType.REQUEST) -> ProtoMessageInfo:
    """手动注册协议消息"""
    message_info = ProtoMessageInfo(
        message_id=message_id,
        message_type=message_type,
        message_class=message_class,
        message_name=message_class.__name__
    )
    
    _proto_registry.register_message(message_info)
    
    # 在类上添加消息信息
    message_class._proto_message_info = message_info
    
    return message_info