"""
消息头模块

该模块定义了消息头结构 MessageHeader，包含消息的元数据信息。
消息头用于标识消息类型、唯一ID、时间戳等关键信息，是协议编解码的基础。
"""

import struct
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Union

from .exceptions import HeaderException, ValidationException


# 消息头固定长度常量
HEADER_SIZE = 28  # 4 + 4 + 8 + 12 = 28 字节
MSG_ID_SIZE = 4   # 消息ID大小（int32）
TIMESTAMP_SIZE = 8  # 时间戳大小（int64）
UNIQUE_ID_SIZE = 16  # UUID大小（128位）

# 消息头格式：小端字节序
# - msg_id: 4字节 int32 (有符号整数)
# - timestamp: 8字节 int64  
# - unique_id: 16字节 UUID
HEADER_FORMAT = '<iQ16s'


@dataclass
class MessageHeader:
    """
    消息头结构
    
    包含消息的元数据信息：
    - unique_id: 全局唯一标识符，用于追踪和去重
    - msg_id: 消息类型ID，正数为请求，负数为响应
    - timestamp: Unix时间戳（毫秒），用于超时检测和时序分析
    
    Attributes:
        unique_id: 全局唯一标识符
        msg_id: 消息类型ID
        timestamp: Unix时间戳（毫秒）
    """
    
    __slots__ = ('unique_id', 'msg_id', 'timestamp')
    
    unique_id: str
    msg_id: int  
    timestamp: int
    
    def __post_init__(self):
        """初始化后验证数据的有效性"""
        self._validate()
    
    def _validate(self) -> None:
        """
        验证消息头数据的有效性
        
        Raises:
            ValidationException: 当数据不符合规范时抛出
        """
        # 验证 unique_id
        if not self.unique_id:
            raise ValidationException("unique_id 不能为空", field_name="unique_id")
        
        if not isinstance(self.unique_id, str):
            raise ValidationException("unique_id 必须是字符串类型", 
                                    field_name="unique_id", 
                                    field_value=type(self.unique_id))
        
        # 尝试解析 UUID 以验证格式
        try:
            uuid.UUID(self.unique_id)
        except ValueError as e:
            raise ValidationException(f"unique_id 格式无效: {e}", 
                                    field_name="unique_id", 
                                    field_value=self.unique_id) from e
        
        # 验证 msg_id
        if not isinstance(self.msg_id, int):
            raise ValidationException("msg_id 必须是整数类型", 
                                    field_name="msg_id", 
                                    field_value=type(self.msg_id))
        
        if self.msg_id == 0:
            raise ValidationException("msg_id 不能为0", 
                                    field_name="msg_id", 
                                    field_value=self.msg_id)
        
        # 验证 timestamp
        if not isinstance(self.timestamp, int):
            raise ValidationException("timestamp 必须是整数类型", 
                                    field_name="timestamp", 
                                    field_value=type(self.timestamp))
        
        if self.timestamp <= 0:
            raise ValidationException("timestamp 必须大于0", 
                                    field_name="timestamp", 
                                    field_value=self.timestamp)
        
        # 验证时间戳合理性（不能太旧或太新）
        current_time = int(time.time() * 1000)
        if abs(current_time - self.timestamp) > 86400000:  # 24小时
            raise ValidationException("timestamp 时间偏差过大", 
                                    field_name="timestamp", 
                                    field_value=self.timestamp,
                                    current_time=current_time)
    
    def is_request(self) -> bool:
        """
        判断是否为请求消息
        
        Returns:
            bool: msg_id > 0 为请求消息
        """
        return self.msg_id > 0
    
    def is_response(self) -> bool:
        """
        判断是否为响应消息
        
        Returns:
            bool: msg_id < 0 为响应消息
        """
        return self.msg_id < 0
    
    def get_response_msg_id(self) -> int:
        """
        获取对应的响应消息ID
        
        Returns:
            int: 响应消息ID（负数）
            
        Raises:
            ValidationException: 如果当前不是请求消息
        """
        if not self.is_request():
            raise ValidationException("只有请求消息才能获取响应消息ID", 
                                    field_name="msg_id", 
                                    field_value=self.msg_id)
        return -self.msg_id
    
    def get_request_msg_id(self) -> int:
        """
        获取对应的请求消息ID
        
        Returns:
            int: 请求消息ID（正数）
            
        Raises:
            ValidationException: 如果当前不是响应消息
        """
        if not self.is_response():
            raise ValidationException("只有响应消息才能获取请求消息ID", 
                                    field_name="msg_id", 
                                    field_value=self.msg_id)
        return -self.msg_id
    
    def get_age_ms(self) -> int:
        """
        获取消息年龄（毫秒）
        
        Returns:
            int: 消息创建后经过的毫秒数
        """
        current_time = int(time.time() * 1000)
        return current_time - self.timestamp
    
    def is_expired(self, timeout_ms: int) -> bool:
        """
        判断消息是否已超时
        
        Args:
            timeout_ms: 超时时间（毫秒）
            
        Returns:
            bool: 是否已超时
        """
        return self.get_age_ms() > timeout_ms
    
    @classmethod
    def create_request(cls, msg_id: int, unique_id: Optional[str] = None) -> 'MessageHeader':
        """
        创建请求消息头
        
        Args:
            msg_id: 消息ID（必须为正数）
            unique_id: 唯一标识符，如果为None则自动生成
            
        Returns:
            MessageHeader: 新创建的消息头
            
        Raises:
            ValidationException: 如果msg_id不是正数
        """
        if msg_id <= 0:
            raise ValidationException("请求消息的msg_id必须为正数", 
                                    field_name="msg_id", 
                                    field_value=msg_id)
        
        if unique_id is None:
            unique_id = str(uuid.uuid4())
        
        timestamp = int(time.time() * 1000)
        return cls(unique_id=unique_id, msg_id=msg_id, timestamp=timestamp)
    
    @classmethod
    def create_response(cls, request_header: 'MessageHeader') -> 'MessageHeader':
        """
        基于请求消息头创建响应消息头
        
        Args:
            request_header: 请求消息头
            
        Returns:
            MessageHeader: 响应消息头（保持相同unique_id，msg_id取负值）
            
        Raises:
            ValidationException: 如果请求消息头不是请求类型
        """
        if not request_header.is_request():
            raise ValidationException("只能基于请求消息头创建响应消息头", 
                                    field_name="msg_id", 
                                    field_value=request_header.msg_id)
        
        timestamp = int(time.time() * 1000)
        return cls(
            unique_id=request_header.unique_id,
            msg_id=request_header.get_response_msg_id(),
            timestamp=timestamp
        )
    
    def __str__(self) -> str:
        """返回可读的字符串表示"""
        msg_type = "REQUEST" if self.is_request() else "RESPONSE"
        age_ms = self.get_age_ms()
        return (f"MessageHeader({msg_type}, "
                f"id={abs(self.msg_id)}, "
                f"uuid={self.unique_id[:8]}..., "
                f"age={age_ms}ms)")
    
    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        return (f"MessageHeader("
                f"unique_id='{self.unique_id}', "
                f"msg_id={self.msg_id}, "
                f"timestamp={self.timestamp})")


def encode_header(header: MessageHeader) -> bytes:
    """
    编码消息头为二进制数据
    
    消息头格式（28字节，小端字节序）：
    - msg_id: 4字节 uint32
    - timestamp: 8字节 uint64
    - unique_id: 16字节 UUID
    
    Args:
        header: 要编码的消息头
        
    Returns:
        bytes: 编码后的二进制数据
        
    Raises:
        HeaderException: 编码失败时抛出
    """
    try:
        # 将 unique_id 字符串转换为 UUID 字节
        uuid_obj = uuid.UUID(header.unique_id)
        uuid_bytes = uuid_obj.bytes
        
        # 打包为二进制数据
        data = struct.pack(
            HEADER_FORMAT,
            header.msg_id,
            header.timestamp,
            uuid_bytes
        )
        
        return data
        
    except struct.error as e:
        raise HeaderException(f"消息头编码失败: {e}", 
                            msg_id=header.msg_id) from e
    except ValueError as e:
        raise HeaderException(f"UUID格式错误: {e}", 
                            msg_id=header.msg_id) from e
    except Exception as e:
        raise HeaderException(f"消息头编码发生未知错误: {e}", 
                            msg_id=header.msg_id) from e


def decode_header(data: bytes) -> MessageHeader:
    """
    解码二进制数据为消息头
    
    Args:
        data: 要解码的二进制数据（必须至少包含28字节的消息头）
        
    Returns:
        MessageHeader: 解码后的消息头
        
    Raises:
        HeaderException: 解码失败时抛出
    """
    if not isinstance(data, bytes):
        raise HeaderException("输入数据必须是bytes类型", 
                            header_data=data)
    
    if len(data) < HEADER_SIZE:
        raise HeaderException(f"消息头数据长度不足，需要{HEADER_SIZE}字节，实际{len(data)}字节", 
                            header_data=data)
    
    try:
        # 解包二进制数据
        msg_id, timestamp, uuid_bytes = struct.unpack(
            HEADER_FORMAT,
            data[:HEADER_SIZE]
        )
        
        # 将UUID字节转换为字符串
        uuid_obj = uuid.UUID(bytes=uuid_bytes)
        unique_id = str(uuid_obj)
        
        # 创建消息头对象
        header = MessageHeader(
            unique_id=unique_id,
            msg_id=msg_id,
            timestamp=timestamp
        )
        
        return header
        
    except struct.error as e:
        raise HeaderException(f"消息头解码失败: {e}", 
                            header_data=data[:HEADER_SIZE]) from e
    except ValueError as e:
        raise HeaderException(f"UUID解析错误: {e}", 
                            header_data=data[:HEADER_SIZE]) from e
    except Exception as e:
        raise HeaderException(f"消息头解码发生未知错误: {e}", 
                            header_data=data[:HEADER_SIZE]) from e


def validate_header_data(data: bytes) -> bool:
    """
    验证二进制数据是否包含有效的消息头
    
    Args:
        data: 要验证的二进制数据
        
    Returns:
        bool: 数据是否包含有效消息头
    """
    try:
        decode_header(data)
        return True
    except HeaderException:
        return False


def get_header_size() -> int:
    """
    获取消息头固定大小
    
    Returns:
        int: 消息头字节数
    """
    return HEADER_SIZE


def extract_msg_id(data: bytes) -> int:
    """
    从二进制数据中快速提取消息ID
    
    不进行完整的消息头解码，只提取msg_id字段，用于快速消息分发。
    
    Args:
        data: 包含消息头的二进制数据
        
    Returns:
        int: 消息ID
        
    Raises:
        HeaderException: 数据格式错误时抛出
    """
    if not isinstance(data, bytes):
        raise HeaderException("输入数据必须是bytes类型")
    
    if len(data) < MSG_ID_SIZE:
        raise HeaderException(f"数据长度不足，无法提取消息ID，需要至少{MSG_ID_SIZE}字节")
    
    try:
        msg_id, = struct.unpack('<i', data[:MSG_ID_SIZE])
        return msg_id
    except struct.error as e:
        raise HeaderException(f"提取消息ID失败: {e}") from e