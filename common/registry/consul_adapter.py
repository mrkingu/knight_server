"""
Consul 适配器实现

基于 Consul 的服务注册发现实现，使用 aiohttp 与 Consul API 交互，
支持健康检查配置和服务变更通知。
"""

import asyncio
import json
import time
from typing import List, Dict, Optional, Any, AsyncIterator, Callable
from dataclasses import asdict
try:
    from loguru import logger
except ImportError:
    from ..logger.mock_logger import logger

try:
    import aiohttp
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    logger.warning("aiohttp 未安装，consul适配器将使用模拟模式")

from .base_adapter import BaseRegistryAdapter, ServiceInfo, ServiceStatus, WatchEvent
from .exceptions import (
    BaseRegistryException, RegistryConnectionError, RegistryTimeoutError,
    ServiceRegistrationError, ServiceDiscoveryError, HealthCheckError,
    handle_async_registry_exception
)


class MockConsulClient:
    """模拟的 Consul 客户端，用于测试和开发"""
    
    def __init__(self):
        self._services: Dict[str, Dict[str, Any]] = {}
        self._health_checks: Dict[str, Dict[str, Any]] = {}
        self._watch_callbacks: List[Callable] = []
        
    async def register_service(self, service_data: Dict[str, Any]) -> bool:
        """注册服务"""
        service_id = service_data["ID"]
        self._services[service_id] = service_data
        
        # 如果有健康检查配置，也注册健康检查
        if "Check" in service_data:
            check_id = f"service:{service_id}"
            self._health_checks[check_id] = {
                "CheckID": check_id,
                "ServiceID": service_id,
                "Status": "passing"
            }
        
        # 触发监听器
        for callback in self._watch_callbacks:
            try:
                await callback("service-register", service_data)
            except Exception:
                pass
        
        return True
    
    async def deregister_service(self, service_id: str) -> bool:
        """注销服务"""
        if service_id in self._services:
            service_data = self._services.pop(service_id)
            
            # 删除相关的健康检查
            check_id = f"service:{service_id}"
            if check_id in self._health_checks:
                del self._health_checks[check_id]
            
            # 触发监听器
            for callback in self._watch_callbacks:
                try:
                    await callback("service-deregister", service_data)
                except Exception:
                    pass
            
            return True
        return False
    
    async def get_services(self, service_name: str = None) -> List[Dict[str, Any]]:
        """获取服务列表"""
        services = []
        for service_data in self._services.values():
            if service_name is None or service_data["Service"] == service_name:
                # 模拟健康检查状态
                service_id = service_data["ID"]
                check_id = f"service:{service_id}"
                
                if check_id in self._health_checks:
                    health_status = self._health_checks[check_id]["Status"]
                else:
                    health_status = "passing"
                
                service_data_copy = service_data.copy()
                service_data_copy["HealthStatus"] = health_status
                services.append(service_data_copy)
        
        return services
    
    async def update_health_check(self, check_id: str, status: str) -> bool:
        """更新健康检查状态"""
        if check_id in self._health_checks:
            self._health_checks[check_id]["Status"] = status
            return True
        return False
    
    async def watch_services(self, service_name: str = None, callback=None):
        """监听服务变化"""
        if callback:
            self._watch_callbacks.append(callback)


class ConsulAdapter(BaseRegistryAdapter):
    """
    Consul 注册中心适配器
    
    基于 Consul 实现服务注册发现功能，支持：
    - 异步 HTTP API 调用
    - 健康检查配置
    - 服务变更通知
    - 标签和元数据支持
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Consul 适配器
        
        Args:
            config: Consul 配置
                - host: Consul 主机地址
                - port: Consul 端口
                - token: 访问令牌（可选）
                - scheme: 协议方案 (http/https)
                - timeout: 请求超时时间
        """
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._watch_tasks: List[asyncio.Task] = []
        
        # 配置参数
        self._host = config.get("host", "localhost")
        self._port = config.get("port", 8500)
        self._token = config.get("token")
        self._scheme = config.get("scheme", "http")
        self._timeout = config.get("timeout", 5)
        
        # 构建基础 URL
        self._base_url = f"{self._scheme}://{self._host}:{self._port}"
        
        # 请求头
        self._headers = {"Content-Type": "application/json"}
        if self._token:
            self._headers["X-Consul-Token"] = self._token
    
    @handle_async_registry_exception
    async def connect(self) -> None:
        """连接到 Consul"""
        if self._connected:
            return
        
        try:
            if HTTP_AVAILABLE:
                # 创建 HTTP 会话
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                self._session = aiohttp.ClientSession(
                    timeout=timeout,
                    headers=self._headers
                )
                
                # 测试连接
                await self._test_connection()
            else:
                # 使用模拟客户端
                self._session = MockConsulClient()
            
            self._connected = True
            logger.info(f"Consul 适配器连接成功: {self._base_url}")
            
        except Exception as e:
            logger.error(f"Consul 连接失败: {e}")
            raise RegistryConnectionError(
                f"无法连接到 Consul: {e}",
                endpoint=self._base_url,
                timeout=self._timeout,
                cause=e
            )
    
    async def disconnect(self) -> None:
        """断开与 Consul 的连接"""
        if not self._connected:
            return
        
        self._closing = True
        
        try:
            # 停止所有监听任务
            for task in self._watch_tasks:
                if not task.done():
                    task.cancel()
            
            if self._watch_tasks:
                await asyncio.gather(*self._watch_tasks, return_exceptions=True)
            
            # 关闭 HTTP 会话
            if self._session and hasattr(self._session, 'close'):
                await self._session.close()
            
            self._connected = False
            self._watch_tasks.clear()
            
            logger.info("Consul 适配器连接已断开")
            
        except Exception as e:
            logger.error(f"断开 Consul 连接时发生错误: {e}")
        finally:
            self._closing = False
    
    async def _test_connection(self) -> None:
        """测试 Consul 连接"""
        url = f"{self._base_url}/v1/status/leader"
        async with self._session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Consul 健康检查失败: {response.status}")
    
    @handle_async_registry_exception
    async def register_service(self, service: ServiceInfo) -> bool:
        """注册服务到 Consul"""
        if not self._connected:
            await self.connect()
        
        try:
            # 构建服务注册数据
            service_data = {
                "ID": service.id,
                "Name": service.name,
                "Address": service.host,
                "Port": service.port,
                "Tags": service.tags or [],
                "Meta": service.metadata or {},
                "EnableTagOverride": False
            }
            
            # 添加健康检查配置
            if service.health_check_url:
                service_data["Check"] = {
                    "HTTP": service.health_check_url,
                    "Interval": f"{service.health_check_interval}s",
                    "Timeout": f"{service.health_check_timeout}s",
                    "DeregisterCriticalServiceAfter": service.health_check_deregister_critical_after
                }
            elif service.port:
                # 默认 TCP 检查
                service_data["Check"] = {
                    "TCP": f"{service.host}:{service.port}",
                    "Interval": f"{service.health_check_interval}s",
                    "Timeout": f"{service.health_check_timeout}s",
                    "DeregisterCriticalServiceAfter": service.health_check_deregister_critical_after
                }
            
            # 注册服务
            if hasattr(self._session, 'register_service'):
                # 模拟客户端
                success = await self._session.register_service(service_data)
            else:
                # 真实的 HTTP 客户端
                url = f"{self._base_url}/v1/agent/service/register"
                async with self._session.put(url, json=service_data) as response:
                    success = response.status == 200
            
            if success:
                logger.info(f"服务注册成功: {service.name}/{service.id} -> {service.address}")
                return True
            else:
                raise Exception("Consul 返回注册失败")
            
        except Exception as e:
            logger.error(f"服务注册失败: {service.name}/{service.id} - {e}")
            raise ServiceRegistrationError(
                f"注册服务失败: {e}",
                service_name=service.name,
                service_id=service.id,
                cause=e
            )
    
    @handle_async_registry_exception
    async def deregister_service(self, service_id: str) -> bool:
        """从 Consul 注销服务"""
        if not self._connected:
            return False
        
        try:
            if hasattr(self._session, 'deregister_service'):
                # 模拟客户端
                success = await self._session.deregister_service(service_id)
            else:
                # 真实的 HTTP 客户端
                url = f"{self._base_url}/v1/agent/service/deregister/{service_id}"
                async with self._session.put(url) as response:
                    success = response.status == 200
            
            if success:
                logger.info(f"服务注销成功: {service_id}")
                return True
            else:
                logger.warning(f"服务注销失败: {service_id}")
                return False
            
        except Exception as e:
            logger.error(f"服务注销失败: {service_id} - {e}")
            raise ServiceRegistrationError(
                f"注销服务失败: {e}",
                service_id=service_id,
                cause=e
            )
    
    @handle_async_registry_exception
    async def discover_services(
        self, 
        service_name: str,
        tags: Optional[List[str]] = None,
        healthy_only: bool = True
    ) -> List[ServiceInfo]:
        """从 Consul 发现服务"""
        if not self._connected:
            await self.connect()
        
        try:
            if hasattr(self._session, 'get_services'):
                # 模拟客户端
                consul_services = await self._session.get_services(service_name)
            else:
                # 真实的 HTTP 客户端
                url = f"{self._base_url}/v1/health/service/{service_name}"
                params = {}
                if healthy_only:
                    params["passing"] = "true"
                if tags:
                    for tag in tags:
                        params["tag"] = tag
                
                async with self._session.get(url, params=params) as response:
                    if response.status == 200:
                        consul_services = await response.json()
                    else:
                        consul_services = []
            
            # 转换为 ServiceInfo 对象
            services = []
            for consul_service in consul_services:
                try:
                    if hasattr(self._session, 'get_services'):
                        # 模拟客户端格式
                        service_data = consul_service
                        health_status = consul_service.get("HealthStatus", "passing")
                    else:
                        # 真实 Consul API 格式
                        service_data = consul_service.get("Service", {})
                        checks = consul_service.get("Checks", [])
                        health_status = "passing" if all(check.get("Status") == "passing" for check in checks) else "critical"
                    
                    # 确定服务状态
                    if health_status == "passing":
                        status = ServiceStatus.HEALTHY
                    elif health_status == "warning":
                        status = ServiceStatus.UNHEALTHY
                    else:
                        status = ServiceStatus.CRITICAL
                    
                    service = ServiceInfo(
                        name=service_data.get("Service", service_name),
                        id=service_data.get("ID", ""),
                        host=service_data.get("Address", ""),
                        port=service_data.get("Port", 0),
                        tags=service_data.get("Tags", []),
                        metadata=service_data.get("Meta", {}),
                        status=status
                    )
                    
                    # 标签过滤（如果 Consul API 不支持）
                    if tags and not all(tag in service.tags for tag in tags):
                        continue
                    
                    services.append(service)
                    
                except Exception as e:
                    logger.warning(f"解析服务数据失败: {e}")
                    continue
            
            logger.debug(f"发现服务: {service_name} -> {len(services)} 个实例")
            return services
            
        except Exception as e:
            logger.error(f"服务发现失败: {service_name} - {e}")
            raise ServiceDiscoveryError(
                f"发现服务失败: {e}",
                service_name=service_name,
                tags=tags,
                cause=e
            )
    
    @handle_async_registry_exception
    async def get_service(self, service_id: str) -> Optional[ServiceInfo]:
        """获取指定服务信息"""
        if not self._connected:
            await self.connect()
        
        try:
            if hasattr(self._session, 'get_services'):
                # 模拟客户端
                all_services = await self._session.get_services()
                for service_data in all_services:
                    if service_data.get("ID") == service_id:
                        return ServiceInfo(
                            name=service_data.get("Service", ""),
                            id=service_data.get("ID", ""),
                            host=service_data.get("Address", ""),
                            port=service_data.get("Port", 0),
                            tags=service_data.get("Tags", []),
                            metadata=service_data.get("Meta", {}),
                            status=ServiceStatus.HEALTHY if service_data.get("HealthStatus") == "passing" else ServiceStatus.UNHEALTHY
                        )
            else:
                # 真实的 HTTP 客户端
                url = f"{self._base_url}/v1/agent/service/{service_id}"
                async with self._session.get(url) as response:
                    if response.status == 200:
                        service_data = await response.json()
                        return ServiceInfo(
                            name=service_data.get("Service", ""),
                            id=service_data.get("ID", ""),
                            host=service_data.get("Address", ""),
                            port=service_data.get("Port", 0),
                            tags=service_data.get("Tags", []),
                            metadata=service_data.get("Meta", {}),
                            status=ServiceStatus.UNKNOWN  # 需要额外查询健康状态
                        )
            
            return None
            
        except Exception as e:
            logger.error(f"获取服务信息失败: {service_id} - {e}")
            return None
    
    async def health_check(self, service_id: str) -> ServiceStatus:
        """检查服务健康状态"""
        if not self._connected:
            await self.connect()
        
        try:
            if hasattr(self._session, 'get_services'):
                # 模拟客户端
                all_services = await self._session.get_services()
                for service_data in all_services:
                    if service_data.get("ID") == service_id:
                        health_status = service_data.get("HealthStatus", "passing")
                        if health_status == "passing":
                            return ServiceStatus.HEALTHY
                        elif health_status == "warning":
                            return ServiceStatus.UNHEALTHY
                        else:
                            return ServiceStatus.CRITICAL
            else:
                # 真实的 HTTP 客户端
                url = f"{self._base_url}/v1/health/checks/{service_id}"
                async with self._session.get(url) as response:
                    if response.status == 200:
                        checks = await response.json()
                        if all(check.get("Status") == "passing" for check in checks):
                            return ServiceStatus.HEALTHY
                        elif any(check.get("Status") == "critical" for check in checks):
                            return ServiceStatus.CRITICAL
                        else:
                            return ServiceStatus.UNHEALTHY
            
            return ServiceStatus.UNKNOWN
            
        except Exception as e:
            logger.error(f"健康检查失败: {service_id} - {e}")
            return ServiceStatus.UNKNOWN
    
    async def update_service_status(self, service_id: str, status: ServiceStatus) -> bool:
        """更新服务状态"""
        if not self._connected:
            await self.connect()
        
        try:
            # 将状态映射到 Consul 健康检查状态
            consul_status = "pass"
            if status == ServiceStatus.HEALTHY:
                consul_status = "pass"
            elif status == ServiceStatus.UNHEALTHY:
                consul_status = "warn"
            elif status == ServiceStatus.CRITICAL:
                consul_status = "fail"
            
            check_id = f"service:{service_id}"
            
            if hasattr(self._session, 'update_health_check'):
                # 模拟客户端
                return await self._session.update_health_check(check_id, consul_status)
            else:
                # 真实的 HTTP 客户端
                url = f"{self._base_url}/v1/agent/check/{consul_status}/{check_id}"
                async with self._session.put(url) as response:
                    return response.status == 200
            
        except Exception as e:
            logger.error(f"更新服务状态失败: {service_id} - {e}")
            return False
    
    async def watch_services(
        self, 
        service_name: Optional[str] = None,
        callback: Optional[Callable[[WatchEvent], None]] = None
    ) -> AsyncIterator[WatchEvent]:
        """监听服务变更"""
        if not self._connected:
            await self.connect()
        
        # Consul 的 blocking query 实现服务监听
        index = 0
        
        while not self._closing:
            try:
                if hasattr(self._session, 'watch_services'):
                    # 模拟客户端
                    async def watch_callback(event_type: str, service_data: Dict[str, Any]):
                        try:
                            if event_type == "service-register":
                                event = WatchEvent(
                                    event_type="PUT",
                                    service=ServiceInfo(
                                        name=service_data.get("Service", ""),
                                        id=service_data.get("ID", ""),
                                        host=service_data.get("Address", ""),
                                        port=service_data.get("Port", 0),
                                        tags=service_data.get("Tags", []),
                                        metadata=service_data.get("Meta", {}),
                                        status=ServiceStatus.HEALTHY
                                    ),
                                    timestamp=time.time()
                                )
                            elif event_type == "service-deregister":
                                event = WatchEvent(
                                    event_type="DELETE",
                                    service=ServiceInfo(
                                        name=service_data.get("Service", ""),
                                        id=service_data.get("ID", ""),
                                        host=service_data.get("Address", ""),
                                        port=service_data.get("Port", 0),
                                        status=ServiceStatus.UNKNOWN
                                    ),
                                    timestamp=time.time()
                                )
                            else:
                                return
                            
                            if callback:
                                try:
                                    callback(event)
                                except Exception as e:
                                    logger.error(f"监听回调函数执行失败: {e}")
                            
                            yield event
                            
                        except Exception as e:
                            logger.error(f"处理服务变更事件失败: {e}")
                    
                    await self._session.watch_services(service_name, watch_callback)
                    
                else:
                    # 真实的 HTTP 客户端 - 使用轮询方式
                    if service_name:
                        url = f"{self._base_url}/v1/health/service/{service_name}"
                    else:
                        url = f"{self._base_url}/v1/agent/services"
                    
                    params = {"index": index, "wait": "30s"}
                    
                    async with self._session.get(url, params=params) as response:
                        if response.status == 200:
                            new_index = response.headers.get("X-Consul-Index")
                            if new_index and int(new_index) > index:
                                index = int(new_index)
                                # 服务有变更，生成事件
                                # 这里简化处理，实际应该比较前后差异
                                # TODO: 实现更精确的变更检测
                                pass
                
                await asyncio.sleep(1)  # 避免过于频繁的轮询
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监听服务变更失败: {e}")
                await asyncio.sleep(5)  # 错误后等待重试
    
    async def renew_lease(self, service_id: str) -> bool:
        """续期服务租约（Consul 自动管理，这里总是返回 True）"""
        return True