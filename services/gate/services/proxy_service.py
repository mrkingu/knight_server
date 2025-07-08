"""
代理服务

该模块负责代理请求到后端微服务（gRPC），提供统一的请求转发、
负载均衡、错误处理等功能。

主要功能：
- 代理请求到后端微服务（gRPC）
- 负载均衡和故障转移
- 请求响应转换
- 错误处理和重试
- 性能监控
"""

import asyncio
import time
import json
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum

from common.logger import logger
from common.grpc import create_client, GrpcClient
from common.proto import encode_message, decode_message
from ..config import GatewayConfig
from ..gate_handler import RequestContext
from .route_service import RouteService


class ProxyStrategy(Enum):
    """代理策略枚举"""
    DIRECT = "direct"        # 直接代理
    LOAD_BALANCE = "load_balance"  # 负载均衡
    CIRCUIT_BREAKER = "circuit_breaker"  # 熔断器
    RETRY = "retry"          # 重试


@dataclass
class ProxyRequest:
    """代理请求"""
    service_name: str
    method_name: str
    request_data: Any
    context: RequestContext
    timeout: float = 30.0
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "service_name": self.service_name,
            "method_name": self.method_name,
            "request_data": self.request_data,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        }


@dataclass
class ProxyResponse:
    """代理响应"""
    success: bool
    data: Any = None
    error_code: int = 0
    error_message: str = ""
    response_time: float = 0.0
    service_node: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "response_time": self.response_time,
            "service_node": self.service_node
        }


class ProxyService:
    """代理服务"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化代理服务
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.route_service: Optional[RouteService] = None
        
        # gRPC客户端缓存
        self.grpc_clients: Dict[str, GrpcClient] = {}
        
        # 代理策略
        self.proxy_strategies: Dict[str, ProxyStrategy] = {}
        
        # 熔断器状态
        self.circuit_breaker_states: Dict[str, Dict[str, Any]] = {}
        
        # 统计信息
        self._total_requests = 0
        self._success_requests = 0
        self._failed_requests = 0
        self._total_response_time = 0.0
        self._service_stats: Dict[str, Dict[str, Any]] = {}
        
        logger.info("代理服务初始化完成")
        
    async def initialize(self):
        """初始化代理服务"""
        # 初始化路由服务
        self.route_service = RouteService(self.config)
        await self.route_service.initialize()
        
        # 初始化gRPC客户端
        await self._init_grpc_clients()
        
        # 初始化代理策略
        await self._init_proxy_strategies()
        
        logger.info("代理服务初始化完成")
        
    async def start(self):
        """启动代理服务"""
        # 启动路由服务
        await self.route_service.start()
        
        logger.info("代理服务启动完成")
        
    async def stop(self):
        """停止代理服务"""
        # 停止路由服务
        if self.route_service:
            await self.route_service.stop()
            
        # 关闭gRPC客户端
        await self._close_grpc_clients()
        
        logger.info("代理服务停止完成")
        
    async def forward_request(self, 
                            service_name: str,
                            method_name: str,
                            request_data: Any,
                            context: RequestContext,
                            timeout: float = 30.0,
                            max_retries: int = 3) -> Dict[str, Any]:
        """
        转发请求到后端服务
        
        Args:
            service_name: 服务名称
            method_name: 方法名称
            request_data: 请求数据
            context: 请求上下文
            timeout: 超时时间
            max_retries: 最大重试次数
            
        Returns:
            Dict[str, Any]: 响应结果
        """
        start_time = time.time()
        
        try:
            # 创建代理请求
            proxy_request = ProxyRequest(
                service_name=service_name,
                method_name=method_name,
                request_data=request_data,
                context=context,
                timeout=timeout,
                max_retries=max_retries
            )
            
            # 更新统计
            self._total_requests += 1
            self._update_service_stats(service_name, "total_requests", 1)
            
            # 执行代理请求
            response = await self._execute_proxy_request(proxy_request)
            
            # 更新统计
            duration = time.time() - start_time
            self._total_response_time += duration
            response.response_time = duration
            
            if response.success:
                self._success_requests += 1
                self._update_service_stats(service_name, "success_requests", 1)
            else:
                self._failed_requests += 1
                self._update_service_stats(service_name, "failed_requests", 1)
                
            # 更新路由统计
            if self.route_service:
                # 解析服务节点信息
                node_info = response.service_node.split(":")
                if len(node_info) == 2:
                    host, port = node_info[0], int(node_info[1])
                    await self.route_service.update_node_stats(
                        service_name, host, port, response.success, duration
                    )
                    
            return response.to_dict()
            
        except Exception as e:
            # 更新失败统计
            self._failed_requests += 1
            self._update_service_stats(service_name, "failed_requests", 1)
            
            logger.error("转发请求失败", 
                        service_name=service_name,
                        method_name=method_name,
                        error=str(e))
            
            return {
                "success": False,
                "error_code": 500,
                "error_message": f"代理请求失败: {str(e)}",
                "response_time": time.time() - start_time
            }
            
    async def call_service_method(self,
                                service_name: str,
                                method_name: str,
                                request_data: Any,
                                timeout: float = 30.0) -> Dict[str, Any]:
        """
        调用服务方法
        
        Args:
            service_name: 服务名称
            method_name: 方法名称
            request_data: 请求数据
            timeout: 超时时间
            
        Returns:
            Dict[str, Any]: 响应结果
        """
        try:
            # 获取gRPC客户端
            client = await self._get_grpc_client(service_name)
            if not client:
                return {
                    "success": False,
                    "error_code": 404,
                    "error_message": f"服务不可用: {service_name}"
                }
                
            # 调用服务方法
            result = await client.call_method(method_name, request_data, timeout=timeout)
            
            return {
                "success": True,
                "data": result
            }
            
        except Exception as e:
            logger.error("调用服务方法失败", 
                        service_name=service_name,
                        method_name=method_name,
                        error=str(e))
            
            return {
                "success": False,
                "error_code": 500,
                "error_message": str(e)
            }
            
    async def check_service_health(self, service_name: str) -> bool:
        """
        检查服务健康状态
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否健康
        """
        try:
            # 获取服务节点
            service_node = await self.route_service.discover_service(service_name)
            if not service_node:
                return False
                
            # 调用健康检查方法
            result = await self.call_service_method(
                service_name=service_name,
                method_name="health_check",
                request_data={},
                timeout=5.0
            )
            
            return result.get("success", False)
            
        except Exception as e:
            logger.error("检查服务健康状态失败", 
                        service_name=service_name,
                        error=str(e))
            return False
            
    def get_service_statistics(self, service_name: str) -> Dict[str, Any]:
        """
        获取服务统计信息
        
        Args:
            service_name: 服务名称
            
        Returns:
            Dict[str, Any]: 统计信息
        """
        return self._service_stats.get(service_name, {
            "total_requests": 0,
            "success_requests": 0,
            "failed_requests": 0,
            "avg_response_time": 0.0,
            "circuit_breaker_state": "closed"
        })
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        avg_response_time = 0.0
        if self._total_requests > 0:
            avg_response_time = self._total_response_time / self._total_requests
            
        success_rate = 0.0
        if self._total_requests > 0:
            success_rate = self._success_requests / self._total_requests
            
        return {
            "total_requests": self._total_requests,
            "success_requests": self._success_requests,
            "failed_requests": self._failed_requests,
            "success_rate": success_rate,
            "avg_response_time": avg_response_time,
            "services": self._service_stats
        }
        
    async def _execute_proxy_request(self, proxy_request: ProxyRequest) -> ProxyResponse:
        """
        执行代理请求
        
        Args:
            proxy_request: 代理请求
            
        Returns:
            ProxyResponse: 代理响应
        """
        service_name = proxy_request.service_name
        
        # 检查熔断器状态
        if await self._is_circuit_breaker_open(service_name):
            return ProxyResponse(
                success=False,
                error_code=503,
                error_message="服务熔断中",
                service_node=service_name
            )
            
        # 获取代理策略
        strategy = self.proxy_strategies.get(service_name, ProxyStrategy.DIRECT)
        
        # 根据策略执行请求
        if strategy == ProxyStrategy.RETRY:
            return await self._execute_with_retry(proxy_request)
        elif strategy == ProxyStrategy.CIRCUIT_BREAKER:
            return await self._execute_with_circuit_breaker(proxy_request)
        else:
            return await self._execute_direct(proxy_request)
            
    async def _execute_direct(self, proxy_request: ProxyRequest) -> ProxyResponse:
        """
        直接执行代理请求
        
        Args:
            proxy_request: 代理请求
            
        Returns:
            ProxyResponse: 代理响应
        """
        try:
            # 发现服务节点
            service_node = await self.route_service.discover_service(proxy_request.service_name)
            if not service_node:
                return ProxyResponse(
                    success=False,
                    error_code=404,
                    error_message="服务不可用",
                    service_node=proxy_request.service_name
                )
                
            # 调用服务方法
            result = await self.call_service_method(
                service_name=proxy_request.service_name,
                method_name=proxy_request.method_name,
                request_data=proxy_request.request_data,
                timeout=proxy_request.timeout
            )
            
            return ProxyResponse(
                success=result.get("success", False),
                data=result.get("data"),
                error_code=result.get("error_code", 0),
                error_message=result.get("error_message", ""),
                service_node=f"{service_node.host}:{service_node.port}"
            )
            
        except Exception as e:
            return ProxyResponse(
                success=False,
                error_code=500,
                error_message=str(e),
                service_node=proxy_request.service_name
            )
            
    async def _execute_with_retry(self, proxy_request: ProxyRequest) -> ProxyResponse:
        """
        带重试的执行代理请求
        
        Args:
            proxy_request: 代理请求
            
        Returns:
            ProxyResponse: 代理响应
        """
        last_response = None
        
        for attempt in range(proxy_request.max_retries + 1):
            proxy_request.retry_count = attempt
            
            response = await self._execute_direct(proxy_request)
            
            if response.success:
                return response
            
            last_response = response
            
            # 如果不是最后一次尝试，等待一段时间再重试
            if attempt < proxy_request.max_retries:
                await asyncio.sleep(0.1 * (2 ** attempt))  # 指数退避
                
        return last_response
        
    async def _execute_with_circuit_breaker(self, proxy_request: ProxyRequest) -> ProxyResponse:
        """
        带熔断器的执行代理请求
        
        Args:
            proxy_request: 代理请求
            
        Returns:
            ProxyResponse: 代理响应
        """
        service_name = proxy_request.service_name
        
        # 执行请求
        response = await self._execute_direct(proxy_request)
        
        # 更新熔断器状态
        await self._update_circuit_breaker_state(service_name, response.success)
        
        return response
        
    async def _is_circuit_breaker_open(self, service_name: str) -> bool:
        """
        检查熔断器是否打开
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否打开
        """
        if not self.config.circuit_breaker.enabled:
            return False
            
        cb_state = self.circuit_breaker_states.get(service_name)
        if not cb_state:
            return False
            
        # 检查熔断器状态
        if cb_state["state"] == "open":
            # 检查是否可以切换到半开状态
            if time.time() - cb_state["last_failure_time"] > self.config.circuit_breaker.timeout:
                cb_state["state"] = "half_open"
                cb_state["half_open_requests"] = 0
                return False
            return True
            
        return False
        
    async def _update_circuit_breaker_state(self, service_name: str, success: bool):
        """
        更新熔断器状态
        
        Args:
            service_name: 服务名称
            success: 是否成功
        """
        if not self.config.circuit_breaker.enabled:
            return
            
        if service_name not in self.circuit_breaker_states:
            self.circuit_breaker_states[service_name] = {
                "state": "closed",
                "failure_count": 0,
                "success_count": 0,
                "last_failure_time": 0,
                "half_open_requests": 0
            }
            
        cb_state = self.circuit_breaker_states[service_name]
        
        if success:
            cb_state["success_count"] += 1
            cb_state["failure_count"] = 0
            
            # 半开状态下的成功处理
            if cb_state["state"] == "half_open":
                cb_state["half_open_requests"] += 1
                if cb_state["half_open_requests"] >= self.config.circuit_breaker.success_threshold:
                    cb_state["state"] = "closed"
                    cb_state["half_open_requests"] = 0
                    
        else:
            cb_state["failure_count"] += 1
            cb_state["last_failure_time"] = time.time()
            
            # 检查是否需要打开熔断器
            total_requests = cb_state["failure_count"] + cb_state["success_count"]
            if total_requests >= self.config.circuit_breaker.minimum_requests:
                failure_rate = cb_state["failure_count"] / total_requests * 100
                if failure_rate >= self.config.circuit_breaker.failure_threshold:
                    cb_state["state"] = "open"
                    
    async def _init_grpc_clients(self):
        """初始化gRPC客户端"""
        for service_name in self.config.backend_services.keys():
            await self._create_grpc_client(service_name)
            
    async def _create_grpc_client(self, service_name: str):
        """创建gRPC客户端"""
        try:
            service_config = self.config.backend_services.get(service_name)
            if not service_config:
                return
                
            # 创建客户端
            client = await create_client(
                service_name=service_name,
                endpoints=[f"{service_config.host}:{service_config.port}"]
            )
            
            self.grpc_clients[service_name] = client
            
            logger.info("创建gRPC客户端成功", 
                       service_name=service_name,
                       host=service_config.host,
                       port=service_config.port)
            
        except Exception as e:
            logger.error("创建gRPC客户端失败", 
                        service_name=service_name,
                        error=str(e))
            
    async def _get_grpc_client(self, service_name: str) -> Optional[GrpcClient]:
        """获取gRPC客户端"""
        client = self.grpc_clients.get(service_name)
        if not client:
            await self._create_grpc_client(service_name)
            client = self.grpc_clients.get(service_name)
        return client
        
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
        
    async def _init_proxy_strategies(self):
        """初始化代理策略"""
        # 根据配置设置代理策略
        for service_name in self.config.backend_services.keys():
            if self.config.circuit_breaker.enabled:
                self.proxy_strategies[service_name] = ProxyStrategy.CIRCUIT_BREAKER
            else:
                self.proxy_strategies[service_name] = ProxyStrategy.RETRY
                
    def _update_service_stats(self, service_name: str, metric: str, value: int):
        """更新服务统计"""
        if service_name not in self._service_stats:
            self._service_stats[service_name] = {
                "total_requests": 0,
                "success_requests": 0,
                "failed_requests": 0,
                "avg_response_time": 0.0,
                "circuit_breaker_state": "closed"
            }
            
        self._service_stats[service_name][metric] += value
        
        # 更新熔断器状态
        cb_state = self.circuit_breaker_states.get(service_name)
        if cb_state:
            self._service_stats[service_name]["circuit_breaker_state"] = cb_state["state"]