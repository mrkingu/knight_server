"""
common/proto 模块

该模块提供了Protocol Buffers编解码相关的功能实现，是整个框架的核心通信基础。

主要功能:
- 消息头处理 (MessageHeader)
- 消息基类 (BaseRequest, BaseResponse)
- 消息注册表 (MessageRegistry)
- 环形缓冲区 (RingBuffer)
- 消息对象池 (MessagePool)
- 编解码器 (ProtoCodec)
- 自定义异常 (ProtoException及其子类)

使用示例:
    # 基本编解码
    codec = ProtoCodec()
    encoded_data = codec.encode(request_message)
    decoded_message = codec.decode(encoded_data)
    
    # 使用对象池
    pool = MessagePool(LoginRequest, size=100)
    await pool.initialize()
    async with pool.acquire() as msg:
        msg.username = "player1"
        encoded = codec.encode(msg)
    
    # 环形缓冲区
    buffer = RingBuffer(size=1024*1024)
    await buffer.write(data)
    message_data = await buffer.read_message()
"""

# 导出异常类
from .exceptions import (
    ProtoException,
    EncodeException,
    DecodeException,
    PoolException,
    BufferException,
    HeaderException,
    RegistryException,
    ValidationException,
    handle_proto_exception,
    handle_async_proto_exception
)

# 导出消息头相关
from .header import (
    MessageHeader,
    encode_header,
    decode_header,
    get_header_size,
    extract_msg_id,
    validate_header_data,
    HEADER_SIZE,
    MSG_ID_SIZE,
    TIMESTAMP_SIZE,
    UNIQUE_ID_SIZE
)

# 导出基础消息类
from .base_proto import (
    BaseMessage,
    BaseRequest,
    BaseResponse,
    MessageFactory
)

# 导出消息注册表
from .registry import (
    MessageRegistry,
    get_default_registry,
    register_message,
    get_message_class,
    scan_and_register
)

# 导出环形缓冲区
from .ring_buffer import (
    RingBuffer
)

# 导出消息对象池
from .message_pool import (
    MessagePool,
    PooledMessage,
    create_message_pool
)

# 导出编解码器
from .codec import (
    ProtoCodec,
    CompressionType,
    create_codec,
    encode_message,
    decode_message
)

# 版本信息
__version__ = "1.0.0"
__author__ = "Knight Server Team"

# 模块级别的公共接口
__all__ = [
    # 异常类
    "ProtoException",
    "EncodeException", 
    "DecodeException",
    "PoolException",
    "BufferException",
    "HeaderException",
    "RegistryException",
    "ValidationException",
    "handle_proto_exception",
    "handle_async_proto_exception",
    
    # 消息头
    "MessageHeader",
    "encode_header",
    "decode_header", 
    "get_header_size",
    "extract_msg_id",
    "validate_header_data",
    "HEADER_SIZE",
    "MSG_ID_SIZE",
    "TIMESTAMP_SIZE", 
    "UNIQUE_ID_SIZE",
    
    # 基础消息类
    "BaseMessage",
    "BaseRequest",
    "BaseResponse", 
    "MessageFactory",
    
    # 消息注册表
    "MessageRegistry",
    "get_default_registry",
    "register_message",
    "get_message_class",
    "scan_and_register",
    
    # 环形缓冲区
    "RingBuffer",
    
    # 消息对象池
    "MessagePool",
    "PooledMessage",
    "create_message_pool",
    
    # 编解码器
    "ProtoCodec",
    "CompressionType",
    "create_codec", 
    "encode_message",
    "decode_message",
    
    # 版本信息
    "__version__",
    "__author__"
]


def initialize_proto_system(compression: CompressionType = CompressionType.NONE,
                           compression_threshold: int = 1024,
                           enable_hot_reload: bool = False) -> ProtoCodec:
    """
    初始化Proto系统
    
    这是一个便捷的初始化函数，会设置默认的编解码器和注册表。
    
    Args:
        compression: 默认压缩类型
        compression_threshold: 压缩阈值
        enable_hot_reload: 是否启用热更新
        
    Returns:
        ProtoCodec: 配置好的编解码器实例
        
    Example:
        >>> codec = initialize_proto_system(
        ...     compression=CompressionType.ZSTD,
        ...     compression_threshold=512
        ... )
        >>> # 现在可以使用codec进行编解码
    """
    # 获取默认注册表并配置
    registry = get_default_registry()
    if enable_hot_reload:
        registry.enable_hot_reload()
    
    # 创建编解码器
    codec = ProtoCodec(
        registry=registry,
        compression=compression,
        compression_threshold=compression_threshold
    )
    
    return codec


def get_system_info() -> dict:
    """
    获取Proto系统信息
    
    Returns:
        dict: 系统信息包括注册表状态、统计信息等
    """
    registry = get_default_registry()
    
    return {
        "version": __version__,
        "author": __author__,
        "registry_info": registry.get_registry_info(),
        "registered_message_count": registry.get_registration_count(),
        "request_message_count": len(registry.get_request_ids()),
        "response_message_count": len(registry.get_response_ids()),
        "compression_types": [ct.value for ct in CompressionType]
    }
