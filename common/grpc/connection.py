"""
gRPC连接管理模块

该模块实现了gRPC连接的创建、管理和监控，包含连接状态监控、自动重连机制、
SSL/TLS支持等功能。
"""

import asyncio
import time
import ssl
from typing import Optional, Dict, Any, Callable, Union
from enum import Enum
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

try:
    import grpc
    import grpc.aio
    from grpc import StatusCode
    GRPC_AVAILABLE = True
except ImportError:
    # 如果grpc不可用，创建模拟类
    GRPC_AVAILABLE = False
    
    class StatusCode:
        OK = 'OK'
        UNAVAILABLE = 'UNAVAILABLE'
        DEADLINE_EXCEEDED = 'DEADLINE_EXCEEDED'
    
    class grpc:
        @staticmethod
        def insecure_channel(target, options=None):
            return MockChannel(target)
        
        @staticmethod
        def secure_channel(target, credentials, options=None):
            return MockChannel(target)
            
        class aio:
            @staticmethod
            def insecure_channel(target, options=None):
                return MockAsyncChannel(target)
            
            @staticmethod
            def secure_channel(target, credentials, options=None):
                return MockAsyncChannel(target)

from .exceptions import (
    GrpcConnectionError,
    GrpcTimeoutError,
    GrpcConfigError,
    handle_async_grpc_exception
)


class ConnectionState(Enum):
    """连接状态枚举"""
    IDLE = "idle"                    # 空闲
    CONNECTING = "connecting"        # 连接中
    READY = "ready"                  # 就绪
    TRANSIENT_FAILURE = "transient_failure"  # 临时失败
    SHUTDOWN = "shutdown"            # 已关闭


@dataclass
class ConnectionConfig:
    """连接配置类"""
    # 基本配置
    target: str                                    # 目标地址
    port: Optional[int] = None                     # 端口号
    use_ssl: bool = False                          # 是否使用SSL
    
    # 超时配置
    connect_timeout: float = 10.0                  # 连接超时
    request_timeout: float = 30.0                  # 请求超时
    
    # keepalive配置
    keepalive_time_ms: int = 30000                 # keepalive时间(毫秒)
    keepalive_timeout_ms: int = 5000               # keepalive超时(毫秒)
    keepalive_permit_without_calls: bool = True    # 允许无调用时keepalive
    
    # HTTP/2配置
    http2_max_pings_without_data: int = 2          # 无数据时最大ping数
    http2_min_time_between_pings_ms: int = 10000   # ping间最小时间(毫秒)
    http2_min_ping_interval_without_data_ms: int = 300000  # 无数据时ping间隔(毫秒)
    
    # 消息大小限制
    max_receive_message_length: int = 1024 * 1024 * 4  # 最大接收消息大小(4MB)
    max_send_message_length: int = 1024 * 1024 * 4     # 最大发送消息大小(4MB)
    
    # 重连配置
    enable_reconnect: bool = True                  # 启用自动重连
    max_reconnect_attempts: int = 5                # 最大重连次数
    reconnect_backoff_base: float = 1.0           # 重连退避基础时间
    reconnect_backoff_max: float = 30.0           # 重连退避最大时间
    
    # SSL配置
    ssl_cert_file: Optional[str] = None            # SSL证书文件
    ssl_key_file: Optional[str] = None             # SSL私钥文件
    ssl_ca_file: Optional[str] = None              # SSL CA文件
    ssl_verify_hostname: bool = True               # 验证主机名
    
    # 其他配置
    compression: Optional[str] = None              # 压缩类型 ('gzip', 'deflate')
    user_agent: Optional[str] = None               # 用户代理
    metadata: Optional[Dict[str, str]] = field(default_factory=dict)  # 元数据

    def get_channel_options(self) -> list:
        """获取channel选项"""
        options = [
            ('grpc.keepalive_time_ms', self.keepalive_time_ms),
            ('grpc.keepalive_timeout_ms', self.keepalive_timeout_ms),
            ('grpc.keepalive_permit_without_calls', self.keepalive_permit_without_calls),
            ('grpc.http2.max_pings_without_data', self.http2_max_pings_without_data),
            ('grpc.http2.min_time_between_pings_ms', self.http2_min_time_between_pings_ms),
            ('grpc.http2.min_ping_interval_without_data_ms', self.http2_min_ping_interval_without_data_ms),
            ('grpc.max_receive_message_length', self.max_receive_message_length),
            ('grpc.max_send_message_length', self.max_send_message_length),
        ]
        
        if self.compression:
            options.append(('grpc.default_compression', self.compression))
        
        if self.user_agent:
            options.append(('grpc.primary_user_agent', self.user_agent))
            
        return options

    @property
    def endpoint(self) -> str:
        """获取完整的端点地址"""
        if self.port:
            return f"{self.target}:{self.port}"
        return self.target


# Mock classes for testing when grpc is not available
class MockChannel:
    def __init__(self, target):
        self.target = target
        self._state = ConnectionState.READY
    
    def get_state(self):
        return self._state
    
    def close(self):
        self._state = ConnectionState.SHUTDOWN


class MockAsyncChannel:
    def __init__(self, target):
        self.target = target
        self._state = ConnectionState.READY
    
    def get_state(self):
        return self._state
    
    async def close(self):
        self._state = ConnectionState.SHUTDOWN


@dataclass
class ConnectionStats:
    """连接统计信息"""
    created_at: float = field(default_factory=time.time)
    connected_at: Optional[float] = None
    last_used_at: float = field(default_factory=time.time)
    total_requests: int = 0
    failed_requests: int = 0
    reconnect_count: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    
    def update_usage(self):
        """更新使用时间"""
        self.last_used_at = time.time()
        self.total_requests += 1
    
    def update_failure(self):
        """更新失败计数"""
        self.failed_requests += 1
    
    def update_reconnect(self):
        """更新重连计数"""
        self.reconnect_count += 1
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 1.0
        return (self.total_requests - self.failed_requests) / self.total_requests
    
    @property
    def uptime(self) -> float:
        """运行时间(秒)"""
        if self.connected_at:
            return time.time() - self.connected_at
        return 0.0
    
    @property
    def idle_time(self) -> float:
        """空闲时间(秒)"""
        return time.time() - self.last_used_at


class GrpcConnection:
    """gRPC连接管理类"""
    
    def __init__(
        self,
        config: ConnectionConfig,
        on_state_change: Optional[Callable[[ConnectionState], None]] = None
    ):
        """
        初始化gRPC连接
        
        Args:
            config: 连接配置
            on_state_change: 状态变化回调函数
        """
        self._config = config
        self._on_state_change = on_state_change
        self._channel: Optional[Union['grpc.Channel', 'grpc.aio.Channel']] = None
        self._state = ConnectionState.IDLE
        self._stats = ConnectionStats()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    @property
    def config(self) -> ConnectionConfig:
        """获取连接配置"""
        return self._config
    
    @property
    def state(self) -> ConnectionState:
        """获取连接状态"""
        return self._state
    
    @property
    def stats(self) -> ConnectionStats:
        """获取连接统计"""
        return self._stats
    
    @property
    def channel(self) -> Optional[Union['grpc.Channel', 'grpc.aio.Channel']]:
        """获取gRPC channel"""
        return self._channel
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._state == ConnectionState.READY and self._channel is not None
    
    @property
    def endpoint(self) -> str:
        """获取端点地址"""
        return self._config.endpoint
    
    def _update_state(self, new_state: ConnectionState):
        """更新连接状态"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            
            # 触发状态变化回调
            if self._on_state_change:
                try:
                    self._on_state_change(new_state)
                except Exception:
                    pass  # 忽略回调异常
    
    def _create_ssl_credentials(self):
        """创建SSL凭据"""
        if not GRPC_AVAILABLE:
            return None
            
        if not self._config.use_ssl:
            return None
        
        try:
            # 读取证书文件
            root_certificates = None
            private_key = None
            certificate_chain = None
            
            if self._config.ssl_ca_file:
                with open(self._config.ssl_ca_file, 'rb') as f:
                    root_certificates = f.read()
            
            if self._config.ssl_key_file:
                with open(self._config.ssl_key_file, 'rb') as f:
                    private_key = f.read()
            
            if self._config.ssl_cert_file:
                with open(self._config.ssl_cert_file, 'rb') as f:
                    certificate_chain = f.read()
            
            return grpc.ssl_channel_credentials(
                root_certificates=root_certificates,
                private_key=private_key,
                certificate_chain=certificate_chain
            )
        except Exception as e:
            raise GrpcConfigError(
                message=f"创建SSL凭据失败: {str(e)}",
                config_key="ssl_credentials",
                cause=e
            )
    
    @handle_async_grpc_exception
    async def connect(self) -> bool:
        """
        建立连接
        
        Returns:
            bool: 连接是否成功
        """
        async with self._lock:
            if self._state == ConnectionState.CONNECTING:
                return False
            
            if self.is_connected:
                return True
            
            self._update_state(ConnectionState.CONNECTING)
            
            try:
                # 创建channel选项
                options = self._config.get_channel_options()
                target = self._config.endpoint
                
                if not GRPC_AVAILABLE:
                    # 使用模拟channel进行测试
                    if self._config.use_ssl:
                        self._channel = MockAsyncChannel(target)
                    else:
                        self._channel = MockAsyncChannel(target)
                else:
                    # 创建真实的gRPC channel
                    if self._config.use_ssl:
                        credentials = self._create_ssl_credentials()
                        self._channel = grpc.aio.secure_channel(
                            target, credentials, options=options
                        )
                    else:
                        self._channel = grpc.aio.insecure_channel(
                            target, options=options
                        )
                
                # 等待连接就绪
                try:
                    await asyncio.wait_for(
                        self._wait_for_ready(),
                        timeout=self._config.connect_timeout
                    )
                except asyncio.TimeoutError:
                    raise GrpcTimeoutError(
                        message=f"连接超时: {target}",
                        timeout=self._config.connect_timeout,
                        operation="connect"
                    )
                
                self._stats.connected_at = time.time()
                self._update_state(ConnectionState.READY)
                
                # 启动健康检查任务
                if self._config.enable_reconnect:
                    self._start_health_check()
                
                return True
                
            except Exception as e:
                self._update_state(ConnectionState.TRANSIENT_FAILURE)
                await self._cleanup_channel()
                
                if isinstance(e, (GrpcConnectionError, GrpcTimeoutError)):
                    raise
                
                raise GrpcConnectionError(
                    message=f"连接失败: {str(e)}",
                    endpoint=self._config.endpoint,
                    timeout=self._config.connect_timeout,
                    cause=e
                )
    
    async def _wait_for_ready(self):
        """等待连接就绪"""
        if not GRPC_AVAILABLE or not hasattr(self._channel, 'wait_for_state_change'):
            # 模拟等待
            await asyncio.sleep(0.1)
            return
            
        # 等待连接状态变为READY
        while True:
            state = self._channel.get_state()
            if state == grpc.ChannelConnectivity.READY:
                break
            elif state == grpc.ChannelConnectivity.TRANSIENT_FAILURE:
                raise GrpcConnectionError(
                    message="连接进入临时失败状态",
                    endpoint=self._config.endpoint
                )
            elif state == grpc.ChannelConnectivity.SHUTDOWN:
                raise GrpcConnectionError(
                    message="连接已关闭",
                    endpoint=self._config.endpoint
                )
            
            # 等待状态变化
            try:
                await self._channel.wait_for_state_change(state)
            except Exception as e:
                raise GrpcConnectionError(
                    message=f"等待连接状态变化失败: {str(e)}",
                    endpoint=self._config.endpoint,
                    cause=e
                )
    
    @handle_async_grpc_exception
    async def disconnect(self):
        """断开连接"""
        async with self._lock:
            # 停止健康检查任务
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None
            
            # 停止重连任务
            if self._reconnect_task:
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass
                self._reconnect_task = None
            
            # 关闭channel
            await self._cleanup_channel()
            self._update_state(ConnectionState.SHUTDOWN)
    
    async def _cleanup_channel(self):
        """清理channel"""
        if self._channel:
            try:
                if hasattr(self._channel, 'close'):
                    await self._channel.close()
            except Exception:
                pass  # 忽略关闭异常
            finally:
                self._channel = None
    
    @handle_async_grpc_exception
    async def reconnect(self) -> bool:
        """
        重新连接
        
        Returns:
            bool: 重连是否成功
        """
        if not self._config.enable_reconnect:
            return False
        
        # 断开当前连接
        await self._cleanup_channel()
        self._update_state(ConnectionState.CONNECTING)
        
        # 重连逻辑
        for attempt in range(self._config.max_reconnect_attempts):
            try:
                # 计算退避时间
                backoff_time = min(
                    self._config.reconnect_backoff_base * (2 ** attempt),
                    self._config.reconnect_backoff_max
                )
                
                if attempt > 0:
                    await asyncio.sleep(backoff_time)
                
                # 尝试连接
                success = await self.connect()
                if success:
                    self._stats.update_reconnect()
                    return True
                    
            except Exception:
                self._stats.update_failure()
                continue
        
        self._update_state(ConnectionState.TRANSIENT_FAILURE)
        return False
    
    def _start_health_check(self):
        """启动健康检查任务"""
        if self._health_check_task is None or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def _health_check_loop(self):
        """健康检查循环"""
        check_interval = 60.0  # 健康检查间隔
        
        try:
            while self._state != ConnectionState.SHUTDOWN:
                await asyncio.sleep(check_interval)
                
                if not self.is_connected:
                    # 尝试重连
                    if self._config.enable_reconnect and not self._reconnect_task:
                        self._reconnect_task = asyncio.create_task(self.reconnect())
                    break
                
                # 检查连接状态
                try:
                    await self._check_connection_health()
                except Exception:
                    # 健康检查失败，标记为临时失败
                    self._update_state(ConnectionState.TRANSIENT_FAILURE)
                    if self._config.enable_reconnect and not self._reconnect_task:
                        self._reconnect_task = asyncio.create_task(self.reconnect())
                    break
        
        except asyncio.CancelledError:
            pass
    
    async def _check_connection_health(self):
        """检查连接健康状态"""
        if not GRPC_AVAILABLE or not self._channel:
            return
        
        # 简单的健康检查：检查channel状态
        state = self._channel.get_state()
        if state not in [grpc.ChannelConnectivity.READY, grpc.ChannelConnectivity.IDLE]:
            raise GrpcConnectionError(
                message=f"连接状态异常: {state}",
                endpoint=self._config.endpoint
            )
    
    @asynccontextmanager
    async def use_connection(self):
        """
        使用连接的上下文管理器
        
        确保连接可用，并更新使用统计
        """
        if not self.is_connected:
            success = await self.connect()
            if not success:
                raise GrpcConnectionError(
                    message="无法建立连接",
                    endpoint=self._config.endpoint
                )
        
        try:
            yield self._channel
            self._stats.update_usage()
        except Exception as e:
            self._stats.update_failure()
            raise
    
    def get_stats_dict(self) -> Dict[str, Any]:
        """获取统计信息字典"""
        return {
            'endpoint': self.endpoint,
            'state': self._state.value,
            'is_connected': self.is_connected,
            'created_at': self._stats.created_at,
            'connected_at': self._stats.connected_at,
            'last_used_at': self._stats.last_used_at,
            'total_requests': self._stats.total_requests,
            'failed_requests': self._stats.failed_requests,
            'reconnect_count': self._stats.reconnect_count,
            'success_rate': self._stats.success_rate,
            'uptime': self._stats.uptime,
            'idle_time': self._stats.idle_time,
            'bytes_sent': self._stats.bytes_sent,
            'bytes_received': self._stats.bytes_received
        }


# 便捷函数
async def create_connection(
    target: str,
    port: Optional[int] = None,
    use_ssl: bool = False,
    **kwargs
) -> GrpcConnection:
    """
    创建gRPC连接的便捷函数
    
    Args:
        target: 目标地址
        port: 端口号
        use_ssl: 是否使用SSL
        **kwargs: 其他配置参数
    
    Returns:
        GrpcConnection: gRPC连接实例
    """
    config = ConnectionConfig(
        target=target,
        port=port,
        use_ssl=use_ssl,
        **kwargs
    )
    
    connection = GrpcConnection(config)
    await connection.connect()
    return connection


# 导出所有公共接口
__all__ = [
    'ConnectionState',
    'ConnectionConfig', 
    'ConnectionStats',
    'GrpcConnection',
    'create_connection'
]