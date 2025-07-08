"""
分布式ID生成器模块

该模块提供分布式ID生成功能，包括：
- 雪花算法（Snowflake）实现
- 多数据中心部署支持
- ID生成性能优化（预分配）
- 时钟回拨处理
- 多种ID格式支持
- ID解析和反解析功能
"""

import time
import threading
import asyncio
import json
from typing import Dict, Any, Optional, List, Union, Tuple
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

from common.logger import logger


class IDFormat(Enum):
    """ID格式枚举"""
    DECIMAL = "decimal"      # 十进制
    HEXADECIMAL = "hex"      # 十六进制
    BASE62 = "base62"        # Base62编码
    UUID = "uuid"            # UUID格式


@dataclass
class SnowflakeConfig:
    """雪花算法配置"""
    datacenter_id: int = 0           # 数据中心ID（0-31）
    worker_id: int = 0               # 工作节点ID（0-31）
    epoch: int = 1640995200000       # 起始时间戳（2022-01-01 00:00:00 UTC）
    sequence_bits: int = 12          # 序列号位数
    worker_id_bits: int = 5          # 工作节点ID位数
    datacenter_id_bits: int = 5      # 数据中心ID位数
    max_sequence: int = 4095         # 最大序列号（2^12-1）
    max_worker_id: int = 31          # 最大工作节点ID（2^5-1）
    max_datacenter_id: int = 31      # 最大数据中心ID（2^5-1）
    clock_backward_tolerance: int = 5000  # 时钟回拨容忍度（毫秒）
    enable_preallocation: bool = True     # 启用预分配
    preallocation_size: int = 1000        # 预分配大小
    enable_redis_coordination: bool = True  # 启用Redis协调


@dataclass
class IDMetadata:
    """ID元数据"""
    id_value: int
    timestamp: int
    datacenter_id: int
    worker_id: int
    sequence: int
    format_type: IDFormat
    generated_at: float


class IDGeneratorError(Exception):
    """ID生成器异常基类"""
    pass


class ClockBackwardError(IDGeneratorError):
    """时钟回拨异常"""
    pass


class InvalidConfigError(IDGeneratorError):
    """配置无效异常"""
    pass


class WorkerIDConflictError(IDGeneratorError):
    """工作节点ID冲突异常"""
    pass


class SnowflakeIDGenerator:
    """雪花算法ID生成器"""
    
    def __init__(self, config: SnowflakeConfig, redis_manager=None):
        """
        初始化雪花算法ID生成器
        
        Args:
            config: 雪花算法配置
            redis_manager: Redis管理器（用于多实例协调）
        """
        self.config = config
        self.redis_manager = redis_manager
        
        # 验证配置
        self._validate_config()
        
        # 状态变量
        self.last_timestamp = -1
        self.sequence = 0
        self.lock = threading.Lock()
        
        # 预分配相关
        self.preallocation_pool: List[int] = []
        self.preallocation_lock = threading.Lock()
        self.preallocation_task: Optional[asyncio.Task] = None
        
        # 性能统计
        self.stats = {
            'total_generated': 0,
            'clock_backward_count': 0,
            'preallocation_hits': 0,
            'preallocation_misses': 0,
            'generation_time_total': 0.0
        }
        
        # 注册工作节点（如果启用Redis协调）
        if self.config.enable_redis_coordination and self.redis_manager:
            asyncio.create_task(self._register_worker())
        
        # 启动预分配任务
        if self.config.enable_preallocation:
            self._start_preallocation_task()
    
    def _validate_config(self):
        """验证配置"""
        if self.config.datacenter_id < 0 or self.config.datacenter_id > self.config.max_datacenter_id:
            raise InvalidConfigError(f"数据中心ID超出范围: {self.config.datacenter_id}")
        
        if self.config.worker_id < 0 or self.config.worker_id > self.config.max_worker_id:
            raise InvalidConfigError(f"工作节点ID超出范围: {self.config.worker_id}")
        
        if self.config.sequence_bits + self.config.worker_id_bits + self.config.datacenter_id_bits >= 22:
            raise InvalidConfigError("位数配置超出限制")
    
    async def _register_worker(self):
        """注册工作节点"""
        if not self.redis_manager:
            return
        
        try:
            worker_key = f"snowflake:workers:{self.config.datacenter_id}:{self.config.worker_id}"
            worker_info = {
                'datacenter_id': self.config.datacenter_id,
                'worker_id': self.config.worker_id,
                'registered_at': time.time(),
                'last_heartbeat': time.time()
            }
            
            # 检查是否已存在
            existing = await self.redis_manager.get(worker_key)
            if existing:
                existing_info = json.loads(existing)
                # 如果是不同的进程，抛出异常
                if existing_info.get('process_id') != threading.current_thread().ident:
                    raise WorkerIDConflictError(f"工作节点ID冲突: {self.config.worker_id}")
            
            worker_info['process_id'] = threading.current_thread().ident
            
            # 注册工作节点
            await self.redis_manager.setex(
                worker_key,
                60,  # 60秒过期
                json.dumps(worker_info)
            )
            
            # 启动心跳任务
            asyncio.create_task(self._heartbeat_loop())
            
            logger.info(f"工作节点注册成功: datacenter_id={self.config.datacenter_id}, worker_id={self.config.worker_id}")
            
        except Exception as e:
            logger.error(f"工作节点注册失败: {e}")
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while True:
            try:
                await asyncio.sleep(30)  # 每30秒发送心跳
                
                if self.redis_manager:
                    worker_key = f"snowflake:workers:{self.config.datacenter_id}:{self.config.worker_id}"
                    worker_info = {
                        'datacenter_id': self.config.datacenter_id,
                        'worker_id': self.config.worker_id,
                        'registered_at': time.time(),
                        'last_heartbeat': time.time(),
                        'process_id': threading.current_thread().ident
                    }
                    
                    await self.redis_manager.setex(
                        worker_key,
                        60,
                        json.dumps(worker_info)
                    )
                    
            except Exception as e:
                logger.error(f"心跳发送失败: {e}")
                break
    
    def _start_preallocation_task(self):
        """启动预分配任务"""
        if self.preallocation_task is None:
            self.preallocation_task = asyncio.create_task(self._preallocation_loop())
    
    async def _preallocation_loop(self):
        """预分配循环"""
        while True:
            try:
                await asyncio.sleep(0.1)  # 每100ms检查一次
                
                with self.preallocation_lock:
                    pool_size = len(self.preallocation_pool)
                
                # 如果池中ID数量不足，预分配新的ID
                if pool_size < self.config.preallocation_size // 2:
                    await self._prealloc_ids()
                    
            except asyncio.CancelledError:
                logger.debug("预分配任务已取消")
                break
            except Exception as e:
                logger.error(f"预分配异常: {e}")
                await asyncio.sleep(1.0)
    
    async def _prealloc_ids(self):
        """预分配ID"""
        try:
            batch_size = self.config.preallocation_size
            new_ids = []
            
            for _ in range(batch_size):
                id_value = self._generate_id_internal()
                new_ids.append(id_value)
            
            with self.preallocation_lock:
                self.preallocation_pool.extend(new_ids)
                # 限制池大小
                if len(self.preallocation_pool) > self.config.preallocation_size * 2:
                    self.preallocation_pool = self.preallocation_pool[-self.config.preallocation_size:]
            
            logger.debug(f"预分配ID成功: {len(new_ids)} 个")
            
        except Exception as e:
            logger.error(f"预分配ID失败: {e}")
    
    def _current_timestamp(self) -> int:
        """获取当前时间戳（毫秒）"""
        return int(time.time() * 1000)
    
    def _wait_next_millis(self, last_timestamp: int) -> int:
        """等待下一毫秒"""
        timestamp = self._current_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._current_timestamp()
        return timestamp
    
    def _generate_id_internal(self) -> int:
        """内部生成ID方法"""
        with self.lock:
            timestamp = self._current_timestamp()
            
            # 检查时钟回拨
            if timestamp < self.last_timestamp:
                offset = self.last_timestamp - timestamp
                if offset <= self.config.clock_backward_tolerance:
                    # 容忍范围内，等待时钟追上
                    timestamp = self.last_timestamp
                    logger.warning(f"检测到时钟回拨: {offset}ms，等待追赶")
                    self.stats['clock_backward_count'] += 1
                else:
                    # 超出容忍范围，抛出异常
                    raise ClockBackwardError(f"时钟回拨过大: {offset}ms")
            
            # 同一毫秒内生成多个ID
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.config.max_sequence
                if self.sequence == 0:
                    # 序列号溢出，等待下一毫秒
                    timestamp = self._wait_next_millis(self.last_timestamp)
            else:
                # 新的毫秒，重置序列号
                self.sequence = 0
            
            self.last_timestamp = timestamp
            
            # 生成ID
            id_value = (
                ((timestamp - self.config.epoch) << (self.config.datacenter_id_bits + self.config.worker_id_bits + self.config.sequence_bits)) |
                (self.config.datacenter_id << (self.config.worker_id_bits + self.config.sequence_bits)) |
                (self.config.worker_id << self.config.sequence_bits) |
                self.sequence
            )
            
            self.stats['total_generated'] += 1
            return id_value
    
    def generate_id(self, format_type: IDFormat = IDFormat.DECIMAL) -> Union[int, str]:
        """
        生成ID
        
        Args:
            format_type: ID格式类型
            
        Returns:
            Union[int, str]: 生成的ID
        """
        start_time = time.time()
        
        try:
            # 优先从预分配池获取
            if self.config.enable_preallocation:
                with self.preallocation_lock:
                    if self.preallocation_pool:
                        id_value = self.preallocation_pool.pop(0)
                        self.stats['preallocation_hits'] += 1
                    else:
                        id_value = self._generate_id_internal()
                        self.stats['preallocation_misses'] += 1
            else:
                id_value = self._generate_id_internal()
            
            # 格式化ID
            formatted_id = self._format_id(id_value, format_type)
            
            # 更新统计
            generation_time = time.time() - start_time
            self.stats['generation_time_total'] += generation_time
            
            return formatted_id
            
        except Exception as e:
            logger.error(f"生成ID失败: {e}")
            raise e
    
    def _format_id(self, id_value: int, format_type: IDFormat) -> Union[int, str]:
        """格式化ID"""
        if format_type == IDFormat.DECIMAL:
            return id_value
        elif format_type == IDFormat.HEXADECIMAL:
            return hex(id_value)[2:]  # 移除'0x'前缀
        elif format_type == IDFormat.BASE62:
            return self._base62_encode(id_value)
        elif format_type == IDFormat.UUID:
            return self._uuid_format(id_value)
        else:
            return id_value
    
    def _base62_encode(self, number: int) -> str:
        """Base62编码"""
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        if number == 0:
            return alphabet[0]
        
        result = []
        while number:
            number, remainder = divmod(number, 62)
            result.append(alphabet[remainder])
        
        return ''.join(reversed(result))
    
    def _base62_decode(self, encoded: str) -> int:
        """Base62解码"""
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        result = 0
        for char in encoded:
            result = result * 62 + alphabet.index(char)
        return result
    
    def _uuid_format(self, id_value: int) -> str:
        """UUID格式化"""
        # 将64位整数格式化为UUID样式的字符串
        hex_str = f"{id_value:016x}"
        return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"
    
    def parse_id(self, id_value: Union[int, str], format_type: IDFormat = IDFormat.DECIMAL) -> IDMetadata:
        """
        解析ID
        
        Args:
            id_value: ID值
            format_type: ID格式类型
            
        Returns:
            IDMetadata: ID元数据
        """
        # 转换为整数
        if isinstance(id_value, str):
            if format_type == IDFormat.HEXADECIMAL:
                numeric_id = int(id_value, 16)
            elif format_type == IDFormat.BASE62:
                numeric_id = self._base62_decode(id_value)
            elif format_type == IDFormat.UUID:
                # 移除UUID中的连字符
                hex_str = id_value.replace('-', '')
                numeric_id = int(hex_str, 16)
            else:
                numeric_id = int(id_value)
        else:
            numeric_id = id_value
        
        # 解析各个组件
        sequence = numeric_id & self.config.max_sequence
        worker_id = (numeric_id >> self.config.sequence_bits) & self.config.max_worker_id
        datacenter_id = (numeric_id >> (self.config.sequence_bits + self.config.worker_id_bits)) & self.config.max_datacenter_id
        timestamp = (numeric_id >> (self.config.sequence_bits + self.config.worker_id_bits + self.config.datacenter_id_bits)) + self.config.epoch
        
        return IDMetadata(
            id_value=numeric_id,
            timestamp=timestamp,
            datacenter_id=datacenter_id,
            worker_id=worker_id,
            sequence=sequence,
            format_type=format_type,
            generated_at=timestamp / 1000.0
        )
    
    def batch_generate_ids(self, count: int, format_type: IDFormat = IDFormat.DECIMAL) -> List[Union[int, str]]:
        """
        批量生成ID
        
        Args:
            count: 生成数量
            format_type: ID格式类型
            
        Returns:
            List[Union[int, str]]: ID列表
        """
        ids = []
        for _ in range(count):
            ids.append(self.generate_id(format_type))
        return ids
    
    async def async_generate_id(self, format_type: IDFormat = IDFormat.DECIMAL) -> Union[int, str]:
        """
        异步生成ID
        
        Args:
            format_type: ID格式类型
            
        Returns:
            Union[int, str]: 生成的ID
        """
        # 在线程池中执行生成操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate_id, format_type)
    
    async def async_batch_generate_ids(self, count: int, format_type: IDFormat = IDFormat.DECIMAL) -> List[Union[int, str]]:
        """
        异步批量生成ID
        
        Args:
            count: 生成数量
            format_type: ID格式类型
            
        Returns:
            List[Union[int, str]]: ID列表
        """
        # 在线程池中执行批量生成操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_generate_ids, count, format_type)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        stats = self.stats.copy()
        
        if stats['total_generated'] > 0:
            stats['avg_generation_time'] = stats['generation_time_total'] / stats['total_generated']
            stats['preallocation_hit_rate'] = stats['preallocation_hits'] / stats['total_generated']
        else:
            stats['avg_generation_time'] = 0.0
            stats['preallocation_hit_rate'] = 0.0
        
        with self.preallocation_lock:
            stats['preallocation_pool_size'] = len(self.preallocation_pool)
        
        stats['config'] = {
            'datacenter_id': self.config.datacenter_id,
            'worker_id': self.config.worker_id,
            'epoch': self.config.epoch,
            'enable_preallocation': self.config.enable_preallocation,
            'preallocation_size': self.config.preallocation_size
        }
        
        return stats
    
    def reset_stats(self):
        """重置统计信息"""
        self.stats = {
            'total_generated': 0,
            'clock_backward_count': 0,
            'preallocation_hits': 0,
            'preallocation_misses': 0,
            'generation_time_total': 0.0
        }
        logger.info("ID生成器统计信息已重置")
    
    async def close(self):
        """关闭ID生成器"""
        # 取消预分配任务
        if self.preallocation_task:
            self.preallocation_task.cancel()
            try:
                await self.preallocation_task
            except asyncio.CancelledError:
                pass
        
        # 注销工作节点
        if self.config.enable_redis_coordination and self.redis_manager:
            try:
                worker_key = f"snowflake:workers:{self.config.datacenter_id}:{self.config.worker_id}"
                await self.redis_manager.delete(worker_key)
            except Exception as e:
                logger.error(f"注销工作节点失败: {e}")
        
        logger.info("ID生成器已关闭")


class IDGeneratorManager:
    """ID生成器管理器"""
    
    def __init__(self, redis_manager=None):
        self.redis_manager = redis_manager
        self.generators: Dict[str, SnowflakeIDGenerator] = {}
    
    def create_generator(self, name: str, config: SnowflakeConfig) -> SnowflakeIDGenerator:
        """
        创建ID生成器
        
        Args:
            name: 生成器名称
            config: 配置
            
        Returns:
            SnowflakeIDGenerator: ID生成器实例
        """
        if name in self.generators:
            logger.warning(f"ID生成器 {name} 已存在")
            return self.generators[name]
        
        generator = SnowflakeIDGenerator(config, self.redis_manager)
        self.generators[name] = generator
        
        logger.info(f"已创建ID生成器: {name}")
        return generator
    
    def get_generator(self, name: str) -> Optional[SnowflakeIDGenerator]:
        """
        获取ID生成器
        
        Args:
            name: 生成器名称
            
        Returns:
            Optional[SnowflakeIDGenerator]: ID生成器实例
        """
        return self.generators.get(name)
    
    def remove_generator(self, name: str):
        """
        移除ID生成器
        
        Args:
            name: 生成器名称
        """
        if name in self.generators:
            generator = self.generators[name]
            asyncio.create_task(generator.close())
            del self.generators[name]
            logger.info(f"已移除ID生成器: {name}")
    
    def list_generators(self) -> List[str]:
        """
        列出所有ID生成器名称
        
        Returns:
            List[str]: 生成器名称列表
        """
        return list(self.generators.keys())
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有生成器的统计信息
        
        Returns:
            Dict[str, Dict[str, Any]]: 统计信息字典
        """
        return {
            name: generator.get_stats()
            for name, generator in self.generators.items()
        }
    
    async def close_all(self):
        """关闭所有ID生成器"""
        tasks = []
        for generator in self.generators.values():
            tasks.append(generator.close())
        
        if tasks:
            await asyncio.gather(*tasks)
        
        self.generators.clear()


# 默认配置实例
default_config = SnowflakeConfig()

# 默认ID生成器管理器实例
_default_manager = None


def get_id_generator_manager(redis_manager=None) -> IDGeneratorManager:
    """
    获取ID生成器管理器实例
    
    Args:
        redis_manager: Redis管理器
        
    Returns:
        IDGeneratorManager: ID生成器管理器实例
    """
    global _default_manager
    
    if _default_manager is None:
        _default_manager = IDGeneratorManager(redis_manager)
    
    return _default_manager


# 便捷函数
def create_id_generator(name: str, datacenter_id: int = 0, worker_id: int = 0, 
                       config: SnowflakeConfig = None) -> SnowflakeIDGenerator:
    """创建ID生成器的便捷函数"""
    if config is None:
        config = SnowflakeConfig(datacenter_id=datacenter_id, worker_id=worker_id)
    
    manager = get_id_generator_manager()
    return manager.create_generator(name, config)


def get_id_generator(name: str) -> Optional[SnowflakeIDGenerator]:
    """获取ID生成器的便捷函数"""
    manager = get_id_generator_manager()
    return manager.get_generator(name)


def generate_id(generator_name: str = "default", format_type: IDFormat = IDFormat.DECIMAL) -> Union[int, str]:
    """生成ID的便捷函数"""
    generator = get_id_generator(generator_name)
    if generator is None:
        # 创建默认生成器
        generator = create_id_generator(generator_name)
    
    return generator.generate_id(format_type)


async def async_generate_id(generator_name: str = "default", format_type: IDFormat = IDFormat.DECIMAL) -> Union[int, str]:
    """异步生成ID的便捷函数"""
    generator = get_id_generator(generator_name)
    if generator is None:
        # 创建默认生成器
        generator = create_id_generator(generator_name)
    
    return await generator.async_generate_id(format_type)


def parse_id(id_value: Union[int, str], generator_name: str = "default", 
            format_type: IDFormat = IDFormat.DECIMAL) -> IDMetadata:
    """解析ID的便捷函数"""
    generator = get_id_generator(generator_name)
    if generator is None:
        # 创建默认生成器
        generator = create_id_generator(generator_name)
    
    return generator.parse_id(id_value, format_type)


# ID生成器装饰器
def id_generator_decorator(generator_name: str = "default", format_type: IDFormat = IDFormat.DECIMAL):
    """ID生成器装饰器，为函数返回值添加唯一ID"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            if isinstance(result, dict):
                result['id'] = await async_generate_id(generator_name, format_type)
            return result
        
        def sync_wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                result['id'] = generate_id(generator_name, format_type)
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator