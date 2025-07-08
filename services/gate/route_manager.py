"""
路由管理器

该模块负责管理请求路由，包括动态路由注册、协议号到处理器的映射、
路由权限验证、路由统计和监控等功能。

主要功能：
- 动态路由注册
- 协议号到处理器的映射
- 路由权限验证
- 路由统计和监控
- 支持路由热更新
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import inspect

from common.logger import logger
from common.utils.singleton import Singleton
from .config import GatewayConfig


class RouteType(Enum):
    """路由类型枚举"""
    REQUEST = "request"       # 请求路由
    RESPONSE = "response"     # 响应路由
    NOTIFICATION = "notification"  # 通知路由
    BROADCAST = "broadcast"   # 广播路由


class RouteStatus(Enum):
    """路由状态枚举"""
    ACTIVE = "active"         # 活跃
    DISABLED = "disabled"     # 禁用
    DEPRECATED = "deprecated" # 废弃
    MAINTENANCE = "maintenance"  # 维护中


@dataclass
class RouteInfo:
    """路由信息"""
    route_id: str
    protocol_id: int
    handler: Callable
    controller_name: str
    method_name: str
    route_type: RouteType = RouteType.REQUEST
    status: RouteStatus = RouteStatus.ACTIVE
    description: str = ""
    required_permissions: Set[str] = field(default_factory=set)
    rate_limit: Optional[int] = None  # 每秒请求数限制
    timeout: float = 30.0  # 超时时间(秒)
    deprecated_version: Optional[str] = None
    replacement_route: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 统计信息
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_time: float = 0.0
    last_call_time: float = 0.0
    
    def add_request_stat(self, success: bool, duration: float):
        """添加请求统计"""
        self.request_count += 1
        self.total_time += duration
        self.last_call_time = time.time()
        
        if success:
            self.success_count += 1
        else:
            self.error_count += 1
            
    def get_average_time(self) -> float:
        """获取平均响应时间"""
        if self.request_count == 0:
            return 0.0
        return self.total_time / self.request_count
        
    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.request_count == 0:
            return 0.0
        return self.success_count / self.request_count
        
    def is_available(self) -> bool:
        """检查路由是否可用"""
        return self.status == RouteStatus.ACTIVE
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "route_id": self.route_id,
            "protocol_id": self.protocol_id,
            "controller_name": self.controller_name,
            "method_name": self.method_name,
            "route_type": self.route_type.value,
            "status": self.status.value,
            "description": self.description,
            "required_permissions": list(self.required_permissions),
            "rate_limit": self.rate_limit,
            "timeout": self.timeout,
            "deprecated_version": self.deprecated_version,
            "replacement_route": self.replacement_route,
            "metadata": self.metadata,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "average_time": self.get_average_time(),
            "success_rate": self.get_success_rate(),
            "last_call_time": self.last_call_time
        }


@dataclass
class RouteGroup:
    """路由分组"""
    group_name: str
    description: str = ""
    prefix: str = ""
    middleware: List[str] = field(default_factory=list)
    required_permissions: Set[str] = field(default_factory=set)
    rate_limit: Optional[int] = None
    enabled: bool = True
    routes: Dict[str, RouteInfo] = field(default_factory=dict)
    
    def add_route(self, route_info: RouteInfo):
        """添加路由"""
        self.routes[route_info.route_id] = route_info
        
    def remove_route(self, route_id: str):
        """移除路由"""
        self.routes.pop(route_id, None)
        
    def get_route(self, route_id: str) -> Optional[RouteInfo]:
        """获取路由"""
        return self.routes.get(route_id)
        
    def get_active_routes(self) -> List[RouteInfo]:
        """获取活跃路由"""
        return [route for route in self.routes.values() if route.is_available()]


class RouteManager(Singleton):
    """路由管理器"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化路由管理器
        
        Args:
            config: 网关配置
        """
        self.config = config
        self._routes: Dict[int, RouteInfo] = {}  # protocol_id -> RouteInfo
        self._route_groups: Dict[str, RouteGroup] = {}  # group_name -> RouteGroup
        self._route_aliases: Dict[str, int] = {}  # route_alias -> protocol_id
        self._controllers: Dict[str, Any] = {}  # controller_name -> controller_instance
        self._middleware: Dict[str, Callable] = {}  # middleware_name -> middleware_func
        self._route_lock = asyncio.Lock()
        
        # 路由缓存
        self._route_cache: Dict[int, RouteInfo] = {}
        self._cache_ttl = 300  # 缓存TTL(秒)
        self._cache_update_time = 0
        
        # 热更新支持
        self._hot_reload_enabled = config.debug
        self._file_watchers: Dict[str, Any] = {}
        
        # 统计信息
        self._total_routes = 0
        self._active_routes = 0
        self._disabled_routes = 0
        
        logger.info("路由管理器初始化完成")
        
    async def initialize(self):
        """初始化路由管理器"""
        # 创建默认路由分组
        await self._create_default_groups()
        
        # 如果启用热更新，启动文件监控
        if self._hot_reload_enabled:
            await self._start_file_watchers()
            
        logger.info("路由管理器初始化完成")
        
    async def register_controller(self, controller_name: str, controller_instance: Any):
        """
        注册控制器
        
        Args:
            controller_name: 控制器名称
            controller_instance: 控制器实例
        """
        self._controllers[controller_name] = controller_instance
        
        # 自动扫描控制器方法并注册路由
        await self._scan_controller_routes(controller_name, controller_instance)
        
        logger.info("控制器注册成功", controller_name=controller_name)
        
    async def register_route(self, protocol_id: int, handler: Callable,
                           controller_name: str, method_name: str,
                           route_type: RouteType = RouteType.REQUEST,
                           description: str = "",
                           required_permissions: Optional[Set[str]] = None,
                           rate_limit: Optional[int] = None,
                           timeout: float = 30.0,
                           group_name: str = "default",
                           alias: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        注册路由
        
        Args:
            protocol_id: 协议ID
            handler: 处理器函数
            controller_name: 控制器名称
            method_name: 方法名称
            route_type: 路由类型
            description: 描述
            required_permissions: 必需权限
            rate_limit: 速率限制
            timeout: 超时时间
            group_name: 分组名称
            alias: 路由别名
            metadata: 元数据
            
        Returns:
            bool: 是否注册成功
        """
        async with self._route_lock:
            # 检查协议ID是否已存在
            if protocol_id in self._routes:
                logger.warning("协议ID已存在", protocol_id=protocol_id)
                return False
                
            # 创建路由信息
            route_id = f"{controller_name}.{method_name}"
            route_info = RouteInfo(
                route_id=route_id,
                protocol_id=protocol_id,
                handler=handler,
                controller_name=controller_name,
                method_name=method_name,
                route_type=route_type,
                description=description,
                required_permissions=required_permissions or set(),
                rate_limit=rate_limit,
                timeout=timeout,
                metadata=metadata or {}
            )
            
            # 注册路由
            self._routes[protocol_id] = route_info
            
            # 添加到分组
            if group_name not in self._route_groups:
                self._route_groups[group_name] = RouteGroup(group_name=group_name)
            self._route_groups[group_name].add_route(route_info)
            
            # 添加别名
            if alias:
                self._route_aliases[alias] = protocol_id
                
            # 更新统计
            self._total_routes += 1
            self._active_routes += 1
            
            # 清除缓存
            self._clear_route_cache()
            
            logger.info("路由注册成功", 
                       protocol_id=protocol_id,
                       route_id=route_id,
                       controller_name=controller_name,
                       method_name=method_name,
                       group_name=group_name)
            
            return True
            
    async def unregister_route(self, protocol_id: int) -> bool:
        """
        注销路由
        
        Args:
            protocol_id: 协议ID
            
        Returns:
            bool: 是否注销成功
        """
        async with self._route_lock:
            if protocol_id not in self._routes:
                return False
                
            route_info = self._routes[protocol_id]
            
            # 从分组中移除
            for group in self._route_groups.values():
                group.remove_route(route_info.route_id)
                
            # 移除别名
            aliases_to_remove = []
            for alias, pid in self._route_aliases.items():
                if pid == protocol_id:
                    aliases_to_remove.append(alias)
            for alias in aliases_to_remove:
                del self._route_aliases[alias]
                
            # 移除路由
            del self._routes[protocol_id]
            
            # 更新统计
            self._active_routes -= 1
            
            # 清除缓存
            self._clear_route_cache()
            
            logger.info("路由注销成功", 
                       protocol_id=protocol_id,
                       route_id=route_info.route_id)
            
            return True
            
    async def get_route(self, protocol_id: int) -> Optional[RouteInfo]:
        """
        获取路由信息
        
        Args:
            protocol_id: 协议ID
            
        Returns:
            RouteInfo: 路由信息
        """
        # 首先从缓存获取
        if self._is_cache_valid():
            route_info = self._route_cache.get(protocol_id)
            if route_info:
                return route_info
                
        # 从主存储获取
        route_info = self._routes.get(protocol_id)
        if route_info:
            # 更新缓存
            self._route_cache[protocol_id] = route_info
            
        return route_info
        
    async def get_route_by_alias(self, alias: str) -> Optional[RouteInfo]:
        """
        通过别名获取路由
        
        Args:
            alias: 路由别名
            
        Returns:
            RouteInfo: 路由信息
        """
        protocol_id = self._route_aliases.get(alias)
        if protocol_id:
            return await self.get_route(protocol_id)
        return None
        
    async def find_handler(self, protocol_id: int) -> Optional[Callable]:
        """
        查找处理器
        
        Args:
            protocol_id: 协议ID
            
        Returns:
            Callable: 处理器函数
        """
        route_info = await self.get_route(protocol_id)
        if route_info and route_info.is_available():
            return route_info.handler
        return None
        
    async def check_permission(self, protocol_id: int, user_permissions: Set[str]) -> bool:
        """
        检查权限
        
        Args:
            protocol_id: 协议ID
            user_permissions: 用户权限集合
            
        Returns:
            bool: 是否有权限
        """
        route_info = await self.get_route(protocol_id)
        if not route_info:
            return False
            
        # 检查路由权限
        if route_info.required_permissions:
            return bool(route_info.required_permissions.intersection(user_permissions))
            
        return True
        
    async def update_route_status(self, protocol_id: int, status: RouteStatus) -> bool:
        """
        更新路由状态
        
        Args:
            protocol_id: 协议ID
            status: 新状态
            
        Returns:
            bool: 是否更新成功
        """
        route_info = await self.get_route(protocol_id)
        if not route_info:
            return False
            
        old_status = route_info.status
        route_info.status = status
        
        # 更新统计
        if old_status == RouteStatus.ACTIVE and status != RouteStatus.ACTIVE:
            self._active_routes -= 1
            self._disabled_routes += 1
        elif old_status != RouteStatus.ACTIVE and status == RouteStatus.ACTIVE:
            self._active_routes += 1
            self._disabled_routes -= 1
            
        # 清除缓存
        self._clear_route_cache()
        
        logger.info("路由状态更新", 
                   protocol_id=protocol_id,
                   old_status=old_status.value,
                   new_status=status.value)
        
        return True
        
    async def add_route_stat(self, protocol_id: int, success: bool, duration: float):
        """
        添加路由统计
        
        Args:
            protocol_id: 协议ID
            success: 是否成功
            duration: 执行时间
        """
        route_info = await self.get_route(protocol_id)
        if route_info:
            route_info.add_request_stat(success, duration)
            
    def get_route_list(self, group_name: Optional[str] = None, 
                      status: Optional[RouteStatus] = None) -> List[RouteInfo]:
        """
        获取路由列表
        
        Args:
            group_name: 分组名称
            status: 状态过滤
            
        Returns:
            List[RouteInfo]: 路由列表
        """
        routes = []
        
        if group_name:
            # 从指定分组获取
            group = self._route_groups.get(group_name)
            if group:
                routes = list(group.routes.values())
        else:
            # 获取所有路由
            routes = list(self._routes.values())
            
        # 状态过滤
        if status:
            routes = [route for route in routes if route.status == status]
            
        return routes
        
    def get_group_list(self) -> List[RouteGroup]:
        """获取分组列表"""
        return list(self._route_groups.values())
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_routes": self._total_routes,
            "active_routes": self._active_routes,
            "disabled_routes": self._disabled_routes,
            "route_groups": len(self._route_groups),
            "route_aliases": len(self._route_aliases),
            "controllers": len(self._controllers),
            "middleware": len(self._middleware),
            "cache_hit_rate": self._get_cache_hit_rate()
        }
        
    async def register_middleware(self, middleware_name: str, middleware_func: Callable):
        """注册中间件"""
        self._middleware[middleware_name] = middleware_func
        logger.info("中间件注册成功", middleware_name=middleware_name)
        
    async def apply_middleware(self, middleware_names: List[str], request: Any, context: Any):
        """应用中间件"""
        for middleware_name in middleware_names:
            middleware_func = self._middleware.get(middleware_name)
            if middleware_func:
                try:
                    if inspect.iscoroutinefunction(middleware_func):
                        await middleware_func(request, context)
                    else:
                        middleware_func(request, context)
                except Exception as e:
                    logger.error("中间件执行失败", 
                               middleware_name=middleware_name,
                               error=str(e))
                    raise
                    
    async def _scan_controller_routes(self, controller_name: str, controller_instance: Any):
        """扫描控制器路由"""
        # 获取控制器的所有方法
        methods = inspect.getmembers(controller_instance, predicate=inspect.ismethod)
        
        for method_name, method in methods:
            # 检查方法是否有路由装饰器
            if hasattr(method, '_route_info'):
                route_info = method._route_info
                await self.register_route(
                    protocol_id=route_info.get('protocol_id'),
                    handler=method,
                    controller_name=controller_name,
                    method_name=method_name,
                    route_type=route_info.get('route_type', RouteType.REQUEST),
                    description=route_info.get('description', ''),
                    required_permissions=route_info.get('required_permissions', set()),
                    rate_limit=route_info.get('rate_limit'),
                    timeout=route_info.get('timeout', 30.0),
                    group_name=route_info.get('group_name', 'default'),
                    alias=route_info.get('alias'),
                    metadata=route_info.get('metadata', {})
                )
                
    async def _create_default_groups(self):
        """创建默认分组"""
        default_groups = [
            RouteGroup(group_name="default", description="默认分组"),
            RouteGroup(group_name="auth", description="认证相关"),
            RouteGroup(group_name="game", description="游戏相关"),
            RouteGroup(group_name="chat", description="聊天相关"),
            RouteGroup(group_name="admin", description="管理相关", required_permissions={"admin"})
        ]
        
        for group in default_groups:
            self._route_groups[group.group_name] = group
            
    async def _start_file_watchers(self):
        """启动文件监控"""
        # TODO: 实现文件监控，支持控制器热更新
        pass
        
    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        return time.time() - self._cache_update_time < self._cache_ttl
        
    def _clear_route_cache(self):
        """清除路由缓存"""
        self._route_cache.clear()
        self._cache_update_time = time.time()
        
    def _get_cache_hit_rate(self) -> float:
        """获取缓存命中率"""
        # TODO: 实现缓存命中率统计
        return 0.0


# 路由装饰器
def route(protocol_id: int, route_type: RouteType = RouteType.REQUEST,
         description: str = "", required_permissions: Optional[Set[str]] = None,
         rate_limit: Optional[int] = None, timeout: float = 30.0,
         group_name: str = "default", alias: Optional[str] = None,
         metadata: Optional[Dict[str, Any]] = None):
    """
    路由装饰器
    
    Args:
        protocol_id: 协议ID
        route_type: 路由类型
        description: 描述
        required_permissions: 必需权限
        rate_limit: 速率限制
        timeout: 超时时间
        group_name: 分组名称
        alias: 路由别名
        metadata: 元数据
    """
    def decorator(func):
        func._route_info = {
            'protocol_id': protocol_id,
            'route_type': route_type,
            'description': description,
            'required_permissions': required_permissions or set(),
            'rate_limit': rate_limit,
            'timeout': timeout,
            'group_name': group_name,
            'alias': alias,
            'metadata': metadata or {}
        }
        return func
    return decorator


# 全局路由管理器实例
_route_manager: Optional[RouteManager] = None


def get_route_manager() -> Optional[RouteManager]:
    """获取路由管理器实例"""
    return _route_manager


def create_route_manager(config: GatewayConfig) -> RouteManager:
    """创建路由管理器"""
    global _route_manager
    _route_manager = RouteManager(config)
    return _route_manager