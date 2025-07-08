"""
异步工具模块

该模块提供异步任务管理工具、异步上下文管理器、协程池管理
和异步装饰器等实用功能。
"""

import asyncio
import functools
import inspect
import time
import weakref
from typing import (
    Any, Awaitable, Callable, Dict, List, Optional, Set, TypeVar, Union,
    Generic, Coroutine, Iterator, AsyncIterator, AsyncContextManager
)
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from loguru import logger

T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


class AsyncTaskManager:
    """
    异步任务管理器
    
    提供批量执行、超时控制、任务监控等功能。
    """
    
    def __init__(self, max_concurrent_tasks: int = 100):
        """
        初始化任务管理器
        
        Args:
            max_concurrent_tasks: 最大并发任务数
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self._running_tasks: Set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._task_results: Dict[str, Any] = {}
        self._task_errors: Dict[str, Exception] = {}
    
    async def run_task(self, coro: Coroutine, task_id: Optional[str] = None) -> Any:
        """
        运行单个任务
        
        Args:
            coro: 协程对象
            task_id: 任务ID
            
        Returns:
            Any: 任务结果
        """
        async with self._semaphore:
            task = asyncio.create_task(coro)
            if task_id:
                task.set_name(task_id)
            
            self._running_tasks.add(task)
            try:
                result = await task
                if task_id:
                    self._task_results[task_id] = result
                return result
            except Exception as e:
                if task_id:
                    self._task_errors[task_id] = e
                raise
            finally:
                self._running_tasks.discard(task)
    
    async def run_tasks_batch(self, coros: List[Coroutine], 
                            return_exceptions: bool = False) -> List[Any]:
        """
        批量运行任务
        
        Args:
            coros: 协程列表
            return_exceptions: 是否返回异常而不是抛出
            
        Returns:
            List[Any]: 任务结果列表
        """
        tasks = []
        for i, coro in enumerate(coros):
            task = asyncio.create_task(self.run_task(coro, f"batch_task_{i}"))
            tasks.append(task)
        
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    
    async def run_tasks_with_timeout(self, coros: List[Coroutine], 
                                   timeout: float) -> List[Any]:
        """
        运行任务并设置超时
        
        Args:
            coros: 协程列表
            timeout: 超时时间（秒）
            
        Returns:
            List[Any]: 任务结果列表
            
        Raises:
            asyncio.TimeoutError: 如果超时
        """
        try:
            return await asyncio.wait_for(
                self.run_tasks_batch(coros, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # 取消所有运行中的任务
            await self.cancel_all_tasks()
            raise
    
    async def run_tasks_as_completed(self, coros: List[Coroutine]) -> AsyncIterator[Any]:
        """
        按完成顺序返回任务结果
        
        Args:
            coros: 协程列表
            
        Yields:
            Any: 任务结果
        """
        tasks = [asyncio.create_task(self.run_task(coro)) for coro in coros]
        
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
                yield result
            except Exception as e:
                logger.error(f"任务执行失败: {e}")
                yield e
    
    async def cancel_all_tasks(self) -> None:
        """取消所有运行中的任务"""
        if self._running_tasks:
            for task in self._running_tasks.copy():
                task.cancel()
            
            # 等待所有任务完成取消
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
            self._running_tasks.clear()
    
    def get_running_task_count(self) -> int:
        """获取运行中的任务数量"""
        return len(self._running_tasks)
    
    def get_task_result(self, task_id: str) -> Any:
        """获取任务结果"""
        return self._task_results.get(task_id)
    
    def get_task_error(self, task_id: str) -> Optional[Exception]:
        """获取任务错误"""
        return self._task_errors.get(task_id)
    
    def clear_results(self) -> None:
        """清空任务结果和错误"""
        self._task_results.clear()
        self._task_errors.clear()


class AsyncContextManager:
    """
    异步上下文管理器基类
    
    提供异步资源管理的基础功能。
    """
    
    async def __aenter__(self):
        """进入上下文"""
        await self.setup()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        await self.cleanup()
        return False
    
    async def setup(self):
        """设置资源（子类重写）"""
        pass
    
    async def cleanup(self):
        """清理资源（子类重写）"""
        pass


class AsyncConnectionPool(AsyncContextManager):
    """
    异步连接池
    
    管理异步连接的获取和释放。
    """
    
    def __init__(self, connection_factory: Callable[[], Awaitable[T]], 
                 max_size: int = 10, min_size: int = 2):
        """
        初始化连接池
        
        Args:
            connection_factory: 连接工厂函数
            max_size: 最大连接数
            min_size: 最小连接数
        """
        self.connection_factory = connection_factory
        self.max_size = max_size
        self.min_size = min_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._active_connections: Set[T] = set()
        self._closed = False
    
    async def setup(self):
        """初始化连接池"""
        # 创建最小数量的连接
        for _ in range(self.min_size):
            connection = await self.connection_factory()
            await self._pool.put(connection)
    
    async def acquire(self) -> T:
        """
        获取连接
        
        Returns:
            T: 连接对象
        """
        if self._closed:
            raise RuntimeError("连接池已关闭")
        
        try:
            # 尝试从池中获取连接
            connection = self._pool.get_nowait()
        except asyncio.QueueEmpty:
            # 如果池为空且未达到最大连接数，创建新连接
            if len(self._active_connections) < self.max_size:
                connection = await self.connection_factory()
            else:
                # 等待连接可用
                connection = await self._pool.get()
        
        self._active_connections.add(connection)
        return connection
    
    async def release(self, connection: T):
        """
        释放连接
        
        Args:
            connection: 连接对象
        """
        if connection in self._active_connections:
            self._active_connections.remove(connection)
            
            if not self._closed and self._pool.qsize() < self.max_size:
                await self._pool.put(connection)
            else:
                # 关闭多余的连接
                if hasattr(connection, 'close'):
                    if asyncio.iscoroutinefunction(connection.close):
                        await connection.close()
                    else:
                        connection.close()
    
    async def cleanup(self):
        """清理连接池"""
        self._closed = True
        
        # 关闭池中的所有连接
        while not self._pool.empty():
            try:
                connection = self._pool.get_nowait()
                if hasattr(connection, 'close'):
                    if asyncio.iscoroutinefunction(connection.close):
                        await connection.close()
                    else:
                        connection.close()
            except asyncio.QueueEmpty:
                break
        
        # 关闭活跃连接
        for connection in self._active_connections.copy():
            if hasattr(connection, 'close'):
                if asyncio.iscoroutinefunction(connection.close):
                    await connection.close()
                else:
                    connection.close()
        
        self._active_connections.clear()
    
    @asynccontextmanager
    async def get_connection(self):
        """
        获取连接的上下文管理器
        
        Example:
            async with pool.get_connection() as conn:
                # 使用连接
                result = await conn.execute("SELECT 1")
        """
        connection = await self.acquire()
        try:
            yield connection
        finally:
            await self.release(connection)


class CoroutinePool:
    """
    协程池管理器
    
    管理协程的创建、执行和生命周期。
    """
    
    def __init__(self, max_workers: int = 10):
        """
        初始化协程池
        
        Args:
            max_workers: 最大工作协程数
        """
        self.max_workers = max_workers
        self._semaphore = asyncio.Semaphore(max_workers)
        self._workers: Set[asyncio.Task] = set()
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._results: Dict[str, Any] = {}
        self._running = False
    
    async def start(self):
        """启动协程池"""
        if self._running:
            return
        
        self._running = True
        
        # 启动工作协程
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(f"worker_{i}"))
            self._workers.add(worker)
    
    async def stop(self):
        """停止协程池"""
        if not self._running:
            return
        
        self._running = False
        
        # 等待队列清空
        await self._task_queue.join()
        
        # 取消所有工作协程
        for worker in self._workers:
            worker.cancel()
        
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
    
    async def submit(self, coro: Coroutine, task_id: Optional[str] = None) -> str:
        """
        提交任务到协程池
        
        Args:
            coro: 协程对象
            task_id: 任务ID
            
        Returns:
            str: 任务ID
        """
        if not self._running:
            raise RuntimeError("协程池未启动")
        
        if task_id is None:
            task_id = f"task_{time.time()}_{id(coro)}"
        
        await self._task_queue.put((task_id, coro))
        return task_id
    
    def get_result(self, task_id: str) -> Any:
        """获取任务结果"""
        return self._results.get(task_id)
    
    async def _worker(self, worker_name: str):
        """工作协程"""
        while self._running:
            try:
                # 获取任务
                task_id, coro = await asyncio.wait_for(
                    self._task_queue.get(), timeout=1.0
                )
                
                try:
                    # 执行任务
                    result = await coro
                    self._results[task_id] = result
                except Exception as e:
                    logger.error(f"任务 {task_id} 执行失败: {e}")
                    self._results[task_id] = e
                finally:
                    self._task_queue.task_done()
                    
            except asyncio.TimeoutError:
                # 超时继续循环
                continue
            except Exception as e:
                logger.error(f"工作协程 {worker_name} 发生错误: {e}")


# 异步装饰器

def async_retry(max_attempts: int = 3, delay: float = 1.0, 
               backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """
    异步重试装饰器
    
    Args:
        max_attempts: 最大重试次数
        delay: 初始延迟时间
        backoff: 退避倍数
        exceptions: 需要重试的异常类型
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts - 1:
                        break
                    
                    logger.warning(f"第 {attempt + 1} 次尝试失败: {e}, "
                                 f"{current_delay:.2f}秒后重试")
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            raise last_exception
        
        return wrapper
    return decorator


def async_timeout(timeout: float):
    """
    异步超时装饰器
    
    Args:
        timeout: 超时时间（秒）
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
        return wrapper
    return decorator


def async_cache(maxsize: int = 128, ttl: Optional[float] = None):
    """
    异步缓存装饰器
    
    Args:
        maxsize: 最大缓存条目数
        ttl: 缓存生存时间（秒）
    """
    def decorator(func: F) -> F:
        cache: Dict[str, tuple] = {}
        cache_times: Dict[str, float] = {}
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            key = str(args) + str(sorted(kwargs.items()))
            current_time = time.time()
            
            # 检查缓存
            if key in cache:
                cached_time = cache_times.get(key, 0)
                if ttl is None or (current_time - cached_time) < ttl:
                    return cache[key][0]
                else:
                    # 缓存过期，删除
                    del cache[key]
                    del cache_times[key]
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 缓存结果
            if len(cache) >= maxsize:
                # 删除最老的缓存条目
                oldest_key = min(cache_times.keys(), key=lambda k: cache_times[k])
                del cache[oldest_key]
                del cache_times[oldest_key]
            
            cache[key] = (result,)
            cache_times[key] = current_time
            
            return result
        
        # 添加缓存管理方法
        wrapper.cache_info = lambda: {
            'size': len(cache),
            'maxsize': maxsize,
            'keys': list(cache.keys())
        }
        wrapper.cache_clear = lambda: (cache.clear(), cache_times.clear())
        
        return wrapper
    return decorator


def async_rate_limit(calls_per_second: float):
    """
    异步限流装饰器
    
    Args:
        calls_per_second: 每秒调用次数限制
    """
    def decorator(func: F) -> F:
        min_interval = 1.0 / calls_per_second
        last_called = [0.0]
        lock = asyncio.Lock()
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async with lock:
                current_time = time.time()
                time_since_last = current_time - last_called[0]
                
                if time_since_last < min_interval:
                    sleep_time = min_interval - time_since_last
                    await asyncio.sleep(sleep_time)
                
                last_called[0] = time.time()
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def run_in_thread_pool(executor: Optional[ThreadPoolExecutor] = None):
    """
    在线程池中运行同步函数的装饰器
    
    Args:
        executor: 线程池执行器
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, 
                                            functools.partial(func, *args, **kwargs))
        return wrapper
    return decorator


# 工具函数

async def gather_with_concurrency(n: int, *coros) -> List[Any]:
    """
    限制并发数的gather函数
    
    Args:
        n: 最大并发数
        *coros: 协程对象
        
    Returns:
        List[Any]: 结果列表
    """
    semaphore = asyncio.Semaphore(n)
    
    async def sem_coro(coro):
        async with semaphore:
            return await coro
    
    return await asyncio.gather(*(sem_coro(coro) for coro in coros))


async def wait_for_any(*coros, timeout: Optional[float] = None) -> Any:
    """
    等待任意一个协程完成
    
    Args:
        *coros: 协程对象
        timeout: 超时时间
        
    Returns:
        Any: 第一个完成的协程结果
    """
    tasks = [asyncio.create_task(coro) for coro in coros]
    
    try:
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED, timeout=timeout
        )
        
        if not done:
            raise asyncio.TimeoutError("等待超时")
        
        # 取消未完成的任务
        for task in pending:
            task.cancel()
        
        # 返回第一个完成的结果
        return await list(done)[0]
    
    except Exception:
        # 取消所有任务
        for task in tasks:
            task.cancel()
        raise


@asynccontextmanager
async def async_timer(name: str = "operation"):
    """
    异步计时器上下文管理器
    
    Args:
        name: 操作名称
    """
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.debug(f"{name} 耗时: {elapsed:.3f}秒")


# 示例使用

if __name__ == "__main__":
    async def example_usage():
        """示例使用"""
        
        # 使用任务管理器
        task_manager = AsyncTaskManager(max_concurrent_tasks=5)
        
        async def sample_task(n: int) -> int:
            await asyncio.sleep(0.1)
            return n * 2
        
        # 批量执行任务
        coros = [sample_task(i) for i in range(10)]
        results = await task_manager.run_tasks_batch(coros)
        print(f"批量任务结果: {results}")
        
        # 使用装饰器
        @async_retry(max_attempts=3)
        @async_timeout(5.0)
        @async_cache(maxsize=100, ttl=60.0)
        async def api_call(param: str) -> str:
            await asyncio.sleep(0.1)
            return f"Result for {param}"
        
        result = await api_call("test")
        print(f"API调用结果: {result}")
        
        # 使用计时器
        async with async_timer("测试操作"):
            await asyncio.sleep(0.1)
    
    # 运行示例
    asyncio.run(example_usage())