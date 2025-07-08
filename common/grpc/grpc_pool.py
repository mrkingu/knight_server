"""
gRPC连接池管理模块

提供高性能的gRPC连接池，支持连接复用、自动扩缩容、健康检查、统计监控等功能。
连接池支持多个服务地址的管理，并提供连接负载均衡。
"""

import asyncio
import threading
import time
from typing import Dict, List, Optional, Set, Callable, Any, Union
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from ..logger import logger
from .connection import GrpcConnection, ConnectionConfig, ConnectionState
from .exceptions import (
    GrpcPoolExhaustedError,
    GrpcConnectionError,
    GrpcConfigurationError,
    handle_grpc_exception_async
)


@dataclass
class PoolConfig:
    """连接池配置类"""
    
    # 基本池配置
    min_connections: int = 2
    max_connections: int = 20
    
    # 获取连接的超时配置
    acquire_timeout: float = 10.0
    
    # 连接空闲超时（秒）
    idle_timeout: float = 300.0  # 5分钟
    
    # 连接生存时间（秒）
    max_lifetime: float = 3600.0  # 1小时
    
    # 健康检查配置
    health_check_interval: float = 30.0
    health_check_on_acquire: bool = True
    
    # 预热配置
    preload_connections: bool = True
    preload_count: int = 2
    
    # 统计和监控
    enable_stats: bool = True
    stats_interval: float = 60.0
    
    # 清理配置
    cleanup_interval: float = 60.0
    
    # 连接配置
    connection_config: ConnectionConfig = field(default_factory=ConnectionConfig)


@dataclass
class PoolStats:
    """连接池统计信息"""
    
    # 基本统计
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    pending_requests: int = 0
    
    # 请求统计
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_requests: int = 0
    
    # 性能统计
    total_acquire_time: float = 0.0
    max_acquire_time: float = 0.0
    min_acquire_time: float = float('inf')
    
    # 连接事件统计
    connections_created: int = 0
    connections_destroyed: int = 0
    connections_reused: int = 0
    
    # 时间戳
    created_time: float = field(default_factory=time.time)
    last_reset_time: float = field(default_factory=time.time)
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    @property
    def avg_acquire_time(self) -> float:
        """平均获取时间"""
        if self.successful_requests == 0:
            return 0.0
        return self.total_acquire_time / self.successful_requests
    
    @property
    def pool_utilization(self) -> float:
        """池利用率"""
        if self.total_connections == 0:
            return 0.0
        return self.active_connections / self.total_connections


class PooledConnection:
    """池化连接包装器"""
    
    def __init__(
        self, 
        connection: GrpcConnection, 
        pool: 'GrpcConnectionPool',
        acquired_time: Optional[float] = None
    ):
        """
        初始化池化连接
        
        Args:
            connection: gRPC连接
            pool: 连接池
            acquired_time: 获取时间
        """
        self.connection = connection
        self.pool = pool
        self.acquired_time = acquired_time or time.time()
        self.is_released = False
    
    async def release(self) -> None:
        """释放连接回池"""
        if not self.is_released:
            await self.pool.release(self)
            self.is_released = True
    
    def __getattr__(self, name):
        """代理连接方法"""
        return getattr(self.connection, name)
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.release()


class GrpcConnectionPool:
    """
    gRPC连接池类
    
    提供高性能的连接池管理，支持自动扩缩容、健康检查、连接复用等功能。
    线程安全，支持同时处理多个并发请求。
    """
    
    def __init__(
        self, 
        config: PoolConfig,
        pool_id: Optional[str] = None,
        connection_factory: Optional[Callable[[], GrpcConnection]] = None
    ):
        """
        初始化连接池
        
        Args:
            config: 池配置
            pool_id: 池ID
            connection_factory: 连接工厂函数
        """
        self.config = config
        self.pool_id = pool_id or f"pool_{id(self)}"
        self.connection_factory = connection_factory or self._default_connection_factory
        
        # 连接管理
        self._connections: Set[GrpcConnection] = set()
        self._idle_connections: deque[GrpcConnection] = deque()
        self._active_connections: Set[GrpcConnection] = set()
        self._pending_requests: deque[asyncio.Future] = deque()
        
        # 同步控制
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        
        # 状态管理
        self._closed = False
        self._initialized = False
        
        # 统计信息
        self.stats = PoolStats()
        
        # 后台任务
        self._health_check_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        
        logger.info(f"创建gRPC连接池: {self.pool_id}, 配置: {config}")
    
    def _default_connection_factory(self) -> GrpcConnection:
        """
        默认连接工厂
        
        Returns:
            GrpcConnection: 新的连接实例
        """
        return GrpcConnection(
            config=self.config.connection_config,
            connection_id=f"{self.pool_id}_conn_{len(self._connections)}",
            state_change_callback=self._on_connection_state_change
        )
    
    def _on_connection_state_change(self, connection: GrpcConnection, state: ConnectionState) -> None:
        """
        连接状态变化回调
        
        Args:
            connection: 连接对象
            state: 新状态
        """
        logger.debug(f"连接池 {self.pool_id} 中连接 {connection.connection_id} 状态变化: {state.value}")
        
        # 如果连接失败，从活跃连接中移除
        if state == ConnectionState.TRANSIENT_FAILURE:
            asyncio.create_task(self._handle_failed_connection(connection))
    
    async def _handle_failed_connection(self, connection: GrpcConnection) -> None:
        """
        处理失败的连接
        
        Args:
            connection: 失败的连接
        """
        async with self._lock:
            if connection in self._active_connections:
                self._active_connections.remove(connection)
            
            if connection in self._idle_connections:
                self._idle_connections.remove(connection)
            
            self.stats.failed_requests += 1
            
            logger.warning(f"连接池 {self.pool_id} 移除失败连接: {connection.connection_id}")
    
    async def initialize(self) -> None:
        """
        初始化连接池
        """
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                # 预创建最小连接数
                if self.config.preload_connections:
                    preload_count = min(self.config.preload_count, self.config.min_connections)
                    for _ in range(preload_count):
                        connection = await self._create_connection()
                        self._idle_connections.append(connection)
                
                # 启动后台任务
                self._start_background_tasks()
                
                self._initialized = True
                logger.info(f"连接池 {self.pool_id} 初始化完成")
                
            except Exception as e:
                logger.error(f"连接池 {self.pool_id} 初始化失败: {e}")
                raise GrpcConfigurationError(f"连接池初始化失败: {e}", cause=e)
    
    def _start_background_tasks(self) -> None:
        """启动后台任务"""
        
        # 健康检查任务
        if self.config.health_check_interval > 0:
            self._health_check_task = asyncio.create_task(
                self._health_check_loop()
            )
        
        # 清理任务
        if self.config.cleanup_interval > 0:
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop()
            )
        
        # 统计任务
        if self.config.enable_stats and self.config.stats_interval > 0:
            self._stats_task = asyncio.create_task(
                self._stats_loop()
            )
    
    async def _create_connection(self) -> GrpcConnection:
        """
        创建新连接
        
        Returns:
            GrpcConnection: 新连接
        """
        connection = self.connection_factory()
        await connection.connect()
        
        self._connections.add(connection)
        self.stats.connections_created += 1
        self.stats.total_connections += 1
        
        logger.debug(f"连接池 {self.pool_id} 创建新连接: {connection.connection_id}")
        return connection
    
    async def _destroy_connection(self, connection: GrpcConnection) -> None:
        """
        销毁连接
        
        Args:
            connection: 要销毁的连接
        """
        try:
            await connection.close()
        except Exception as e:
            logger.warning(f"关闭连接失败: {connection.connection_id}, 错误: {e}")
        
        # 从所有集合中移除
        self._connections.discard(connection)
        
        if connection in self._idle_connections:
            self._idle_connections.remove(connection)
        
        self._active_connections.discard(connection)
        
        self.stats.connections_destroyed += 1
        self.stats.total_connections = len(self._connections)
        
        logger.debug(f"连接池 {self.pool_id} 销毁连接: {connection.connection_id}")
    
    @handle_grpc_exception_async
    async def acquire(self, timeout: Optional[float] = None) -> PooledConnection:
        """
        获取连接
        
        Args:
            timeout: 超时时间，None使用配置默认值
            
        Returns:
            PooledConnection: 池化连接
            
        Raises:
            GrpcPoolExhaustedError: 连接池耗尽
            GrpcConnectionError: 连接失败
        """
        if not self._initialized:
            await self.initialize()
        
        if self._closed:
            raise GrpcConnectionError("连接池已关闭")
        
        acquire_timeout = timeout or self.config.acquire_timeout
        start_time = time.time()
        
        try:
            # 使用超时等待获取连接
            connection = await asyncio.wait_for(
                self._do_acquire(),
                timeout=acquire_timeout
            )
            
            acquire_time = time.time() - start_time
            self._update_acquire_stats(acquire_time, True)
            
            return PooledConnection(connection, self, start_time)
            
        except asyncio.TimeoutError:
            acquire_time = time.time() - start_time
            self._update_acquire_stats(acquire_time, False)
            self.stats.timeout_requests += 1
            
            raise GrpcPoolExhaustedError(
                f"获取连接超时: {acquire_timeout}秒",
                pool_size=len(self._connections),
                active_connections=len(self._active_connections),
                waiting_requests=len(self._pending_requests)
            )
    
    async def _do_acquire(self) -> GrpcConnection:
        """
        执行连接获取逻辑
        
        Returns:
            GrpcConnection: 可用连接
        """
        async with self._condition:
            while True:
                # 1. 尝试从空闲连接中获取
                connection = await self._try_get_idle_connection()
                if connection:
                    return connection
                
                # 2. 尝试创建新连接
                if len(self._connections) < self.config.max_connections:
                    try:
                        connection = await self._create_connection()
                        self._mark_connection_active(connection)
                        return connection
                    except Exception as e:
                        logger.warning(f"创建连接失败: {e}")
                
                # 3. 等待连接可用
                self.stats.pending_requests += 1
                try:
                    await self._condition.wait()
                finally:
                    self.stats.pending_requests -= 1
    
    async def _try_get_idle_connection(self) -> Optional[GrpcConnection]:
        """
        尝试从空闲连接中获取可用连接
        
        Returns:
            Optional[GrpcConnection]: 可用连接或None
        """
        while self._idle_connections:
            connection = self._idle_connections.popleft()
            
            # 检查连接是否仍然有效
            if self._is_connection_valid(connection):
                # 执行健康检查（如果配置了）
                if self.config.health_check_on_acquire:
                    if await connection.health_check():
                        self._mark_connection_active(connection)
                        self.stats.connections_reused += 1
                        return connection
                    else:
                        # 连接不健康，销毁它
                        await self._destroy_connection(connection)
                else:
                    self._mark_connection_active(connection)
                    self.stats.connections_reused += 1
                    return connection
            else:
                # 连接无效，销毁它
                await self._destroy_connection(connection)
        
        return None
    
    def _is_connection_valid(self, connection: GrpcConnection) -> bool:
        """
        检查连接是否有效
        
        Args:
            connection: 要检查的连接
            
        Returns:
            bool: 连接是否有效
        """
        current_time = time.time()
        
        # 检查连接是否已关闭
        if connection.is_closed:
            return False
        
        # 检查空闲超时
        if current_time - connection.stats.last_used_time > self.config.idle_timeout:
            logger.debug(f"连接空闲超时: {connection.connection_id}")
            return False
        
        # 检查生存时间
        if current_time - connection.stats.created_time > self.config.max_lifetime:
            logger.debug(f"连接超过最大生存时间: {connection.connection_id}")
            return False
        
        return True
    
    def _mark_connection_active(self, connection: GrpcConnection) -> None:
        """
        标记连接为活跃状态
        
        Args:
            connection: 连接对象
        """
        self._active_connections.add(connection)
        self.stats.active_connections = len(self._active_connections)
        self.stats.idle_connections = len(self._idle_connections)
    
    def _update_acquire_stats(self, acquire_time: float, success: bool) -> None:
        """
        更新获取统计
        
        Args:
            acquire_time: 获取时间
            success: 是否成功
        """
        self.stats.total_requests += 1
        
        if success:
            self.stats.successful_requests += 1
            self.stats.total_acquire_time += acquire_time
            
            if acquire_time > self.stats.max_acquire_time:
                self.stats.max_acquire_time = acquire_time
            
            if acquire_time < self.stats.min_acquire_time:
                self.stats.min_acquire_time = acquire_time
        else:
            self.stats.failed_requests += 1
    
    async def release(self, pooled_connection: PooledConnection) -> None:
        """
        释放连接回池
        
        Args:
            pooled_connection: 池化连接
        """
        connection = pooled_connection.connection
        
        async with self._condition:
            # 从活跃连接中移除
            self._active_connections.discard(connection)
            
            # 检查连接是否仍然有效
            if self._is_connection_valid(connection) and not self._closed:
                # 连接有效，放回空闲池
                self._idle_connections.append(connection)
                
                # 更新统计
                self.stats.active_connections = len(self._active_connections)
                self.stats.idle_connections = len(self._idle_connections)
                
                # 通知等待中的请求
                self._condition.notify()
                
                logger.debug(f"连接已释放回池: {connection.connection_id}")
            else:
                # 连接无效，销毁它
                await self._destroy_connection(connection)
    
    @asynccontextmanager
    async def get_connection(self, timeout: Optional[float] = None):
        """
        获取连接的上下文管理器
        
        Args:
            timeout: 超时时间
            
        Usage:
            async with pool.get_connection() as conn:
                # 使用连接
                async with conn.get_channel() as channel:
                    # gRPC调用
        """
        pooled_conn = await self.acquire(timeout)
        try:
            yield pooled_conn
        finally:
            await pooled_conn.release()
    
    async def _health_check_loop(self) -> None:
        """健康检查循环"""
        while not self._closed:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")
                await asyncio.sleep(self.config.health_check_interval)
    
    async def _perform_health_checks(self) -> None:
        """执行健康检查"""
        unhealthy_connections = []
        
        # 检查空闲连接
        for connection in list(self._idle_connections):
            if not await connection.health_check():
                unhealthy_connections.append(connection)
        
        # 移除不健康的连接
        async with self._lock:
            for connection in unhealthy_connections:
                if connection in self._idle_connections:
                    self._idle_connections.remove(connection)
                await self._destroy_connection(connection)
        
        if unhealthy_connections:
            logger.info(f"健康检查移除了 {len(unhealthy_connections)} 个不健康连接")
    
    async def _cleanup_loop(self) -> None:
        """清理循环"""
        while not self._closed:
            try:
                await self._perform_cleanup()
                await asyncio.sleep(self.config.cleanup_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理循环异常: {e}")
                await asyncio.sleep(self.config.cleanup_interval)
    
    async def _perform_cleanup(self) -> None:
        """执行清理操作"""
        current_time = time.time()
        expired_connections = []
        
        # 查找过期连接
        for connection in list(self._idle_connections):
            if not self._is_connection_valid(connection):
                expired_connections.append(connection)
        
        # 移除过期连接
        async with self._lock:
            for connection in expired_connections:
                if connection in self._idle_connections:
                    self._idle_connections.remove(connection)
                await self._destroy_connection(connection)
        
        # 确保最小连接数
        if len(self._connections) < self.config.min_connections:
            needed = self.config.min_connections - len(self._connections)
            async with self._lock:
                for _ in range(needed):
                    try:
                        connection = await self._create_connection()
                        self._idle_connections.append(connection)
                    except Exception as e:
                        logger.warning(f"清理时创建连接失败: {e}")
                        break
        
        if expired_connections:
            logger.debug(f"清理移除了 {len(expired_connections)} 个过期连接")
    
    async def _stats_loop(self) -> None:
        """统计循环"""
        while not self._closed:
            try:
                stats = self.get_stats()
                logger.info(f"连接池统计 {self.pool_id}: {stats}")
                await asyncio.sleep(self.config.stats_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"统计循环异常: {e}")
                await asyncio.sleep(self.config.stats_interval)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取连接池统计信息
        
        Returns:
            Dict[str, Any]: 统计信息字典
        """
        self.stats.total_connections = len(self._connections)
        self.stats.active_connections = len(self._active_connections)
        self.stats.idle_connections = len(self._idle_connections)
        self.stats.pending_requests = len(self._pending_requests)
        
        return {
            "pool_id": self.pool_id,
            "config": {
                "min_connections": self.config.min_connections,
                "max_connections": self.config.max_connections,
                "acquire_timeout": self.config.acquire_timeout,
                "idle_timeout": self.config.idle_timeout,
                "max_lifetime": self.config.max_lifetime,
            },
            "connections": {
                "total": self.stats.total_connections,
                "active": self.stats.active_connections,
                "idle": self.stats.idle_connections,
                "pending_requests": self.stats.pending_requests,
            },
            "requests": {
                "total": self.stats.total_requests,
                "successful": self.stats.successful_requests,
                "failed": self.stats.failed_requests,
                "timeout": self.stats.timeout_requests,
                "success_rate": self.stats.success_rate,
            },
            "performance": {
                "avg_acquire_time": self.stats.avg_acquire_time,
                "max_acquire_time": self.stats.max_acquire_time,
                "min_acquire_time": self.stats.min_acquire_time if self.stats.min_acquire_time != float('inf') else 0,
                "pool_utilization": self.stats.pool_utilization,
            },
            "events": {
                "connections_created": self.stats.connections_created,
                "connections_destroyed": self.stats.connections_destroyed,
                "connections_reused": self.stats.connections_reused,
            },
            "timestamps": {
                "created_time": self.stats.created_time,
                "last_reset_time": self.stats.last_reset_time,
            }
        }
    
    async def close(self) -> None:
        """
        关闭连接池
        """
        if self._closed:
            return
        
        self._closed = True
        
        # 取消后台任务
        tasks = [self._health_check_task, self._cleanup_task, self._stats_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 关闭所有连接
        async with self._lock:
            connections_to_close = list(self._connections)
            
            for connection in connections_to_close:
                await self._destroy_connection(connection)
            
            # 清空所有集合
            self._connections.clear()
            self._idle_connections.clear()
            self._active_connections.clear()
            self._pending_requests.clear()
        
        logger.info(f"连接池 {self.pool_id} 已关闭")
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        self.stats = PoolStats()
        logger.info(f"连接池 {self.pool_id} 统计信息已重置")
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"GrpcConnectionPool(id={self.pool_id}, size={len(self._connections)})"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        return (f"GrpcConnectionPool(id={self.pool_id}, total={len(self._connections)}, "
                f"active={len(self._active_connections)}, idle={len(self._idle_connections)})")


class MultiAddressPool:
    """
    多地址连接池管理器
    
    管理多个服务地址的连接池，提供负载均衡和故障转移功能。
    """
    
    def __init__(self, pool_configs: Dict[str, PoolConfig]):
        """
        初始化多地址连接池
        
        Args:
            pool_configs: 地址到池配置的映射
        """
        self.pool_configs = pool_configs
        self.pools: Dict[str, GrpcConnectionPool] = {}
        self._lock = asyncio.Lock()
        
        logger.info(f"创建多地址连接池管理器，地址数量: {len(pool_configs)}")
    
    async def initialize(self) -> None:
        """初始化所有连接池"""
        async with self._lock:
            for address, config in self.pool_configs.items():
                pool = GrpcConnectionPool(config, f"pool_{address}")
                await pool.initialize()
                self.pools[address] = pool
                
                logger.info(f"初始化地址 {address} 的连接池")
    
    async def get_pool(self, address: str) -> GrpcConnectionPool:
        """
        获取指定地址的连接池
        
        Args:
            address: 服务地址
            
        Returns:
            GrpcConnectionPool: 连接池
        """
        if address not in self.pools:
            raise GrpcConfigurationError(f"未找到地址 {address} 的连接池")
        
        return self.pools[address]
    
    async def get_connection(self, address: str, timeout: Optional[float] = None):
        """
        获取指定地址的连接
        
        Args:
            address: 服务地址
            timeout: 超时时间
            
        Returns:
            PooledConnection: 池化连接
        """
        pool = await self.get_pool(address)
        return await pool.acquire(timeout)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """
        获取所有连接池的统计信息
        
        Returns:
            Dict[str, Any]: 所有池的统计信息
        """
        stats = {}
        for address, pool in self.pools.items():
            stats[address] = pool.get_stats()
        return stats
    
    async def close(self) -> None:
        """关闭所有连接池"""
        async with self._lock:
            for address, pool in self.pools.items():
                await pool.close()
                logger.info(f"已关闭地址 {address} 的连接池")
            
            self.pools.clear()
            logger.info("多地址连接池管理器已关闭")