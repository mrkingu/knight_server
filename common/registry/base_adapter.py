"""
基础适配器接口

该模块定义了统一的注册中心接口规范，支持多种注册中心实现（etcd、consul等）。
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, AsyncIterator, Callable
from dataclasses import dataclass
from enum import Enum

from .exceptions import BaseRegistryException


class ServiceStatus(Enum):
    """服务状态枚举"""
    UNKNOWN = "unknown"          # 未知状态
    HEALTHY = "healthy"          # 健康状态
    UNHEALTHY = "unhealthy"      # 不健康状态
    CRITICAL = "critical"        # 严重故障状态


@dataclass
class ServiceInfo:
    """
    服务信息数据类
    
    包含服务的基本信息、网络地址、元数据和健康状态等。
    """
    # 基本信息
    name: str                                    # 服务名称
    id: str                                      # 服务唯一标识
    host: str                                    # 服务主机地址
    port: int                                    # 服务端口号
    
    # 可选信息
    tags: List[str] = None                       # 服务标签
    metadata: Dict[str, Any] = None              # 服务元数据
    version: str = "1.0.0"                       # 服务版本
    weight: int = 100                            # 服务权重（用于负载均衡）
    ttl: int = 30                                # 服务TTL（秒）
    
    # 健康检查配置
    health_check_url: Optional[str] = None       # HTTP健康检查URL
    health_check_interval: int = 5               # 健康检查间隔（秒）
    health_check_timeout: int = 3                # 健康检查超时（秒）
    health_check_deregister_critical_after: str = "30s"  # 严重故障后注销时间
    
    # 状态信息
    status: ServiceStatus = ServiceStatus.UNKNOWN  # 服务状态
    last_seen: Optional[float] = None            # 最后活跃时间
    
    def __post_init__(self):
        """初始化后处理"""
        if self.tags is None:
            self.tags = []
        if self.metadata is None:
            self.metadata = {}
    
    @property
    def address(self) -> str:
        """获取服务地址"""
        return f"{self.host}:{self.port}"
    
    @property
    def service_url(self) -> str:
        """获取服务URL"""
        return f"http://{self.host}:{self.port}"
    
    def is_healthy(self) -> bool:
        """判断服务是否健康"""
        return self.status == ServiceStatus.HEALTHY
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "tags": self.tags,
            "metadata": self.metadata,
            "version": self.version,
            "weight": self.weight,
            "ttl": self.ttl,
            "health_check_url": self.health_check_url,
            "health_check_interval": self.health_check_interval,
            "health_check_timeout": self.health_check_timeout,
            "health_check_deregister_critical_after": self.health_check_deregister_critical_after,
            "status": self.status.value,
            "last_seen": self.last_seen,
            "address": self.address,
            "service_url": self.service_url
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ServiceInfo':
        """从字典创建服务信息"""
        # 提取基本字段
        kwargs = {}
        for field in cls.__dataclass_fields__:
            if field in data:
                value = data[field]
                # 处理枚举类型
                if field == "status" and isinstance(value, str):
                    kwargs[field] = ServiceStatus(value)
                else:
                    kwargs[field] = value
        
        return cls(**kwargs)


@dataclass
class WatchEvent:
    """
    服务变更事件数据类
    """
    event_type: str                              # 事件类型: PUT, DELETE
    service: ServiceInfo                         # 相关的服务信息
    timestamp: float                             # 事件时间戳
    
    def is_service_added(self) -> bool:
        """判断是否为服务新增事件"""
        return self.event_type == "PUT"
    
    def is_service_removed(self) -> bool:
        """判断是否为服务删除事件"""
        return self.event_type == "DELETE"


class BaseRegistryAdapter(ABC):
    """
    注册中心适配器基类
    
    定义了统一的注册中心接口规范，所有具体的注册中心实现都应该继承此类。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化适配器
        
        Args:
            config: 注册中心配置
        """
        self.config = config
        self._connected = False
        self._closing = False
        
    @abstractmethod
    async def connect(self) -> None:
        """
        连接到注册中心
        
        Raises:
            BaseRegistryException: 连接失败时抛出异常
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """
        断开与注册中心的连接
        """
        pass
    
    @abstractmethod
    async def register_service(self, service: ServiceInfo) -> bool:
        """
        注册服务
        
        Args:
            service: 服务信息
            
        Returns:
            bool: 注册是否成功
            
        Raises:
            ServiceRegistrationError: 注册失败时抛出异常
        """
        pass
    
    @abstractmethod
    async def deregister_service(self, service_id: str) -> bool:
        """
        注销服务
        
        Args:
            service_id: 服务ID
            
        Returns:
            bool: 注销是否成功
            
        Raises:
            ServiceRegistrationError: 注销失败时抛出异常
        """
        pass
    
    @abstractmethod
    async def discover_services(
        self, 
        service_name: str,
        tags: Optional[List[str]] = None,
        healthy_only: bool = True
    ) -> List[ServiceInfo]:
        """
        发现服务
        
        Args:
            service_name: 服务名称
            tags: 服务标签过滤
            healthy_only: 是否只返回健康的服务
            
        Returns:
            List[ServiceInfo]: 服务列表
            
        Raises:
            ServiceDiscoveryError: 发现失败时抛出异常
        """
        pass
    
    @abstractmethod
    async def get_service(self, service_id: str) -> Optional[ServiceInfo]:
        """
        获取指定服务信息
        
        Args:
            service_id: 服务ID
            
        Returns:
            Optional[ServiceInfo]: 服务信息，未找到返回None
        """
        pass
    
    @abstractmethod
    async def health_check(self, service_id: str) -> ServiceStatus:
        """
        检查服务健康状态
        
        Args:
            service_id: 服务ID
            
        Returns:
            ServiceStatus: 服务状态
            
        Raises:
            HealthCheckError: 健康检查失败时抛出异常
        """
        pass
    
    @abstractmethod
    async def update_service_status(self, service_id: str, status: ServiceStatus) -> bool:
        """
        更新服务状态
        
        Args:
            service_id: 服务ID
            status: 新状态
            
        Returns:
            bool: 更新是否成功
        """
        pass
    
    @abstractmethod
    async def watch_services(
        self, 
        service_name: Optional[str] = None,
        callback: Optional[Callable[[WatchEvent], None]] = None
    ) -> AsyncIterator[WatchEvent]:
        """
        监听服务变更
        
        Args:
            service_name: 监听的服务名称，None表示监听所有服务
            callback: 事件回调函数
            
        Yields:
            WatchEvent: 服务变更事件
        """
        pass
    
    @abstractmethod
    async def renew_lease(self, service_id: str) -> bool:
        """
        续期服务租约
        
        Args:
            service_id: 服务ID
            
        Returns:
            bool: 续期是否成功
        """
        pass
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected
    
    @property
    def is_closing(self) -> bool:
        """检查是否正在关闭"""
        return self._closing
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()


class HealthChecker(ABC):
    """
    健康检查器基类
    
    定义了健康检查的通用接口。
    """
    
    @abstractmethod
    async def check_health(self, service: ServiceInfo) -> ServiceStatus:
        """
        执行健康检查
        
        Args:
            service: 服务信息
            
        Returns:
            ServiceStatus: 健康状态
        """
        pass
    
    @abstractmethod
    def supports(self, check_type: str) -> bool:
        """
        检查是否支持指定的检查类型
        
        Args:
            check_type: 检查类型
            
        Returns:
            bool: 是否支持
        """
        pass