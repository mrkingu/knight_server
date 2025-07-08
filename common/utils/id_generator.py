"""
ID生成器模块

该模块提供雪花算法ID生成器，支持分布式环境的唯一ID生成，
包括ID解析工具和短ID生成功能。
"""

import time
import threading
import hashlib
import base64
import random
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class SnowflakeComponents:
    """雪花算法ID组成部分"""
    timestamp: int          # 时间戳部分
    datacenter_id: int      # 数据中心ID
    worker_id: int          # 工作节点ID
    sequence: int           # 序列号
    raw_id: int            # 原始ID


class SnowflakeError(Exception):
    """雪花算法相关异常"""
    pass


class SnowflakeGenerator:
    """
    雪花算法ID生成器
    
    生成64位唯一ID，格式如下：
    - 1位符号位（固定为0）
    - 41位时间戳（毫秒级，可用69年）
    - 5位数据中心ID（0-31）
    - 5位工作节点ID（0-31）
    - 12位序列号（0-4095）
    
    支持分布式环境下的高并发唯一ID生成。
    """
    
    # 时间戳位数
    TIMESTAMP_BITS = 41
    # 数据中心ID位数
    DATACENTER_ID_BITS = 5
    # 工作节点ID位数
    WORKER_ID_BITS = 5
    # 序列号位数
    SEQUENCE_BITS = 12
    
    # 最大值
    MAX_DATACENTER_ID = (1 << DATACENTER_ID_BITS) - 1  # 31
    MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1          # 31
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1            # 4095
    
    # 位移量
    WORKER_ID_SHIFT = SEQUENCE_BITS                                    # 12
    DATACENTER_ID_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS             # 17
    TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS + DATACENTER_ID_BITS  # 22
    
    def __init__(self, datacenter_id: int = 1, worker_id: int = 1, 
                 epoch: int = 1609459200000):  # 2021-01-01 00:00:00 UTC
        """
        初始化雪花算法生成器
        
        Args:
            datacenter_id: 数据中心ID (0-31)
            worker_id: 工作节点ID (0-31)
            epoch: 起始时间戳（毫秒）
            
        Raises:
            SnowflakeError: 如果参数超出范围
        """
        if not (0 <= datacenter_id <= self.MAX_DATACENTER_ID):
            raise SnowflakeError(f"数据中心ID必须在0-{self.MAX_DATACENTER_ID}之间")
        
        if not (0 <= worker_id <= self.MAX_WORKER_ID):
            raise SnowflakeError(f"工作节点ID必须在0-{self.MAX_WORKER_ID}之间")
        
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.epoch = epoch
        
        # 状态变量
        self._last_timestamp = -1
        self._sequence = 0
        self._lock = threading.Lock()
        
        logger.info(f"雪花算法生成器初始化: datacenter_id={datacenter_id}, "
                   f"worker_id={worker_id}, epoch={epoch}")
    
    def generate(self) -> int:
        """
        生成下一个ID
        
        Returns:
            int: 64位唯一ID
            
        Raises:
            SnowflakeError: 如果时钟回退
        """
        with self._lock:
            timestamp = self._get_timestamp()
            
            # 检查时钟回退
            if timestamp < self._last_timestamp:
                offset = self._last_timestamp - timestamp
                raise SnowflakeError(f"时钟回退 {offset}ms，拒绝生成ID")
            
            # 同一毫秒内的并发处理
            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & self.MAX_SEQUENCE
                
                # 序列号用完，等待下一毫秒
                if self._sequence == 0:
                    timestamp = self._wait_next_millis(timestamp)
            else:
                self._sequence = 0
            
            self._last_timestamp = timestamp
            
            # 组装ID
            snowflake_id = (
                ((timestamp - self.epoch) << self.TIMESTAMP_SHIFT) |
                (self.datacenter_id << self.DATACENTER_ID_SHIFT) |
                (self.worker_id << self.WORKER_ID_SHIFT) |
                self._sequence
            )
            
            return snowflake_id
    
    def generate_multiple(self, count: int) -> list[int]:
        """
        批量生成ID
        
        Args:
            count: 生成数量
            
        Returns:
            list[int]: ID列表
        """
        return [self.generate() for _ in range(count)]
    
    def parse(self, snowflake_id: int) -> SnowflakeComponents:
        """
        解析雪花算法ID
        
        Args:
            snowflake_id: 雪花算法ID
            
        Returns:
            SnowflakeComponents: ID组成部分
        """
        # 提取各部分
        sequence = snowflake_id & self.MAX_SEQUENCE
        worker_id = (snowflake_id >> self.WORKER_ID_SHIFT) & self.MAX_WORKER_ID
        datacenter_id = (snowflake_id >> self.DATACENTER_ID_SHIFT) & self.MAX_DATACENTER_ID
        timestamp = (snowflake_id >> self.TIMESTAMP_SHIFT) + self.epoch
        
        return SnowflakeComponents(
            timestamp=timestamp,
            datacenter_id=datacenter_id,
            worker_id=worker_id,
            sequence=sequence,
            raw_id=snowflake_id
        )
    
    def get_timestamp_from_id(self, snowflake_id: int) -> int:
        """
        从ID中提取时间戳
        
        Args:
            snowflake_id: 雪花算法ID
            
        Returns:
            int: 时间戳（毫秒）
        """
        return (snowflake_id >> self.TIMESTAMP_SHIFT) + self.epoch
    
    def get_datetime_from_id(self, snowflake_id: int) -> datetime:
        """
        从ID中提取时间
        
        Args:
            snowflake_id: 雪花算法ID
            
        Returns:
            datetime: 时间对象
        """
        timestamp = self.get_timestamp_from_id(snowflake_id)
        return datetime.fromtimestamp(timestamp / 1000)
    
    def is_valid_id(self, snowflake_id: int) -> bool:
        """
        验证ID是否有效
        
        Args:
            snowflake_id: 要验证的ID
            
        Returns:
            bool: 是否有效
        """
        try:
            components = self.parse(snowflake_id)
            
            # 检查各部分是否在有效范围内
            if not (0 <= components.datacenter_id <= self.MAX_DATACENTER_ID):
                return False
            if not (0 <= components.worker_id <= self.MAX_WORKER_ID):
                return False
            if not (0 <= components.sequence <= self.MAX_SEQUENCE):
                return False
            
            # 检查时间戳是否合理
            current_timestamp = self._get_timestamp()
            if components.timestamp > current_timestamp:
                return False
            
            return True
        except Exception:
            return False
    
    def _get_timestamp(self) -> int:
        """获取当前时间戳（毫秒）"""
        return int(time.time() * 1000)
    
    def _wait_next_millis(self, last_timestamp: int) -> int:
        """等待下一毫秒"""
        timestamp = self._get_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._get_timestamp()
        return timestamp
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取生成器信息
        
        Returns:
            Dict[str, Any]: 生成器信息
        """
        return {
            'datacenter_id': self.datacenter_id,
            'worker_id': self.worker_id,
            'epoch': self.epoch,
            'last_timestamp': self._last_timestamp,
            'sequence': self._sequence,
            'max_ids_per_ms': self.MAX_SEQUENCE + 1,
            'max_datacenter': self.MAX_DATACENTER_ID + 1,
            'max_worker': self.MAX_WORKER_ID + 1
        }


class ShortIDGenerator:
    """
    短ID生成器
    
    生成用于展示的短ID，基于Base62编码。
    """
    
    BASE62_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    
    def __init__(self, min_length: int = 6):
        """
        初始化短ID生成器
        
        Args:
            min_length: 最小长度
        """
        self.min_length = min_length
        self._counter = 0
        self._lock = threading.Lock()
    
    def generate(self, prefix: str = "") -> str:
        """
        生成短ID
        
        Args:
            prefix: 前缀
            
        Returns:
            str: 短ID
        """
        with self._lock:
            self._counter += 1
            
            # 使用时间戳和计数器生成基础数字
            timestamp = int(time.time() * 1000)
            base_number = (timestamp << 16) | (self._counter & 0xFFFF)
            
            # 添加随机因子
            random_factor = random.randint(0, 999)
            base_number = (base_number << 10) | random_factor
            
            # 转换为Base62
            short_id = self._encode_base62(base_number)
            
            # 确保最小长度
            while len(short_id) < self.min_length:
                short_id = "0" + short_id
            
            return prefix + short_id
    
    def generate_from_snowflake(self, snowflake_id: int, prefix: str = "") -> str:
        """
        从雪花算法ID生成短ID
        
        Args:
            snowflake_id: 雪花算法ID
            prefix: 前缀
            
        Returns:
            str: 短ID
        """
        # 使用MD5哈希压缩ID，然后转换为Base62
        hash_bytes = hashlib.md5(str(snowflake_id).encode()).digest()
        hash_int = int.from_bytes(hash_bytes[:8], byteorder='big')
        
        short_id = self._encode_base62(hash_int)
        
        # 确保最小长度
        while len(short_id) < self.min_length:
            short_id = "0" + short_id
        
        return prefix + short_id
    
    def _encode_base62(self, number: int) -> str:
        """
        Base62编码
        
        Args:
            number: 要编码的数字
            
        Returns:
            str: Base62编码结果
        """
        if number == 0:
            return self.BASE62_CHARS[0]
        
        result = ""
        while number > 0:
            result = self.BASE62_CHARS[number % 62] + result
            number //= 62
        
        return result
    
    def _decode_base62(self, encoded: str) -> int:
        """
        Base62解码
        
        Args:
            encoded: Base62编码的字符串
            
        Returns:
            int: 解码结果
        """
        result = 0
        for char in encoded:
            result = result * 62 + self.BASE62_CHARS.index(char)
        return result


class UUIDGenerator:
    """
    UUID生成器
    
    生成各种格式的UUID。
    """
    
    @staticmethod
    def generate_uuid4() -> str:
        """
        生成UUID4
        
        Returns:
            str: UUID4字符串
        """
        import uuid
        return str(uuid.uuid4())
    
    @staticmethod
    def generate_compact_uuid() -> str:
        """
        生成紧凑UUID（去除连字符）
        
        Returns:
            str: 紧凑UUID字符串
        """
        import uuid
        return str(uuid.uuid4()).replace('-', '')
    
    @staticmethod
    def generate_base64_uuid() -> str:
        """
        生成Base64编码的UUID
        
        Returns:
            str: Base64编码的UUID
        """
        import uuid
        uuid_bytes = uuid.uuid4().bytes
        return base64.urlsafe_b64encode(uuid_bytes).decode().rstrip('=')


class IDManager:
    """
    ID管理器
    
    统一管理各种ID生成器。
    """
    
    def __init__(self):
        """初始化ID管理器"""
        self._snowflake_generators: Dict[str, SnowflakeGenerator] = {}
        self._short_id_generator = ShortIDGenerator()
        self._default_generator: Optional[SnowflakeGenerator] = None
    
    def create_snowflake_generator(self, name: str, datacenter_id: int = 1, 
                                 worker_id: int = 1, epoch: int = 1609459200000) -> SnowflakeGenerator:
        """
        创建雪花算法生成器
        
        Args:
            name: 生成器名称
            datacenter_id: 数据中心ID
            worker_id: 工作节点ID
            epoch: 起始时间戳
            
        Returns:
            SnowflakeGenerator: 生成器实例
        """
        generator = SnowflakeGenerator(datacenter_id, worker_id, epoch)
        self._snowflake_generators[name] = generator
        
        # 如果是第一个生成器，设为默认
        if self._default_generator is None:
            self._default_generator = generator
        
        logger.info(f"创建雪花算法生成器: {name}")
        return generator
    
    def get_snowflake_generator(self, name: str) -> Optional[SnowflakeGenerator]:
        """
        获取雪花算法生成器
        
        Args:
            name: 生成器名称
            
        Returns:
            Optional[SnowflakeGenerator]: 生成器实例
        """
        return self._snowflake_generators.get(name)
    
    def generate_id(self, generator_name: Optional[str] = None) -> int:
        """
        生成ID
        
        Args:
            generator_name: 生成器名称，为None时使用默认生成器
            
        Returns:
            int: 生成的ID
        """
        if generator_name:
            generator = self._snowflake_generators.get(generator_name)
            if not generator:
                raise ValueError(f"生成器 {generator_name} 不存在")
        else:
            generator = self._default_generator
            if not generator:
                raise ValueError("没有可用的ID生成器")
        
        return generator.generate()
    
    def generate_short_id(self, prefix: str = "") -> str:
        """
        生成短ID
        
        Args:
            prefix: 前缀
            
        Returns:
            str: 短ID
        """
        return self._short_id_generator.generate(prefix)
    
    def generate_uuid(self, format_type: str = "standard") -> str:
        """
        生成UUID
        
        Args:
            format_type: 格式类型 (standard, compact, base64)
            
        Returns:
            str: UUID字符串
        """
        if format_type == "standard":
            return UUIDGenerator.generate_uuid4()
        elif format_type == "compact":
            return UUIDGenerator.generate_compact_uuid()
        elif format_type == "base64":
            return UUIDGenerator.generate_base64_uuid()
        else:
            raise ValueError(f"不支持的UUID格式: {format_type}")
    
    def parse_id(self, snowflake_id: int, 
                generator_name: Optional[str] = None) -> SnowflakeComponents:
        """
        解析ID
        
        Args:
            snowflake_id: 雪花算法ID
            generator_name: 生成器名称
            
        Returns:
            SnowflakeComponents: ID组成部分
        """
        if generator_name:
            generator = self._snowflake_generators.get(generator_name)
            if not generator:
                raise ValueError(f"生成器 {generator_name} 不存在")
        else:
            generator = self._default_generator
            if not generator:
                raise ValueError("没有可用的ID生成器")
        
        return generator.parse(snowflake_id)
    
    def get_generators_info(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有生成器信息
        
        Returns:
            Dict[str, Dict[str, Any]]: 生成器信息
        """
        info = {}
        for name, generator in self._snowflake_generators.items():
            info[name] = generator.get_info()
        return info


# 全局ID管理器实例
id_manager = IDManager()

# 便捷函数
def create_snowflake_generator(name: str = "default", datacenter_id: int = 1, 
                             worker_id: int = 1) -> SnowflakeGenerator:
    """创建雪花算法生成器的便捷函数"""
    return id_manager.create_snowflake_generator(name, datacenter_id, worker_id)

def generate_id(generator_name: Optional[str] = None) -> int:
    """生成ID的便捷函数"""
    return id_manager.generate_id(generator_name)

def generate_short_id(prefix: str = "") -> str:
    """生成短ID的便捷函数"""
    return id_manager.generate_short_id(prefix)

def generate_uuid(format_type: str = "standard") -> str:
    """生成UUID的便捷函数"""
    return id_manager.generate_uuid(format_type)

def parse_id(snowflake_id: int, generator_name: Optional[str] = None) -> SnowflakeComponents:
    """解析ID的便捷函数"""
    return id_manager.parse_id(snowflake_id, generator_name)


if __name__ == "__main__":
    # 测试代码
    def test_id_generator():
        """测试ID生成器"""
        
        # 创建雪花算法生成器
        generator = create_snowflake_generator("test", datacenter_id=1, worker_id=1)
        
        # 生成ID
        ids = []
        for i in range(10):
            snowflake_id = generate_id("test")
            ids.append(snowflake_id)
            print(f"生成ID: {snowflake_id}")
        
        # 解析ID
        print("\n解析ID:")
        for snowflake_id in ids[:3]:
            components = parse_id(snowflake_id, "test")
            print(f"ID: {snowflake_id}")
            print(f"  时间戳: {components.timestamp}")
            print(f"  数据中心ID: {components.datacenter_id}")
            print(f"  工作节点ID: {components.worker_id}")
            print(f"  序列号: {components.sequence}")
            print(f"  生成时间: {generator.get_datetime_from_id(snowflake_id)}")
        
        # 测试短ID
        print("\n短ID生成:")
        for i in range(5):
            short_id = generate_short_id("USR")
            print(f"短ID: {short_id}")
        
        # 测试UUID
        print("\nUUID生成:")
        print(f"标准UUID: {generate_uuid('standard')}")
        print(f"紧凑UUID: {generate_uuid('compact')}")
        print(f"Base64 UUID: {generate_uuid('base64')}")
        
        # 测试生成器信息
        print("\n生成器信息:")
        info = id_manager.get_generators_info()
        for name, gen_info in info.items():
            print(f"{name}: {gen_info}")
    
    test_id_generator()