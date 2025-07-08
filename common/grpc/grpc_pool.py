"""
gRPC连接池管理模块

该模块实现了高性能的gRPC连接池，支持连接复用、自动扩容、健康检查等功能。
提供多服务地址的连接池管理，支持负载均衡和故障转移。
"""

import asyncio
import time
import random
from typing import Dict, List, Optional, Set, Callable, Any, Union
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from .connection import GrpcConnection, ConnectionConfig, ConnectionState
from .exceptions import (
    GrpcPoolExhaustedError,
    GrpcConnectionError,
    GrpcConfigError,
    handle_async_grpc_exception
)


@dataclass
class PoolConfig:
    """连接池配置类"""
    # 连接池大小配置
    min_size: int = 2                       # 最小连接数
    max_size: int = 20                      # 最大连接数
    
    # 超时配置
    acquire_timeout: float = 30.0           # 获取连接超时
    idle_timeout: float = 300.0             # 连接空闲超时(秒)
    max_lifetime: float = 3600.0            # 连接最大生存时间(秒)
    
    # 健康检查配置
    health_check_interval: float = 60.0     # 健康检查间隔(秒)
    enable_health_check: bool = True        # 启用健康检查
    
    # 连接池行为配置
    enable_preconnect: bool = True          # 启用预连接
    enable_auto_scaling: bool = True        # 启用自动扩缩容
    scale_up_threshold: float = 0.8         # 扩容阈值(使用率)
    scale_down_threshold: float = 0.3       # 缩容阈值(使用率)
    scale_check_interval: float = 30.0      # 扩缩容检查间隔(秒)
    
    # 清理配置
    cleanup_interval: float = 120.0         # 清理间隔(秒)
    enable_auto_cleanup: bool = True        # 启用自动清理
    
    # 统计配置
    enable_metrics: bool = True             # 启用指标收集


@dataclass 
class PoolStats:
    """连接池统计信息"""
    # 基本统计
    total_connections: int = 0              # 总连接数
    active_connections: int = 0             # 活跃连接数
    idle_connections: int = 0               # 空闲连接数
    
    # 操作统计
    total_acquired: int = 0                 # 总获取次数
    total_released: int = 0                 # 总释放次数
    total_created: int = 0                  # 总创建次数
    total_destroyed: int = 0                # 总销毁次数
    
    # 性能统计
    acquire_failures: int = 0               # 获取失败次数
    acquire_timeouts: int = 0               # 获取超时次数
    connection_failures: int = 0            # 连接失败次数
    
    # 队列统计
    max_queue_size: int = 0                 # 最大队列长度
    current_queue_size: int = 0             # 当前队列长度
    
    # 时间统计
    avg_acquire_time: float = 0.0           # 平均获取时间
    max_acquire_time: float = 0.0           # 最大获取时间
    
    # 扩缩容统计
    scale_up_count: int = 0                 # 扩容次数
    scale_down_count: int = 0               # 缩容次数
    
    # 运行时统计
    created_at: float = field(default_factory=time.time)
    last_reset_at: float = field(default_factory=time.time)
    
    def reset(self):
        """重置统计信息"""
        self.total_acquired = 0
        self.total_released = 0
        self.acquire_failures = 0
        self.acquire_timeouts = 0
        self.connection_failures = 0
        self.scale_up_count = 0
        self.scale_down_count = 0
        self.avg_acquire_time = 0.0
        self.max_acquire_time = 0.0
        self.last_reset_at = time.time()
    
    @property
    def success_rate(self) -> float:
        """获取成功率"""
        if self.total_acquired == 0:
            return 1.0
        return (self.total_acquired - self.acquire_failures) / self.total_acquired
    
    @property
    def utilization_rate(self) -> float:
        """获取使用率"""
        if self.total_connections == 0:
            return 0.0
        return self.active_connections / self.total_connections
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total_connections': self.total_connections,
            'active_connections': self.active_connections,
            'idle_connections': self.idle_connections,
            'total_acquired': self.total_acquired,
            'total_released': self.total_released,
            'total_created': self.total_created,
            'total_destroyed': self.total_destroyed,
            'acquire_failures': self.acquire_failures,
            'acquire_timeouts': self.acquire_timeouts,
            'connection_failures': self.connection_failures,
            'current_queue_size': self.current_queue_size,
            'max_queue_size': self.max_queue_size,
            'avg_acquire_time': self.avg_acquire_time,
            'max_acquire_time': self.max_acquire_time,
            'scale_up_count': self.scale_up_count,
            'scale_down_count': self.scale_down_count,
            'success_rate': self.success_rate,
            'utilization_rate': self.utilization_rate,
            'uptime': time.time() - self.created_at
        }


class PooledConnection:
    """池化连接包装器"""
    
    def __init__(self, connection: GrpcConnection, pool: 'GrpcConnectionPool'):
        self._connection = connection
        self._pool = pool
        self._acquired_at = time.time()
        self._in_use = True
    
    @property
    def connection(self) -> GrpcConnection:
        """获取原始连接"""
        return self._connection
    
    @property
    def channel(self):
        """获取gRPC channel"""
        return self._connection.channel
    
    @property
    def endpoint(self) -> str:
        """获取端点地址"""
        return self._connection.endpoint
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connection.is_connected
    
    @property
    def usage_time(self) -> float:
        """使用时间"""
        return time.time() - self._acquired_at
    
    async def release(self):
        """释放连接回池"""
        if self._in_use:
            self._in_use = False
            await self._pool._release_connection(self)


class GrpcConnectionPool:
    """gRPC连接池"""
    
    def __init__(
        self,
        connection_config: ConnectionConfig,
        pool_config: PoolConfig,
        name: Optional[str] = None
    ):
        """
        初始化连接池
        
        Args:
            connection_config: 连接配置
            pool_config: 池配置
            name: 池名称
        """
        self._connection_config = connection_config
        self._pool_config = pool_config
        self._name = name or f"pool_{connection_config.endpoint}"
        
        # 连接管理
        self._connections: Set[GrpcConnection] = set()
        self._idle_connections: asyncio.Queue = asyncio.Queue()
        self._active_connections: Set[PooledConnection] = set()
        
        # 等待队列
        self._waiting_queue: asyncio.Queue = asyncio.Queue()
        
        # 同步锁
        self._lock = asyncio.Lock()
        self._acquiring_lock = asyncio.Lock()
        
        # 统计信息
        self._stats = PoolStats()
        
        # 后台任务
        self._health_check_task: Optional[asyncio.Task] = None
        self._scaling_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # 状态标志
        self._initialized = False
        self._closed = False
        
        # 事件回调
        self._on_connection_created: Optional[Callable[[GrpcConnection], None]] = None
        self._on_connection_destroyed: Optional[Callable[[GrpcConnection], None]] = None
        self._on_pool_exhausted: Optional[Callable[[], None]] = None
    
    @property
    def name(self) -> str:
        """获取池名称"""
        return self._name
    
    @property
    def stats(self) -> PoolStats:
        """获取统计信息"""
        return self._stats
    
    @property
    def size(self) -> int:
        """获取池大小"""
        return len(self._connections)
    
    @property
    def active_count(self) -> int:
        """获取活跃连接数"""
        return len(self._active_connections)
    
    @property
    def idle_count(self) -> int:
        """获取空闲连接数"""
        return self._idle_connections.qsize()
    
    @property
    def waiting_count(self) -> int:
        """获取等待获取连接的请求数"""
        return self._waiting_queue.qsize()
    
    @property
    def is_exhausted(self) -> bool:
        """是否已耗尽"""
        return (
            self.size >= self._pool_config.max_size and 
            self.idle_count == 0
        )
    
    def set_event_callbacks(
        self,
        on_connection_created: Optional[Callable[[GrpcConnection], None]] = None,
        on_connection_destroyed: Optional[Callable[[GrpcConnection], None]] = None,
        on_pool_exhausted: Optional[Callable[[], None]] = None
    ):
        """设置事件回调"""
        self._on_connection_created = on_connection_created
        self._on_connection_destroyed = on_connection_destroyed
        self._on_pool_exhausted = on_pool_exhausted
    
    @handle_async_grpc_exception
    async def initialize(self):
        """初始化连接池"""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                # 创建最小数量的连接
                if self._pool_config.enable_preconnect:
                    await self._create_min_connections()
                
                # 启动后台任务
                if self._pool_config.enable_health_check:
                    self._start_health_check()
                
                if self._pool_config.enable_auto_scaling:
                    self._start_scaling_monitor()
                
                if self._pool_config.enable_auto_cleanup:
                    self._start_cleanup_monitor()
                
                self._initialized = True
                
            except Exception as e:
                raise GrpcConfigError(
                    message=f"连接池初始化失败: {str(e)}",
                    config_key="pool_initialization",
                    cause=e
                )
    
    async def _create_min_connections(self):
        """创建最小数量的连接"""
        for _ in range(self._pool_config.min_size):
            try:
                connection = await self._create_connection()
                await self._idle_connections.put(connection)
            except Exception:
                # 如果创建连接失败，记录统计但不抛出异常
                self._stats.connection_failures += 1
    
    async def _create_connection(self) -> GrpcConnection:
        """创建新连接"""
        connection = GrpcConnection(
            config=self._connection_config,
            on_state_change=self._on_connection_state_change
        )
        
        await connection.connect()
        
        async with self._lock:
            self._connections.add(connection)
            self._stats.total_created += 1
            self._stats.total_connections = len(self._connections)
        
        # 触发创建回调
        if self._on_connection_created:
            try:
                self._on_connection_created(connection)
            except Exception:
                pass
        
        return connection
    
    def _on_connection_state_change(self, state: ConnectionState):
        """连接状态变化回调"""
        if state == ConnectionState.TRANSIENT_FAILURE:
            self._stats.connection_failures += 1
    
    @handle_async_grpc_exception
    async def acquire(self, timeout: Optional[float] = None) -> PooledConnection:
        """
        获取连接
        
        Args:
            timeout: 获取超时时间
            
        Returns:
            PooledConnection: 池化连接
        """
        if self._closed:
            raise GrpcPoolExhaustedError(
                message="连接池已关闭",
                pool_size=self.size
            )
        
        if not self._initialized:
            await self.initialize()
        
        acquire_timeout = timeout or self._pool_config.acquire_timeout
        start_time = time.time()
        
        try:
            async with self._acquiring_lock:
                # 更新等待队列统计
                self._stats.current_queue_size = self.waiting_count + 1
                self._stats.max_queue_size = max(
                    self._stats.max_queue_size, 
                    self._stats.current_queue_size
                )
                
                try:
                    connection = await asyncio.wait_for(
                        self._acquire_connection(),
                        timeout=acquire_timeout
                    )
                    
                    # 创建池化连接
                    pooled_conn = PooledConnection(connection, self)
                    
                    async with self._lock:
                        self._active_connections.add(pooled_conn)
                        self._stats.total_acquired += 1
                        self._stats.active_connections = len(self._active_connections)
                        self._stats.idle_connections = self.idle_count
                    
                    # 更新获取时间统计
                    acquire_time = time.time() - start_time
                    self._update_acquire_time_stats(acquire_time)
                    
                    return pooled_conn
                    
                except asyncio.TimeoutError:
                    self._stats.acquire_timeouts += 1
                    
                    # 触发池耗尽回调
                    if self._on_pool_exhausted:
                        try:
                            self._on_pool_exhausted()
                        except Exception:
                            pass
                    
                    raise GrpcPoolExhaustedError(
                        message=f"获取连接超时: {acquire_timeout}秒",
                        pool_size=self.size,
                        active_connections=self.active_count,
                        waiting_requests=self.waiting_count
                    )
                finally:
                    self._stats.current_queue_size = max(0, self._stats.current_queue_size - 1)
        
        except Exception as e:
            self._stats.acquire_failures += 1
            if isinstance(e, GrpcPoolExhaustedError):
                raise
            
            raise GrpcConnectionError(
                message=f"获取连接失败: {str(e)}",
                endpoint=self._connection_config.endpoint,
                cause=e
            )
    
    async def _acquire_connection(self) -> GrpcConnection:
        """内部获取连接逻辑"""
        # 尝试从空闲队列获取连接
        try:
            connection = self._idle_connections.get_nowait()
            
            # 检查连接是否有效
            if await self._is_connection_valid(connection):
                return connection
            else:
                # 连接无效，销毁并重新创建
                await self._destroy_connection(connection)
        except asyncio.QueueEmpty:
            pass
        
        # 如果没有空闲连接且未达到最大连接数，创建新连接
        if self.size < self._pool_config.max_size:
            return await self._create_connection()
        
        # 等待连接释放
        connection = await self._idle_connections.get()
        
        # 再次检查连接有效性
        if await self._is_connection_valid(connection):
            return connection
        else:
            await self._destroy_connection(connection)
            # 递归重试
            return await self._acquire_connection()
    
    async def _is_connection_valid(self, connection: GrpcConnection) -> bool:
        """检查连接是否有效"""
        try:
            # 检查连接状态
            if not connection.is_connected:
                return False
            
            # 检查空闲超时
            if connection.stats.idle_time > self._pool_config.idle_timeout:
                return False
            
            # 检查最大生存时间
            if connection.stats.uptime > self._pool_config.max_lifetime:
                return False
            
            return True
            
        except Exception:
            return False
    
    async def _release_connection(self, pooled_conn: PooledConnection):
        """释放连接回池"""
        connection = pooled_conn.connection
        
        async with self._lock:
            # 从活跃集合中移除
            self._active_connections.discard(pooled_conn)
            
            # 检查连接是否仍然有效
            if await self._is_connection_valid(connection):
                # 放回空闲队列
                await self._idle_connections.put(connection)
            else:
                # 连接无效，销毁
                await self._destroy_connection(connection)
            
            # 更新统计
            self._stats.total_released += 1
            self._stats.active_connections = len(self._active_connections)
            self._stats.idle_connections = self.idle_count
    
    async def _destroy_connection(self, connection: GrpcConnection):
        """销毁连接"""
        try:
            # 断开连接
            await connection.disconnect()
            
            async with self._lock:
                # 从连接集合中移除
                self._connections.discard(connection)
                self._stats.total_destroyed += 1
                self._stats.total_connections = len(self._connections)
            
            # 触发销毁回调
            if self._on_connection_destroyed:
                try:
                    self._on_connection_destroyed(connection)
                except Exception:
                    pass
                    
        except Exception:
            pass  # 忽略销毁异常
    
    def _update_acquire_time_stats(self, acquire_time: float):
        """更新获取时间统计"""
        if self._stats.avg_acquire_time == 0:
            self._stats.avg_acquire_time = acquire_time
        else:
            # 简单的移动平均
            self._stats.avg_acquire_time = (
                self._stats.avg_acquire_time * 0.9 + acquire_time * 0.1
            )
        
        self._stats.max_acquire_time = max(
            self._stats.max_acquire_time, 
            acquire_time
        )
    
    def _start_health_check(self):
        """启动健康检查任务"""
        if self._health_check_task is None or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def _health_check_loop(self):
        """健康检查循环"""
        try:
            while not self._closed:
                await asyncio.sleep(self._pool_config.health_check_interval)
                await self._perform_health_check()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略健康检查异常
    
    async def _perform_health_check(self):
        """执行健康检查"""
        unhealthy_connections = []
        
        # 检查所有连接
        for connection in list(self._connections):
            try:
                if not await self._is_connection_valid(connection):
                    unhealthy_connections.append(connection)
            except Exception:
                unhealthy_connections.append(connection)
        
        # 销毁不健康的连接
        for connection in unhealthy_connections:
            await self._destroy_connection(connection)
    
    def _start_scaling_monitor(self):
        """启动扩缩容监控任务"""
        if self._scaling_task is None or self._scaling_task.done():
            self._scaling_task = asyncio.create_task(self._scaling_loop())
    
    async def _scaling_loop(self):
        """扩缩容循环"""
        try:
            while not self._closed:
                await asyncio.sleep(self._pool_config.scale_check_interval)
                await self._check_scaling()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略扩缩容异常
    
    async def _check_scaling(self):
        """检查是否需要扩缩容"""
        utilization = self._stats.utilization_rate
        
        # 检查是否需要扩容
        if (utilization > self._pool_config.scale_up_threshold and
            self.size < self._pool_config.max_size):
            await self._scale_up()
        
        # 检查是否需要缩容
        elif (utilization < self._pool_config.scale_down_threshold and
              self.size > self._pool_config.min_size):
            await self._scale_down()
    
    async def _scale_up(self):
        """扩容"""
        try:
            # 创建新连接
            connection = await self._create_connection()
            await self._idle_connections.put(connection)
            self._stats.scale_up_count += 1
        except Exception:
            self._stats.connection_failures += 1
    
    async def _scale_down(self):
        """缩容"""
        try:
            # 获取一个空闲连接并销毁
            connection = self._idle_connections.get_nowait()
            await self._destroy_connection(connection)
            self._stats.scale_down_count += 1
        except asyncio.QueueEmpty:
            pass  # 没有空闲连接可以缩容
    
    def _start_cleanup_monitor(self):
        """启动清理监控任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def _cleanup_loop(self):
        """清理循环"""
        try:
            while not self._closed:
                await asyncio.sleep(self._pool_config.cleanup_interval)
                await self._perform_cleanup()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略清理异常
    
    async def _perform_cleanup(self):
        """执行清理操作"""
        # 清理过期的空闲连接
        expired_connections = []
        
        # 检查空闲队列中的连接
        temp_connections = []
        while not self._idle_connections.empty():
            try:
                connection = self._idle_connections.get_nowait()
                if await self._is_connection_valid(connection):
                    temp_connections.append(connection)
                else:
                    expired_connections.append(connection)
            except asyncio.QueueEmpty:
                break
        
        # 将有效连接放回队列
        for connection in temp_connections:
            await self._idle_connections.put(connection)
        
        # 销毁过期连接
        for connection in expired_connections:
            await self._destroy_connection(connection)
    
    @asynccontextmanager
    async def get_connection(self, timeout: Optional[float] = None):
        """
        获取连接的上下文管理器
        
        Args:
            timeout: 获取超时时间
        """
        pooled_conn = await self.acquire(timeout)
        try:
            yield pooled_conn
        finally:
            await pooled_conn.release()
    
    async def close(self):
        """关闭连接池"""
        if self._closed:
            return
        
        self._closed = True
        
        # 停止后台任务
        tasks = [
            self._health_check_task,
            self._scaling_task,
            self._cleanup_task
        ]
        
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 关闭所有连接
        connections_to_close = list(self._connections)
        for connection in connections_to_close:
            await self._destroy_connection(connection)
        
        # 清空队列
        while not self._idle_connections.empty():
            try:
                self._idle_connections.get_nowait()
            except asyncio.QueueEmpty:
                break
    
    def get_stats_dict(self) -> Dict[str, Any]:
        """获取统计信息字典"""
        stats_dict = self._stats.to_dict()
        stats_dict.update({
            'pool_name': self._name,
            'endpoint': self._connection_config.endpoint,
            'pool_config': {
                'min_size': self._pool_config.min_size,
                'max_size': self._pool_config.max_size,
                'acquire_timeout': self._pool_config.acquire_timeout,
                'idle_timeout': self._pool_config.idle_timeout,
                'max_lifetime': self._pool_config.max_lifetime
            },
            'is_closed': self._closed,
            'is_initialized': self._initialized
        })
        return stats_dict


# 连接池管理器
class GrpcConnectionPoolManager:
    """gRPC连接池管理器"""
    
    def __init__(self):
        self._pools: Dict[str, GrpcConnectionPool] = {}
        self._lock = asyncio.Lock()
    
    async def create_pool(
        self,
        name: str,
        connection_config: ConnectionConfig,
        pool_config: Optional[PoolConfig] = None
    ) -> GrpcConnectionPool:
        """
        创建连接池
        
        Args:
            name: 池名称
            connection_config: 连接配置
            pool_config: 池配置
            
        Returns:
            GrpcConnectionPool: 连接池实例
        """
        if pool_config is None:
            pool_config = PoolConfig()
        
        async with self._lock:
            if name in self._pools:
                raise GrpcConfigError(
                    message=f"连接池已存在: {name}",
                    config_key="pool_name",
                    config_value=name
                )
            
            pool = GrpcConnectionPool(connection_config, pool_config, name)
            await pool.initialize()
            self._pools[name] = pool
            return pool
    
    async def get_pool(self, name: str) -> Optional[GrpcConnectionPool]:
        """获取连接池"""
        return self._pools.get(name)
    
    async def remove_pool(self, name: str) -> bool:
        """移除连接池"""
        async with self._lock:
            pool = self._pools.pop(name, None)
            if pool:
                await pool.close()
                return True
            return False
    
    async def close_all(self):
        """关闭所有连接池"""
        async with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        
        # 并行关闭所有池
        if pools:
            await asyncio.gather(
                *[pool.close() for pool in pools],
                return_exceptions=True
            )
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有池的统计信息"""
        return {
            name: pool.get_stats_dict() 
            for name, pool in self._pools.items()
        }
    
    @property
    def pool_names(self) -> List[str]:
        """获取所有池名称"""
        return list(self._pools.keys())


# 全局连接池管理器实例
_pool_manager = GrpcConnectionPoolManager()


# 便捷函数
async def create_pool(
    name: str,
    target: str,
    port: Optional[int] = None,
    **kwargs
) -> GrpcConnectionPool:
    """
    创建连接池的便捷函数
    
    Args:
        name: 池名称
        target: 目标地址
        port: 端口号
        **kwargs: 其他配置参数
    """
    # 分离连接配置和池配置
    connection_kwargs = {}
    pool_kwargs = {}
    
    connection_fields = {
        'use_ssl', 'connect_timeout', 'request_timeout', 'keepalive_time_ms',
        'keepalive_timeout_ms', 'keepalive_permit_without_calls',
        'http2_max_pings_without_data', 'http2_min_time_between_pings_ms',
        'http2_min_ping_interval_without_data_ms', 'max_receive_message_length',
        'max_send_message_length', 'enable_reconnect', 'max_reconnect_attempts',
        'reconnect_backoff_base', 'reconnect_backoff_max', 'ssl_cert_file',
        'ssl_key_file', 'ssl_ca_file', 'ssl_verify_hostname', 'compression',
        'user_agent', 'metadata'
    }
    
    for key, value in kwargs.items():
        if key in connection_fields:
            connection_kwargs[key] = value
        else:
            pool_kwargs[key] = value
    
    connection_config = ConnectionConfig(
        target=target,
        port=port,
        **connection_kwargs
    )
    
    pool_config = PoolConfig(**pool_kwargs)
    
    return await _pool_manager.create_pool(name, connection_config, pool_config)


async def get_pool(name: str) -> Optional[GrpcConnectionPool]:
    """获取连接池"""
    return await _pool_manager.get_pool(name)


async def close_all_pools():
    """关闭所有连接池"""
    await _pool_manager.close_all()


# 导出所有公共接口
__all__ = [
    'PoolConfig',
    'PoolStats', 
    'PooledConnection',
    'GrpcConnectionPool',
    'GrpcConnectionPoolManager',
    'create_pool',
    'get_pool',
    'close_all_pools'
]