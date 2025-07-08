"""
etcd 适配器实现

基于 etcd 的服务注册发现实现，使用 aioetcd3 库实现异步操作，
支持服务租约和自动续期，实现服务变更监听。
"""

import asyncio
import json
import time
from typing import List, Dict, Optional, Any, AsyncIterator, Callable
from dataclasses import asdict
from loguru import logger

try:
    import aioetcd3 as etcd3
    ETCD_AVAILABLE = True
except ImportError:
    ETCD_AVAILABLE = False
    logger.warning("aioetcd3 未安装，etcd适配器将使用模拟模式")

from .base_adapter import BaseRegistryAdapter, ServiceInfo, ServiceStatus, WatchEvent
from .exceptions import (
    BaseRegistryException, RegistryConnectionError, RegistryTimeoutError,
    ServiceRegistrationError, ServiceDiscoveryError, HealthCheckError,
    handle_async_registry_exception
)


class MockEtcdClient:
    """模拟的 etcd 客户端，用于测试和开发"""
    
    def __init__(self):
        self._data: Dict[str, str] = {}
        self._leases: Dict[int, Dict[str, Any]] = {}
        self._watches: List[Callable] = []
        self._lease_counter = 1
        
    async def connect(self):
        """连接"""
        pass
        
    async def close(self):
        """关闭连接"""
        pass
        
    async def put(self, key: str, value: str, lease=None):
        """设置键值"""
        self._data[key] = value
        if lease:
            if lease not in self._leases:
                self._leases[lease] = {"keys": [], "ttl": 30}
            self._leases[lease]["keys"].append(key)
        
        # 触发监听器
        for callback in self._watches:
            try:
                await callback("PUT", key, value)
            except Exception:
                pass
                
    async def get(self, key: str):
        """获取键值"""
        if key in self._data:
            return [(key, self._data[key])]
        return []
        
    async def get_prefix(self, prefix: str):
        """获取前缀匹配的键值"""
        result = []
        for key, value in self._data.items():
            if key.startswith(prefix):
                result.append((key, value))
        return result
        
    async def delete(self, key: str):
        """删除键"""
        if key in self._data:
            del self._data[key]
            
        # 触发监听器
        for callback in self._watches:
            try:
                await callback("DELETE", key, None)
            except Exception:
                pass
                
    async def delete_prefix(self, prefix: str):
        """删除前缀匹配的键"""
        keys_to_delete = [key for key in self._data.keys() if key.startswith(prefix)]
        for key in keys_to_delete:
            await self.delete(key)
            
    def lease(self, ttl: int):
        """创建租约"""
        lease_id = self._lease_counter
        self._lease_counter += 1
        self._leases[lease_id] = {"keys": [], "ttl": ttl, "created": time.time()}
        return MockLease(lease_id, self)
        
    async def watch_prefix(self, prefix: str, callback):
        """监听前缀"""
        self._watches.append(callback)


class MockLease:
    """模拟的租约对象"""
    
    def __init__(self, lease_id: int, client):
        self.id = lease_id
        self._client = client
        self._refresh_task = None
        
    async def refresh(self):
        """刷新租约"""
        if self.id in self._client._leases:
            self._client._leases[self.id]["created"] = time.time()
            
    async def revoke(self):
        """撤销租约"""
        if self.id in self._client._leases:
            lease_info = self._client._leases[self.id]
            for key in lease_info["keys"]:
                if key in self._client._data:
                    del self._client._data[key]
            del self._client._leases[self.id]
            
        if self._refresh_task:
            self._refresh_task.cancel()
            
    def start_refresh(self, interval: int = 10):
        """开始自动续期"""
        async def refresh_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    await self.refresh()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"租约续期失败: {e}")
                    
        self._refresh_task = asyncio.create_task(refresh_loop())


class EtcdAdapter(BaseRegistryAdapter):
    """
    etcd 注册中心适配器
    
    基于 etcd 实现服务注册发现功能，支持：
    - 异步操作
    - 服务租约和自动续期
    - 服务变更监听
    - 健康检查集成
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 etcd 适配器
        
        Args:
            config: etcd 配置
                - endpoints: etcd 端点列表
                - timeout: 连接超时时间
                - username: 用户名（可选）
                - password: 密码（可选）
                - ca_cert: CA证书路径（可选）
                - cert_cert: 客户端证书路径（可选）
                - cert_key: 客户端私钥路径（可选）
        """
        super().__init__(config)
        self._client: Optional[Any] = None
        self._leases: Dict[str, Any] = {}  # service_id -> lease
        self._refresh_tasks: Dict[str, asyncio.Task] = {}  # service_id -> task
        self._watch_tasks: List[asyncio.Task] = []
        self._service_prefix = "/services/"
        
        # 配置参数
        self._endpoints = config.get("endpoints", ["http://localhost:2379"])
        self._timeout = config.get("timeout", 5)
        self._username = config.get("username")
        self._password = config.get("password")
        self._ca_cert = config.get("ca_cert")
        self._cert_cert = config.get("cert_cert")
        self._cert_key = config.get("cert_key")
        
    @handle_async_registry_exception
    async def connect(self) -> None:
        """连接到 etcd"""
        if self._connected:
            return
            
        try:
            if ETCD_AVAILABLE:
                # 创建 etcd 客户端
                client_kwargs = {
                    "endpoint": self._endpoints[0] if self._endpoints else "http://localhost:2379",
                    "timeout": self._timeout
                }
                
                # 添加认证信息
                if self._username and self._password:
                    client_kwargs["user"] = self._username
                    client_kwargs["password"] = self._password
                    
                # 添加SSL证书
                if self._ca_cert:
                    client_kwargs["ca_cert"] = self._ca_cert
                if self._cert_cert:
                    client_kwargs["cert_cert"] = self._cert_cert
                if self._cert_key:
                    client_kwargs["cert_key"] = self._cert_key
                    
                self._client = etcd3.client(**client_kwargs)
                await self._client.connect()
            else:
                # 使用模拟客户端
                self._client = MockEtcdClient()
                await self._client.connect()
                
            self._connected = True
            logger.info(f"etcd 适配器连接成功: {self._endpoints}")
            
        except Exception as e:
            logger.error(f"etcd 连接失败: {e}")
            raise RegistryConnectionError(
                f"无法连接到 etcd: {e}",
                endpoint=str(self._endpoints),
                timeout=self._timeout,
                cause=e
            )
    
    async def disconnect(self) -> None:
        """断开与 etcd 的连接"""
        if not self._connected:
            return
            
        self._closing = True
        
        try:
            # 停止所有监听任务
            for task in self._watch_tasks:
                if not task.done():
                    task.cancel()
                    
            # 停止所有续期任务
            for task in self._refresh_tasks.values():
                if not task.done():
                    task.cancel()
                    
            # 撤销所有租约
            for lease in self._leases.values():
                try:
                    await lease.revoke()
                except Exception as e:
                    logger.warning(f"撤销租约失败: {e}")
                    
            # 关闭客户端连接
            if self._client:
                await self._client.close()
                
            self._connected = False
            self._leases.clear()
            self._refresh_tasks.clear()
            self._watch_tasks.clear()
            
            logger.info("etcd 适配器连接已断开")
            
        except Exception as e:
            logger.error(f"断开 etcd 连接时发生错误: {e}")
        finally:
            self._closing = False
    
    @handle_async_registry_exception
    async def register_service(self, service: ServiceInfo) -> bool:
        """注册服务到 etcd"""
        if not self._connected:
            await self.connect()
            
        try:
            # 创建服务键
            service_key = f"{self._service_prefix}{service.name}/{service.id}"
            
            # 创建租约
            lease = self._client.lease(service.ttl)
            
            # 准备服务数据
            service_data = {
                **service.to_dict(),
                "registered_at": time.time()
            }
            
            # 注册服务
            await self._client.put(
                service_key,
                json.dumps(service_data),
                lease=lease.id
            )
            
            # 保存租约并启动续期
            self._leases[service.id] = lease
            
            # 启动自动续期任务
            refresh_interval = max(1, service.ttl // 3)  # 每 TTL/3 时间续期一次
            lease.start_refresh(refresh_interval)
            
            logger.info(f"服务注册成功: {service.name}/{service.id} -> {service.address}")
            return True
            
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
        """从 etcd 注销服务"""
        if not self._connected:
            return False
            
        try:
            # 停止续期任务
            if service_id in self._refresh_tasks:
                task = self._refresh_tasks.pop(service_id)
                if not task.done():
                    task.cancel()
                    
            # 撤销租约（会自动删除相关的键）
            if service_id in self._leases:
                lease = self._leases.pop(service_id)
                await lease.revoke()
                
            logger.info(f"服务注销成功: {service_id}")
            return True
            
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
        """从 etcd 发现服务"""
        if not self._connected:
            await self.connect()
            
        try:
            # 构建搜索前缀
            search_prefix = f"{self._service_prefix}{service_name}/"
            
            # 获取所有匹配的服务
            results = await self._client.get_prefix(search_prefix)
            services = []
            
            for key, value in results:
                try:
                    service_data = json.loads(value)
                    service = ServiceInfo.from_dict(service_data)
                    
                    # 标签过滤
                    if tags:
                        if not all(tag in service.tags for tag in tags):
                            continue
                    
                    # 健康状态过滤
                    if healthy_only and not service.is_healthy():
                        continue
                        
                    services.append(service)
                    
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"解析服务数据失败: {key} - {e}")
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
            # 搜索所有服务，找到匹配的 service_id
            results = await self._client.get_prefix(self._service_prefix)
            
            for key, value in results:
                try:
                    service_data = json.loads(value)
                    if service_data.get("id") == service_id:
                        return ServiceInfo.from_dict(service_data)
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"解析服务数据失败: {key} - {e}")
                    continue
                    
            return None
            
        except Exception as e:
            logger.error(f"获取服务信息失败: {service_id} - {e}")
            return None
    
    async def health_check(self, service_id: str) -> ServiceStatus:
        """检查服务健康状态"""
        service = await self.get_service(service_id)
        if not service:
            return ServiceStatus.UNKNOWN
            
        # 简单的状态检查（基于服务是否存在于etcd中）
        return service.status
    
    async def update_service_status(self, service_id: str, status: ServiceStatus) -> bool:
        """更新服务状态"""
        service = await self.get_service(service_id)
        if not service:
            return False
            
        try:
            # 更新服务状态
            service.status = status
            service.last_seen = time.time()
            
            # 重新注册服务（更新数据）
            service_key = f"{self._service_prefix}{service.name}/{service.id}"
            service_data = service.to_dict()
            
            # 使用现有租约或创建新租约
            lease_id = None
            if service_id in self._leases:
                lease_id = self._leases[service_id].id
                
            await self._client.put(
                service_key,
                json.dumps(service_data),
                lease=lease_id
            )
            
            return True
            
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
            
        # 确定监听的前缀
        if service_name:
            watch_prefix = f"{self._service_prefix}{service_name}/"
        else:
            watch_prefix = self._service_prefix
            
        async def watch_callback(event_type: str, key: str, value: Optional[str]):
            """处理 etcd 变更事件"""
            try:
                if event_type == "PUT" and value:
                    service_data = json.loads(value)
                    service = ServiceInfo.from_dict(service_data)
                elif event_type == "DELETE":
                    # 删除事件，创建一个最小化的服务信息
                    key_parts = key.split("/")
                    if len(key_parts) >= 3:
                        service_name = key_parts[-2]
                        service_id = key_parts[-1]
                        service = ServiceInfo(
                            name=service_name,
                            id=service_id,
                            host="",
                            port=0,
                            status=ServiceStatus.UNKNOWN
                        )
                    else:
                        return
                else:
                    return
                    
                event = WatchEvent(
                    event_type=event_type,
                    service=service,
                    timestamp=time.time()
                )
                
                # 调用回调函数
                if callback:
                    try:
                        callback(event)
                    except Exception as e:
                        logger.error(f"监听回调函数执行失败: {e}")
                        
                # 生成事件
                yield event
                
            except Exception as e:
                logger.error(f"处理服务变更事件失败: {key} - {e}")
        
        try:
            # 开始监听
            await self._client.watch_prefix(watch_prefix, watch_callback)
            
        except Exception as e:
            logger.error(f"监听服务变更失败: {e}")
            raise
    
    @handle_async_registry_exception
    async def renew_lease(self, service_id: str) -> bool:
        """续期服务租约"""
        if service_id not in self._leases:
            return False
            
        try:
            lease = self._leases[service_id]
            await lease.refresh()
            return True
            
        except Exception as e:
            logger.error(f"续期租约失败: {service_id} - {e}")
            return False