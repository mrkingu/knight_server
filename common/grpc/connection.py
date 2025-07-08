"""
gRPC连接管理模块

提供gRPC连接的创建、管理、监控和自动重连功能。
封装了grpc.Channel的复杂性，提供简单易用的连接接口。
"""

import asyncio
import threading
import time
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager

try:
    import grpc
    from grpc import aio as grpc_aio
except ImportError:
    # 如果grpc未安装，创建模拟对象以避免导入错误
    grpc = None
    grpc_aio = None

from ..logger import logger
from .exceptions import (
    GrpcConnectionError, 
    GrpcTimeoutError, 
    GrpcConfigurationError,
    handle_grpc_exception_async
)


class ConnectionState(Enum):
    """连接状态枚举"""
    IDLE = "idle"                    # 空闲状态
    CONNECTING = "connecting"        # 连接中
    READY = "ready"                 # 就绪状态
    TRANSIENT_FAILURE = "transient_failure"  # 临时失败
    SHUTDOWN = "shutdown"           # 已关闭


@dataclass
class ConnectionConfig:
    """连接配置类"""
    
    # 基本连接配置
    host: str = "localhost"
    port: int = 50051
    
    # 超时配置（秒）
    connect_timeout: float = 10.0
    request_timeout: float = 30.0
    keepalive_timeout: float = 30.0
    
    # 重连配置
    max_retry_attempts: int = 3
    retry_delay: float = 1.0
    retry_backoff_multiplier: float = 2.0
    max_retry_delay: float = 60.0
    
    # keepalive配置
    keepalive_time: int = 30
    keepalive_timeout: int = 5
    keepalive_permit_without_calls: bool = True
    
    # SSL/TLS配置
    use_ssl: bool = False
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    ssl_ca_path: Optional[str] = None
    ssl_verify: bool = True
    
    # 压缩配置
    compression: Optional[str] = None  # gzip, deflate
    
    # 最大消息大小（字节）
    max_send_message_length: int = 4 * 1024 * 1024  # 4MB
    max_receive_message_length: int = 4 * 1024 * 1024  # 4MB
    
    # 其他选项
    options: Dict[str, Any] = field(default_factory=dict)
    
    def to_grpc_options(self) -> List[tuple]:
        """
        转换为gRPC选项列表
        
        Returns:
            List[tuple]: gRPC选项列表
        """
        if not grpc:
            return []
            
        options = [
            ('grpc.keepalive_time_ms', self.keepalive_time * 1000),
            ('grpc.keepalive_timeout_ms', self.keepalive_timeout * 1000),
            ('grpc.keepalive_permit_without_calls', self.keepalive_permit_without_calls),
            ('grpc.http2.max_pings_without_data', 0),
            ('grpc.http2.min_time_between_pings_ms', 10 * 1000),
            ('grpc.http2.min_ping_interval_without_data_ms', 5 * 60 * 1000),
            ('grpc.max_send_message_length', self.max_send_message_length),
            ('grpc.max_receive_message_length', self.max_receive_message_length),
        ]
        
        # 添加自定义选项
        for key, value in self.options.items():
            options.append((key, value))
            
        return options


@dataclass
class ConnectionStats:
    """连接统计信息"""
    
    created_time: float = field(default_factory=time.time)
    last_used_time: float = field(default_factory=time.time)
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_response_time: float = 0.0
    
    @property
    def avg_response_time(self) -> float:
        """平均响应时间"""
        if self.success_count == 0:
            return 0.0
        return self.total_response_time / self.success_count
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.request_count == 0:
            return 0.0
        return self.success_count / self.request_count
    
    @property
    def age(self) -> float:
        """连接年龄（秒）"""
        return time.time() - self.created_time
    
    @property
    def idle_time(self) -> float:
        """空闲时间（秒）"""
        return time.time() - self.last_used_time


class GrpcConnection:
    """
    gRPC连接管理类
    
    封装grpc.Channel，提供连接状态监控、自动重连、统计信息收集等功能。
    支持同步和异步两种模式。
    """
    
    def __init__(
        self, 
        config: ConnectionConfig,
        connection_id: Optional[str] = None,
        state_change_callback: Optional[Callable[['GrpcConnection', ConnectionState], None]] = None
    ):
        """
        初始化gRPC连接
        
        Args:
            config: 连接配置
            connection_id: 连接ID，用于标识连接
            state_change_callback: 状态变化回调函数
        """
        self.config = config
        self.connection_id = connection_id or f"{config.host}:{config.port}"
        self.state_change_callback = state_change_callback
        
        # 连接对象
        self._channel: Optional[grpc.Channel] = None
        self._async_channel: Optional[grpc_aio.Channel] = None
        
        # 状态管理
        self._state = ConnectionState.IDLE
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        
        # 统计信息
        self.stats = ConnectionStats()
        
        # 重连相关
        self._retry_count = 0
        self._last_error: Optional[Exception] = None
        
        # 连接监控
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        logger.debug(f"创建gRPC连接: {self.connection_id}")
    
    @property
    def state(self) -> ConnectionState:
        """获取连接状态"""
        return self._state
    
    @property
    def is_ready(self) -> bool:
        """检查连接是否就绪"""
        return self._state == ConnectionState.READY
    
    @property
    def is_closed(self) -> bool:
        """检查连接是否已关闭"""
        return self._state == ConnectionState.SHUTDOWN
    
    @property
    def address(self) -> str:
        """获取连接地址"""
        return f"{self.config.host}:{self.config.port}"
    
    def _set_state(self, new_state: ConnectionState) -> None:
        """
        设置连接状态
        
        Args:
            new_state: 新状态
        """
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            
            logger.debug(f"连接状态变化: {self.connection_id} {old_state.value} -> {new_state.value}")
            
            # 调用状态变化回调
            if self.state_change_callback:
                try:
                    self.state_change_callback(self, new_state)
                except Exception as e:
                    logger.error(f"状态变化回调执行失败: {e}")
    
    def _create_channel_address(self) -> str:
        """
        创建gRPC频道地址
        
        Returns:
            str: 频道地址
        """
        return f"{self.config.host}:{self.config.port}"
    
    def _create_credentials(self):
        """
        创建SSL凭据
        
        Returns:
            grpc.ChannelCredentials: SSL凭据对象
        """
        if not self.config.use_ssl or not grpc:
            return None
        
        try:
            if self.config.ssl_cert_path and self.config.ssl_key_path:
                # 使用客户端证书
                with open(self.config.ssl_cert_path, 'rb') as cert_file:
                    cert_data = cert_file.read()
                with open(self.config.ssl_key_path, 'rb') as key_file:
                    key_data = key_file.read()
                
                ca_data = None
                if self.config.ssl_ca_path:
                    with open(self.config.ssl_ca_path, 'rb') as ca_file:
                        ca_data = ca_file.read()
                
                return grpc.ssl_channel_credentials(
                    root_certificates=ca_data,
                    private_key=key_data,
                    certificate_chain=cert_data
                )
            else:
                # 仅使用服务器证书验证
                ca_data = None
                if self.config.ssl_ca_path:
                    with open(self.config.ssl_ca_path, 'rb') as ca_file:
                        ca_data = ca_file.read()
                
                return grpc.ssl_channel_credentials(root_certificates=ca_data)
                
        except Exception as e:
            raise GrpcConfigurationError(f"SSL凭据创建失败: {e}", cause=e)
    
    @handle_grpc_exception_async
    async def connect(self) -> None:
        """
        建立连接
        
        Raises:
            GrpcConnectionError: 连接失败
        """
        async with self._async_lock:
            if self._state in [ConnectionState.CONNECTING, ConnectionState.READY]:
                return
            
            self._set_state(ConnectionState.CONNECTING)
            
            try:
                await self._do_connect()
                self._set_state(ConnectionState.READY)
                self._retry_count = 0
                self._last_error = None
                
                logger.info(f"gRPC连接建立成功: {self.connection_id}")
                
            except Exception as e:
                self._set_state(ConnectionState.TRANSIENT_FAILURE)
                self._last_error = e
                
                logger.error(f"gRPC连接建立失败: {self.connection_id}, 错误: {e}")
                raise GrpcConnectionError(f"连接失败: {e}", self.config.host, self.config.port, e)
    
    async def _do_connect(self) -> None:
        """
        执行实际连接操作
        """
        if not grpc_aio:
            raise GrpcConfigurationError("grpcio未安装，无法创建异步连接")
        
        address = self._create_channel_address()
        options = self.config.to_grpc_options()
        credentials = self._create_credentials()
        
        if credentials:
            self._async_channel = grpc_aio.secure_channel(address, credentials, options=options)
        else:
            self._async_channel = grpc_aio.insecure_channel(address, options=options)
        
        # 等待连接就绪
        try:
            await asyncio.wait_for(
                self._async_channel.channel_ready(),
                timeout=self.config.connect_timeout
            )
        except asyncio.TimeoutError:
            await self._async_channel.close()
            self._async_channel = None
            raise GrpcTimeoutError(f"连接超时: {self.config.connect_timeout}秒")
    
    def connect_sync(self) -> None:
        """
        同步建立连接
        
        Raises:
            GrpcConnectionError: 连接失败
        """
        with self._lock:
            if self._state in [ConnectionState.CONNECTING, ConnectionState.READY]:
                return
            
            self._set_state(ConnectionState.CONNECTING)
            
            try:
                self._do_connect_sync()
                self._set_state(ConnectionState.READY)
                self._retry_count = 0
                self._last_error = None
                
                logger.info(f"gRPC同步连接建立成功: {self.connection_id}")
                
            except Exception as e:
                self._set_state(ConnectionState.TRANSIENT_FAILURE)
                self._last_error = e
                
                logger.error(f"gRPC同步连接建立失败: {self.connection_id}, 错误: {e}")
                raise GrpcConnectionError(f"连接失败: {e}", self.config.host, self.config.port, e)
    
    def _do_connect_sync(self) -> None:
        """
        执行同步连接操作
        """
        if not grpc:
            raise GrpcConfigurationError("grpcio未安装，无法创建同步连接")
        
        address = self._create_channel_address()
        options = self.config.to_grpc_options()
        credentials = self._create_credentials()
        
        if credentials:
            self._channel = grpc.secure_channel(address, credentials, options=options)
        else:
            self._channel = grpc.insecure_channel(address, options=options)
        
        # 等待连接就绪
        try:
            future = grpc.channel_ready_future(self._channel)
            future.result(timeout=self.config.connect_timeout)
        except Exception as e:
            self._channel.close()
            self._channel = None
            if "timeout" in str(e).lower():
                raise GrpcTimeoutError(f"连接超时: {self.config.connect_timeout}秒")
            raise e
    
    async def close(self) -> None:
        """
        关闭连接
        """
        async with self._async_lock:
            self._set_state(ConnectionState.SHUTDOWN)
            
            # 停止监控
            if self._monitor_task:
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
                self._monitor_task = None
            
            # 关闭异步频道
            if self._async_channel:
                await self._async_channel.close()
                self._async_channel = None
            
            # 关闭同步频道
            if self._channel:
                self._channel.close()
                self._channel = None
            
            logger.info(f"gRPC连接已关闭: {self.connection_id}")
    
    def close_sync(self) -> None:
        """
        同步关闭连接
        """
        with self._lock:
            self._set_state(ConnectionState.SHUTDOWN)
            
            # 关闭同步频道
            if self._channel:
                self._channel.close()
                self._channel = None
            
            logger.info(f"gRPC同步连接已关闭: {self.connection_id}")
    
    @asynccontextmanager
    async def get_channel(self):
        """
        获取异步gRPC频道的上下文管理器
        
        Usage:
            async with connection.get_channel() as channel:
                # 使用channel进行gRPC调用
        """
        if not self.is_ready:
            await self.connect()
        
        if not self._async_channel:
            raise GrpcConnectionError("异步频道未创建")
        
        self.stats.last_used_time = time.time()
        yield self._async_channel
    
    def get_channel_sync(self):
        """
        获取同步gRPC频道
        
        Returns:
            grpc.Channel: 同步gRPC频道
        """
        if not self.is_ready:
            self.connect_sync()
        
        if not self._channel:
            raise GrpcConnectionError("同步频道未创建")
        
        self.stats.last_used_time = time.time()
        return self._channel
    
    async def health_check(self) -> bool:
        """
        执行健康检查
        
        Returns:
            bool: 连接是否健康
        """
        try:
            if not self._async_channel:
                return False
            
            # 简单的连接状态检查
            state = self._async_channel.get_state(try_to_connect=False)
            if grpc_aio and hasattr(grpc_aio, 'ChannelConnectivity'):
                return state == grpc_aio.ChannelConnectivity.READY
            
            return True
            
        except Exception as e:
            logger.warning(f"健康检查失败: {self.connection_id}, 错误: {e}")
            return False
    
    def record_request(self, success: bool, response_time: float = 0.0) -> None:
        """
        记录请求统计
        
        Args:
            success: 请求是否成功
            response_time: 响应时间（秒）
        """
        self.stats.request_count += 1
        
        if success:
            self.stats.success_count += 1
            self.stats.total_response_time += response_time
        else:
            self.stats.error_count += 1
        
        self.stats.last_used_time = time.time()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取连接统计信息
        
        Returns:
            Dict[str, Any]: 统计信息字典
        """
        return {
            "connection_id": self.connection_id,
            "address": self.address,
            "state": self.state.value,
            "created_time": self.stats.created_time,
            "last_used_time": self.stats.last_used_time,
            "age": self.stats.age,
            "idle_time": self.stats.idle_time,
            "request_count": self.stats.request_count,
            "success_count": self.stats.success_count,
            "error_count": self.stats.error_count,
            "success_rate": self.stats.success_rate,
            "avg_response_time": self.stats.avg_response_time,
            "retry_count": self._retry_count,
            "last_error": str(self._last_error) if self._last_error else None
        }
    
    def start_monitoring(self, interval: float = 30.0) -> None:
        """
        启动连接监控
        
        Args:
            interval: 监控间隔（秒）
        """
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        
        logger.debug(f"启动连接监控: {self.connection_id}, 间隔: {interval}秒")
    
    async def _monitor_loop(self, interval: float) -> None:
        """
        监控循环
        
        Args:
            interval: 监控间隔
        """
        while self._monitoring and not self.is_closed:
            try:
                # 执行健康检查
                is_healthy = await self.health_check()
                
                if not is_healthy and self.state == ConnectionState.READY:
                    logger.warning(f"连接健康检查失败: {self.connection_id}")
                    self._set_state(ConnectionState.TRANSIENT_FAILURE)
                
                # 记录监控日志
                stats = self.get_stats()
                logger.debug(f"连接监控: {self.connection_id}, 统计: {stats}")
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"连接监控异常: {self.connection_id}, 错误: {e}")
                await asyncio.sleep(interval)
        
        self._monitoring = False
        logger.debug(f"连接监控已停止: {self.connection_id}")
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"GrpcConnection(id={self.connection_id}, state={self.state.value}, address={self.address})"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        return (f"GrpcConnection(id={self.connection_id}, state={self.state.value}, "
                f"address={self.address}, stats={self.stats})")