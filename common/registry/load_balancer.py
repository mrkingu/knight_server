"""
负载均衡模块

该模块实现多种负载均衡算法，包括轮询、随机、加权轮询、最少连接、一致性哈希等，
支持动态权重调整、故障节点自动剔除和恢复。
"""

import asyncio
import time
import random
import hashlib
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
try:
    from loguru import logger
except ImportError:
    from ..logger.mock_logger import logger

from .base_adapter import ServiceInfo, ServiceStatus
from .exceptions import LoadBalancerError, handle_async_registry_exception


class LoadBalanceStrategy(Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"              # 轮询
    RANDOM = "random"                        # 随机
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"  # 加权轮询
    LEAST_CONNECTIONS = "least_connections"  # 最少连接
    CONSISTENT_HASH = "consistent_hash"      # 一致性哈希
    IP_HASH = "ip_hash"                      # IP哈希
    RESPONSE_TIME = "response_time"          # 响应时间最优


@dataclass
class ConnectionStats:
    """连接统计信息"""
    service_id: str
    active_connections: int = 0
    total_connections: int = 0
    total_errors: int = 0
    total_response_time: float = 0.0
    last_request_time: float = 0.0
    
    def add_connection(self):
        """添加连接"""
        self.active_connections += 1
        self.total_connections += 1
        self.last_request_time = time.time()
    
    def remove_connection(self, response_time: float = 0.0, error: bool = False):
        """移除连接"""
        self.active_connections = max(0, self.active_connections - 1)
        if error:
            self.total_errors += 1
        else:
            self.total_response_time += response_time
    
    def get_average_response_time(self) -> float:
        """获取平均响应时间"""
        success_count = self.total_connections - self.total_errors
        if success_count <= 0:
            return float('inf')
        return self.total_response_time / success_count
    
    def get_error_rate(self) -> float:
        """获取错误率"""
        if self.total_connections <= 0:
            return 0.0
        return self.total_errors / self.total_connections


@dataclass
class LoadBalanceContext:
    """负载均衡上下文"""
    client_id: Optional[str] = None          # 客户端ID
    client_ip: Optional[str] = None          # 客户端IP
    session_id: Optional[str] = None         # 会话ID
    metadata: Dict[str, Any] = field(default_factory=dict)  # 附加元数据


class BaseLoadBalancer(ABC):
    """负载均衡器基类"""
    
    def __init__(self, name: str):
        self.name = name
        self._stats: Dict[str, ConnectionStats] = {}
        self._lock = asyncio.Lock()
    
    @abstractmethod
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """
        选择服务实例
        
        Args:
            services: 可用的服务列表
            context: 负载均衡上下文
            
        Returns:
            Optional[ServiceInfo]: 选中的服务实例
        """
        pass
    
    async def start_request(self, service_id: str) -> None:
        """开始请求，增加连接计数"""
        async with self._lock:
            if service_id not in self._stats:
                self._stats[service_id] = ConnectionStats(service_id=service_id)
            self._stats[service_id].add_connection()
    
    async def end_request(self, service_id: str, response_time: float = 0.0, error: bool = False) -> None:
        """结束请求，减少连接计数"""
        async with self._lock:
            if service_id in self._stats:
                self._stats[service_id].remove_connection(response_time, error)
    
    def get_stats(self, service_id: str) -> Optional[ConnectionStats]:
        """获取服务统计信息"""
        return self._stats.get(service_id)
    
    def get_all_stats(self) -> Dict[str, ConnectionStats]:
        """获取所有统计信息"""
        return self._stats.copy()
    
    def _filter_healthy_services(self, services: List[ServiceInfo]) -> List[ServiceInfo]:
        """过滤健康的服务"""
        return [service for service in services if service.is_healthy()]


class RoundRobinBalancer(BaseLoadBalancer):
    """轮询负载均衡器"""
    
    def __init__(self):
        super().__init__("round_robin")
        self._current_index = 0
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """轮询选择服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        async with self._lock:
            service = healthy_services[self._current_index % len(healthy_services)]
            self._current_index = (self._current_index + 1) % len(healthy_services)
            return service


class RandomBalancer(BaseLoadBalancer):
    """随机负载均衡器"""
    
    def __init__(self):
        super().__init__("random")
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """随机选择服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        return random.choice(healthy_services)


class WeightedRoundRobinBalancer(BaseLoadBalancer):
    """加权轮询负载均衡器"""
    
    def __init__(self):
        super().__init__("weighted_round_robin")
        self._current_weights: Dict[str, int] = {}
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """加权轮询选择服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        async with self._lock:
            # 初始化权重
            for service in healthy_services:
                if service.id not in self._current_weights:
                    self._current_weights[service.id] = 0
            
            # 增加当前权重
            for service in healthy_services:
                self._current_weights[service.id] += service.weight
            
            # 选择权重最高的服务
            selected_service = max(healthy_services, key=lambda s: self._current_weights[s.id])
            
            # 减少选中服务的权重
            total_weight = sum(service.weight for service in healthy_services)
            self._current_weights[selected_service.id] -= total_weight
            
            return selected_service


class LeastConnectionsBalancer(BaseLoadBalancer):
    """最少连接负载均衡器"""
    
    def __init__(self):
        super().__init__("least_connections")
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """选择连接数最少的服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        async with self._lock:
            # 确保所有服务都有统计信息
            for service in healthy_services:
                if service.id not in self._stats:
                    self._stats[service.id] = ConnectionStats(service_id=service.id)
            
            # 选择活跃连接数最少的服务
            selected_service = min(
                healthy_services,
                key=lambda s: self._stats[s.id].active_connections
            )
            
            return selected_service


class ConsistentHashBalancer(BaseLoadBalancer):
    """一致性哈希负载均衡器"""
    
    def __init__(self, virtual_nodes: int = 150):
        super().__init__("consistent_hash")
        self._virtual_nodes = virtual_nodes
        self._hash_ring: Dict[int, str] = {}  # hash_value -> service_id
        self._services: Dict[str, ServiceInfo] = {}  # service_id -> service
    
    def _hash(self, key: str) -> int:
        """计算哈希值"""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
    
    def _build_hash_ring(self, services: List[ServiceInfo]):
        """构建哈希环"""
        self._hash_ring.clear()
        self._services.clear()
        
        for service in services:
            self._services[service.id] = service
            
            # 为每个服务创建虚拟节点
            for i in range(self._virtual_nodes):
                virtual_key = f"{service.id}:{i}"
                hash_value = self._hash(virtual_key)
                self._hash_ring[hash_value] = service.id
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """使用一致性哈希选择服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        # 构建哈希环
        self._build_hash_ring(healthy_services)
        
        # 确定哈希键
        if context and context.client_id:
            hash_key = context.client_id
        elif context and context.session_id:
            hash_key = context.session_id
        elif context and context.client_ip:
            hash_key = context.client_ip
        else:
            # 如果没有上下文信息，使用随机值
            hash_key = str(random.random())
        
        # 计算哈希值
        key_hash = self._hash(hash_key)
        
        # 在哈希环上查找下一个节点
        sorted_hashes = sorted(self._hash_ring.keys())
        for hash_value in sorted_hashes:
            if hash_value >= key_hash:
                service_id = self._hash_ring[hash_value]
                return self._services[service_id]
        
        # 如果没有找到，返回第一个节点
        if sorted_hashes:
            service_id = self._hash_ring[sorted_hashes[0]]
            return self._services[service_id]
        
        return None


class IPHashBalancer(BaseLoadBalancer):
    """IP哈希负载均衡器"""
    
    def __init__(self):
        super().__init__("ip_hash")
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """基于客户端IP选择服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        # 获取客户端IP
        client_ip = "unknown"
        if context and context.client_ip:
            client_ip = context.client_ip
        
        # 计算IP哈希
        ip_hash = hash(client_ip)
        index = ip_hash % len(healthy_services)
        
        return healthy_services[index]


class ResponseTimeBalancer(BaseLoadBalancer):
    """响应时间最优负载均衡器"""
    
    def __init__(self):
        super().__init__("response_time")
    
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """选择响应时间最短的服务"""
        healthy_services = self._filter_healthy_services(services)
        if not healthy_services:
            return None
        
        async with self._lock:
            # 确保所有服务都有统计信息
            for service in healthy_services:
                if service.id not in self._stats:
                    self._stats[service.id] = ConnectionStats(service_id=service.id)
            
            # 选择平均响应时间最短的服务
            selected_service = min(
                healthy_services,
                key=lambda s: self._stats[s.id].get_average_response_time()
            )
            
            return selected_service


class LoadBalancer:
    """
    负载均衡器管理器
    
    支持多种负载均衡策略，提供动态权重调整、故障节点自动剔除和恢复功能。
    """
    
    def __init__(self, strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN):
        """
        初始化负载均衡器
        
        Args:
            strategy: 负载均衡策略
        """
        self._strategy = strategy
        self._balancer = self._create_balancer(strategy)
        self._failed_services: Dict[str, float] = {}  # service_id -> failure_time
        self._failure_threshold = 3  # 失败阈值（次数）
        self._recovery_time = 30.0  # 恢复时间（秒）
        self._lock = asyncio.Lock()
        
        # 事件回调
        self._node_failure_callbacks: List[Callable[[str], None]] = []
        self._node_recovery_callbacks: List[Callable[[str], None]] = []
    
    def _create_balancer(self, strategy: LoadBalanceStrategy) -> BaseLoadBalancer:
        """创建负载均衡器实例"""
        if strategy == LoadBalanceStrategy.ROUND_ROBIN:
            return RoundRobinBalancer()
        elif strategy == LoadBalanceStrategy.RANDOM:
            return RandomBalancer()
        elif strategy == LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN:
            return WeightedRoundRobinBalancer()
        elif strategy == LoadBalanceStrategy.LEAST_CONNECTIONS:
            return LeastConnectionsBalancer()
        elif strategy == LoadBalanceStrategy.CONSISTENT_HASH:
            return ConsistentHashBalancer()
        elif strategy == LoadBalanceStrategy.IP_HASH:
            return IPHashBalancer()
        elif strategy == LoadBalanceStrategy.RESPONSE_TIME:
            return ResponseTimeBalancer()
        else:
            raise LoadBalancerError(f"不支持的负载均衡策略: {strategy.value}")
    
    def add_node_failure_callback(self, callback: Callable[[str], None]) -> None:
        """添加节点故障回调"""
        self._node_failure_callbacks.append(callback)
    
    def add_node_recovery_callback(self, callback: Callable[[str], None]) -> None:
        """添加节点恢复回调"""
        self._node_recovery_callbacks.append(callback)
    
    @handle_async_registry_exception
    async def select(
        self, 
        services: List[ServiceInfo], 
        context: Optional[LoadBalanceContext] = None
    ) -> Optional[ServiceInfo]:
        """
        选择服务实例
        
        Args:
            services: 可用的服务列表
            context: 负载均衡上下文
            
        Returns:
            Optional[ServiceInfo]: 选中的服务实例
        """
        if not services:
            raise LoadBalancerError("没有可用的服务实例")
        
        # 过滤掉失败的服务
        available_services = await self._filter_available_services(services)
        
        if not available_services:
            # 如果没有可用服务，尝试恢复失败的服务
            await self._try_recover_failed_services(services)
            available_services = await self._filter_available_services(services)
            
            if not available_services:
                raise LoadBalancerError("没有健康的服务实例可用", available_nodes=0)
        
        # 使用负载均衡策略选择服务
        selected_service = await self._balancer.select(available_services, context)
        
        if not selected_service:
            raise LoadBalancerError("负载均衡器未能选择合适的服务实例")
        
        logger.debug(f"负载均衡选择服务: {self._strategy.value} -> "
                    f"{selected_service.name}/{selected_service.id}")
        
        return selected_service
    
    async def start_request(self, service_id: str) -> None:
        """开始请求"""
        await self._balancer.start_request(service_id)
    
    async def end_request(
        self, 
        service_id: str, 
        response_time: float = 0.0, 
        success: bool = True
    ) -> None:
        """结束请求"""
        await self._balancer.end_request(service_id, response_time, not success)
        
        if not success:
            await self._handle_request_failure(service_id)
    
    async def _filter_available_services(self, services: List[ServiceInfo]) -> List[ServiceInfo]:
        """过滤可用的服务"""
        current_time = time.time()
        available = []
        
        async with self._lock:
            for service in services:
                # 检查是否在失败列表中
                if service.id in self._failed_services:
                    failure_time = self._failed_services[service.id]
                    if current_time - failure_time > self._recovery_time:
                        # 恢复时间到，移除失败记录
                        del self._failed_services[service.id]
                        await self._notify_node_recovery(service.id)
                        available.append(service)
                    # 否则跳过失败的服务
                else:
                    available.append(service)
        
        return available
    
    async def _try_recover_failed_services(self, services: List[ServiceInfo]) -> None:
        """尝试恢复失败的服务"""
        current_time = time.time()
        recovered_services = []
        
        async with self._lock:
            for service in services:
                if service.id in self._failed_services:
                    failure_time = self._failed_services[service.id]
                    if current_time - failure_time > self._recovery_time:
                        recovered_services.append(service.id)
            
            for service_id in recovered_services:
                del self._failed_services[service_id]
                await self._notify_node_recovery(service_id)
    
    async def _handle_request_failure(self, service_id: str) -> None:
        """处理请求失败"""
        stats = self._balancer.get_stats(service_id)
        if not stats:
            return
        
        # 检查错误率是否超过阈值
        error_rate = stats.get_error_rate()
        recent_errors = stats.total_errors
        
        if recent_errors >= self._failure_threshold or error_rate > 0.5:
            async with self._lock:
                if service_id not in self._failed_services:
                    self._failed_services[service_id] = time.time()
                    await self._notify_node_failure(service_id)
                    logger.warning(f"节点标记为失败: {service_id}, 错误率: {error_rate:.2%}")
    
    async def _notify_node_failure(self, service_id: str) -> None:
        """通知节点故障"""
        for callback in self._node_failure_callbacks:
            try:
                callback(service_id)
            except Exception as e:
                logger.error(f"节点故障回调执行失败: {e}")
    
    async def _notify_node_recovery(self, service_id: str) -> None:
        """通知节点恢复"""
        for callback in self._node_recovery_callbacks:
            try:
                callback(service_id)
            except Exception as e:
                logger.error(f"节点恢复回调执行失败: {e}")
        
        logger.info(f"节点恢复: {service_id}")
    
    async def mark_service_failed(self, service_id: str) -> None:
        """手动标记服务为失败"""
        async with self._lock:
            self._failed_services[service_id] = time.time()
            await self._notify_node_failure(service_id)
    
    async def mark_service_recovered(self, service_id: str) -> None:
        """手动标记服务为恢复"""
        async with self._lock:
            if service_id in self._failed_services:
                del self._failed_services[service_id]
                await self._notify_node_recovery(service_id)
    
    def get_failed_services(self) -> List[str]:
        """获取失败的服务列表"""
        return list(self._failed_services.keys())
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "strategy": self._strategy.value,
            "failed_services": len(self._failed_services),
            "balancer_stats": self._balancer.get_all_stats()
        }
    
    def change_strategy(self, strategy: LoadBalanceStrategy) -> None:
        """
        改变负载均衡策略
        
        Args:
            strategy: 新的负载均衡策略
        """
        if strategy != self._strategy:
            old_stats = self._balancer.get_all_stats()
            self._strategy = strategy
            self._balancer = self._create_balancer(strategy)
            
            # 迁移统计信息
            self._balancer._stats = old_stats
            
            logger.info(f"负载均衡策略已更改为: {strategy.value}")


# 上下文管理器，用于自动管理请求生命周期
class RequestContext:
    """请求上下文管理器"""
    
    def __init__(self, load_balancer: LoadBalancer, service: ServiceInfo):
        self._load_balancer = load_balancer
        self._service = service
        self._start_time = 0.0
        self._success = True
    
    async def __aenter__(self):
        await self._load_balancer.start_request(self._service.id)
        self._start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        response_time = (time.time() - self._start_time) * 1000
        success = exc_type is None and self._success
        await self._load_balancer.end_request(self._service.id, response_time, success)
    
    def mark_failed(self):
        """标记请求失败"""
        self._success = False