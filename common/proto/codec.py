"""
协议编解码器模块

该模块实现了 ProtoCodec 编解码器类，是整个框架的核心通信组件。
负责处理消息的完整编解码流程，包括消息头处理、Protocol Buffers序列化和可选的压缩。
"""

import time
try:
    import zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False
    # Mock zstd implementation
    class zstd:
        @staticmethod
        def compress(data):
            return data
        
        @staticmethod
        def decompress(data):
            return data
from typing import Type, Optional, Union, Dict, Any, Tuple
from enum import Enum

from .base_proto import BaseMessage, BaseRequest, BaseResponse
from .header import MessageHeader, encode_header, decode_header, get_header_size
from .registry import MessageRegistry, get_default_registry
from .exceptions import (
    EncodeException, DecodeException, HeaderException, RegistryException,
    ValidationException, handle_proto_exception
)


class CompressionType(Enum):
    """压缩类型枚举"""
    NONE = "none"
    ZSTD = "zstd"


class ProtoCodec:
    """
    Protocol Buffers 编解码器
    
    提供完整的消息编解码功能：
    - 自动处理消息头
    - Protocol Buffers 序列化/反序列化
    - 可选的压缩支持
    - 错误处理和异常包装
    - 性能统计
    
    消息格式：
    [消息头 28字节][压缩标志 1字节][消息体长度 4字节][消息体]
    
    Attributes:
        _registry: 消息注册表
        _compression: 压缩类型
        _compression_threshold: 压缩阈值（字节）
        _statistics: 编解码统计信息
    """
    
    __slots__ = (
        '_registry', '_compression', '_compression_threshold', '_statistics',
        '_compression_level', '_enable_validation'
    )
    
    def __init__(self, registry: Optional[MessageRegistry] = None,
                 compression: CompressionType = CompressionType.NONE,
                 compression_threshold: int = 1024,
                 compression_level: int = 3,
                 enable_validation: bool = True):
        """
        初始化编解码器
        
        Args:
            registry: 消息注册表，如果为None则使用默认注册表
            compression: 压缩类型
            compression_threshold: 压缩阈值（字节），小于此值不压缩
            compression_level: 压缩级别（1-22，级别越高压缩率越高但速度越慢）
            enable_validation: 是否启用消息验证
            
        Raises:
            ValidationException: 参数验证失败时抛出
        """
        if registry is None:
            registry = get_default_registry()
        
        if compression_threshold <= 0:
            raise ValidationException("压缩阈值必须大于0",
                                    field_name="compression_threshold",
                                    field_value=compression_threshold)
        
        if not (1 <= compression_level <= 22):
            raise ValidationException("压缩级别必须在1-22之间",
                                    field_name="compression_level",
                                    field_value=compression_level)
        
        self._registry = registry
        self._compression = compression
        self._compression_threshold = compression_threshold
        self._compression_level = compression_level
        self._enable_validation = enable_validation
        
        # 统计信息
        self._statistics = {
            'total_encoded': 0,
            'total_decoded': 0,
            'total_compressed': 0,
            'total_decompressed': 0,
            'encode_errors': 0,
            'decode_errors': 0,
            'compression_errors': 0,
            'total_encode_time': 0.0,
            'total_decode_time': 0.0,
            'total_compression_time': 0.0,
            'total_decompression_time': 0.0,
            'original_bytes': 0,
            'compressed_bytes': 0,
            'encoded_bytes': 0,
            'decoded_bytes': 0
        }
    
    @property
    def compression(self) -> CompressionType:
        """获取压缩类型"""
        return self._compression
    
    @property
    def compression_threshold(self) -> int:
        """获取压缩阈值"""
        return self._compression_threshold
    
    @property
    def registry(self) -> MessageRegistry:
        """获取消息注册表"""
        return self._registry
    
    @handle_proto_exception
    def encode(self, message: Union[BaseRequest, BaseResponse]) -> bytes:
        """
        编码消息为二进制数据
        
        编码流程：
        1. 验证消息
        2. 序列化消息体
        3. 可选压缩
        4. 编码消息头
        5. 组装完整数据包
        
        Args:
            message: 要编码的消息对象
            
        Returns:
            bytes: 编码后的二进制数据
            
        Raises:
            EncodeException: 编码失败时抛出
        """
        start_time = time.time()
        
        try:
            # 验证消息
            if not isinstance(message, BaseMessage):
                raise EncodeException("消息必须继承自BaseMessage",
                                    message_type=type(message).__name__)
            
            if self._enable_validation:
                message._validate_message()
            
            # 序列化消息体
            try:
                message_data = message.serialize()
            except Exception as e:
                raise EncodeException(f"消息序列化失败: {e}",
                                    message_type=message.__class__.__name__,
                                    data=message) from e
            
            # 记录原始大小
            original_size = len(message_data)
            self._statistics['original_bytes'] += original_size
            
            # 压缩处理
            compressed_data, is_compressed = self._compress_data(message_data)
            
            # 编码消息头
            header_data = self.encode_header(message.header)
            
            # 组装完整数据包
            # 格式：[消息头][压缩标志][消息体长度][消息体]
            compression_flag = b'\x01' if is_compressed else b'\x00'
            body_length = len(compressed_data).to_bytes(4, byteorder='big')  # 网络字节序
            
            complete_data = header_data + compression_flag + body_length + compressed_data
            
            # 更新统计
            self._statistics['total_encoded'] += 1
            self._statistics['encoded_bytes'] += len(complete_data)
            self._statistics['total_encode_time'] += time.time() - start_time
            
            return complete_data
            
        except EncodeException:
            self._statistics['encode_errors'] += 1
            raise
        except Exception as e:
            self._statistics['encode_errors'] += 1
            raise EncodeException(f"编码过程发生未知错误: {e}",
                                message_type=getattr(message.__class__, '__name__', 'Unknown')) from e
    
    @handle_proto_exception
    def decode(self, data: bytes, expected_msg_id: Optional[int] = None) -> Union[BaseRequest, BaseResponse]:
        """
        解码二进制数据为消息对象
        
        解码流程：
        1. 解码消息头
        2. 验证消息格式
        3. 提取压缩标志和消息体长度
        4. 解压缩（如果需要）
        5. 反序列化消息对象
        
        Args:
            data: 要解码的二进制数据
            expected_msg_id: 期望的消息ID，用于验证
            
        Returns:
            Union[BaseRequest, BaseResponse]: 解码后的消息对象
            
        Raises:
            DecodeException: 解码失败时抛出
        """
        start_time = time.time()
        
        try:
            # 验证数据基本格式
            if not isinstance(data, bytes):
                raise DecodeException("输入数据必须是bytes类型",
                                    data=data)
            
            min_size = get_header_size() + 1 + 4  # 消息头 + 压缩标志 + 长度字段
            if len(data) < min_size:
                raise DecodeException(f"数据长度不足，最少需要{min_size}字节，实际{len(data)}字节",
                                    data=data)
            
            # 解码消息头
            header = self.decode_header(data)
            
            # 验证期望的消息ID
            if expected_msg_id is not None and header.msg_id != expected_msg_id:
                raise DecodeException(f"消息ID不匹配，期望{expected_msg_id}，实际{header.msg_id}",
                                    data=data,
                                    expected_type=str(expected_msg_id))
            
            # 提取压缩标志和消息体长度
            header_size = get_header_size()
            compression_flag = data[header_size:header_size + 1]
            body_length_bytes = data[header_size + 1:header_size + 5]
            
            is_compressed = compression_flag == b'\x01'
            body_length = int.from_bytes(body_length_bytes, byteorder='big')
            
            # 验证消息体长度
            expected_total_length = header_size + 1 + 4 + body_length
            if len(data) < expected_total_length:
                raise DecodeException(f"消息体数据不完整，期望{expected_total_length}字节，实际{len(data)}字节",
                                    data=data)
            
            # 提取消息体数据
            message_body = data[header_size + 5:header_size + 5 + body_length]
            
            # 解压缩处理
            decompressed_data = self._decompress_data(message_body, is_compressed)
            
            # 获取消息类并反序列化
            try:
                message_class = self._registry.get_message_class(header.msg_id)
            except RegistryException as e:
                raise DecodeException(f"消息类未注册: {e}",
                                    data=data,
                                    expected_type=str(header.msg_id)) from e
            
            try:
                message = message_class.deserialize(decompressed_data, header)
            except Exception as e:
                raise DecodeException(f"消息反序列化失败: {e}",
                                    data=data,
                                    expected_type=message_class.__name__) from e
            
            # 更新统计
            self._statistics['total_decoded'] += 1
            self._statistics['decoded_bytes'] += len(data)
            self._statistics['total_decode_time'] += time.time() - start_time
            
            return message
            
        except DecodeException:
            self._statistics['decode_errors'] += 1
            raise
        except Exception as e:
            self._statistics['decode_errors'] += 1
            raise DecodeException(f"解码过程发生未知错误: {e}",
                                data=data) from e
    
    @handle_proto_exception
    def encode_header(self, header: MessageHeader) -> bytes:
        """
        编码消息头
        
        Args:
            header: 消息头对象
            
        Returns:
            bytes: 编码后的消息头数据
            
        Raises:
            HeaderException: 编码失败时抛出
        """
        try:
            return encode_header(header)
        except Exception as e:
            raise HeaderException(f"消息头编码失败: {e}",
                                msg_id=header.msg_id) from e
    
    @handle_proto_exception
    def decode_header(self, data: bytes) -> MessageHeader:
        """
        解码消息头
        
        Args:
            data: 包含消息头的二进制数据
            
        Returns:
            MessageHeader: 解码后的消息头
            
        Raises:
            HeaderException: 解码失败时抛出
        """
        try:
            return decode_header(data)
        except Exception as e:
            raise HeaderException(f"消息头解码失败: {e}",
                                header_data=data[:get_header_size()]) from e
    
    def _compress_data(self, data: bytes) -> Tuple[bytes, bool]:
        """
        压缩数据
        
        Args:
            data: 要压缩的数据
            
        Returns:
            Tuple[bytes, bool]: (压缩后的数据, 是否已压缩)
        """
        if (self._compression == CompressionType.NONE or 
            len(data) < self._compression_threshold):
            return data, False
        
        start_time = time.time()
        
        try:
            if self._compression == CompressionType.ZSTD:
                compressed_data = zstd.compress(data, level=self._compression_level)
                
                # 检查压缩效果，如果压缩后更大则不压缩
                if len(compressed_data) >= len(data):
                    return data, False
                
                # 更新统计
                self._statistics['total_compressed'] += 1
                self._statistics['compressed_bytes'] += len(compressed_data)
                self._statistics['total_compression_time'] += time.time() - start_time
                
                return compressed_data, True
            else:
                return data, False
                
        except Exception as e:
            self._statistics['compression_errors'] += 1
            # 压缩失败时返回原始数据
            return data, False
    
    def _decompress_data(self, data: bytes, is_compressed: bool) -> bytes:
        """
        解压缩数据
        
        Args:
            data: 要解压缩的数据
            is_compressed: 是否已压缩
            
        Returns:
            bytes: 解压缩后的数据
        """
        if not is_compressed:
            return data
        
        start_time = time.time()
        
        try:
            if self._compression == CompressionType.ZSTD:
                decompressed_data = zstd.decompress(data)
                
                # 更新统计
                self._statistics['total_decompressed'] += 1
                self._statistics['total_decompression_time'] += time.time() - start_time
                
                return decompressed_data
            else:
                raise DecodeException("不支持的压缩类型",
                                    data=data)
                
        except Exception as e:
            self._statistics['compression_errors'] += 1
            raise DecodeException(f"解压缩失败: {e}",
                                data=data) from e
    
    def set_compression(self, compression: CompressionType, 
                       threshold: Optional[int] = None,
                       level: Optional[int] = None) -> None:
        """
        设置压缩参数
        
        Args:
            compression: 压缩类型
            threshold: 压缩阈值
            level: 压缩级别
        """
        self._compression = compression
        
        if threshold is not None:
            if threshold <= 0:
                raise ValidationException("压缩阈值必须大于0",
                                        field_name="threshold",
                                        field_value=threshold)
            self._compression_threshold = threshold
        
        if level is not None:
            if not (1 <= level <= 22):
                raise ValidationException("压缩级别必须在1-22之间",
                                        field_name="level",
                                        field_value=level)
            self._compression_level = level
    
    def enable_validation(self, enabled: bool = True) -> None:
        """
        启用或禁用消息验证
        
        Args:
            enabled: 是否启用验证
        """
        self._enable_validation = enabled
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取编解码统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        stats = self._statistics.copy()
        
        # 计算派生统计
        if stats['total_encoded'] > 0:
            stats['avg_encode_time'] = stats['total_encode_time'] / stats['total_encoded']
            stats['avg_encoded_size'] = stats['encoded_bytes'] / stats['total_encoded']
        else:
            stats['avg_encode_time'] = 0.0
            stats['avg_encoded_size'] = 0.0
        
        if stats['total_decoded'] > 0:
            stats['avg_decode_time'] = stats['total_decode_time'] / stats['total_decoded']
            stats['avg_decoded_size'] = stats['decoded_bytes'] / stats['total_decoded']
        else:
            stats['avg_decode_time'] = 0.0
            stats['avg_decoded_size'] = 0.0
        
        if stats['total_compressed'] > 0:
            stats['avg_compression_time'] = stats['total_compression_time'] / stats['total_compressed']
            compression_ratio = stats['compressed_bytes'] / stats['original_bytes'] if stats['original_bytes'] > 0 else 1.0
            stats['compression_ratio'] = compression_ratio
            stats['compression_savings'] = 1.0 - compression_ratio
        else:
            stats['avg_compression_time'] = 0.0
            stats['compression_ratio'] = 1.0
            stats['compression_savings'] = 0.0
        
        if stats['total_decompressed'] > 0:
            stats['avg_decompression_time'] = stats['total_decompression_time'] / stats['total_decompressed']
        else:
            stats['avg_decompression_time'] = 0.0
        
        # 计算错误率
        total_operations = stats['total_encoded'] + stats['total_decoded']
        total_errors = stats['encode_errors'] + stats['decode_errors']
        stats['error_rate'] = total_errors / total_operations if total_operations > 0 else 0.0
        
        # 添加配置信息
        stats['compression_type'] = self._compression.value
        stats['compression_threshold'] = self._compression_threshold
        stats['compression_level'] = self._compression_level
        stats['validation_enabled'] = self._enable_validation
        
        return stats
    
    def reset_statistics(self) -> None:
        """重置统计信息"""
        for key in self._statistics:
            if isinstance(self._statistics[key], (int, float)):
                self._statistics[key] = 0 if isinstance(self._statistics[key], int) else 0.0
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        获取性能报告
        
        Returns:
            Dict[str, Any]: 性能报告
        """
        stats = self.get_statistics()
        
        # 性能评估
        performance_issues = []
        recommendations = []
        
        # 检查编码性能
        if stats['avg_encode_time'] > 0.01:  # 10ms
            performance_issues.append(f"编码时间过长: {stats['avg_encode_time']*1000:.1f}ms")
            recommendations.append("考虑优化消息结构或禁用压缩")
        
        # 检查解码性能
        if stats['avg_decode_time'] > 0.01:  # 10ms
            performance_issues.append(f"解码时间过长: {stats['avg_decode_time']*1000:.1f}ms")
            recommendations.append("考虑优化消息结构")
        
        # 检查压缩效果
        if stats['compression_ratio'] > 0.9 and stats['total_compressed'] > 0:
            performance_issues.append(f"压缩效果差: 压缩比{stats['compression_ratio']:.1%}")
            recommendations.append("考虑提高压缩阈值或禁用压缩")
        
        # 检查错误率
        if stats['error_rate'] > 0.01:  # 1%
            performance_issues.append(f"错误率过高: {stats['error_rate']:.1%}")
            recommendations.append("检查消息格式和网络质量")
        
        # 性能等级
        if not performance_issues:
            performance_grade = "A"
        elif len(performance_issues) <= 1:
            performance_grade = "B"
        elif len(performance_issues) <= 2:
            performance_grade = "C"
        else:
            performance_grade = "D"
        
        return {
            'performance_grade': performance_grade,
            'performance_issues': performance_issues,
            'recommendations': recommendations,
            'statistics': stats
        }
    
    def __str__(self) -> str:
        """返回可读的字符串表示"""
        stats = self._statistics
        return (f"ProtoCodec("
                f"compression={self._compression.value}, "
                f"encoded={stats['total_encoded']}, "
                f"decoded={stats['total_decoded']}, "
                f"errors={stats['encode_errors'] + stats['decode_errors']})")
    
    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        return (f"ProtoCodec("
                f"compression={self._compression.value}, "
                f"threshold={self._compression_threshold}, "
                f"level={self._compression_level}, "
                f"validation={self._enable_validation})")


# 便捷函数

def create_codec(compression: CompressionType = CompressionType.NONE,
                compression_threshold: int = 1024,
                compression_level: int = 3,
                registry: Optional[MessageRegistry] = None) -> ProtoCodec:
    """
    创建编解码器实例
    
    Args:
        compression: 压缩类型
        compression_threshold: 压缩阈值
        compression_level: 压缩级别
        registry: 消息注册表
        
    Returns:
        ProtoCodec: 编解码器实例
    """
    return ProtoCodec(
        registry=registry,
        compression=compression,
        compression_threshold=compression_threshold,
        compression_level=compression_level
    )


def encode_message(message: Union[BaseRequest, BaseResponse], 
                  codec: Optional[ProtoCodec] = None) -> bytes:
    """
    编码消息（便捷函数）
    
    Args:
        message: 要编码的消息
        codec: 编解码器，如果为None则创建默认编解码器
        
    Returns:
        bytes: 编码后的数据
    """
    if codec is None:
        codec = ProtoCodec()
    return codec.encode(message)


def decode_message(data: bytes, expected_msg_id: Optional[int] = None,
                  codec: Optional[ProtoCodec] = None) -> Union[BaseRequest, BaseResponse]:
    """
    解码消息（便捷函数）
    
    Args:
        data: 要解码的数据
        expected_msg_id: 期望的消息ID
        codec: 编解码器，如果为None则创建默认编解码器
        
    Returns:
        Union[BaseRequest, BaseResponse]: 解码后的消息
    """
    if codec is None:
        codec = ProtoCodec()
    return codec.decode(data, expected_msg_id)