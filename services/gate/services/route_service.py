"""
路由服务

该模块负责管理请求路由，动态发现后端服务，提供路由规则管理、
服务发现、负载均衡等功能。

主要功能：
- 管理请求路由
- 动态发现后端服务
- 负载均衡策略
- 健康检查
- 路由规则管理
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import random

from common.logger import logger
from common.grpc import create_client
from ..config import GatewayConfig, BackendService, LoadBalanceStrategy


@dataclass
class ServiceNode:
    """服务节点"""
    service_name: str
    host: str
    port: int
    weight: int = 100
    is_healthy: bool = True
    last_check: float = 0.0
    response_time: float = 0.0
    error_count: int = 0
    request_count: int = 0
    
    def update_health(self, is_healthy: bool, response_time: float = 0.0):
        """更新健康状态"""
        self.is_healthy = is_healthy
        self.last_check = time.time()
        self.response_time = response_time
        
    def add_request_stat(self, success: bool, response_time: float):
        """添加请求统计"""
        self.request_count += 1
        if success:
            self.response_time = (self.response_time + response_time) / 2
        else:
            self.error_count += 1
            
    def get_score(self) -> float:
        """获取节点评分（用于负载均衡）"""
        if not self.is_healthy:
            return 0.0
        
        # 基础分数是权重
        score = self.weight
        
        # 根据响应时间调整分数
        if self.response_time > 0:
            score = score / (1 + self.response_time)
        
        # 根据错误率调整分数
        if self.request_count > 0:
            error_rate = self.error_count / self.request_count
            score = score * (1 - error_rate)
        
        return max(score, 0.0)


class RouteService:
    """路由服务"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化路由服务
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.service_nodes: Dict[str, List[ServiceNode]] = {}
        self.grpc_clients: Dict[str, Any] = {}
        self.load_balance_strategy = config.load_balance_strategy
        
        # 健康检查
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30  # 30秒检查一次
        
        # 统计信息
        self._total_requests = 0
        self._failed_requests = 0
        self._last_discovery_time = 0
        
        logger.info("路由服务初始化完成")
        
    async def initialize(self):
        """初始化路由服务"""
        # 初始化服务节点
        await self._init_service_nodes()
        
        # 初始化gRPC客户端
        await self._init_grpc_clients()
        
        logger.info("路由服务初始化完成")
        
    async def start(self):
        """启动路由服务"""
        # 启动健康检查任务
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        logger.info("路由服务启动完成")
        
    async def stop(self):
        """停止路由服务"""
        # 停止健康检查任务
        if self._health_check_task:
            self._health_check_task.cancel()
            
        # 关闭gRPC客户端
        await self._close_grpc_clients()
        
        logger.info("路由服务停止完成")
        
    async def discover_service(self, service_name: str) -> Optional[ServiceNode]:
        """
        发现服务节点
        
        Args:
            service_name: 服务名称
            
        Returns:
            ServiceNode: 服务节点，如果没有可用节点则返回None
        """
        if service_name not in self.service_nodes:
            logger.warning("服务不存在", service_name=service_name)
            return None
            
        nodes = self.service_nodes[service_name]
        healthy_nodes = [node for node in nodes if node.is_healthy]
        
        if not healthy_nodes:
            logger.warning("没有可用的服务节点", service_name=service_name)
            return None
            
        # 根据负载均衡策略选择节点
        selected_node = await self._select_node(healthy_nodes)
        
        logger.debug("选择服务节点", 
                    service_name=service_name,
                    node_host=selected_node.host,
                    node_port=selected_node.port)
        
        return selected_node
        
    async def get_service_client(self, service_name: str) -> Optional[Any]:
        """
        获取服务的gRPC客户端
        
        Args:
            service_name: 服务名称
            
        Returns:
            gRPC客户端实例
        """
        if service_name not in self.grpc_clients:
            # 尝试创建新的客户端
            await self._create_grpc_client(service_name)
            
        return self.grpc_clients.get(service_name)
        
    async def add_service_node(self, service_name: str, host: str, port: int, weight: int = 100):
        """
        添加服务节点
        
        Args:
            service_name: 服务名称
            host: 主机地址
            port: 端口
            weight: 权重
        """
        node = ServiceNode(
            service_name=service_name,
            host=host,
            port=port,
            weight=weight
        )
        
        if service_name not in self.service_nodes:
            self.service_nodes[service_name] = []
            
        self.service_nodes[service_name].append(node)
        
        # 创建对应的gRPC客户端
        await self._create_grpc_client(service_name)
        
        logger.info("添加服务节点", 
                   service_name=service_name,
                   host=host,
                   port=port,
                   weight=weight)
        
    async def remove_service_node(self, service_name: str, host: str, port: int):
        """
        移除服务节点
        
        Args:
            service_name: 服务名称
            host: 主机地址
            port: 端口
        """
        if service_name not in self.service_nodes:
            return
            
        nodes = self.service_nodes[service_name]
        self.service_nodes[service_name] = [
            node for node in nodes 
            if not (node.host == host and node.port == port)
        ]
        
        # 如果没有节点了，移除gRPC客户端
        if not self.service_nodes[service_name]:
            del self.service_nodes[service_name]
            if service_name in self.grpc_clients:
                del self.grpc_clients[service_name]
                
        logger.info("移除服务节点", 
                   service_name=service_name,
                   host=host,
                   port=port)
        
    async def update_node_stats(self, service_name: str, host: str, port: int, 
                              success: bool, response_time: float):
        """
        更新节点统计信息
        
        Args:
            service_name: 服务名称
            host: 主机地址
            port: 端口
            success: 是否成功
            response_time: 响应时间
        """
        if service_name not in self.service_nodes:
            return
            
        for node in self.service_nodes[service_name]:
            if node.host == host and node.port == port:
                node.add_request_stat(success, response_time)
                break
                
    def get_service_list(self) -> List[str]:
        """获取服务列表"""
        return list(self.service_nodes.keys())
        
    def get_service_nodes(self, service_name: str) -> List[ServiceNode]:
        """获取服务节点列表"""
        return self.service_nodes.get(service_name, [])
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        service_stats = {}
        for service_name, nodes in self.service_nodes.items():
            healthy_count = sum(1 for node in nodes if node.is_healthy)
            total_requests = sum(node.request_count for node in nodes)
            total_errors = sum(node.error_count for node in nodes)
            avg_response_time = sum(node.response_time for node in nodes) / len(nodes) if nodes else 0
            
            service_stats[service_name] = {
                "total_nodes": len(nodes),
                "healthy_nodes": healthy_count,
                "total_requests": total_requests,
                "total_errors": total_errors,
                "avg_response_time": avg_response_time
            }
            
        return {
            "services": service_stats,
            "total_requests": self._total_requests,
            "failed_requests": self._failed_requests,
            "success_rate": 1 - (self._failed_requests / self._total_requests) if self._total_requests > 0 else 0,
            "last_discovery_time": self._last_discovery_time
        }
        
    async def _init_service_nodes(self):
        """初始化服务节点"""
        for service_name, service_config in self.config.backend_services.items():
            await self.add_service_node(
                service_name=service_name,
                host=service_config.host,
                port=service_config.port,
                weight=service_config.weight
            )
            
    async def _init_grpc_clients(self):
        """初始化gRPC客户端"""
        for service_name in self.service_nodes.keys():
            await self._create_grpc_client(service_name)
            
    async def _create_grpc_client(self, service_name: str):
        """创建gRPC客户端"""
        if service_name not in self.service_nodes:
            return
            
        nodes = self.service_nodes[service_name]
        if not nodes:
            return
            
        # 构造端点列表
        endpoints = [f"{node.host}:{node.port}" for node in nodes]
        
        try:
            # 创建gRPC客户端
            client = await create_client(
                service_name=service_name,
                endpoints=endpoints
            )
            
            self.grpc_clients[service_name] = client
            
            logger.info("创建gRPC客户端成功", 
                       service_name=service_name,
                       endpoints=endpoints)
            
        except Exception as e:
            logger.error("创建gRPC客户端失败", 
                        service_name=service_name,
                        error=str(e))
            
    async def _close_grpc_clients(self):
        """关闭gRPC客户端"""
        for service_name, client in self.grpc_clients.items():
            try:
                if hasattr(client, 'close'):
                    await client.close()
            except Exception as e:
                logger.error("关闭gRPC客户端失败", 
                           service_name=service_name,
                           error=str(e))
                
        self.grpc_clients.clear()
        
    async def _select_node(self, nodes: List[ServiceNode]) -> ServiceNode:
        """
        选择节点（负载均衡）
        
        Args:
            nodes: 可用节点列表
            
        Returns:
            ServiceNode: 选择的节点
        """
        if not nodes:
            raise ValueError("没有可用节点")
            
        if len(nodes) == 1:
            return nodes[0]
            
        if self.load_balance_strategy == LoadBalanceStrategy.ROUND_ROBIN:
            # 轮询
            return await self._round_robin_select(nodes)
        elif self.load_balance_strategy == LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN:
            # 加权轮询
            return await self._weighted_round_robin_select(nodes)
        elif self.load_balance_strategy == LoadBalanceStrategy.LEAST_CONNECTIONS:
            # 最少连接
            return await self._least_connections_select(nodes)
        elif self.load_balance_strategy == LoadBalanceStrategy.RANDOM:
            # 随机
            return random.choice(nodes)
        else:
            # 默认随机
            return random.choice(nodes)
            
    async def _round_robin_select(self, nodes: List[ServiceNode]) -> ServiceNode:
        """轮询选择"""
        # 简单实现，实际应该维护每个服务的轮询状态
        return nodes[int(time.time()) % len(nodes)]
        
    async def _weighted_round_robin_select(self, nodes: List[ServiceNode]) -> ServiceNode:
        """加权轮询选择"""
        # 根据权重创建选择池
        weighted_nodes = []
        for node in nodes:
            weighted_nodes.extend([node] * node.weight)
            
        if not weighted_nodes:
            return nodes[0]
            
        return random.choice(weighted_nodes)
        
    async def _least_connections_select(self, nodes: List[ServiceNode]) -> ServiceNode:
        """最少连接选择"""
        # 根据评分选择最佳节点
        best_node = max(nodes, key=lambda n: n.get_score())
        return best_node
        
    async def _health_check_loop(self):
        """健康检查循环"""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._check_all_nodes_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("健康检查失败", error=str(e))
                
    async def _check_all_nodes_health(self):
        """检查所有节点健康状态"""
        for service_name, nodes in self.service_nodes.items():
            for node in nodes:
                await self._check_node_health(node)
                
    async def _check_node_health(self, node: ServiceNode):
        """检查单个节点健康状态"""
        try:
            start_time = time.time()
            
            # 这里应该调用实际的健康检查API
            # 暂时使用简单的连接测试
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((node.host, node.port))
            sock.close()
            
            response_time = time.time() - start_time
            is_healthy = result == 0
            
            node.update_health(is_healthy, response_time)
            
            if not is_healthy:
                logger.warning("节点健康检查失败", 
                             service_name=node.service_name,
                             host=node.host,
                             port=node.port)
                
        except Exception as e:
            node.update_health(False, 0.0)
            logger.error("节点健康检查异常", 
                        service_name=node.service_name,
                        host=node.host,
                        port=node.port,
                        error=str(e))