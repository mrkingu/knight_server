"""
协议适配器模块

该模块实现了协议适配器，负责自动将Python对象转换为protobuf格式。
支持多种消息格式转换和编码优化。

主要功能：
- Python对象到protobuf转换
- 消息编码和解码
- 协议版本管理
- 消息压缩优化
- 错误处理和验证
"""

import json
import time
import struct
from typing import Any, Dict, Optional, Union, Type, List, Tuple
from dataclasses import dataclass, is_dataclass, asdict
from enum import Enum
import base64

from common.logger import logger


class MessageFormat(Enum):
    """消息格式枚举"""
    JSON = "json"
    PROTOBUF = "protobuf"
    BINARY = "binary"
    MSGPACK = "msgpack"


class CompressionType(Enum):
    """压缩类型枚举"""
    NONE = "none"
    GZIP = "gzip"
    ZLIB = "zlib"
    ZSTD = "zstd"


@dataclass
class ProtocolConfig:
    """协议配置"""
    default_format: MessageFormat = MessageFormat.JSON
    compression_type: CompressionType = CompressionType.NONE
    compression_threshold: int = 1024  # 超过此大小才压缩
    enable_validation: bool = True
    protocol_version: str = "1.0"
    encoding: str = "utf-8"


@dataclass
class ConversionResult:
    """转换结果"""
    success: bool
    data: Optional[bytes] = None
    error: Optional[str] = None
    original_size: int = 0
    compressed_size: int = 0
    format: MessageFormat = MessageFormat.JSON
    compression: CompressionType = CompressionType.NONE


class ProtocolAdapter:
    """
    协议适配器
    
    负责将Python对象转换为各种协议格式，特别是protobuf格式。
    支持自动类型检测、编码优化和错误处理。
    
    Attributes:
        _config: 协议配置
        _format_handlers: 格式处理器映射
        _compression_handlers: 压缩处理器映射
    """
    
    def __init__(self, config: Optional[ProtocolConfig] = None):
        """
        初始化协议适配器
        
        Args:
            config: 协议配置
        """
        self._config = config or ProtocolConfig()
        
        # 格式处理器映射
        self._format_handlers = {
            MessageFormat.JSON: self._handle_json_format,
            MessageFormat.PROTOBUF: self._handle_protobuf_format,
            MessageFormat.BINARY: self._handle_binary_format,
            MessageFormat.MSGPACK: self._handle_msgpack_format,
        }
        
        # 压缩处理器映射
        self._compression_handlers = {
            CompressionType.NONE: self._no_compression,
            CompressionType.GZIP: self._gzip_compression,
            CompressionType.ZLIB: self._zlib_compression,
            CompressionType.ZSTD: self._zstd_compression,
        }
        
        logger.info("协议适配器初始化完成", 
                   default_format=self._config.default_format.value,
                   compression_type=self._config.compression_type.value)
    
    async def encode_message(self, message: Any, 
                           format: Optional[MessageFormat] = None,
                           compression: Optional[CompressionType] = None) -> bytes:
        """
        编码消息
        
        Args:
            message: 消息对象
            format: 消息格式
            compression: 压缩类型
            
        Returns:
            bytes: 编码后的消息数据
        """
        try:
            # 使用指定格式或默认格式
            msg_format = format or self._config.default_format
            comp_type = compression or self._config.compression_type
            
            # 格式转换
            result = await self._convert_to_format(message, msg_format)
            if not result.success:
                raise Exception(f"格式转换失败: {result.error}")
            
            data = result.data
            original_size = len(data)
            
            # 压缩处理
            if comp_type != CompressionType.NONE and original_size > self._config.compression_threshold:
                data = await self._compress_data(data, comp_type)
                compressed_size = len(data)
                
                logger.debug("消息压缩完成",
                           original_size=original_size,
                           compressed_size=compressed_size,
                           compression_ratio=compressed_size / original_size)
            
            # 构造消息头
            header = self._build_message_header(msg_format, comp_type, len(data))
            
            # 组装完整消息
            full_message = header + data
            
            logger.debug("消息编码完成",
                        format=msg_format.value,
                        compression=comp_type.value,
                        size=len(full_message))
            
            return full_message
            
        except Exception as e:
            logger.error("消息编码失败", error=str(e))
            raise
    
    async def decode_message(self, data: bytes) -> Tuple[Any, MessageFormat, CompressionType]:
        """
        解码消息
        
        Args:
            data: 编码后的消息数据
            
        Returns:
            Tuple[Any, MessageFormat, CompressionType]: 解码后的消息、格式、压缩类型
        """
        try:
            # 解析消息头
            header_info = self._parse_message_header(data)
            msg_format = header_info["format"]
            comp_type = header_info["compression"]
            payload_size = header_info["payload_size"]
            header_size = header_info["header_size"]
            
            # 提取消息体
            payload = data[header_size:header_size + payload_size]
            
            # 解压缩
            if comp_type != CompressionType.NONE:
                payload = await self._decompress_data(payload, comp_type)
            
            # 格式解析
            message = await self._parse_from_format(payload, msg_format)
            
            logger.debug("消息解码完成",
                        format=msg_format.value,
                        compression=comp_type.value,
                        payload_size=payload_size)
            
            return message, msg_format, comp_type
            
        except Exception as e:
            logger.error("消息解码失败", error=str(e))
            raise
    
    async def convert_to_protobuf(self, message: Any) -> bytes:
        """
        将Python对象转换为protobuf格式
        
        Args:
            message: Python对象
            
        Returns:
            bytes: protobuf编码数据
        """
        try:
            # 如果已经是protobuf消息，直接序列化
            if hasattr(message, 'SerializeToString'):
                return message.SerializeToString()
            
            # 如果是dataclass，转换为字典
            if is_dataclass(message):
                data = asdict(message)
            elif hasattr(message, '__dict__'):
                data = message.__dict__
            else:
                data = message
            
            # 创建通用protobuf消息结构
            proto_data = self._create_generic_protobuf_message(data)
            
            # 序列化
            return proto_data.SerializeToString()
            
        except Exception as e:
            logger.error("protobuf转换失败", error=str(e))
            # 降级到JSON格式
            return json.dumps(self._serialize_object(message)).encode(self._config.encoding)
    
    async def _convert_to_format(self, message: Any, format: MessageFormat) -> ConversionResult:
        """
        转换消息到指定格式
        
        Args:
            message: 消息对象
            format: 目标格式
            
        Returns:
            ConversionResult: 转换结果
        """
        try:
            handler = self._format_handlers.get(format)
            if not handler:
                return ConversionResult(
                    success=False,
                    error=f"不支持的消息格式: {format.value}"
                )
            
            data = await handler(message)
            
            return ConversionResult(
                success=True,
                data=data,
                original_size=len(data),
                format=format
            )
            
        except Exception as e:
            return ConversionResult(
                success=False,
                error=str(e)
            )
    
    async def _parse_from_format(self, data: bytes, format: MessageFormat) -> Any:
        """
        从指定格式解析消息
        
        Args:
            data: 消息数据
            format: 消息格式
            
        Returns:
            Any: 解析后的消息对象
        """
        if format == MessageFormat.JSON:
            return json.loads(data.decode(self._config.encoding))
        elif format == MessageFormat.PROTOBUF:
            # 这里应该根据实际的protobuf消息类型进行解析
            # 暂时返回原始数据
            return data
        elif format == MessageFormat.BINARY:
            return data
        elif format == MessageFormat.MSGPACK:
            try:
                import msgpack
                return msgpack.unpackb(data, raw=False)
            except ImportError:
                logger.warning("msgpack未安装，使用JSON解析")
                return json.loads(data.decode(self._config.encoding))
        else:
            raise ValueError(f"不支持的消息格式: {format.value}")
    
    async def _handle_json_format(self, message: Any) -> bytes:
        """处理JSON格式"""
        data = self._serialize_object(message)
        return json.dumps(data, ensure_ascii=False).encode(self._config.encoding)
    
    async def _handle_protobuf_format(self, message: Any) -> bytes:
        """处理protobuf格式"""
        return await self.convert_to_protobuf(message)
    
    async def _handle_binary_format(self, message: Any) -> bytes:
        """处理二进制格式"""
        if isinstance(message, bytes):
            return message
        elif isinstance(message, str):
            return message.encode(self._config.encoding)
        else:
            # 转换为JSON字符串然后编码
            return json.dumps(self._serialize_object(message)).encode(self._config.encoding)
    
    async def _handle_msgpack_format(self, message: Any) -> bytes:
        """处理msgpack格式"""
        try:
            import msgpack
            data = self._serialize_object(message)
            return msgpack.packb(data, use_bin_type=True)
        except ImportError:
            logger.warning("msgpack未安装，使用JSON格式")
            return await self._handle_json_format(message)
    
    def _serialize_object(self, obj: Any) -> Any:
        """序列化对象为可JSON化的数据"""
        if obj is None:
            return None
        elif isinstance(obj, (bool, int, float, str)):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [self._serialize_object(item) for item in obj]
        elif isinstance(obj, dict):
            return {str(k): self._serialize_object(v) for k, v in obj.items()}
        elif is_dataclass(obj):
            return asdict(obj)
        elif hasattr(obj, '__dict__'):
            return {k: self._serialize_object(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, Enum):
            return obj.value
        elif hasattr(obj, 'isoformat'):  # datetime对象
            return obj.isoformat()
        else:
            return str(obj)
    
    def _create_generic_protobuf_message(self, data: Dict[str, Any]) -> Any:
        """创建通用protobuf消息"""
        # 这里应该根据实际的protobuf定义创建消息
        # 暂时返回序列化的JSON数据
        return json.dumps(data).encode(self._config.encoding)
    
    def _build_message_header(self, format: MessageFormat, 
                            compression: CompressionType, payload_size: int) -> bytes:
        """
        构建消息头
        
        消息头格式：
        - 魔数 (4 bytes): 0x4D534747 ('MSGG')
        - 版本 (1 byte): 协议版本
        - 格式 (1 byte): 消息格式
        - 压缩 (1 byte): 压缩类型
        - 保留 (1 byte): 保留字段
        - 载荷大小 (4 bytes): 载荷数据大小
        - 时间戳 (8 bytes): 消息时间戳
        
        Args:
            format: 消息格式
            compression: 压缩类型
            payload_size: 载荷大小
            
        Returns:
            bytes: 消息头数据
        """
        magic = b'MSGG'
        version = 1
        format_byte = list(MessageFormat).index(format)
        compression_byte = list(CompressionType).index(compression)
        reserved = 0
        timestamp = int(time.time() * 1000)  # 毫秒时间戳
        
        header = struct.pack(
            '>4sBBBBIQ',  # 大端序
            magic,
            version,
            format_byte,
            compression_byte,
            reserved,
            payload_size,
            timestamp
        )
        
        return header
    
    def _parse_message_header(self, data: bytes) -> Dict[str, Any]:
        """
        解析消息头
        
        Args:
            data: 消息数据
            
        Returns:
            Dict[str, Any]: 消息头信息
        """
        if len(data) < 20:  # 消息头最小长度
            raise ValueError("消息数据太短，无法解析消息头")
        
        # 解析消息头
        magic, version, format_byte, compression_byte, reserved, payload_size, timestamp = struct.unpack(
            '>4sBBBBIQ', data[:20]
        )
        
        # 验证魔数
        if magic != b'MSGG':
            raise ValueError("无效的消息魔数")
        
        # 转换枚举
        format_enum = list(MessageFormat)[format_byte]
        compression_enum = list(CompressionType)[compression_byte]
        
        return {
            "version": version,
            "format": format_enum,
            "compression": compression_enum,
            "payload_size": payload_size,
            "timestamp": timestamp,
            "header_size": 20
        }
    
    async def _compress_data(self, data: bytes, compression: CompressionType) -> bytes:
        """压缩数据"""
        handler = self._compression_handlers.get(compression)
        if not handler:
            raise ValueError(f"不支持的压缩类型: {compression.value}")
        
        return await handler(data, compress=True)
    
    async def _decompress_data(self, data: bytes, compression: CompressionType) -> bytes:
        """解压缩数据"""
        handler = self._compression_handlers.get(compression)
        if not handler:
            raise ValueError(f"不支持的压缩类型: {compression.value}")
        
        return await handler(data, compress=False)
    
    async def _no_compression(self, data: bytes, compress: bool = True) -> bytes:
        """无压缩处理"""
        return data
    
    async def _gzip_compression(self, data: bytes, compress: bool = True) -> bytes:
        """GZIP压缩处理"""
        try:
            import gzip
            if compress:
                return gzip.compress(data)
            else:
                return gzip.decompress(data)
        except ImportError:
            logger.warning("gzip模块不可用，跳过压缩")
            return data
    
    async def _zlib_compression(self, data: bytes, compress: bool = True) -> bytes:
        """ZLIB压缩处理"""
        try:
            import zlib
            if compress:
                return zlib.compress(data)
            else:
                return zlib.decompress(data)
        except ImportError:
            logger.warning("zlib模块不可用，跳过压缩")
            return data
    
    async def _zstd_compression(self, data: bytes, compress: bool = True) -> bytes:
        """ZSTD压缩处理"""
        try:
            import zstd
            if compress:
                return zstd.compress(data)
            else:
                return zstd.decompress(data)
        except ImportError:
            logger.warning("zstd模块不可用，跳过压缩")
            return data


# 工厂函数
def create_protocol_adapter(config: Optional[ProtocolConfig] = None) -> ProtocolAdapter:
    """
    创建协议适配器实例
    
    Args:
        config: 协议配置
        
    Returns:
        ProtocolAdapter: 协议适配器实例
    """
    return ProtocolAdapter(config)