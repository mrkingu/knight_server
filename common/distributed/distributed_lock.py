"""
分布式锁模块

该模块提供分布式锁功能，包括：
- 基于Redis的分布式锁实现
- 可重入锁支持
- 自动续期机制（看门狗）
- 死锁检测和预防
- 公平锁和非公平锁
- 读写锁实现
- 异步锁操作支持
"""

import asyncio
import time
import uuid
import json
import threading
from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass
from enum import Enum
from contextlib import asynccontextmanager
from abc import ABC, abstractmethod

from common.logger import logger


class LockType(Enum):
    """锁类型枚举"""
    EXCLUSIVE = "exclusive"  # 排他锁
    SHARED = "shared"       # 共享锁
    REENTRANT = "reentrant" # 可重入锁


class LockState(Enum):
    """锁状态枚举"""
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    EXPIRED = "expired"


@dataclass
class LockConfig:
    """分布式锁配置"""
    timeout: float = 30.0           # 锁超时时间（秒）
    retry_delay: float = 0.1        # 重试延迟（秒）
    max_retries: int = 10           # 最大重试次数
    auto_renewal: bool = True       # 自动续期
    renewal_interval: float = 10.0  # 续期间隔（秒）
    enable_watchdog: bool = True    # 启用看门狗
    fair_lock: bool = False         # 公平锁
    enable_deadlock_detection: bool = True  # 启用死锁检测
    deadlock_timeout: float = 60.0  # 死锁检测超时
    lock_prefix: str = "distributed_lock"  # 锁前缀


@dataclass
class LockInfo:
    """锁信息"""
    key: str
    owner: str
    lock_type: LockType
    acquired_at: float
    expires_at: float
    reentrant_count: int = 0
    thread_id: Optional[int] = None
    process_id: Optional[int] = None


class DistributedLockError(Exception):
    """分布式锁异常基类"""
    pass


class LockTimeoutError(DistributedLockError):
    """锁超时异常"""
    pass


class LockNotOwnedError(DistributedLockError):
    """锁未持有异常"""
    pass


class DeadlockError(DistributedLockError):
    """死锁异常"""
    pass


class LockExpiredError(DistributedLockError):
    """锁过期异常"""
    pass


class BaseLock(ABC):
    """基础锁抽象类"""
    
    def __init__(self, key: str, config: LockConfig, redis_manager=None):
        self.key = key
        self.config = config
        self.redis_manager = redis_manager
        self.lock_info: Optional[LockInfo] = None
        self._renewal_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        
        # 生成唯一的锁持有者ID
        self.owner_id = f"{uuid.uuid4()}_{threading.get_ident()}"
    
    @abstractmethod
    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """获取锁"""
        pass
    
    @abstractmethod
    async def release(self) -> bool:
        """释放锁"""
        pass
    
    @abstractmethod
    async def is_locked(self) -> bool:
        """检查锁是否被持有"""
        pass
    
    @abstractmethod
    async def extend(self, timeout: Optional[float] = None) -> bool:
        """延长锁的持有时间"""
        pass
    
    def _get_redis_key(self) -> str:
        """获取Redis键"""
        return f"{self.config.lock_prefix}:{self.key}"
    
    def _get_queue_key(self) -> str:
        """获取队列键（用于公平锁）"""
        return f"{self.config.lock_prefix}:queue:{self.key}"
    
    def _get_owner_key(self) -> str:
        """获取持有者键（用于可重入锁）"""
        return f"{self.config.lock_prefix}:owner:{self.key}"
    
    async def _start_renewal_task(self):
        """启动自动续期任务"""
        if self.config.auto_renewal and self._renewal_task is None:
            self._renewal_task = asyncio.create_task(self._renewal_loop())
    
    async def _stop_renewal_task(self):
        """停止自动续期任务"""
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
            self._renewal_task = None
    
    async def _renewal_loop(self):
        """自动续期循环"""
        while True:
            try:
                await asyncio.sleep(self.config.renewal_interval)
                
                if self.lock_info and self.lock_info.expires_at > time.time():
                    success = await self.extend()
                    if success:
                        logger.debug(f"锁续期成功: {self.key}")
                    else:
                        logger.warning(f"锁续期失败: {self.key}")
                        break
                else:
                    logger.warning(f"锁已过期，停止续期: {self.key}")
                    break
                    
            except asyncio.CancelledError:
                logger.debug(f"锁续期任务已取消: {self.key}")
                break
            except Exception as e:
                logger.error(f"锁续期异常: {self.key}, 错误: {e}")
                break
    
    async def _start_watchdog_task(self):
        """启动看门狗任务"""
        if self.config.enable_watchdog and self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
    
    async def _stop_watchdog_task(self):
        """停止看门狗任务"""
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
    
    async def _watchdog_loop(self):
        """看门狗循环"""
        while True:
            try:
                await asyncio.sleep(1.0)  # 每秒检查一次
                
                if self.lock_info:
                    current_time = time.time()
                    
                    # 检查锁是否即将过期
                    if self.lock_info.expires_at - current_time < 5.0:
                        logger.warning(f"锁即将过期: {self.key}")
                        
                        # 尝试续期
                        if self.config.auto_renewal:
                            success = await self.extend()
                            if not success:
                                logger.error(f"看门狗续期失败: {self.key}")
                                break
                    
                    # 检查锁是否已过期
                    if self.lock_info.expires_at <= current_time:
                        logger.error(f"锁已过期: {self.key}")
                        self.lock_info = None
                        break
                        
            except asyncio.CancelledError:
                logger.debug(f"看门狗任务已取消: {self.key}")
                break
            except Exception as e:
                logger.error(f"看门狗异常: {self.key}, 错误: {e}")
                break
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        success = await self.acquire()
        if not success:
            raise LockTimeoutError(f"无法获取锁: {self.key}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.release()


class ExclusiveLock(BaseLock):
    """排他锁实现"""
    
    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """获取排他锁"""
        if timeout is None:
            timeout = self.config.timeout
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        start_time = time.time()
        redis_key = self._get_redis_key()
        
        # 如果是公平锁，先加入队列
        if self.config.fair_lock:
            await self._join_queue()
        
        retries = 0
        while retries < self.config.max_retries:
            try:
                current_time = time.time()
                
                # 检查超时
                if current_time - start_time > timeout:
                    raise LockTimeoutError(f"获取锁超时: {self.key}")
                
                # 公平锁检查队列顺序
                if self.config.fair_lock:
                    is_my_turn = await self._is_my_turn()
                    if not is_my_turn:
                        await asyncio.sleep(self.config.retry_delay)
                        retries += 1
                        continue
                
                # 尝试获取锁
                expires_at = current_time + self.config.timeout
                lock_data = {
                    'owner': self.owner_id,
                    'type': LockType.EXCLUSIVE.value,
                    'acquired_at': current_time,
                    'expires_at': expires_at,
                    'reentrant_count': 1,
                    'thread_id': threading.get_ident(),
                    'process_id': threading.current_thread().ident
                }
                
                # 使用SET NX EX命令原子性设置锁
                success = await self.redis_manager.set(
                    redis_key,
                    json.dumps(lock_data),
                    nx=True,
                    ex=int(self.config.timeout)
                )
                
                if success:
                    # 获取锁成功
                    self.lock_info = LockInfo(
                        key=self.key,
                        owner=self.owner_id,
                        lock_type=LockType.EXCLUSIVE,
                        acquired_at=current_time,
                        expires_at=expires_at,
                        reentrant_count=1,
                        thread_id=threading.get_ident(),
                        process_id=threading.current_thread().ident
                    )
                    
                    # 启动续期和看门狗任务
                    await self._start_renewal_task()
                    await self._start_watchdog_task()
                    
                    # 从队列中移除
                    if self.config.fair_lock:
                        await self._leave_queue()
                    
                    logger.debug(f"获取排他锁成功: {self.key}")
                    return True
                
                # 获取锁失败，重试
                await asyncio.sleep(self.config.retry_delay)
                retries += 1
                
            except Exception as e:
                logger.error(f"获取锁异常: {self.key}, 错误: {e}")
                retries += 1
                await asyncio.sleep(self.config.retry_delay)
        
        # 从队列中移除
        if self.config.fair_lock:
            await self._leave_queue()
        
        return False
    
    async def release(self) -> bool:
        """释放排他锁"""
        if not self.lock_info:
            logger.warning(f"锁未持有，无法释放: {self.key}")
            return False
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        # 停止续期和看门狗任务
        await self._stop_renewal_task()
        await self._stop_watchdog_task()
        
        redis_key = self._get_redis_key()
        
        try:
            # 使用Lua脚本确保只有锁持有者才能释放锁
            lua_script = """
            local key = KEYS[1]
            local owner = ARGV[1]
            
            local lock_data = redis.call('GET', key)
            if lock_data then
                local lock_info = cjson.decode(lock_data)
                if lock_info.owner == owner then
                    return redis.call('DEL', key)
                end
            end
            return 0
            """
            
            result = await self.redis_manager.eval(
                lua_script,
                1,
                redis_key,
                self.owner_id
            )
            
            if result == 1:
                logger.debug(f"释放排他锁成功: {self.key}")
                self.lock_info = None
                return True
            else:
                logger.warning(f"释放锁失败，可能已被其他进程持有: {self.key}")
                return False
                
        except Exception as e:
            logger.error(f"释放锁异常: {self.key}, 错误: {e}")
            return False
    
    async def is_locked(self) -> bool:
        """检查锁是否被持有"""
        if not self.redis_manager:
            return self.lock_info is not None
        
        redis_key = self._get_redis_key()
        
        try:
            lock_data = await self.redis_manager.get(redis_key)
            return lock_data is not None
        except Exception as e:
            logger.error(f"检查锁状态异常: {self.key}, 错误: {e}")
            return False
    
    async def extend(self, timeout: Optional[float] = None) -> bool:
        """延长锁的持有时间"""
        if not self.lock_info:
            logger.warning(f"锁未持有，无法延长: {self.key}")
            return False
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        if timeout is None:
            timeout = self.config.timeout
        
        redis_key = self._get_redis_key()
        
        try:
            # 使用Lua脚本确保只有锁持有者才能延长锁
            lua_script = """
            local key = KEYS[1]
            local owner = ARGV[1]
            local timeout = tonumber(ARGV[2])
            
            local lock_data = redis.call('GET', key)
            if lock_data then
                local lock_info = cjson.decode(lock_data)
                if lock_info.owner == owner then
                    local current_time = tonumber(ARGV[3])
                    lock_info.expires_at = current_time + timeout
                    redis.call('SET', key, cjson.encode(lock_info))
                    redis.call('EXPIRE', key, timeout)
                    return 1
                end
            end
            return 0
            """
            
            current_time = time.time()
            result = await self.redis_manager.eval(
                lua_script,
                1,
                redis_key,
                self.owner_id,
                timeout,
                current_time
            )
            
            if result == 1:
                # 更新本地锁信息
                self.lock_info.expires_at = current_time + timeout
                logger.debug(f"延长锁成功: {self.key}")
                return True
            else:
                logger.warning(f"延长锁失败，可能已被其他进程持有: {self.key}")
                return False
                
        except Exception as e:
            logger.error(f"延长锁异常: {self.key}, 错误: {e}")
            return False
    
    async def _join_queue(self):
        """加入公平锁队列"""
        if not self.redis_manager:
            return
        
        queue_key = self._get_queue_key()
        
        try:
            # 使用有序集合实现队列
            await self.redis_manager.zadd(
                queue_key,
                {self.owner_id: time.time()}
            )
            
            # 设置队列过期时间
            await self.redis_manager.expire(queue_key, int(self.config.timeout * 2))
            
        except Exception as e:
            logger.error(f"加入队列异常: {self.key}, 错误: {e}")
    
    async def _leave_queue(self):
        """离开公平锁队列"""
        if not self.redis_manager:
            return
        
        queue_key = self._get_queue_key()
        
        try:
            await self.redis_manager.zrem(queue_key, self.owner_id)
        except Exception as e:
            logger.error(f"离开队列异常: {self.key}, 错误: {e}")
    
    async def _is_my_turn(self) -> bool:
        """检查是否轮到我获取锁"""
        if not self.redis_manager:
            return True
        
        queue_key = self._get_queue_key()
        
        try:
            # 获取队列中的第一个元素
            first_member = await self.redis_manager.zrange(
                queue_key, 0, 0, withscores=False
            )
            
            if first_member and len(first_member) > 0:
                return first_member[0] == self.owner_id
            
            return True
            
        except Exception as e:
            logger.error(f"检查队列顺序异常: {self.key}, 错误: {e}")
            return True


class ReentrantLock(BaseLock):
    """可重入锁实现"""
    
    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """获取可重入锁"""
        if timeout is None:
            timeout = self.config.timeout
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        start_time = time.time()
        redis_key = self._get_redis_key()
        
        retries = 0
        while retries < self.config.max_retries:
            try:
                current_time = time.time()
                
                # 检查超时
                if current_time - start_time > timeout:
                    raise LockTimeoutError(f"获取锁超时: {self.key}")
                
                # 检查是否已经持有锁
                existing_lock = await self.redis_manager.get(redis_key)
                if existing_lock:
                    lock_data = json.loads(existing_lock)
                    
                    # 如果是同一个持有者，增加重入计数
                    if lock_data.get('owner') == self.owner_id:
                        lock_data['reentrant_count'] += 1
                        
                        # 更新锁数据
                        await self.redis_manager.set(
                            redis_key,
                            json.dumps(lock_data),
                            ex=int(self.config.timeout)
                        )
                        
                        # 更新本地锁信息
                        if self.lock_info:
                            self.lock_info.reentrant_count = lock_data['reentrant_count']
                        else:
                            self.lock_info = LockInfo(
                                key=self.key,
                                owner=self.owner_id,
                                lock_type=LockType.REENTRANT,
                                acquired_at=lock_data['acquired_at'],
                                expires_at=lock_data['expires_at'],
                                reentrant_count=lock_data['reentrant_count'],
                                thread_id=threading.get_ident(),
                                process_id=threading.current_thread().ident
                            )
                        
                        logger.debug(f"重入锁成功: {self.key}, 重入次数: {lock_data['reentrant_count']}")
                        return True
                    else:
                        # 被其他进程持有，等待
                        await asyncio.sleep(self.config.retry_delay)
                        retries += 1
                        continue
                
                # 首次获取锁
                expires_at = current_time + self.config.timeout
                lock_data = {
                    'owner': self.owner_id,
                    'type': LockType.REENTRANT.value,
                    'acquired_at': current_time,
                    'expires_at': expires_at,
                    'reentrant_count': 1,
                    'thread_id': threading.get_ident(),
                    'process_id': threading.current_thread().ident
                }
                
                # 使用SET NX EX命令原子性设置锁
                success = await self.redis_manager.set(
                    redis_key,
                    json.dumps(lock_data),
                    nx=True,
                    ex=int(self.config.timeout)
                )
                
                if success:
                    # 获取锁成功
                    self.lock_info = LockInfo(
                        key=self.key,
                        owner=self.owner_id,
                        lock_type=LockType.REENTRANT,
                        acquired_at=current_time,
                        expires_at=expires_at,
                        reentrant_count=1,
                        thread_id=threading.get_ident(),
                        process_id=threading.current_thread().ident
                    )
                    
                    # 启动续期和看门狗任务
                    await self._start_renewal_task()
                    await self._start_watchdog_task()
                    
                    logger.debug(f"获取可重入锁成功: {self.key}")
                    return True
                
                # 获取锁失败，重试
                await asyncio.sleep(self.config.retry_delay)
                retries += 1
                
            except Exception as e:
                logger.error(f"获取锁异常: {self.key}, 错误: {e}")
                retries += 1
                await asyncio.sleep(self.config.retry_delay)
        
        return False
    
    async def release(self) -> bool:
        """释放可重入锁"""
        if not self.lock_info:
            logger.warning(f"锁未持有，无法释放: {self.key}")
            return False
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        redis_key = self._get_redis_key()
        
        try:
            # 使用Lua脚本确保只有锁持有者才能释放锁
            lua_script = """
            local key = KEYS[1]
            local owner = ARGV[1]
            
            local lock_data = redis.call('GET', key)
            if lock_data then
                local lock_info = cjson.decode(lock_data)
                if lock_info.owner == owner then
                    lock_info.reentrant_count = lock_info.reentrant_count - 1
                    
                    if lock_info.reentrant_count <= 0 then
                        return redis.call('DEL', key)
                    else
                        redis.call('SET', key, cjson.encode(lock_info))
                        return 1
                    end
                end
            end
            return 0
            """
            
            result = await self.redis_manager.eval(
                lua_script,
                1,
                redis_key,
                self.owner_id
            )
            
            if result >= 1:
                # 更新本地锁信息
                self.lock_info.reentrant_count -= 1
                
                if self.lock_info.reentrant_count <= 0:
                    # 完全释放锁
                    await self._stop_renewal_task()
                    await self._stop_watchdog_task()
                    self.lock_info = None
                    logger.debug(f"完全释放可重入锁: {self.key}")
                else:
                    logger.debug(f"部分释放可重入锁: {self.key}, 剩余重入次数: {self.lock_info.reentrant_count}")
                
                return True
            else:
                logger.warning(f"释放锁失败，可能已被其他进程持有: {self.key}")
                return False
                
        except Exception as e:
            logger.error(f"释放锁异常: {self.key}, 错误: {e}")
            return False
    
    async def is_locked(self) -> bool:
        """检查锁是否被持有"""
        if not self.redis_manager:
            return self.lock_info is not None
        
        redis_key = self._get_redis_key()
        
        try:
            lock_data = await self.redis_manager.get(redis_key)
            return lock_data is not None
        except Exception as e:
            logger.error(f"检查锁状态异常: {self.key}, 错误: {e}")
            return False
    
    async def extend(self, timeout: Optional[float] = None) -> bool:
        """延长锁的持有时间"""
        if not self.lock_info:
            logger.warning(f"锁未持有，无法延长: {self.key}")
            return False
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        if timeout is None:
            timeout = self.config.timeout
        
        redis_key = self._get_redis_key()
        
        try:
            # 使用Lua脚本确保只有锁持有者才能延长锁
            lua_script = """
            local key = KEYS[1]
            local owner = ARGV[1]
            local timeout = tonumber(ARGV[2])
            
            local lock_data = redis.call('GET', key)
            if lock_data then
                local lock_info = cjson.decode(lock_data)
                if lock_info.owner == owner then
                    local current_time = tonumber(ARGV[3])
                    lock_info.expires_at = current_time + timeout
                    redis.call('SET', key, cjson.encode(lock_info))
                    redis.call('EXPIRE', key, timeout)
                    return 1
                end
            end
            return 0
            """
            
            current_time = time.time()
            result = await self.redis_manager.eval(
                lua_script,
                1,
                redis_key,
                self.owner_id,
                timeout,
                current_time
            )
            
            if result == 1:
                # 更新本地锁信息
                self.lock_info.expires_at = current_time + timeout
                logger.debug(f"延长锁成功: {self.key}")
                return True
            else:
                logger.warning(f"延长锁失败，可能已被其他进程持有: {self.key}")
                return False
                
        except Exception as e:
            logger.error(f"延长锁异常: {self.key}, 错误: {e}")
            return False


class ReadWriteLock:
    """读写锁实现"""
    
    def __init__(self, key: str, config: LockConfig, redis_manager=None):
        self.key = key
        self.config = config
        self.redis_manager = redis_manager
        self.read_lock = SharedLock(f"{key}:read", config, redis_manager)
        self.write_lock = ExclusiveLock(f"{key}:write", config, redis_manager)
    
    async def acquire_read(self, timeout: Optional[float] = None) -> bool:
        """获取读锁"""
        return await self.read_lock.acquire(timeout)
    
    async def acquire_write(self, timeout: Optional[float] = None) -> bool:
        """获取写锁"""
        return await self.write_lock.acquire(timeout)
    
    async def release_read(self) -> bool:
        """释放读锁"""
        return await self.read_lock.release()
    
    async def release_write(self) -> bool:
        """释放写锁"""
        return await self.write_lock.release()
    
    @asynccontextmanager
    async def read_context(self, timeout: Optional[float] = None):
        """读锁上下文管理器"""
        async with self.read_lock:
            yield
    
    @asynccontextmanager
    async def write_context(self, timeout: Optional[float] = None):
        """写锁上下文管理器"""
        async with self.write_lock:
            yield


class SharedLock(BaseLock):
    """共享锁实现"""
    
    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """获取共享锁"""
        if timeout is None:
            timeout = self.config.timeout
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        start_time = time.time()
        redis_key = self._get_redis_key()
        
        retries = 0
        while retries < self.config.max_retries:
            try:
                current_time = time.time()
                
                # 检查超时
                if current_time - start_time > timeout:
                    raise LockTimeoutError(f"获取锁超时: {self.key}")
                
                # 检查是否存在写锁
                write_lock_key = f"{self.config.lock_prefix}:{self.key}:write"
                write_lock_exists = await self.redis_manager.exists(write_lock_key)
                
                if write_lock_exists:
                    # 存在写锁，等待
                    await asyncio.sleep(self.config.retry_delay)
                    retries += 1
                    continue
                
                # 增加读锁计数
                lua_script = """
                local key = KEYS[1]
                local owner = ARGV[1]
                local timeout = tonumber(ARGV[2])
                local current_time = tonumber(ARGV[3])
                
                local count = redis.call('INCR', key)
                redis.call('EXPIRE', key, timeout)
                
                -- 记录读锁持有者
                local owner_key = key .. ':owners'
                redis.call('HSET', owner_key, owner, current_time)
                redis.call('EXPIRE', owner_key, timeout)
                
                return count
                """
                
                result = await self.redis_manager.eval(
                    lua_script,
                    1,
                    redis_key,
                    self.owner_id,
                    int(self.config.timeout),
                    current_time
                )
                
                if result:
                    # 获取锁成功
                    self.lock_info = LockInfo(
                        key=self.key,
                        owner=self.owner_id,
                        lock_type=LockType.SHARED,
                        acquired_at=current_time,
                        expires_at=current_time + self.config.timeout,
                        reentrant_count=1,
                        thread_id=threading.get_ident(),
                        process_id=threading.current_thread().ident
                    )
                    
                    # 启动续期和看门狗任务
                    await self._start_renewal_task()
                    await self._start_watchdog_task()
                    
                    logger.debug(f"获取共享锁成功: {self.key}, 读锁数量: {result}")
                    return True
                
                # 获取锁失败，重试
                await asyncio.sleep(self.config.retry_delay)
                retries += 1
                
            except Exception as e:
                logger.error(f"获取锁异常: {self.key}, 错误: {e}")
                retries += 1
                await asyncio.sleep(self.config.retry_delay)
        
        return False
    
    async def release(self) -> bool:
        """释放共享锁"""
        if not self.lock_info:
            logger.warning(f"锁未持有，无法释放: {self.key}")
            return False
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        # 停止续期和看门狗任务
        await self._stop_renewal_task()
        await self._stop_watchdog_task()
        
        redis_key = self._get_redis_key()
        
        try:
            # 使用Lua脚本减少读锁计数
            lua_script = """
            local key = KEYS[1]
            local owner = ARGV[1]
            
            local owner_key = key .. ':owners'
            local owner_exists = redis.call('HEXISTS', owner_key, owner)
            
            if owner_exists == 1 then
                redis.call('HDEL', owner_key, owner)
                local count = redis.call('DECR', key)
                
                if count <= 0 then
                    redis.call('DEL', key)
                    redis.call('DEL', owner_key)
                end
                
                return count
            end
            
            return -1
            """
            
            result = await self.redis_manager.eval(
                lua_script,
                1,
                redis_key,
                self.owner_id
            )
            
            if result >= 0:
                logger.debug(f"释放共享锁成功: {self.key}, 剩余读锁数量: {result}")
                self.lock_info = None
                return True
            else:
                logger.warning(f"释放锁失败，可能已被其他进程持有: {self.key}")
                return False
                
        except Exception as e:
            logger.error(f"释放锁异常: {self.key}, 错误: {e}")
            return False
    
    async def is_locked(self) -> bool:
        """检查锁是否被持有"""
        if not self.redis_manager:
            return self.lock_info is not None
        
        redis_key = self._get_redis_key()
        
        try:
            count = await self.redis_manager.get(redis_key)
            return count is not None and int(count) > 0
        except Exception as e:
            logger.error(f"检查锁状态异常: {self.key}, 错误: {e}")
            return False
    
    async def extend(self, timeout: Optional[float] = None) -> bool:
        """延长锁的持有时间"""
        if not self.lock_info:
            logger.warning(f"锁未持有，无法延长: {self.key}")
            return False
        
        if not self.redis_manager:
            logger.warning("Redis管理器未配置，使用本地锁（非分布式）")
            return True
        
        if timeout is None:
            timeout = self.config.timeout
        
        redis_key = self._get_redis_key()
        
        try:
            # 延长锁的过期时间
            await self.redis_manager.expire(redis_key, int(timeout))
            
            # 延长持有者记录的过期时间
            owner_key = f"{redis_key}:owners"
            await self.redis_manager.expire(owner_key, int(timeout))
            
            # 更新本地锁信息
            self.lock_info.expires_at = time.time() + timeout
            logger.debug(f"延长锁成功: {self.key}")
            return True
            
        except Exception as e:
            logger.error(f"延长锁异常: {self.key}, 错误: {e}")
            return False


class DistributedLock:
    """分布式锁工厂类"""
    
    def __init__(self, key: str, config: LockConfig = None, redis_manager=None):
        self.key = key
        self.config = config or LockConfig()
        self.redis_manager = redis_manager
    
    def exclusive_lock(self) -> ExclusiveLock:
        """创建排他锁"""
        return ExclusiveLock(self.key, self.config, self.redis_manager)
    
    def reentrant_lock(self) -> ReentrantLock:
        """创建可重入锁"""
        return ReentrantLock(self.key, self.config, self.redis_manager)
    
    def shared_lock(self) -> SharedLock:
        """创建共享锁"""
        return SharedLock(self.key, self.config, self.redis_manager)
    
    def read_write_lock(self) -> ReadWriteLock:
        """创建读写锁"""
        return ReadWriteLock(self.key, self.config, self.redis_manager)


# 默认配置实例
default_config = LockConfig()

# 默认Redis管理器
_default_redis_manager = None


def set_default_redis_manager(redis_manager):
    """设置默认Redis管理器"""
    global _default_redis_manager
    _default_redis_manager = redis_manager


def get_default_redis_manager():
    """获取默认Redis管理器"""
    return _default_redis_manager


# 便捷函数
def create_lock(key: str, lock_type: LockType = LockType.EXCLUSIVE,
                config: LockConfig = None, redis_manager=None) -> BaseLock:
    """创建锁的便捷函数"""
    if config is None:
        config = default_config
    
    if redis_manager is None:
        redis_manager = get_default_redis_manager()
    
    lock_factory = DistributedLock(key, config, redis_manager)
    
    if lock_type == LockType.EXCLUSIVE:
        return lock_factory.exclusive_lock()
    elif lock_type == LockType.REENTRANT:
        return lock_factory.reentrant_lock()
    elif lock_type == LockType.SHARED:
        return lock_factory.shared_lock()
    else:
        return lock_factory.exclusive_lock()


@asynccontextmanager
async def distributed_lock(key: str, lock_type: LockType = LockType.EXCLUSIVE,
                          timeout: Optional[float] = None,
                          config: LockConfig = None, redis_manager=None):
    """分布式锁上下文管理器"""
    lock = create_lock(key, lock_type, config, redis_manager)
    
    try:
        success = await lock.acquire(timeout)
        if not success:
            raise LockTimeoutError(f"无法获取锁: {key}")
        yield lock
    finally:
        await lock.release()


# 锁装饰器
def distributed_lock_decorator(key: str, lock_type: LockType = LockType.EXCLUSIVE,
                              timeout: Optional[float] = None,
                              config: LockConfig = None, redis_manager=None):
    """分布式锁装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            async with distributed_lock(key, lock_type, timeout, config, redis_manager):
                return await func(*args, **kwargs)
        return wrapper
    return decorator