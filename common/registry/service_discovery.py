"""
服务发现模块

该模块实现服务查询和缓存机制，支持按服务名、标签、元数据过滤，
实现服务列表本地缓存和定期刷新，支持服务变更事件订阅。
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
try:
    from loguru import logger
except ImportError:
    from ..logger.mock_logger import logger

from ..utils.singleton import async_singleton
from .base_adapter import BaseRegistryAdapter, ServiceInfo, ServiceStatus, WatchEvent
from .exceptions import (
    BaseRegistryException, ServiceDiscoveryError, 
    handle_async_registry_exception
)


@dataclass
class DiscoveryFilter:
    """服务发现过滤器"""
    service_name: Optional[str] = None        # 服务名称
    tags: Optional[List[str]] = None          # 必须包含的标签
    metadata: Optional[Dict[str, Any]] = None # 必须匹配的元数据
    version: Optional[str] = None             # 版本过滤
    healthy_only: bool = True                 # 只返回健康服务
    min_weight: Optional[int] = None          # 最小权重
    max_instances: Optional[int] = None       # 最大返回实例数
    
    def matches(self, service: ServiceInfo) -> bool:
        """
        检查服务是否匹配过滤条件
        
        Args:
            service: 服务信息
            
        Returns:
            bool: 是否匹配
        """
        # 健康状态过滤
        if self.healthy_only and not service.is_healthy():
            return False
        
        # 标签过滤
        if self.tags:
            if not all(tag in service.tags for tag in self.tags):
                return False
        
        # 元数据过滤
        if self.metadata:
            for key, value in self.metadata.items():
                if key not in service.metadata or service.metadata[key] != value:
                    return False
        
        # 版本过滤
        if self.version and service.version != self.version:
            return False
        
        # 权重过滤
        if self.min_weight is not None and service.weight < self.min_weight:
            return False
        
        return True


@dataclass
class CacheEntry:
    """缓存条目"""
    services: List[ServiceInfo]
    timestamp: float
    ttl: float = 30.0  # 缓存TTL（秒）
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.timestamp > self.ttl
    
    def get_fresh_services(self) -> List[ServiceInfo]:
        """获取新鲜的服务列表"""
        if self.is_expired():
            return []
        return self.services.copy()


@async_singleton
class ServiceDiscovery:
    """
    服务发现器
    
    负责从注册中心发现服务，提供缓存机制和事件订阅功能，
    支持多种过滤条件和智能缓存策略。
    """
    
    def __init__(self):
        """初始化服务发现器"""
        self._adapters: Dict[str, BaseRegistryAdapter] = {}
        self._cache: Dict[str, CacheEntry] = {}  # cache_key -> CacheEntry
        self._watch_callbacks: Dict[str, List[Callable[[WatchEvent], None]]] = {}
        self._watch_tasks: Dict[str, asyncio.Task] = {}  # adapter_name -> watch_task
        self._cache_refresh_tasks: Dict[str, asyncio.Task] = {}  # cache_key -> refresh_task
        self._lock = asyncio.Lock()
        self._default_cache_ttl = 30.0  # 默认缓存TTL
        self._auto_refresh_enabled = True
        
        # 统计信息
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "discoveries": 0,
            "errors": 0
        }
    
    def add_adapter(self, name: str, adapter: BaseRegistryAdapter) -> None:
        """
        添加注册中心适配器
        
        Args:
            name: 适配器名称
            adapter: 适配器实例
        """
        self._adapters[name] = adapter
        logger.info(f"添加服务发现适配器: {name}")
    
    def remove_adapter(self, name: str) -> bool:
        """
        移除注册中心适配器
        
        Args:
            name: 适配器名称
            
        Returns:
            bool: 是否成功移除
        """
        if name in self._adapters:
            # 停止相关的监听任务
            if name in self._watch_tasks:
                task = self._watch_tasks.pop(name)
                if not task.done():
                    task.cancel()
            
            del self._adapters[name]
            logger.info(f"移除服务发现适配器: {name}")
            return True
        return False
    
    @handle_async_registry_exception
    async def discover(
        self, 
        service_name: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        version: Optional[str] = None,
        healthy_only: bool = True,
        use_cache: bool = True,
        adapter_name: Optional[str] = None
    ) -> List[ServiceInfo]:
        """
        发现服务
        
        Args:
            service_name: 服务名称
            tags: 必须包含的标签
            metadata: 必须匹配的元数据
            version: 版本过滤
            healthy_only: 只返回健康服务
            use_cache: 是否使用缓存
            adapter_name: 指定适配器名称，None表示使用第一个可用适配器
            
        Returns:
            List[ServiceInfo]: 匹配的服务列表
        """
        if not self._adapters:
            raise ServiceDiscoveryError("没有可用的服务发现适配器")
        
        # 创建过滤器
        discovery_filter = DiscoveryFilter(
            service_name=service_name,
            tags=tags,
            metadata=metadata,
            version=version,
            healthy_only=healthy_only
        )
        
        # 生成缓存键
        cache_key = self._generate_cache_key(discovery_filter)
        
        # 尝试从缓存获取
        if use_cache:
            cached_services = await self._get_from_cache(cache_key)
            if cached_services is not None:
                self._stats["cache_hits"] += 1
                logger.debug(f"从缓存获取服务: {service_name} -> {len(cached_services)} 个实例")
                return self._apply_filter(cached_services, discovery_filter)
        
        self._stats["cache_misses"] += 1
        
        try:
            # 确定使用的适配器
            if adapter_name:
                if adapter_name not in self._adapters:
                    raise ServiceDiscoveryError(f"未知的适配器: {adapter_name}")
                adapter = self._adapters[adapter_name]
            else:
                adapter = next(iter(self._adapters.values()))
            
            # 连接适配器
            if not adapter.is_connected:
                await adapter.connect()
            
            # 从适配器发现服务
            services = await adapter.discover_services(
                service_name=service_name,
                tags=tags,
                healthy_only=healthy_only
            )
            
            # 应用额外过滤条件
            filtered_services = self._apply_filter(services, discovery_filter)
            
            # 更新缓存
            if use_cache:
                await self._update_cache(cache_key, services)
            
            self._stats["discoveries"] += 1
            logger.debug(f"发现服务: {service_name} -> {len(filtered_services)} 个实例")
            
            return filtered_services
            
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"服务发现失败: {service_name} - {e}")
            raise ServiceDiscoveryError(
                f"发现服务失败: {e}",
                service_name=service_name,
                tags=tags,
                cause=e
            )
    
    @handle_async_registry_exception
    async def discover_all_services(
        self,
        healthy_only: bool = True,
        adapter_name: Optional[str] = None
    ) -> Dict[str, List[ServiceInfo]]:
        """
        发现所有服务
        
        Args:
            healthy_only: 只返回健康服务
            adapter_name: 指定适配器名称
            
        Returns:
            Dict[str, List[ServiceInfo]]: 服务字典，key为服务名
        """
        if not self._adapters:
            raise ServiceDiscoveryError("没有可用的服务发现适配器")
        
        try:
            # 确定使用的适配器
            if adapter_name:
                if adapter_name not in self._adapters:
                    raise ServiceDiscoveryError(f"未知的适配器: {adapter_name}")
                adapter = self._adapters[adapter_name]
            else:
                adapter = next(iter(self._adapters.values()))
            
            # 连接适配器
            if not adapter.is_connected:
                await adapter.connect()
            
            # 发现所有服务（通过空服务名和通配符）
            all_services = await adapter.discover_services("", healthy_only=healthy_only)
            
            # 按服务名分组
            services_by_name: Dict[str, List[ServiceInfo]] = {}
            for service in all_services:
                if service.name not in services_by_name:
                    services_by_name[service.name] = []
                services_by_name[service.name].append(service)
            
            logger.debug(f"发现所有服务: {len(services_by_name)} 个服务类型")
            return services_by_name
            
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"发现所有服务失败: {e}")
            raise ServiceDiscoveryError(
                f"发现所有服务失败: {e}",
                cause=e
            )
    
    async def get_service_instances(
        self, 
        service_name: str,
        adapter_name: Optional[str] = None
    ) -> int:
        """
        获取服务实例数量
        
        Args:
            service_name: 服务名称
            adapter_name: 指定适配器名称
            
        Returns:
            int: 实例数量
        """
        try:
            services = await self.discover(
                service_name=service_name,
                healthy_only=False,
                use_cache=True,
                adapter_name=adapter_name
            )
            return len(services)
        except Exception as e:
            logger.error(f"获取服务实例数失败: {service_name} - {e}")
            return 0
    
    async def get_healthy_instances(
        self, 
        service_name: str,
        adapter_name: Optional[str] = None
    ) -> int:
        """
        获取健康服务实例数量
        
        Args:
            service_name: 服务名称
            adapter_name: 指定适配器名称
            
        Returns:
            int: 健康实例数量
        """
        try:
            services = await self.discover(
                service_name=service_name,
                healthy_only=True,
                use_cache=True,
                adapter_name=adapter_name
            )
            return len(services)
        except Exception as e:
            logger.error(f"获取健康服务实例数失败: {service_name} - {e}")
            return 0
    
    async def watch_service_changes(
        self,
        service_name: Optional[str] = None,
        callback: Optional[Callable[[WatchEvent], None]] = None,
        adapter_name: Optional[str] = None
    ) -> None:
        """
        监听服务变更
        
        Args:
            service_name: 监听的服务名称，None表示监听所有服务
            callback: 事件回调函数
            adapter_name: 指定适配器名称
        """
        if not self._adapters:
            raise ServiceDiscoveryError("没有可用的服务发现适配器")
        
        # 确定使用的适配器
        if adapter_name:
            if adapter_name not in self._adapters:
                raise ServiceDiscoveryError(f"未知的适配器: {adapter_name}")
            adapters = {adapter_name: self._adapters[adapter_name]}
        else:
            adapters = self._adapters
        
        # 注册回调函数
        watch_key = f"{service_name or 'all'}"
        if watch_key not in self._watch_callbacks:
            self._watch_callbacks[watch_key] = []
        
        if callback:
            self._watch_callbacks[watch_key].append(callback)
        
        # 为每个适配器启动监听任务
        for name, adapter in adapters.items():
            if name not in self._watch_tasks:
                task = asyncio.create_task(
                    self._watch_service_changes_task(name, adapter, service_name)
                )
                self._watch_tasks[name] = task
                logger.info(f"启动服务变更监听: {name} -> {service_name or 'all'}")
    
    async def _watch_service_changes_task(
        self,
        adapter_name: str,
        adapter: BaseRegistryAdapter,
        service_name: Optional[str]
    ) -> None:
        """服务变更监听任务"""
        try:
            # 连接适配器
            if not adapter.is_connected:
                await adapter.connect()
            
            # 开始监听
            async for event in adapter.watch_services(service_name):
                try:
                    # 清理相关缓存
                    await self._invalidate_related_cache(event.service.name)
                    
                    # 调用回调函数
                    watch_key = f"{service_name or 'all'}"
                    if watch_key in self._watch_callbacks:
                        for callback in self._watch_callbacks[watch_key]:
                            try:
                                callback(event)
                            except Exception as e:
                                logger.error(f"服务变更回调函数执行失败: {e}")
                    
                    # 调用全局回调
                    if service_name and "all" in self._watch_callbacks:
                        for callback in self._watch_callbacks["all"]:
                            try:
                                callback(event)
                            except Exception as e:
                                logger.error(f"全局服务变更回调函数执行失败: {e}")
                    
                    logger.debug(f"处理服务变更事件: {adapter_name} -> "
                               f"{event.event_type} {event.service.name}/{event.service.id}")
                    
                except Exception as e:
                    logger.error(f"处理服务变更事件失败: {adapter_name} - {e}")
                    
        except Exception as e:
            logger.error(f"服务变更监听任务失败: {adapter_name} - {e}")
        finally:
            # 清理任务
            if adapter_name in self._watch_tasks:
                del self._watch_tasks[adapter_name]
    
    def _generate_cache_key(self, discovery_filter: DiscoveryFilter) -> str:
        """生成缓存键"""
        key_parts = [
            f"service:{discovery_filter.service_name or 'all'}",
            f"tags:{','.join(sorted(discovery_filter.tags or []))}",
            f"healthy:{discovery_filter.healthy_only}",
            f"version:{discovery_filter.version or 'any'}"
        ]
        
        if discovery_filter.metadata:
            metadata_str = ','.join(f"{k}:{v}" for k, v in sorted(discovery_filter.metadata.items()))
            key_parts.append(f"metadata:{metadata_str}")
        
        return '|'.join(key_parts)
    
    async def _get_from_cache(self, cache_key: str) -> Optional[List[ServiceInfo]]:
        """从缓存获取服务列表"""
        async with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if not entry.is_expired():
                    return entry.get_fresh_services()
                else:
                    # 清理过期缓存
                    del self._cache[cache_key]
                    if cache_key in self._cache_refresh_tasks:
                        task = self._cache_refresh_tasks.pop(cache_key)
                        if not task.done():
                            task.cancel()
            return None
    
    async def _update_cache(self, cache_key: str, services: List[ServiceInfo]) -> None:
        """更新缓存"""
        async with self._lock:
            entry = CacheEntry(
                services=services.copy(),
                timestamp=time.time(),
                ttl=self._default_cache_ttl
            )
            self._cache[cache_key] = entry
            
            # 启动自动刷新任务
            if self._auto_refresh_enabled and cache_key not in self._cache_refresh_tasks:
                task = asyncio.create_task(self._cache_refresh_task(cache_key))
                self._cache_refresh_tasks[cache_key] = task
    
    async def _cache_refresh_task(self, cache_key: str) -> None:
        """缓存自动刷新任务"""
        try:
            while cache_key in self._cache:
                entry = self._cache[cache_key]
                await asyncio.sleep(entry.ttl * 0.8)  # 在缓存过期前刷新
                
                if cache_key not in self._cache:
                    break
                
                # TODO: 实现后台刷新逻辑
                # 这里可以根据缓存键解析出查询参数，然后重新查询
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"缓存刷新任务失败: {cache_key} - {e}")
        finally:
            if cache_key in self._cache_refresh_tasks:
                del self._cache_refresh_tasks[cache_key]
    
    async def _invalidate_related_cache(self, service_name: str) -> None:
        """清理相关缓存"""
        async with self._lock:
            keys_to_remove = [
                key for key in self._cache.keys()
                if f"service:{service_name}" in key or "service:all" in key
            ]
            
            for key in keys_to_remove:
                del self._cache[key]
                if key in self._cache_refresh_tasks:
                    task = self._cache_refresh_tasks.pop(key)
                    if not task.done():
                        task.cancel()
            
            if keys_to_remove:
                logger.debug(f"清理相关缓存: {service_name} -> {len(keys_to_remove)} 个条目")
    
    def _apply_filter(self, services: List[ServiceInfo], discovery_filter: DiscoveryFilter) -> List[ServiceInfo]:
        """应用过滤条件"""
        filtered = [service for service in services if discovery_filter.matches(service)]
        
        # 应用最大实例数限制
        if discovery_filter.max_instances and len(filtered) > discovery_filter.max_instances:
            # 按权重排序，选择权重最高的实例
            filtered.sort(key=lambda s: s.weight, reverse=True)
            filtered = filtered[:discovery_filter.max_instances]
        
        return filtered
    
    async def clear_cache(self, service_name: Optional[str] = None) -> None:
        """
        清理缓存
        
        Args:
            service_name: 指定服务名称，None表示清理所有缓存
        """
        async with self._lock:
            if service_name:
                await self._invalidate_related_cache(service_name)
            else:
                # 清理所有缓存
                keys_to_remove = list(self._cache.keys())
                for key in keys_to_remove:
                    del self._cache[key]
                    if key in self._cache_refresh_tasks:
                        task = self._cache_refresh_tasks.pop(key)
                        if not task.done():
                            task.cancel()
                logger.info(f"清理所有缓存: {len(keys_to_remove)} 个条目")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "cache_size": len(self._cache),
            "active_watches": len(self._watch_tasks),
            "active_refresh_tasks": len(self._cache_refresh_tasks)
        }
    
    async def shutdown(self) -> None:
        """关闭服务发现器"""
        logger.info("开始关闭服务发现器...")
        
        # 停止所有监听任务
        tasks = list(self._watch_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # 停止所有刷新任务
        refresh_tasks = list(self._cache_refresh_tasks.values())
        for task in refresh_tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成
        all_tasks = tasks + refresh_tasks
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        
        # 断开所有适配器连接
        for adapter_name, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
            except Exception as e:
                logger.error(f"断开适配器连接失败: {adapter_name} - {e}")
        
        # 清理状态
        self._cache.clear()
        self._watch_callbacks.clear()
        self._watch_tasks.clear()
        self._cache_refresh_tasks.clear()
        
        logger.info("服务发现器关闭完成")