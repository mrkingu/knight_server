"""
gRPC负载均衡模块

该模块实现了多种负载均衡策略，包括轮询、随机、最少连接、一致性哈希等。
支持权重配置、故障节点自动剔除和健康检查集成。
"""

import asyncio
import time
import random
import hashlib
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum
from collections import defaultdict
import bisect

from .exceptions import GrpcLoadBalancerError, GrpcServiceUnavailableError
from .health_check import HealthStatus


class LoadBalancerStrategy(Enum):
    """负载均衡策略枚举"""
    ROUND_ROBIN = "round_robin"         # 轮询
    RANDOM = "random"                   # 随机
    LEAST_CONNECTION = "least_connection"  # 最少连接
    CONSISTENT_HASH = "consistent_hash"    # 一致性哈希
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"  # 加权轮询
    WEIGHTED_RANDOM = "weighted_random"    # 加权随机


@dataclass
class NodeInfo:
    """节点信息"""
    # 基本信息
    endpoint: str                       # 节点地址
    weight: int = 100                   # 权重(1-100)
    
    # 状态信息
    is_healthy: bool = True             # 是否健康
    is_available: bool = True           # 是否可用
    
    # 连接信息
    active_connections: int = 0         # 活跃连接数
    total_connections: int = 0          # 总连接数
    
    # 性能信息
    avg_response_time: float = 0.0      # 平均响应时间(毫秒)
    success_rate: float = 1.0           # 成功率
    last_request_time: float = 0.0      # 最后请求时间
    
    # 故障信息
    failure_count: int = 0              # 故障次数
    last_failure_time: float = 0.0      # 最后故障时间
    circuit_breaker_open: bool = False  # 熔断器状态
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)
    
    @property
    def load_factor(self) -> float:
        """负载因子（连接数/权重）"""
        if self.weight == 0:
            return float('inf')
        return self.active_connections / self.weight
    
    @property
    def is_usable(self) -> bool:
        """是否可用"""
        return (
            self.is_healthy and 
            self.is_available and 
            not self.circuit_breaker_open
        )
    
    def update_request_stats(self, success: bool, response_time: float):
        """更新请求统计"""
        self.last_request_time = time.time()
        
        if success:
            # 更新成功率（简单移动平均）
            self.success_rate = self.success_rate * 0.9 + 0.1
            # 更新平均响应时间
            if self.avg_response_time == 0:
                self.avg_response_time = response_time
            else:
                self.avg_response_time = self.avg_response_time * 0.9 + response_time * 0.1
        else:
            self.failure_count += 1
            self.last_failure_time = time.time()
            self.success_rate = self.success_rate * 0.9
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'endpoint': self.endpoint,
            'weight': self.weight,
            'is_healthy': self.is_healthy,
            'is_available': self.is_available,
            'is_usable': self.is_usable,
            'active_connections': self.active_connections,
            'total_connections': self.total_connections,
            'avg_response_time': self.avg_response_time,
            'success_rate': self.success_rate,
            'last_request_time': self.last_request_time,
            'failure_count': self.failure_count,
            'last_failure_time': self.last_failure_time,
            'circuit_breaker_open': self.circuit_breaker_open,
            'load_factor': self.load_factor,
            'metadata': self.metadata,
            'tags': self.tags
        }


@dataclass
class LoadBalancerConfig:
    """负载均衡配置"""
    # 基本配置
    strategy: LoadBalancerStrategy = LoadBalancerStrategy.ROUND_ROBIN
    
    # 健康检查配置
    enable_health_check: bool = True     # 启用健康检查
    health_check_interval: float = 30.0  # 健康检查间隔(秒)
    
    # 故障检测配置
    failure_threshold: int = 3           # 故障阈值
    recovery_threshold: int = 2          # 恢复阈值
    circuit_breaker_timeout: float = 60.0  # 熔断器超时(秒)
    
    # 一致性哈希配置
    virtual_nodes: int = 100             # 虚拟节点数
    hash_function: str = "md5"           # 哈希函数
    
    # 权重配置
    default_weight: int = 100            # 默认权重
    max_weight: int = 1000               # 最大权重
    min_weight: int = 1                  # 最小权重
    
    # 性能配置
    enable_metrics: bool = True          # 启用指标收集
    sticky_sessions: bool = False        # 启用会话保持


class LoadBalancer(ABC):
    """负载均衡器基类"""
    
    def __init__(self, config: LoadBalancerConfig):
        self.config = config
        self._nodes: Dict[str, NodeInfo] = {}
        self._lock = asyncio.Lock()
        
        # 统计信息
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        
        # 回调函数
        self._on_node_selected: Optional[Callable[[NodeInfo], None]] = None
        self._on_node_failed: Optional[Callable[[NodeInfo], None]] = None
        self._on_node_recovered: Optional[Callable[[NodeInfo], None]] = None
    
    def set_callbacks(
        self,
        on_node_selected: Optional[Callable[[NodeInfo], None]] = None,
        on_node_failed: Optional[Callable[[NodeInfo], None]] = None,
        on_node_recovered: Optional[Callable[[NodeInfo], None]] = None
    ):
        """设置回调函数"""
        self._on_node_selected = on_node_selected
        self._on_node_failed = on_node_failed
        self._on_node_recovered = on_node_recovered
    
    async def add_node(
        self,
        endpoint: str,
        weight: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        添加节点
        
        Args:
            endpoint: 节点地址
            weight: 权重
            metadata: 元数据
            tags: 标签
            
        Returns:
            bool: 是否添加成功
        """
        async with self._lock:
            if endpoint in self._nodes:
                return False
            
            node = NodeInfo(
                endpoint=endpoint,
                weight=weight or self.config.default_weight,
                metadata=metadata or {},
                tags=tags or {}
            )
            
            self._nodes[endpoint] = node
            await self._on_node_added(node)
            return True
    
    async def remove_node(self, endpoint: str) -> bool:
        """
        移除节点
        
        Args:
            endpoint: 节点地址
            
        Returns:
            bool: 是否移除成功
        """
        async with self._lock:
            node = self._nodes.pop(endpoint, None)
            if node:
                await self._on_node_removed(node)
                return True
            return False
    
    async def update_node_weight(self, endpoint: str, weight: int) -> bool:
        """
        更新节点权重
        
        Args:
            endpoint: 节点地址
            weight: 新权重
            
        Returns:
            bool: 是否更新成功
        """
        async with self._lock:
            if endpoint in self._nodes:
                weight = max(self.config.min_weight, min(self.config.max_weight, weight))
                self._nodes[endpoint].weight = weight
                await self._on_node_weight_updated(self._nodes[endpoint])
                return True
            return False
    
    async def update_node_health(self, endpoint: str, is_healthy: bool):
        """
        更新节点健康状态
        
        Args:
            endpoint: 节点地址
            is_healthy: 是否健康
        """
        async with self._lock:
            if endpoint in self._nodes:
                node = self._nodes[endpoint]
                old_status = node.is_healthy
                node.is_healthy = is_healthy
                
                if old_status != is_healthy:
                    if is_healthy and self._on_node_recovered:
                        self._on_node_recovered(node)
                    elif not is_healthy and self._on_node_failed:
                        self._on_node_failed(node)
    
    async def get_available_nodes(self) -> List[NodeInfo]:
        """获取可用节点列表"""
        async with self._lock:
            return [node for node in self._nodes.values() if node.is_usable]
    
    async def get_node(self, endpoint: str) -> Optional[NodeInfo]:
        """获取节点信息"""
        return self._nodes.get(endpoint)
    
    async def get_all_nodes(self) -> List[NodeInfo]:
        """获取所有节点"""
        return list(self._nodes.values())
    
    @abstractmethod
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """
        选择节点
        
        Args:
            key: 选择键（用于一致性哈希等）
            
        Returns:
            Optional[NodeInfo]: 选中的节点
        """
        pass
    
    async def _on_node_added(self, node: NodeInfo):
        """节点添加后的处理"""
        pass
    
    async def _on_node_removed(self, node: NodeInfo):
        """节点移除后的处理"""
        pass
    
    async def _on_node_weight_updated(self, node: NodeInfo):
        """节点权重更新后的处理"""
        pass
    
    async def record_request_result(
        self,
        endpoint: str,
        success: bool,
        response_time: float = 0.0
    ):
        """
        记录请求结果
        
        Args:
            endpoint: 节点地址
            success: 是否成功
            response_time: 响应时间(毫秒)
        """
        async with self._lock:
            # 更新全局统计
            self._total_requests += 1
            if success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
            
            # 更新节点统计
            if endpoint in self._nodes:
                node = self._nodes[endpoint]
                node.update_request_stats(success, response_time)
                
                # 检查是否需要熔断
                if not success:
                    await self._check_circuit_breaker(node)
    
    async def _check_circuit_breaker(self, node: NodeInfo):
        """检查熔断器"""
        if (
            node.failure_count >= self.config.failure_threshold and
            not node.circuit_breaker_open
        ):
            node.circuit_breaker_open = True
            if self._on_node_failed:
                self._on_node_failed(node)
    
    async def _check_circuit_breaker_recovery(self, node: NodeInfo) -> bool:
        """检查熔断器恢复"""
        if (
            node.circuit_breaker_open and
            time.time() - node.last_failure_time > self.config.circuit_breaker_timeout
        ):
            node.circuit_breaker_open = False
            node.failure_count = 0
            if self._on_node_recovered:
                self._on_node_recovered(node)
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        success_rate = 0.0
        if self._total_requests > 0:
            success_rate = self._successful_requests / self._total_requests
        
        return {
            'strategy': self.config.strategy.value,
            'total_nodes': len(self._nodes),
            'available_nodes': len([n for n in self._nodes.values() if n.is_usable]),
            'total_requests': self._total_requests,
            'successful_requests': self._successful_requests,
            'failed_requests': self._failed_requests,
            'success_rate': success_rate,
            'nodes': {endpoint: node.to_dict() for endpoint, node in self._nodes.items()}
        }


class RoundRobinBalancer(LoadBalancer):
    """轮询负载均衡器"""
    
    def __init__(self, config: LoadBalancerConfig):
        super().__init__(config)
        self._current_index = 0
    
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """轮询选择节点"""
        available_nodes = await self.get_available_nodes()
        if not available_nodes:
            return None
        
        async with self._lock:
            if self._current_index >= len(available_nodes):
                self._current_index = 0
            
            node = available_nodes[self._current_index]
            self._current_index = (self._current_index + 1) % len(available_nodes)
            
            if self._on_node_selected:
                self._on_node_selected(node)
            
            return node


class RandomBalancer(LoadBalancer):
    """随机负载均衡器"""
    
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """随机选择节点"""
        available_nodes = await self.get_available_nodes()
        if not available_nodes:
            return None
        
        node = random.choice(available_nodes)
        
        if self._on_node_selected:
            self._on_node_selected(node)
        
        return node


class LeastConnectionBalancer(LoadBalancer):
    """最少连接负载均衡器"""
    
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """选择连接数最少的节点"""
        available_nodes = await self.get_available_nodes()
        if not available_nodes:
            return None
        
        # 选择负载因子最小的节点
        node = min(available_nodes, key=lambda x: x.load_factor)
        
        if self._on_node_selected:
            self._on_node_selected(node)
        
        return node


class ConsistentHashBalancer(LoadBalancer):
    """一致性哈希负载均衡器"""
    
    def __init__(self, config: LoadBalancerConfig):
        super().__init__(config)
        self._hash_ring: List[Tuple[int, str]] = []  # (hash_value, endpoint)
        self._virtual_nodes = config.virtual_nodes
        self._hash_func = self._get_hash_function(config.hash_function)
    
    def _get_hash_function(self, name: str) -> Callable[[str], int]:
        """获取哈希函数"""
        if name == "md5":
            def md5_hash(data: str) -> int:
                return int(hashlib.md5(data.encode()).hexdigest(), 16)
            return md5_hash
        elif name == "sha1":
            def sha1_hash(data: str) -> int:
                return int(hashlib.sha1(data.encode()).hexdigest(), 16)
            return sha1_hash
        else:
            # 默认使用Python内置hash
            return lambda data: hash(data)
    
    async def _rebuild_hash_ring(self):
        """重建哈希环"""
        self._hash_ring.clear()
        
        for endpoint, node in self._nodes.items():
            if node.is_usable:
                # 为每个节点创建虚拟节点
                for i in range(self._virtual_nodes):
                    virtual_key = f"{endpoint}:{i}"
                    hash_value = self._hash_func(virtual_key)
                    self._hash_ring.append((hash_value, endpoint))
        
        # 按哈希值排序
        self._hash_ring.sort()
    
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """基于一致性哈希选择节点"""
        if not self._hash_ring:
            await self._rebuild_hash_ring()
        
        if not self._hash_ring:
            return None
        
        # 如果没有提供key，使用随机key
        if key is None:
            key = str(random.random())
        
        # 计算key的哈希值
        hash_value = self._hash_func(key)
        
        # 在哈希环中查找第一个大于等于hash_value的节点
        index = bisect.bisect_left(self._hash_ring, (hash_value, ""))
        
        # 如果没找到，使用第一个节点（环形结构）
        if index >= len(self._hash_ring):
            index = 0
        
        endpoint = self._hash_ring[index][1]
        node = self._nodes.get(endpoint)
        
        if node and node.is_usable:
            if self._on_node_selected:
                self._on_node_selected(node)
            return node
        
        # 如果选中的节点不可用，尝试下一个
        for i in range(1, len(self._hash_ring)):
            next_index = (index + i) % len(self._hash_ring)
            endpoint = self._hash_ring[next_index][1]
            node = self._nodes.get(endpoint)
            
            if node and node.is_usable:
                if self._on_node_selected:
                    self._on_node_selected(node)
                return node
        
        return None
    
    async def _on_node_added(self, node: NodeInfo):
        """节点添加后重建哈希环"""
        await self._rebuild_hash_ring()
    
    async def _on_node_removed(self, node: NodeInfo):
        """节点移除后重建哈希环"""
        await self._rebuild_hash_ring()


class WeightedRoundRobinBalancer(LoadBalancer):
    """加权轮询负载均衡器"""
    
    def __init__(self, config: LoadBalancerConfig):
        super().__init__(config)
        self._current_weights: Dict[str, int] = {}
    
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """加权轮询选择节点"""
        available_nodes = await self.get_available_nodes()
        if not available_nodes:
            return None
        
        async with self._lock:
            # 计算当前权重
            total_weight = 0
            max_current_weight = -1
            selected_node = None
            
            for node in available_nodes:
                endpoint = node.endpoint
                
                # 初始化当前权重
                if endpoint not in self._current_weights:
                    self._current_weights[endpoint] = 0
                
                # 增加当前权重
                self._current_weights[endpoint] += node.weight
                total_weight += node.weight
                
                # 找到当前权重最大的节点
                if self._current_weights[endpoint] > max_current_weight:
                    max_current_weight = self._current_weights[endpoint]
                    selected_node = node
            
            # 减少选中节点的当前权重
            if selected_node:
                self._current_weights[selected_node.endpoint] -= total_weight
                
                if self._on_node_selected:
                    self._on_node_selected(selected_node)
            
            return selected_node


class WeightedRandomBalancer(LoadBalancer):
    """加权随机负载均衡器"""
    
    async def select_node(self, key: Optional[str] = None) -> Optional[NodeInfo]:
        """加权随机选择节点"""
        available_nodes = await self.get_available_nodes()
        if not available_nodes:
            return None
        
        # 计算总权重
        total_weight = sum(node.weight for node in available_nodes)
        if total_weight == 0:
            return random.choice(available_nodes)
        
        # 生成随机数
        rand_value = random.randint(1, total_weight)
        
        # 选择节点
        current_weight = 0
        for node in available_nodes:
            current_weight += node.weight
            if rand_value <= current_weight:
                if self._on_node_selected:
                    self._on_node_selected(node)
                return node
        
        # 理论上不应该到达这里
        return available_nodes[-1]


class LoadBalancerManager:
    """负载均衡器管理器"""
    
    def __init__(self):
        self._balancers: Dict[str, LoadBalancer] = {}
        self._lock = asyncio.Lock()
    
    async def create_balancer(
        self,
        name: str,
        strategy: LoadBalancerStrategy,
        config: Optional[LoadBalancerConfig] = None
    ) -> LoadBalancer:
        """
        创建负载均衡器
        
        Args:
            name: 负载均衡器名称
            strategy: 负载均衡策略
            config: 配置
            
        Returns:
            LoadBalancer: 负载均衡器实例
        """
        if config is None:
            config = LoadBalancerConfig(strategy=strategy)
        else:
            config.strategy = strategy
        
        # 根据策略创建相应的负载均衡器
        balancer_class = {
            LoadBalancerStrategy.ROUND_ROBIN: RoundRobinBalancer,
            LoadBalancerStrategy.RANDOM: RandomBalancer,
            LoadBalancerStrategy.LEAST_CONNECTION: LeastConnectionBalancer,
            LoadBalancerStrategy.CONSISTENT_HASH: ConsistentHashBalancer,
            LoadBalancerStrategy.WEIGHTED_ROUND_ROBIN: WeightedRoundRobinBalancer,
            LoadBalancerStrategy.WEIGHTED_RANDOM: WeightedRandomBalancer
        }
        
        if strategy not in balancer_class:
            raise GrpcLoadBalancerError(
                message=f"不支持的负载均衡策略: {strategy.value}",
                strategy=strategy.value
            )
        
        async with self._lock:
            if name in self._balancers:
                raise GrpcLoadBalancerError(
                    message=f"负载均衡器已存在: {name}",
                    strategy=strategy.value
                )
            
            balancer = balancer_class[strategy](config)
            self._balancers[name] = balancer
            return balancer
    
    async def get_balancer(self, name: str) -> Optional[LoadBalancer]:
        """获取负载均衡器"""
        return self._balancers.get(name)
    
    async def remove_balancer(self, name: str) -> bool:
        """移除负载均衡器"""
        async with self._lock:
            return self._balancers.pop(name, None) is not None
    
    async def list_balancers(self) -> List[str]:
        """列出所有负载均衡器名称"""
        return list(self._balancers.keys())
    
    async def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有负载均衡器的统计信息"""
        return {
            name: balancer.get_stats()
            for name, balancer in self._balancers.items()
        }


# 全局负载均衡器管理器
_balancer_manager = LoadBalancerManager()


# 便捷函数
async def create_balancer(
    name: str,
    strategy: LoadBalancerStrategy,
    nodes: Optional[List[Tuple[str, int]]] = None,
    **kwargs
) -> LoadBalancer:
    """
    创建负载均衡器的便捷函数
    
    Args:
        name: 负载均衡器名称
        strategy: 负载均衡策略
        nodes: 节点列表 [(endpoint, weight), ...]
        **kwargs: 其他配置参数
    """
    config = LoadBalancerConfig(strategy=strategy, **kwargs)
    balancer = await _balancer_manager.create_balancer(name, strategy, config)
    
    # 添加节点
    if nodes:
        for endpoint, weight in nodes:
            await balancer.add_node(endpoint, weight)
    
    return balancer


async def get_balancer(name: str) -> Optional[LoadBalancer]:
    """获取负载均衡器"""
    return await _balancer_manager.get_balancer(name)


async def select_node(
    balancer_name: str,
    key: Optional[str] = None
) -> Optional[NodeInfo]:
    """
    选择节点
    
    Args:
        balancer_name: 负载均衡器名称
        key: 选择键
        
    Returns:
        Optional[NodeInfo]: 选中的节点
    """
    balancer = await get_balancer(balancer_name)
    if not balancer:
        raise GrpcLoadBalancerError(
            message=f"未找到负载均衡器: {balancer_name}",
            strategy="unknown"
        )
    
    return await balancer.select_node(key)


# 导出所有公共接口
__all__ = [
    'LoadBalancerStrategy',
    'NodeInfo',
    'LoadBalancerConfig',
    'LoadBalancer',
    'RoundRobinBalancer',
    'RandomBalancer',
    'LeastConnectionBalancer',
    'ConsistentHashBalancer',
    'WeightedRoundRobinBalancer',
    'WeightedRandomBalancer',
    'LoadBalancerManager',
    'create_balancer',
    'get_balancer',
    'select_node'
]