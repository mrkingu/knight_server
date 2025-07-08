"""
环形缓冲区模块

该模块实现了 RingBuffer 环形缓冲区类，用于提高网络IO效率。
支持线程安全的读写操作、动态扩容和粘包处理。
"""

import asyncio
import struct
from typing import Optional, Tuple

from .exceptions import BufferException, ValidationException, handle_async_proto_exception


class RingBuffer:
    """
    环形缓冲区
    
    高效的字节缓冲区实现，支持：
    - 异步安全的读写操作
    - 动态扩容
    - 粘包处理
    - 零拷贝peek操作
    - 缓冲区状态监控
    
    Attributes:
        _buffer: 底层字节数组
        _capacity: 缓冲区容量
        _read_pos: 读指针位置
        _write_pos: 写指针位置
        _size: 当前数据大小
        _lock: 异步锁，保证操作的线程安全
        _min_capacity: 最小容量
        _max_capacity: 最大容量
    """
    
    __slots__ = (
        '_buffer', '_capacity', '_read_pos', '_write_pos', '_size',
        '_lock', '_min_capacity', '_max_capacity', '_growth_factor'
    )
    
    def __init__(self, capacity: int = 8192, max_capacity: int = 1024 * 1024 * 16,
                 growth_factor: float = 2.0):
        """
        初始化环形缓冲区
        
        Args:
            capacity: 初始容量（字节）
            max_capacity: 最大容量（字节）
            growth_factor: 扩容因子
            
        Raises:
            ValidationException: 参数验证失败时抛出
        """
        if capacity <= 0:
            raise ValidationException("缓冲区容量必须大于0",
                                    field_name="capacity",
                                    field_value=capacity)
        
        if max_capacity < capacity:
            raise ValidationException("最大容量不能小于初始容量",
                                    field_name="max_capacity",
                                    field_value=max_capacity)
        
        if growth_factor <= 1.0:
            raise ValidationException("扩容因子必须大于1.0",
                                    field_name="growth_factor",
                                    field_value=growth_factor)
        
        self._buffer = bytearray(capacity)
        self._capacity = capacity
        self._read_pos = 0
        self._write_pos = 0
        self._size = 0
        self._lock = asyncio.Lock()
        self._min_capacity = capacity
        self._max_capacity = max_capacity
        self._growth_factor = growth_factor
    
    @property
    def capacity(self) -> int:
        """获取缓冲区容量"""
        return self._capacity
    
    @property
    def size(self) -> int:
        """获取当前数据大小"""
        return self._size
    
    @property
    def available_read(self) -> int:
        """获取可读字节数"""
        return self._size
    
    @property
    def available_write(self) -> int:
        """获取可写空间"""
        return self._capacity - self._size
    
    @property
    def is_empty(self) -> bool:
        """检查缓冲区是否为空"""
        return self._size == 0
    
    @property
    def is_full(self) -> bool:
        """检查缓冲区是否已满"""
        return self._size == self._capacity
    
    @property
    def utilization(self) -> float:
        """获取缓冲区使用率（0.0-1.0）"""
        return self._size / self._capacity if self._capacity > 0 else 0.0
    
    @handle_async_proto_exception
    async def write(self, data: bytes) -> bool:
        """
        写入数据到缓冲区
        
        Args:
            data: 要写入的数据
            
        Returns:
            bool: 是否写入成功
            
        Raises:
            BufferException: 写入失败时抛出
        """
        if not isinstance(data, (bytes, bytearray)):
            raise ValidationException("写入数据必须是bytes或bytearray类型",
                                    field_name="data",
                                    field_value=type(data))
        
        if not data:
            return True  # 空数据直接返回成功
        
        async with self._lock:
            data_len = len(data)
            
            # 检查是否需要扩容
            if self.available_write < data_len:
                if not await self._expand_if_needed(data_len):
                    raise BufferException(
                        f"缓冲区空间不足，需要{data_len}字节，可用{self.available_write}字节",
                        buffer_size=self._capacity,
                        read_pos=self._read_pos,
                        write_pos=self._write_pos
                    )
            
            # 写入数据
            self._write_data(data)
            return True
    
    def _write_data(self, data: bytes) -> None:
        """
        内部写入数据方法（无锁）
        
        Args:
            data: 要写入的数据
        """
        data_len = len(data)
        
        if self._write_pos + data_len <= self._capacity:
            # 数据可以连续写入
            self._buffer[self._write_pos:self._write_pos + data_len] = data
        else:
            # 数据需要分段写入（绕回）
            first_part_len = self._capacity - self._write_pos
            self._buffer[self._write_pos:] = data[:first_part_len]
            self._buffer[:data_len - first_part_len] = data[first_part_len:]
        
        self._write_pos = (self._write_pos + data_len) % self._capacity
        self._size += data_len
    
    @handle_async_proto_exception
    async def read(self, size: int) -> bytes:
        """
        从缓冲区读取数据
        
        Args:
            size: 要读取的字节数
            
        Returns:
            bytes: 读取的数据
            
        Raises:
            BufferException: 读取失败时抛出
        """
        if size <= 0:
            raise ValidationException("读取大小必须大于0",
                                    field_name="size",
                                    field_value=size)
        
        async with self._lock:
            if self.available_read < size:
                raise BufferException(
                    f"可读数据不足，需要{size}字节，可用{self.available_read}字节",
                    buffer_size=self._capacity,
                    read_pos=self._read_pos,
                    write_pos=self._write_pos
                )
            
            data = self._read_data(size)
            return data
    
    def _read_data(self, size: int) -> bytes:
        """
        内部读取数据方法（无锁）
        
        Args:
            size: 要读取的字节数
            
        Returns:
            bytes: 读取的数据
        """
        if self._read_pos + size <= self._capacity:
            # 数据可以连续读取
            data = bytes(self._buffer[self._read_pos:self._read_pos + size])
        else:
            # 数据需要分段读取（绕回）
            first_part_len = self._capacity - self._read_pos
            first_part = self._buffer[self._read_pos:]
            second_part = self._buffer[:size - first_part_len]
            data = bytes(first_part + second_part)
        
        self._read_pos = (self._read_pos + size) % self._capacity
        self._size -= size
        
        return data
    
    @handle_async_proto_exception
    async def peek(self, size: int) -> bytes:
        """
        预览数据（不移动读指针）
        
        Args:
            size: 要预览的字节数
            
        Returns:
            bytes: 预览的数据
            
        Raises:
            BufferException: 预览失败时抛出
        """
        if size <= 0:
            raise ValidationException("预览大小必须大于0",
                                    field_name="size",
                                    field_value=size)
        
        async with self._lock:
            if self.available_read < size:
                raise BufferException(
                    f"可读数据不足，需要{size}字节，可用{self.available_read}字节",
                    buffer_size=self._capacity,
                    read_pos=self._read_pos,
                    write_pos=self._write_pos
                )
            
            # 不移动读指针，只是读取数据
            if self._read_pos + size <= self._capacity:
                data = bytes(self._buffer[self._read_pos:self._read_pos + size])
            else:
                first_part_len = self._capacity - self._read_pos
                first_part = self._buffer[self._read_pos:]
                second_part = self._buffer[:size - first_part_len]
                data = bytes(first_part + second_part)
            
            return data
    
    @handle_async_proto_exception
    async def skip(self, size: int) -> bool:
        """
        跳过指定字节数的数据
        
        Args:
            size: 要跳过的字节数
            
        Returns:
            bool: 是否跳过成功
        """
        if size <= 0:
            return True
        
        async with self._lock:
            if self.available_read < size:
                return False
            
            self._read_pos = (self._read_pos + size) % self._capacity
            self._size -= size
            
            return True
    
    async def _expand_if_needed(self, required_space: int) -> bool:
        """
        根据需要扩容缓冲区
        
        Args:
            required_space: 需要的额外空间
            
        Returns:
            bool: 是否扩容成功
        """
        if self.available_write >= required_space:
            return True
        
        # 计算新容量
        new_capacity = self._capacity
        while new_capacity - self._size < required_space:
            new_capacity = int(new_capacity * self._growth_factor)
            if new_capacity > self._max_capacity:
                return False  # 超过最大容量限制
        
        # 创建新缓冲区
        new_buffer = bytearray(new_capacity)
        
        # 复制现有数据到新缓冲区
        if self._size > 0:
            if self._read_pos + self._size <= self._capacity:
                # 数据连续
                new_buffer[:self._size] = self._buffer[self._read_pos:self._read_pos + self._size]
            else:
                # 数据分段
                first_part_len = self._capacity - self._read_pos
                new_buffer[:first_part_len] = self._buffer[self._read_pos:]
                new_buffer[first_part_len:self._size] = self._buffer[:self._size - first_part_len]
        
        # 更新缓冲区状态
        self._buffer = new_buffer
        self._capacity = new_capacity
        self._read_pos = 0
        self._write_pos = self._size
        
        return True
    
    @handle_async_proto_exception
    async def clear(self) -> None:
        """清空缓冲区"""
        async with self._lock:
            self._read_pos = 0
            self._write_pos = 0
            self._size = 0
    
    @handle_async_proto_exception
    async def reset(self, new_capacity: Optional[int] = None) -> None:
        """
        重置缓冲区
        
        Args:
            new_capacity: 新容量，如果为None则保持当前容量
        """
        async with self._lock:
            if new_capacity is not None:
                if new_capacity < self._min_capacity:
                    new_capacity = self._min_capacity
                elif new_capacity > self._max_capacity:
                    new_capacity = self._max_capacity
                
                self._buffer = bytearray(new_capacity)
                self._capacity = new_capacity
            
            self._read_pos = 0
            self._write_pos = 0
            self._size = 0
    
    @handle_async_proto_exception
    async def compact(self) -> None:
        """
        压缩缓冲区（移除已读数据，重新整理内存）
        """
        async with self._lock:
            if self._size == 0:
                self._read_pos = 0
                self._write_pos = 0
                return
            
            # 如果数据已经在缓冲区开始位置，无需压缩
            if self._read_pos == 0:
                return
            
            # 移动数据到缓冲区开始位置
            if self._read_pos + self._size <= self._capacity:
                # 数据连续
                self._buffer[:self._size] = self._buffer[self._read_pos:self._read_pos + self._size]
            else:
                # 数据分段，需要重新整理
                temp_data = bytearray(self._size)
                first_part_len = self._capacity - self._read_pos
                temp_data[:first_part_len] = self._buffer[self._read_pos:]
                temp_data[first_part_len:] = self._buffer[:self._size - first_part_len]
                self._buffer[:self._size] = temp_data
            
            self._read_pos = 0
            self._write_pos = self._size
    
    # 粘包处理相关方法
    
    @handle_async_proto_exception
    async def read_message(self, header_size: int = 4) -> Optional[bytes]:
        """
        读取完整消息（处理粘包）
        
        消息格式：[长度字段][消息体]
        
        Args:
            header_size: 长度字段大小（字节），支持1、2、4、8字节
            
        Returns:
            Optional[bytes]: 完整消息数据，如果数据不完整则返回None
            
        Raises:
            BufferException: 读取失败时抛出
        """
        if header_size not in (1, 2, 4, 8):
            raise ValidationException("长度字段大小只支持1、2、4、8字节",
                                    field_name="header_size",
                                    field_value=header_size)
        
        async with self._lock:
            # 检查是否有足够的数据读取长度字段
            if self.available_read < header_size:
                return None
            
            # 读取长度字段
            length_data = self._peek_no_lock(header_size)
            
            # 解析消息长度
            if header_size == 1:
                message_length, = struct.unpack('B', length_data)
            elif header_size == 2:
                message_length, = struct.unpack('!H', length_data)  # 网络字节序
            elif header_size == 4:
                message_length, = struct.unpack('!I', length_data)  # 网络字节序
            else:  # header_size == 8
                message_length, = struct.unpack('!Q', length_data)  # 网络字节序
            
            # 检查消息长度的合理性
            if message_length > self._max_capacity:
                raise BufferException(f"消息长度过大: {message_length}",
                                    buffer_size=self._capacity)
            
            # 检查是否有完整的消息数据
            total_size = header_size + message_length
            if self.available_read < total_size:
                return None
            
            # 读取完整消息
            message_data = self._read_data(total_size)
            return message_data[header_size:]  # 返回消息体，不包括长度字段
    
    async def _peek_no_lock(self, size: int) -> bytes:
        """内部预览方法（无锁版本）"""
        if self._read_pos + size <= self._capacity:
            data = bytes(self._buffer[self._read_pos:self._read_pos + size])
        else:
            first_part_len = self._capacity - self._read_pos
            first_part = self._buffer[self._read_pos:]
            second_part = self._buffer[:size - first_part_len]
            data = bytes(first_part + second_part)
        return data
    
    @handle_async_proto_exception
    async def write_message(self, data: bytes, header_size: int = 4) -> bool:
        """
        写入完整消息（添加长度头）
        
        Args:
            data: 消息数据
            header_size: 长度字段大小（字节）
            
        Returns:
            bool: 是否写入成功
        """
        if header_size not in (1, 2, 4, 8):
            raise ValidationException("长度字段大小只支持1、2、4、8字节",
                                    field_name="header_size",
                                    field_value=header_size)
        
        message_length = len(data)
        
        # 检查消息长度是否超出字段表示范围
        max_length = (1 << (header_size * 8)) - 1
        if message_length > max_length:
            raise BufferException(f"消息长度{message_length}超出{header_size}字节字段表示范围",
                                buffer_size=self._capacity)
        
        # 构造长度字段
        if header_size == 1:
            length_data = struct.pack('B', message_length)
        elif header_size == 2:
            length_data = struct.pack('!H', message_length)  # 网络字节序
        elif header_size == 4:
            length_data = struct.pack('!I', message_length)  # 网络字节序
        else:  # header_size == 8
            length_data = struct.pack('!Q', message_length)  # 网络字节序
        
        # 写入完整消息
        complete_message = length_data + data
        return await self.write(complete_message)
    
    def get_statistics(self) -> dict:
        """
        获取缓冲区统计信息
        
        Returns:
            dict: 统计信息
        """
        return {
            'capacity': self._capacity,
            'size': self._size,
            'available_read': self.available_read,
            'available_write': self.available_write,
            'utilization': self.utilization,
            'read_pos': self._read_pos,
            'write_pos': self._write_pos,
            'is_empty': self.is_empty,
            'is_full': self.is_full,
            'min_capacity': self._min_capacity,
            'max_capacity': self._max_capacity,
            'growth_factor': self._growth_factor
        }
    
    def __len__(self) -> int:
        """返回当前数据大小"""
        return self._size
    
    def __bool__(self) -> bool:
        """返回缓冲区是否包含数据"""
        return self._size > 0
    
    def __str__(self) -> str:
        """返回可读的字符串表示"""
        return (f"RingBuffer("
                f"size={self._size}/{self._capacity}, "
                f"utilization={self.utilization:.1%}, "
                f"read_pos={self._read_pos}, "
                f"write_pos={self._write_pos})")
    
    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        return (f"RingBuffer("
                f"capacity={self._capacity}, "
                f"size={self._size}, "
                f"read_pos={self._read_pos}, "
                f"write_pos={self._write_pos}, "
                f"max_capacity={self._max_capacity})")