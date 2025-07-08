"""
gRPC负载均衡模块

提供多种负载均衡策略，支持服务发现、健康检查、权重配置和故障节点自动剔除。
支持轮询、随机、最少连接、一致性哈希等多种算法。
"""

import asyncio
import random
import hashlib
import bisect
import time
from typing import List, Dict, Optional, Any, Set, Callable, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from ..logger import logger
from .exceptions import (
    GrpcServiceUnavailableError,
    GrpcConfigurationError,
    handle_grpc_exception_async
)


class LoadBalanceStrategy(Enum):
    """负载均衡策略枚举"""
    ROUND_ROBIN = "round_robin"          # 轮询
    RANDOM = "random"                    # 随机
    WEIGHTED_RANDOM = "weighted_random"  # 加权随机
    LEAST_CONNECTIONS = "least_connections"  # 最少连接
    CONSISTENT_HASH = "consistent_hash"  # 一致性哈希
    FASTEST_RESPONSE = "fastest_response"  # 最快响应


@dataclass
class ServerNode:
    """服务器节点信息"""
    
    # 基本信息
    address: str
    port: int
    weight: int = 1
    
    # 状态信息
    is_healthy: bool = True
    is_available: bool = True
    
    # 统计信息
    active_connections: int = 0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    
    # 性能指标
    avg_response_time: float = 0.0
    last_response_time: float = 0.0
    total_response_time: float = 0.0
    
    # 时间戳
    last_health_check: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    failure_count: int = 0
    
    @property
    def endpoint(self) -> str:
        """获取端点地址"""
        return f"{self.address}:{self.port}"
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    @property
    def load_score(self) -> float:
        """负载评分（越低越好）"""
        # 综合考虑连接数、响应时间和成功率
        connection_factor = self.active_connections / max(self.weight, 1)
        response_factor = self.avg_response_time
        success_factor = 1.0 - self.success_rate
        
        return connection_factor + response_factor + success_factor * 10
    
    def update_stats(self, success: bool, response_time: float = 0.0) -> None:
        """
        更新统计信息
        
        Args:
            success: 请求是否成功
            response_time: 响应时间
        """
        self.total_requests += 1
        self.last_used = time.time()
        
        if success:
            self.successful_requests += 1
            self.total_response_time += response_time
            self.last_response_time = response_time
            
            # 更新平均响应时间
            if self.successful_requests > 0:
                self.avg_response_time = self.total_response_time / self.successful_requests
            
            # 重置失败计数
            self.failure_count = 0
        else:
            self.failed_requests += 1
            self.failure_count += 1
    
    def increment_connections(self) -> None:
        """增加连接计数"""
        self.active_connections += 1
    
    def decrement_connections(self) -> None:
        """减少连接计数"""
        self.active_connections = max(0, self.active_connections - 1)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "endpoint": self.endpoint,
            "address": self.address,
            "port": self.port,
            "weight": self.weight,
            "is_healthy": self.is_healthy,
            "is_available": self.is_available,
            "active_connections": self.active_connections,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "avg_response_time": self.avg_response_time,
            "last_response_time": self.last_response_time,
            "load_score": self.load_score,
            "failure_count": self.failure_count,
            "last_health_check": self.last_health_check,
            "last_used": self.last_used
        }


class LoadBalancer(ABC):
    """
    负载均衡器基类
    
    定义负载均衡器的通用接口和基础功能。
    """
    
    def __init__(
        self, 
        servers: Optional[List[ServerNode]] = None,
        health_check_interval: float = 30.0,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0
    ):
        """
        初始化负载均衡器
        
        Args:
            servers: 服务器节点列表
            health_check_interval: 健康检查间隔（秒）
            failure_threshold: 失败阈值
            recovery_timeout: 恢复超时（秒）
        """
        self.servers: Dict[str, ServerNode] = {}
        self.health_check_interval = health_check_interval
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        # 状态管理
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._monitoring = False
        
        # 统计信息
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        
        # 添加初始服务器
        if servers:
            for server in servers:
                self.add_server(server)
        
        logger.info(f"初始化负载均衡器: {self.__class__.__name__}")
    
    def add_server(self, server: ServerNode) -> None:
        """
        添加服务器节点
        
        Args:
            server: 服务器节点
        """
        self.servers[server.endpoint] = server
        logger.info(f"添加服务器节点: {server.endpoint}")
    
    def remove_server(self, endpoint: str) -> None:
        """
        移除服务器节点
        
        Args:
            endpoint: 服务器端点
        """
        if endpoint in self.servers:
            del self.servers[endpoint]
            logger.info(f"移除服务器节点: {endpoint}")
    
    def get_available_servers(self) -> List[ServerNode]:
        """
        获取可用的服务器节点
        
        Returns:
            List[ServerNode]: 可用服务器列表
        """
        return [
            server for server in self.servers.values()
            if server.is_healthy and server.is_available
        ]
    
    @abstractmethod
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        选择服务器节点
        
        Args:
            request_context: 请求上下文
            
        Returns:
            ServerNode: 选中的服务器节点
            
        Raises:
            GrpcServiceUnavailableError: 无可用服务器
        """
        pass
    
    async def mark_server_unhealthy(self, endpoint: str) -> None:
        """
        标记服务器为不健康
        
        Args:
            endpoint: 服务器端点
        """
        async with self._lock:
            if endpoint in self.servers:
                server = self.servers[endpoint]
                server.is_healthy = False
                server.failure_count += 1
                
                logger.warning(f"服务器标记为不健康: {endpoint}, 失败次数: {server.failure_count}")
    
    async def mark_server_healthy(self, endpoint: str) -> None:
        """
        标记服务器为健康
        
        Args:
            endpoint: 服务器端点
        """
        async with self._lock:
            if endpoint in self.servers:
                server = self.servers[endpoint]
                server.is_healthy = True
                server.failure_count = 0
                
                logger.info(f"服务器标记为健康: {endpoint}")
    
    def record_request(self, endpoint: str, success: bool, response_time: float = 0.0) -> None:
        """
        记录请求统计
        
        Args:
            endpoint: 服务器端点
            success: 请求是否成功
            response_time: 响应时间
        """
        self.total_requests += 1
        
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        
        # 更新服务器统计
        if endpoint in self.servers:
            self.servers[endpoint].update_stats(success, response_time)
    
    def start_health_monitoring(self) -> None:
        """启动健康监控"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        logger.info("启动负载均衡器健康监控")
    
    async def stop_health_monitoring(self) -> None:
        """停止健康监控"""
        self._monitoring = False
        
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("停止负载均衡器健康监控")
    
    async def _health_check_loop(self) -> None:
        """健康检查循环"""
        while self._monitoring:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")
                await asyncio.sleep(self.health_check_interval)
    
    async def _perform_health_checks(self) -> None:
        """执行健康检查"""
        current_time = time.time()
        
        for server in self.servers.values():
            # 检查失败阈值
            if server.failure_count >= self.failure_threshold:
                if server.is_healthy:
                    await self.mark_server_unhealthy(server.endpoint)
            
            # 检查恢复条件
            elif not server.is_healthy:
                if current_time - server.last_health_check > self.recovery_timeout:
                    # 尝试恢复服务器
                    await self.mark_server_healthy(server.endpoint)
            
            server.last_health_check = current_time
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取负载均衡器统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        available_servers = self.get_available_servers()
        
        return {
            "strategy": self.__class__.__name__,
            "servers": {
                "total": len(self.servers),
                "available": len(available_servers),
                "healthy": sum(1 for s in self.servers.values() if s.is_healthy),
            },
            "requests": {
                "total": self.total_requests,
                "successful": self.successful_requests,
                "failed": self.failed_requests,
                "success_rate": self.successful_requests / max(self.total_requests, 1),
            },
            "server_details": {
                endpoint: server.to_dict()
                for endpoint, server in self.servers.items()
            }
        }


class RoundRobinBalancer(LoadBalancer):
    """
    轮询负载均衡器
    
    按顺序轮流选择服务器节点。
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_index = 0
    
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        轮询选择服务器
        
        Args:
            request_context: 请求上下文（未使用）
            
        Returns:
            ServerNode: 选中的服务器
        """
        available_servers = self.get_available_servers()
        
        if not available_servers:
            raise GrpcServiceUnavailableError(
                "无可用服务器",
                available_servers=0
            )
        
        async with self._lock:
            server = available_servers[self._current_index % len(available_servers)]
            self._current_index = (self._current_index + 1) % len(available_servers)
            
            server.increment_connections()
            
            logger.debug(f"轮询选择服务器: {server.endpoint}")
            return server


class RandomBalancer(LoadBalancer):
    """
    随机负载均衡器
    
    随机选择服务器节点。
    """
    
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        随机选择服务器
        
        Args:
            request_context: 请求上下文（未使用）
            
        Returns:
            ServerNode: 选中的服务器
        """
        available_servers = self.get_available_servers()
        
        if not available_servers:
            raise GrpcServiceUnavailableError(
                "无可用服务器",
                available_servers=0
            )
        
        server = random.choice(available_servers)
        server.increment_connections()
        
        logger.debug(f"随机选择服务器: {server.endpoint}")
        return server


class WeightedRandomBalancer(LoadBalancer):
    """
    加权随机负载均衡器
    
    根据服务器权重随机选择。
    """
    
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        加权随机选择服务器
        
        Args:
            request_context: 请求上下文（未使用）
            
        Returns:
            ServerNode: 选中的服务器
        """
        available_servers = self.get_available_servers()
        
        if not available_servers:
            raise GrpcServiceUnavailableError(
                "无可用服务器",
                available_servers=0
            )
        
        # 计算权重总和
        total_weight = sum(server.weight for server in available_servers)
        
        if total_weight == 0:
            # 如果所有权重都为0，使用普通随机
            server = random.choice(available_servers)
        else:
            # 加权随机选择
            random_weight = random.randint(1, total_weight)
            cumulative_weight = 0
            
            server = available_servers[0]  # 默认值
            for s in available_servers:
                cumulative_weight += s.weight
                if random_weight <= cumulative_weight:
                    server = s
                    break
        
        server.increment_connections()
        
        logger.debug(f"加权随机选择服务器: {server.endpoint}, 权重: {server.weight}")
        return server


class LeastConnectionBalancer(LoadBalancer):
    """
    最少连接负载均衡器
    
    选择当前连接数最少的服务器。
    """
    
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        选择连接数最少的服务器
        
        Args:
            request_context: 请求上下文（未使用）
            
        Returns:
            ServerNode: 选中的服务器
        """
        available_servers = self.get_available_servers()
        
        if not available_servers:
            raise GrpcServiceUnavailableError(
                "无可用服务器",
                available_servers=0
            )
        
        # 选择连接数最少的服务器
        server = min(available_servers, key=lambda s: s.active_connections / max(s.weight, 1))
        server.increment_connections()
        
        logger.debug(f"选择最少连接服务器: {server.endpoint}, 连接数: {server.active_connections}")
        return server


class FastestResponseBalancer(LoadBalancer):
    """
    最快响应负载均衡器
    
    选择平均响应时间最短的服务器。
    """
    
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        选择响应最快的服务器
        
        Args:
            request_context: 请求上下文（未使用）
            
        Returns:
            ServerNode: 选中的服务器
        """
        available_servers = self.get_available_servers()
        
        if not available_servers:
            raise GrpcServiceUnavailableError(
                "无可用服务器",
                available_servers=0
            )
        
        # 选择平均响应时间最短的服务器
        server = min(available_servers, key=lambda s: s.avg_response_time or float('inf'))
        server.increment_connections()
        
        logger.debug(f"选择最快响应服务器: {server.endpoint}, 响应时间: {server.avg_response_time}ms")
        return server


class ConsistentHashBalancer(LoadBalancer):
    """
    一致性哈希负载均衡器
    
    使用一致性哈希算法选择服务器，确保相同的请求总是路由到同一台服务器。
    """
    
    def __init__(self, virtual_nodes: int = 150, **kwargs):
        """
        初始化一致性哈希均衡器
        
        Args:
            virtual_nodes: 每个实际节点对应的虚拟节点数
        """
        super().__init__(**kwargs)
        self.virtual_nodes = virtual_nodes
        self._hash_ring: List[int] = []
        self._ring_nodes: Dict[int, ServerNode] = {}
        self._rebuild_ring()
    
    def add_server(self, server: ServerNode) -> None:
        """添加服务器并重建哈希环"""
        super().add_server(server)
        self._rebuild_ring()
    
    def remove_server(self, endpoint: str) -> None:
        """移除服务器并重建哈希环"""
        super().remove_server(endpoint)
        self._rebuild_ring()
    
    def _rebuild_ring(self) -> None:
        """重建哈希环"""
        self._hash_ring.clear()
        self._ring_nodes.clear()
        
        for server in self.servers.values():
            if server.is_available:
                for i in range(self.virtual_nodes):
                    # 为每个虚拟节点计算哈希值
                    virtual_key = f"{server.endpoint}:{i}"
                    hash_value = self._hash_function(virtual_key)
                    
                    self._hash_ring.append(hash_value)
                    self._ring_nodes[hash_value] = server
        
        # 保持哈希环有序
        self._hash_ring.sort()
        
        logger.debug(f"重建哈希环，虚拟节点数: {len(self._hash_ring)}")
    
    def _hash_function(self, key: str) -> int:
        """
        哈希函数
        
        Args:
            key: 要哈希的键
            
        Returns:
            int: 哈希值
        """
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
    
    async def select_server(self, request_context: Optional[Dict[str, Any]] = None) -> ServerNode:
        """
        使用一致性哈希选择服务器
        
        Args:
            request_context: 请求上下文，需要包含用于哈希的键
            
        Returns:
            ServerNode: 选中的服务器
        """
        available_servers = self.get_available_servers()
        
        if not available_servers:
            raise GrpcServiceUnavailableError(
                "无可用服务器",
                available_servers=0
            )
        
        # 获取哈希键
        hash_key = self._get_hash_key(request_context)
        hash_value = self._hash_function(hash_key)
        
        # 在哈希环中找到对应的节点
        if not self._hash_ring:
            # 如果哈希环为空，降级为随机选择
            server = random.choice(available_servers)
        else:
            # 在哈希环中查找最近的节点
            index = bisect.bisect_right(self._hash_ring, hash_value)
            if index == len(self._hash_ring):
                index = 0
            
            ring_hash = self._hash_ring[index]
            server = self._ring_nodes[ring_hash]
            
            # 检查选中的服务器是否可用
            if not (server.is_healthy and server.is_available):
                # 如果不可用，降级为随机选择
                server = random.choice(available_servers)
        
        server.increment_connections()
        
        logger.debug(f"一致性哈希选择服务器: {server.endpoint}, 哈希键: {hash_key}")
        return server
    
    def _get_hash_key(self, request_context: Optional[Dict[str, Any]]) -> str:
        """
        从请求上下文中获取哈希键
        
        Args:
            request_context: 请求上下文
            
        Returns:
            str: 哈希键
        """
        if not request_context:
            return "default"
        
        # 尝试从上下文中获取不同的键
        for key in ["user_id", "session_id", "client_id", "trace_id"]:
            if key in request_context:
                return str(request_context[key])
        
        # 如果没有找到合适的键，使用默认值
        return "default"


class LoadBalancerFactory:
    """负载均衡器工厂"""
    
    _strategies = {
        LoadBalanceStrategy.ROUND_ROBIN: RoundRobinBalancer,
        LoadBalanceStrategy.RANDOM: RandomBalancer,
        LoadBalanceStrategy.WEIGHTED_RANDOM: WeightedRandomBalancer,
        LoadBalanceStrategy.LEAST_CONNECTIONS: LeastConnectionBalancer,
        LoadBalanceStrategy.CONSISTENT_HASH: ConsistentHashBalancer,
        LoadBalanceStrategy.FASTEST_RESPONSE: FastestResponseBalancer,
    }
    
    @classmethod
    def create(
        self,
        strategy: LoadBalanceStrategy,
        servers: Optional[List[ServerNode]] = None,
        **kwargs
    ) -> LoadBalancer:
        """
        创建负载均衡器
        
        Args:
            strategy: 负载均衡策略
            servers: 服务器节点列表
            **kwargs: 其他参数
            
        Returns:
            LoadBalancer: 负载均衡器实例
        """
        if strategy not in self._strategies:
            raise GrpcConfigurationError(f"不支持的负载均衡策略: {strategy}")
        
        balancer_class = self._strategies[strategy]
        return balancer_class(servers=servers, **kwargs)
    
    @classmethod
    def register_strategy(
        cls,
        strategy: LoadBalanceStrategy,
        balancer_class: type
    ) -> None:
        """
        注册自定义负载均衡策略
        
        Args:
            strategy: 策略枚举
            balancer_class: 均衡器类
        """
        cls._strategies[strategy] = balancer_class
        logger.info(f"注册负载均衡策略: {strategy.value}")


class ConnectionAwareProxy:
    """
    连接感知代理
    
    封装选中的服务器节点，自动管理连接计数。
    """
    
    def __init__(self, server: ServerNode, balancer: LoadBalancer):
        """
        初始化连接代理
        
        Args:
            server: 服务器节点
            balancer: 负载均衡器
        """
        self.server = server
        self.balancer = balancer
        self._released = False
    
    async def release(self) -> None:
        """释放连接"""
        if not self._released:
            self.server.decrement_connections()
            self._released = True
    
    def record_request(self, success: bool, response_time: float = 0.0) -> None:
        """记录请求结果"""
        self.balancer.record_request(self.server.endpoint, success, response_time)
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.release()
        
        # 记录请求结果
        success = exc_type is None
        self.record_request(success)
        
        # 如果请求失败，标记服务器可能不健康
        if not success:
            await self.balancer.mark_server_unhealthy(self.server.endpoint)
    
    def __getattr__(self, name):
        """代理服务器节点属性"""
        return getattr(self.server, name)