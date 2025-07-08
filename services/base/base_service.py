"""
基础业务服务类模块

该模块提供了业务逻辑的基础框架，支持事务管理、缓存集成、
微服务调用、异步方法支持、业务日志记录、性能监控等功能。

主要功能：
- 业务逻辑的基础框架
- 事务支持
- 缓存集成
- 调用其他微服务的标准方法
- 异步方法支持
- 业务日志记录
- 性能监控点
- 错误处理和回滚机制

使用示例：
```python
from services.base.base_service import BaseService

class UserService(BaseService):
    def __init__(self):
        super().__init__()
        self.user_repository = self.get_repository("UserRepository")
    
    @transactional
    async def create_user(self, user_data: dict) -> dict:
        # 业务逻辑
        user = await self.user_repository.create(user_data)
        
        # 发送通知
        await self.notify_user_created(user)
        
        return user
    
    @cached(ttl=300)
    async def get_user_by_id(self, user_id: str) -> dict:
        return await self.user_repository.get_by_id(user_id)
    
    async def notify_user_created(self, user: dict):
        # 调用其他微服务
        await self.call_service("notification", "send_welcome_email", user)
```
"""

import asyncio
import time
import functools
import inspect
from typing import Dict, List, Optional, Any, Callable, Type, Union
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from common.logger import logger
try:
    from common.db import get_db_connection, TransactionManager
except ImportError:
    # Mock database classes if not available
    class TransactionManager:
        def __init__(self):
            pass
        async def initialize(self):
            pass
        async def begin(self, tx_id):
            pass
        async def commit(self, tx_id):
            pass
        async def rollback(self, tx_id):
            pass
    
    def get_db_connection(name):
        return None

from common.grpc.grpc_client import GrpcClient
try:
    from common.celery.async_task import AsyncTaskManager
except ImportError:
    # Mock AsyncTaskManager if not available
    class AsyncTaskManager:
        def __init__(self):
            pass
        async def initialize(self):
            pass
try:
    from common.monitor import MonitorManager, record_service_metrics
except ImportError:
    class MonitorManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
    
    async def record_service_metrics(*args, **kwargs):
        pass


class ServiceException(Exception):
    """服务异常基类"""
    def __init__(self, message: str, error_code: str = "SERVICE_ERROR", details: dict = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class TransactionException(ServiceException):
    """事务异常"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, "TRANSACTION_ERROR", details)


class CacheException(ServiceException):
    """缓存异常"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, "CACHE_ERROR", details)


class ServiceCallException(ServiceException):
    """服务调用异常"""
    def __init__(self, message: str, service_name: str, details: dict = None):
        super().__init__(message, "SERVICE_CALL_ERROR", details)
        self.service_name = service_name


@dataclass
class ServiceConfig:
    """服务配置"""
    # 事务配置
    enable_transactions: bool = True
    transaction_timeout: float = 30.0
    
    # 缓存配置
    enable_caching: bool = True
    cache_ttl: int = 300
    cache_max_size: int = 1000
    
    # 监控配置
    enable_monitoring: bool = True
    enable_metrics: bool = True
    
    # 异步配置
    thread_pool_size: int = 10
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # 超时配置
    default_timeout: float = 30.0
    
    # 其他配置
    metadata: Dict[str, Any] = field(default_factory=dict)


class TransactionContext:
    """事务上下文"""
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        self.start_time = time.time()
        self.rollback_handlers: List[Callable] = []
        self.commit_handlers: List[Callable] = []
        self.active = True
        self.metadata: Dict[str, Any] = {}


class BaseService:
    """
    基础业务服务类
    
    所有业务服务的基类，提供：
    - 事务管理
    - 缓存集成
    - 微服务调用
    - 异步支持
    - 业务日志
    - 性能监控
    - 错误处理
    - 回滚机制
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        """
        初始化基础服务
        
        Args:
            config: 服务配置
        """
        self.config = config or ServiceConfig()
        self.logger = logger
        
        # 服务基本信息
        self.service_name = self.__class__.__name__
        
        # 核心组件
        self._transaction_manager = TransactionManager() if self.config.enable_transactions else None
        self._monitor_manager = MonitorManager() if self.config.enable_monitoring else None
        self._async_task_manager = AsyncTaskManager()
        
        # 数据访问层
        self._repositories: Dict[str, Any] = {}
        
        # 微服务客户端
        self._service_clients: Dict[str, GrpcClient] = {}
        
        # 缓存
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        
        # 事务上下文
        self._transaction_contexts: Dict[str, TransactionContext] = {}
        
        # 线程池
        self._thread_pool = ThreadPoolExecutor(max_workers=self.config.thread_pool_size)
        
        # 中间件
        self._before_middlewares: List[Callable] = []
        self._after_middlewares: List[Callable] = []
        self._error_middlewares: List[Callable] = []
        
        self.logger.info("基础服务初始化完成", service_name=self.service_name)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化事务管理器
            if self._transaction_manager:
                await self._transaction_manager.initialize()
            
            # 初始化监控管理器
            if self._monitor_manager:
                await self._monitor_manager.initialize()
            
            # 初始化异步任务管理器
            await self._async_task_manager.initialize()
            
            # 初始化服务客户端
            await self._initialize_service_clients()
            
            self.logger.info("服务初始化完成", service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("服务初始化失败", 
                            service_name=self.service_name,
                            error=str(e))
            raise
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理缓存
            self._cache.clear()
            self._cache_timestamps.clear()
            
            # 清理事务上下文
            for context in self._transaction_contexts.values():
                if context.active:
                    await self._rollback_transaction(context)
            self._transaction_contexts.clear()
            
            # 关闭服务客户端
            for client in self._service_clients.values():
                await client.close()
            
            # 关闭线程池
            self._thread_pool.shutdown(wait=True)
            
            # 清理repositories
            for repo in self._repositories.values():
                if hasattr(repo, 'cleanup'):
                    await repo.cleanup()
            
            self.logger.info("服务清理完成", service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("服务清理失败", 
                            service_name=self.service_name,
                            error=str(e))
    
    def get_repository(self, repository_name: str) -> Any:
        """
        获取数据访问层实例
        
        Args:
            repository_name: 数据访问层名称
            
        Returns:
            Any: 数据访问层实例
        """
        if repository_name not in self._repositories:
            raise ServiceException(f"数据访问层 {repository_name} 未找到")
        
        return self._repositories[repository_name]
    
    def register_repository(self, repository_name: str, repository: Any):
        """
        注册数据访问层
        
        Args:
            repository_name: 数据访问层名称
            repository: 数据访问层实例
        """
        self._repositories[repository_name] = repository
        # 异步初始化repository
        asyncio.create_task(self._initialize_repository(repository))
        self.logger.info("数据访问层注册成功", 
                        service_name=self.service_name,
                        repository_name=repository_name)
    
    async def _initialize_repository(self, repository):
        """初始化repository"""
        try:
            if hasattr(repository, 'initialize'):
                await repository.initialize()
        except Exception as e:
            self.logger.error("Repository初始化失败", error=str(e))
    
    async def call_service(self, service_name: str, method_name: str, *args, **kwargs) -> Any:
        """
        调用其他微服务
        
        Args:
            service_name: 服务名称
            method_name: 方法名称
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 调用结果
        """
        start_time = time.time()
        
        try:
            # 获取服务客户端
            client = self._service_clients.get(service_name)
            if not client:
                raise ServiceCallException(f"服务 {service_name} 的客户端未找到", service_name)
            
            # 调用远程服务
            result = await client.call_method(method_name, *args, **kwargs)
            
            # 记录监控指标
            if self._monitor_manager:
                await record_service_metrics(
                    service_name=service_name,
                    method_name=method_name,
                    latency=time.time() - start_time,
                    success=True
                )
            
            self.logger.info("微服务调用成功", 
                           service_name=service_name,
                           method_name=method_name,
                           latency=time.time() - start_time)
            
            return result
            
        except Exception as e:
            # 记录监控指标
            if self._monitor_manager:
                await record_service_metrics(
                    service_name=service_name,
                    method_name=method_name,
                    latency=time.time() - start_time,
                    success=False
                )
            
            self.logger.error("微服务调用失败", 
                            service_name=service_name,
                            method_name=method_name,
                            error=str(e))
            
            raise ServiceCallException(f"调用服务 {service_name}.{method_name} 失败: {str(e)}", service_name)
    
    async def execute_async_task(self, task_func: Callable, *args, **kwargs) -> Any:
        """
        执行异步任务
        
        Args:
            task_func: 任务函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 任务结果
        """
        try:
            # 如果是协程函数，直接调用
            if inspect.iscoroutinefunction(task_func):
                return await task_func(*args, **kwargs)
            else:
                # 如果是普通函数，在线程池中执行
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(self._thread_pool, task_func, *args, **kwargs)
                
        except Exception as e:
            self.logger.error("异步任务执行失败", 
                            task_func=task_func.__name__,
                            error=str(e))
            raise
    
    def get_cache(self, key: str) -> Any:
        """
        获取缓存
        
        Args:
            key: 缓存键
            
        Returns:
            Any: 缓存值
        """
        if not self.config.enable_caching:
            return None
        
        if key not in self._cache:
            return None
        
        # 检查缓存是否过期
        if time.time() - self._cache_timestamps[key] > self.config.cache_ttl:
            del self._cache[key]
            del self._cache_timestamps[key]
            return None
        
        return self._cache[key]
    
    def set_cache(self, key: str, value: Any, ttl: int = None):
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 缓存过期时间（秒）
        """
        if not self.config.enable_caching:
            return
        
        # 检查缓存大小限制
        if len(self._cache) >= self.config.cache_max_size:
            # 清理最老的缓存项
            oldest_key = min(self._cache_timestamps, key=self._cache_timestamps.get)
            del self._cache[oldest_key]
            del self._cache_timestamps[oldest_key]
        
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()
    
    def clear_cache(self, key: str = None):
        """
        清除缓存
        
        Args:
            key: 缓存键，如果为None则清除所有缓存
        """
        if key:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
    
    @asynccontextmanager
    async def transaction(self, transaction_id: str = None):
        """
        事务上下文管理器
        
        Args:
            transaction_id: 事务ID，如果为None则自动生成
        """
        if not self.config.enable_transactions:
            yield None
            return
        
        if transaction_id is None:
            transaction_id = f"tx_{int(time.time() * 1000000)}"
        
        # 创建事务上下文
        context = TransactionContext(transaction_id)
        self._transaction_contexts[transaction_id] = context
        
        try:
            # 开始事务
            await self._begin_transaction(context)
            
            yield context
            
            # 提交事务
            await self._commit_transaction(context)
            
        except Exception as e:
            # 回滚事务
            await self._rollback_transaction(context)
            raise
            
        finally:
            # 清理事务上下文
            if transaction_id in self._transaction_contexts:
                del self._transaction_contexts[transaction_id]
    
    async def _begin_transaction(self, context: TransactionContext):
        """开始事务"""
        try:
            if self._transaction_manager:
                await self._transaction_manager.begin(context.transaction_id)
            
            self.logger.info("事务开始", 
                           transaction_id=context.transaction_id,
                           service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("事务开始失败", 
                            transaction_id=context.transaction_id,
                            service_name=self.service_name,
                            error=str(e))
            raise TransactionException(f"事务开始失败: {str(e)}")
    
    async def _commit_transaction(self, context: TransactionContext):
        """提交事务"""
        try:
            # 执行提交前处理器
            for handler in context.commit_handlers:
                await handler()
            
            # 提交事务
            if self._transaction_manager:
                await self._transaction_manager.commit(context.transaction_id)
            
            context.active = False
            
            self.logger.info("事务提交成功", 
                           transaction_id=context.transaction_id,
                           service_name=self.service_name,
                           duration=time.time() - context.start_time)
            
        except Exception as e:
            # 提交失败，尝试回滚
            await self._rollback_transaction(context)
            
            self.logger.error("事务提交失败", 
                            transaction_id=context.transaction_id,
                            service_name=self.service_name,
                            error=str(e))
            
            raise TransactionException(f"事务提交失败: {str(e)}")
    
    async def _rollback_transaction(self, context: TransactionContext):
        """回滚事务"""
        try:
            # 执行回滚处理器
            for handler in reversed(context.rollback_handlers):
                try:
                    await handler()
                except Exception as e:
                    self.logger.error("回滚处理器执行失败", 
                                    transaction_id=context.transaction_id,
                                    error=str(e))
            
            # 回滚事务
            if self._transaction_manager:
                await self._transaction_manager.rollback(context.transaction_id)
            
            context.active = False
            
            self.logger.info("事务回滚成功", 
                           transaction_id=context.transaction_id,
                           service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("事务回滚失败", 
                            transaction_id=context.transaction_id,
                            service_name=self.service_name,
                            error=str(e))
            
            raise TransactionException(f"事务回滚失败: {str(e)}")
    
    async def _initialize_service_clients(self):
        """初始化服务客户端"""
        # 这里可以根据配置初始化各种服务客户端
        # 示例：初始化用户服务客户端
        # self._service_clients['user'] = GrpcClient('user_service', 'localhost:50051')
        pass
    
    async def _execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        带重试的执行
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 执行结果
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
                    
            except Exception as e:
                last_exception = e
                
                if attempt < self.config.max_retries:
                    wait_time = self.config.retry_delay * (2 ** attempt)  # 指数退避
                    self.logger.warning(f"执行失败，{wait_time}秒后重试 (第{attempt + 1}次)", 
                                      error=str(e))
                    await asyncio.sleep(wait_time)
                else:
                    break
        
        raise last_exception
    
    def add_before_middleware(self, middleware: Callable):
        """添加前置中间件"""
        self._before_middlewares.append(middleware)
    
    def add_after_middleware(self, middleware: Callable):
        """添加后置中间件"""
        self._after_middlewares.append(middleware)
    
    def add_error_middleware(self, middleware: Callable):
        """添加错误中间件"""
        self._error_middlewares.append(middleware)
    
    @property
    def repositories(self) -> Dict[str, Any]:
        """获取已注册的数据访问层"""
        return self._repositories.copy()
    
    @property
    def service_clients(self) -> Dict[str, GrpcClient]:
        """获取服务客户端"""
        return self._service_clients.copy()


# 装饰器：事务支持
def transactional(timeout: float = None):
    """
    事务装饰器
    
    Args:
        timeout: 事务超时时间
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not isinstance(self, BaseService):
                raise ValueError("@transactional 装饰器只能用于 BaseService 的方法")
            
            async with self.transaction() as tx:
                return await func(self, *args, **kwargs)
        
        return wrapper
    return decorator


# 装饰器：缓存支持
def cached(ttl: int = None, key_func: Callable = None):
    """
    缓存装饰器
    
    Args:
        ttl: 缓存过期时间
        key_func: 缓存键生成函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not isinstance(self, BaseService):
                raise ValueError("@cached 装饰器只能用于 BaseService 的方法")
            
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{self.service_name}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # 尝试从缓存获取
            cached_result = self.get_cache(cache_key)
            if cached_result is not None:
                return cached_result
            
            # 执行原函数
            result = await func(self, *args, **kwargs)
            
            # 设置缓存
            self.set_cache(cache_key, result, ttl or self.config.cache_ttl)
            
            return result
        
        return wrapper
    return decorator


# 装饰器：重试支持
def retry(max_retries: int = 3, delay: float = 1.0):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 重试延迟
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not isinstance(self, BaseService):
                raise ValueError("@retry 装饰器只能用于 BaseService 的方法")
            
            return await self._execute_with_retry(func, self, *args, **kwargs)
        
        return wrapper
    return decorator


# 装饰器：监控支持
def monitored(metric_name: str = None):
    """
    监控装饰器
    
    Args:
        metric_name: 指标名称
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not isinstance(self, BaseService):
                raise ValueError("@monitored 装饰器只能用于 BaseService 的方法")
            
            start_time = time.time()
            success = True
            
            try:
                result = await func(self, *args, **kwargs)
                return result
            except Exception as e:
                success = False
                raise
            finally:
                if self._monitor_manager:
                    await record_service_metrics(
                        service_name=self.service_name,
                        method_name=metric_name or func.__name__,
                        latency=time.time() - start_time,
                        success=success
                    )
        
        return wrapper
    return decorator