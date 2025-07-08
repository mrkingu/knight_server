"""
Proto 模块异常定义

该模块定义了 Proto 编解码相关的所有自定义异常类。
所有异常都继承自 ProtoException 基类，提供统一的错误处理机制。
"""

from typing import Optional, Any


class ProtoException(Exception):
    """
    Proto 模块基础异常类
    
    所有 Proto 相关异常的基类，提供统一的异常处理接口。
    
    Attributes:
        message: 错误消息
        error_code: 错误码
        context: 错误上下文信息
    """
    
    __slots__ = ('message', 'error_code', 'context')
    
    def __init__(self, message: str, error_code: Optional[int] = None, 
                 context: Optional[dict] = None):
        """
        初始化 Proto 异常
        
        Args:
            message: 错误消息
            error_code: 错误码，用于分类不同类型的错误
            context: 错误上下文信息，包含异常发生时的相关数据
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
    
    def __str__(self) -> str:
        """返回格式化的错误信息"""
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message
    
    def __repr__(self) -> str:
        """返回详细的异常表示"""
        return (f"{self.__class__.__name__}("
                f"message='{self.message}', "
                f"error_code={self.error_code}, "
                f"context={self.context})")
    
    def add_context(self, **kwargs) -> 'ProtoException':
        """
        添加上下文信息
        
        Args:
            **kwargs: 要添加的上下文键值对
            
        Returns:
            ProtoException: 返回自身，支持链式调用
        """
        self.context.update(kwargs)
        return self


class EncodeException(ProtoException):
    """
    编码异常
    
    在消息编码过程中发生的异常，包括：
    - 序列化失败
    - 消息头编码错误
    - 数据格式不正确
    """
    
    def __init__(self, message: str, message_type: Optional[str] = None, 
                 data: Optional[Any] = None, **kwargs):
        """
        初始化编码异常
        
        Args:
            message: 错误消息
            message_type: 消息类型
            data: 导致编码失败的数据
            **kwargs: 其他上下文信息
        """
        context = {'message_type': message_type, 'data': data}
        context.update(kwargs)
        super().__init__(message, error_code=1001, context=context)


class DecodeException(ProtoException):
    """
    解码异常
    
    在消息解码过程中发生的异常，包括：
    - 反序列化失败
    - 消息头解析错误
    - 数据格式不正确
    - 消息类型不匹配
    """
    
    def __init__(self, message: str, data: Optional[bytes] = None, 
                 expected_type: Optional[str] = None, **kwargs):
        """
        初始化解码异常
        
        Args:
            message: 错误消息
            data: 导致解码失败的二进制数据
            expected_type: 期望的消息类型
            **kwargs: 其他上下文信息
        """
        context = {
            'data_length': len(data) if data else 0,
            'expected_type': expected_type
        }
        context.update(kwargs)
        super().__init__(message, error_code=1002, context=context)


class PoolException(ProtoException):
    """
    对象池异常
    
    在消息对象池操作中发生的异常，包括：
    - 池满异常
    - 对象获取超时
    - 对象重置失败
    - 池状态异常
    """
    
    def __init__(self, message: str, pool_type: Optional[str] = None,
                 pool_size: Optional[int] = None, **kwargs):
        """
        初始化对象池异常
        
        Args:
            message: 错误消息
            pool_type: 对象池类型
            pool_size: 对象池大小
            **kwargs: 其他上下文信息
        """
        context = {'pool_type': pool_type, 'pool_size': pool_size}
        context.update(kwargs)
        super().__init__(message, error_code=1003, context=context)


class BufferException(ProtoException):
    """
    缓冲区异常
    
    在环形缓冲区操作中发生的异常，包括：
    - 缓冲区溢出
    - 读写指针异常
    - 扩容失败
    - 数据不完整
    """
    
    def __init__(self, message: str, buffer_size: Optional[int] = None,
                 read_pos: Optional[int] = None, write_pos: Optional[int] = None,
                 **kwargs):
        """
        初始化缓冲区异常
        
        Args:
            message: 错误消息
            buffer_size: 缓冲区大小
            read_pos: 读指针位置
            write_pos: 写指针位置
            **kwargs: 其他上下文信息
        """
        context = {
            'buffer_size': buffer_size,
            'read_pos': read_pos,
            'write_pos': write_pos
        }
        context.update(kwargs)
        super().__init__(message, error_code=1004, context=context)


class HeaderException(ProtoException):
    """
    消息头异常
    
    在消息头处理中发生的异常，包括：
    - 消息头格式错误
    - 消息头长度不正确
    - 消息ID无效
    - 时间戳异常
    """
    
    def __init__(self, message: str, header_data: Optional[bytes] = None,
                 msg_id: Optional[int] = None, **kwargs):
        """
        初始化消息头异常
        
        Args:
            message: 错误消息
            header_data: 消息头数据
            msg_id: 消息ID
            **kwargs: 其他上下文信息
        """
        context = {
            'header_length': len(header_data) if header_data else 0,
            'msg_id': msg_id
        }
        context.update(kwargs)
        super().__init__(message, error_code=1005, context=context)


class RegistryException(ProtoException):
    """
    注册表异常
    
    在消息注册表操作中发生的异常，包括：
    - 消息类未注册
    - 消息ID冲突
    - 注册失败
    - 查找失败
    """
    
    def __init__(self, message: str, msg_id: Optional[int] = None,
                 message_class: Optional[str] = None, **kwargs):
        """
        初始化注册表异常
        
        Args:
            message: 错误消息
            msg_id: 消息ID
            message_class: 消息类名
            **kwargs: 其他上下文信息
        """
        context = {'msg_id': msg_id, 'message_class': message_class}
        context.update(kwargs)
        super().__init__(message, error_code=1006, context=context)


class ValidationException(ProtoException):
    """
    验证异常
    
    在消息验证过程中发生的异常，包括：
    - 参数验证失败
    - 消息格式验证失败
    - 业务规则验证失败
    """
    
    def __init__(self, message: str, field_name: Optional[str] = None,
                 field_value: Optional[Any] = None, **kwargs):
        """
        初始化验证异常
        
        Args:
            message: 错误消息
            field_name: 验证失败的字段名
            field_value: 验证失败的字段值
            **kwargs: 其他上下文信息
        """
        context = {'field_name': field_name, 'field_value': field_value}
        context.update(kwargs)
        super().__init__(message, error_code=1007, context=context)


# 异常处理工具函数
def handle_proto_exception(func):
    """
    Proto 异常处理装饰器
    
    用于统一处理 Proto 模块中的异常，提供日志记录和错误包装功能。
    
    Args:
        func: 被装饰的函数
        
    Returns:
        装饰后的函数
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ProtoException:
            # Proto 异常直接向上抛出
            raise
        except Exception as e:
            # 其他异常包装为 ProtoException
            raise ProtoException(
                f"Unexpected error in {func.__name__}: {str(e)}",
                error_code=9999,
                context={'function': func.__name__, 'args': str(args)[:100]}
            ) from e
    
    return wrapper


def handle_async_proto_exception(func):
    """
    异步 Proto 异常处理装饰器
    
    用于统一处理异步函数中的 Proto 模块异常。
    
    Args:
        func: 被装饰的异步函数
        
    Returns:
        装饰后的异步函数
    """
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ProtoException:
            # Proto 异常直接向上抛出
            raise
        except Exception as e:
            # 其他异常包装为 ProtoException
            raise ProtoException(
                f"Unexpected error in async {func.__name__}: {str(e)}",
                error_code=9999,
                context={'function': func.__name__, 'args': str(args)[:100]}
            ) from e
    
    return wrapper