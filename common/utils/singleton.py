"""
单例模式实现

该模块提供线程安全的单例模式元类，支持异步单例模式，
并提供装饰器方式使用单例模式。
"""

import threading
import asyncio
from typing import Any, Dict, Type, TypeVar, Optional, Callable
from functools import wraps

T = TypeVar('T')


class SingletonMeta(type):
    """
    线程安全的单例元类
    
    使用元类实现单例模式，确保在多线程环境下的线程安全。
    """
    
    _instances: Dict[Type, Any] = {}
    _lock = threading.Lock()
    
    def __call__(cls, *args, **kwargs):
        """
        创建或返回单例实例
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 单例实例
        """
        if cls not in cls._instances:
            with cls._lock:
                # 双重检查锁定模式
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]
    
    @classmethod
    def clear_instances(mcs) -> None:
        """清空所有单例实例（主要用于测试）"""
        with mcs._lock:
            mcs._instances.clear()
    
    @classmethod
    def remove_instance(mcs, cls: Type) -> None:
        """
        移除指定类的单例实例
        
        Args:
            cls: 要移除的类
        """
        with mcs._lock:
            if cls in mcs._instances:
                del mcs._instances[cls]


class AsyncSingletonMeta(type):
    """
    异步单例元类
    
    专门为异步类设计的单例模式，支持异步初始化。
    """
    
    _instances: Dict[Type, Any] = {}
    _locks: Dict[Type, asyncio.Lock] = {}
    _main_lock = threading.Lock()
    
    def __call__(cls, *args, **kwargs):
        """
        创建单例实例（同步版本）
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 单例实例
        """
        if cls not in cls._instances:
            with cls._main_lock:
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
                    # 为每个类创建独立的异步锁
                    cls._locks[cls] = asyncio.Lock()
        return cls._instances[cls]
    
    async def get_instance_async(cls, *args, **kwargs):
        """
        异步获取单例实例
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 单例实例
        """
        if cls not in cls._instances:
            # 确保异步锁存在
            if cls not in cls._locks:
                with cls._main_lock:
                    if cls not in cls._locks:
                        cls._locks[cls] = asyncio.Lock()
            
            async with cls._locks[cls]:
                if cls not in cls._instances:
                    instance = cls(*args, **kwargs)
                    # 如果实例有异步初始化方法，调用它
                    if hasattr(instance, 'async_init'):
                        await instance.async_init()
                    cls._instances[cls] = instance
        
        return cls._instances[cls]
    
    @classmethod
    def clear_instances(mcs) -> None:
        """清空所有单例实例"""
        with mcs._main_lock:
            mcs._instances.clear()
            mcs._locks.clear()
    
    @classmethod
    def remove_instance(mcs, cls: Type) -> None:
        """
        移除指定类的单例实例
        
        Args:
            cls: 要移除的类
        """
        with mcs._main_lock:
            if cls in mcs._instances:
                del mcs._instances[cls]
            if cls in mcs._locks:
                del mcs._locks[cls]


class Singleton(metaclass=SingletonMeta):
    """
    单例基类
    
    继承此类的所有子类都将自动成为单例。
    """
    
    def __new__(cls, *args, **kwargs):
        """
        创建实例时的特殊处理
        
        确保单例的__init__方法只被调用一次。
        """
        instance = super().__new__(cls)
        if not hasattr(instance, '_initialized'):
            instance._initialized = False
        return instance
    
    def __init__(self):
        """初始化方法"""
        if not self._initialized:
            self._initialized = True
            # 子类可以重写此方法进行初始化


class AsyncSingleton(metaclass=AsyncSingletonMeta):
    """
    异步单例基类
    
    继承此类的所有子类都将自动成为异步单例。
    """
    
    def __new__(cls, *args, **kwargs):
        """创建实例时的特殊处理"""
        instance = super().__new__(cls)
        if not hasattr(instance, '_initialized'):
            instance._initialized = False
        return instance
    
    def __init__(self):
        """同步初始化方法"""
        if not self._initialized:
            self._initialized = True
    
    async def async_init(self):
        """
        异步初始化方法
        
        子类可以重写此方法进行异步初始化。
        """
        pass
    
    @classmethod
    async def get_instance(cls, *args, **kwargs):
        """
        异步获取单例实例
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 单例实例
        """
        return await cls.__class__.get_instance_async(cls, *args, **kwargs)


def singleton(cls: Type[T]) -> Type[T]:
    """
    单例装饰器
    
    使用装饰器方式实现单例模式。
    
    Args:
        cls: 要装饰的类
        
    Returns:
        Type[T]: 装饰后的类
        
    Example:
        @singleton
        class MyClass:
            def __init__(self):
                self.value = 42
        
        # 以下两个实例是相同的
        instance1 = MyClass()
        instance2 = MyClass()
        assert instance1 is instance2
    """
    instances = {}
    lock = threading.Lock()
    
    @wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            with lock:
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    # 添加清理方法
    get_instance.clear_instance = lambda: instances.pop(cls, None)
    get_instance.get_all_instances = lambda: instances.copy()
    
    return get_instance


def async_singleton(cls: Type[T]) -> Type[T]:
    """
    异步单例装饰器
    
    使用装饰器方式实现异步单例模式。
    
    Args:
        cls: 要装饰的类
        
    Returns:
        Type[T]: 装饰后的类
        
    Example:
        @async_singleton
        class MyAsyncClass:
            async def __init__(self):
                await asyncio.sleep(0.1)
                self.value = 42
        
        # 异步获取单例实例
        instance1 = await MyAsyncClass.get_instance()
        instance2 = await MyAsyncClass.get_instance()
        assert instance1 is instance2
    """
    instances = {}
    lock = asyncio.Lock()
    thread_lock = threading.Lock()
    
    async def get_instance(*args, **kwargs):
        if cls not in instances:
            # 确保锁存在
            if not hasattr(get_instance, '_lock_initialized'):
                with thread_lock:
                    if not hasattr(get_instance, '_lock_initialized'):
                        get_instance._async_lock = asyncio.Lock()
                        get_instance._lock_initialized = True
            
            async with get_instance._async_lock:
                if cls not in instances:
                    instance = cls(*args, **kwargs)
                    # 如果__init__是异步的，等待它完成
                    if asyncio.iscoroutine(instance):
                        instance = await instance
                    # 如果有异步初始化方法，调用它
                    elif hasattr(instance, 'async_init'):
                        await instance.async_init()
                    instances[cls] = instance
        return instances[cls]
    
    # 同步获取方法（如果实例已存在）
    def get_instance_sync(*args, **kwargs):
        if cls in instances:
            return instances[cls]
        raise RuntimeError(f"异步单例 {cls.__name__} 尚未初始化，请使用 await {cls.__name__}.get_instance()")
    
    # 添加方法到类
    cls.get_instance = staticmethod(get_instance)
    cls.get_instance_sync = staticmethod(get_instance_sync)
    cls.clear_instance = staticmethod(lambda: instances.pop(cls, None))
    cls.get_all_instances = staticmethod(lambda: instances.copy())
    
    return cls


class SingletonRegistry:
    """
    单例注册表
    
    管理和监控所有单例实例。
    """
    
    _registry: Dict[str, Any] = {}
    _lock = threading.Lock()
    
    @classmethod
    def register(cls, name: str, instance: Any) -> None:
        """
        注册单例实例
        
        Args:
            name: 实例名称
            instance: 实例对象
        """
        with cls._lock:
            cls._registry[name] = instance
    
    @classmethod
    def get(cls, name: str) -> Optional[Any]:
        """
        获取注册的单例实例
        
        Args:
            name: 实例名称
            
        Returns:
            Optional[Any]: 实例对象，如果不存在则返回None
        """
        return cls._registry.get(name)
    
    @classmethod
    def remove(cls, name: str) -> bool:
        """
        移除注册的单例实例
        
        Args:
            name: 实例名称
            
        Returns:
            bool: 是否成功移除
        """
        with cls._lock:
            if name in cls._registry:
                del cls._registry[name]
                return True
            return False
    
    @classmethod
    def list_all(cls) -> Dict[str, str]:
        """
        列出所有注册的单例实例
        
        Returns:
            Dict[str, str]: 实例名称到类名的映射
        """
        return {name: type(instance).__name__ for name, instance in cls._registry.items()}
    
    @classmethod
    def clear_all(cls) -> None:
        """清空所有注册的实例"""
        with cls._lock:
            cls._registry.clear()
    
    @classmethod
    def count(cls) -> int:
        """
        获取注册实例数量
        
        Returns:
            int: 实例数量
        """
        return len(cls._registry)


def register_singleton(name: str):
    """
    单例注册装饰器
    
    自动将单例实例注册到注册表中。
    
    Args:
        name: 注册名称
        
    Example:
        @register_singleton("database_manager")
        @singleton
        class DatabaseManager:
            pass
        
        # 可以通过注册表获取实例
        db_manager = SingletonRegistry.get("database_manager")
    """
    def decorator(cls: Type[T]) -> Type[T]:
        original_new = cls.__new__
        
        def new_new(cls_inner, *args, **kwargs):
            instance = original_new(cls_inner)
            SingletonRegistry.register(name, instance)
            return instance
        
        cls.__new__ = staticmethod(new_new)
        return cls
    
    return decorator


# 示例使用

class ExampleSingleton(Singleton):
    """示例单例类"""
    
    def __init__(self):
        super().__init__()
        if not hasattr(self, 'value'):
            self.value = "Hello, Singleton!"
    
    def get_value(self) -> str:
        return self.value


class ExampleAsyncSingleton(AsyncSingleton):
    """示例异步单例类"""
    
    async def async_init(self):
        """异步初始化"""
        await asyncio.sleep(0.01)  # 模拟异步操作
        self.value = "Hello, Async Singleton!"
    
    def get_value(self) -> str:
        return getattr(self, 'value', 'Not initialized')


@singleton
class ExampleDecoratorSingleton:
    """示例装饰器单例类"""
    
    def __init__(self):
        self.value = "Hello, Decorator Singleton!"
    
    def get_value(self) -> str:
        return self.value


@async_singleton
class ExampleAsyncDecoratorSingleton:
    """示例异步装饰器单例类"""
    
    def __init__(self):
        self._initialized = False
    
    async def async_init(self):
        """异步初始化"""
        await asyncio.sleep(0.01)
        self.value = "Hello, Async Decorator Singleton!"
        self._initialized = True
    
    def get_value(self) -> str:
        return getattr(self, 'value', 'Not initialized')


if __name__ == "__main__":
    # 测试代码
    import asyncio
    
    def test_singleton():
        """测试普通单例"""
        instance1 = ExampleSingleton()
        instance2 = ExampleSingleton()
        print(f"普通单例测试: {instance1 is instance2}")
        print(f"值: {instance1.get_value()}")
    
    def test_decorator_singleton():
        """测试装饰器单例"""
        instance1 = ExampleDecoratorSingleton()
        instance2 = ExampleDecoratorSingleton()
        print(f"装饰器单例测试: {instance1 is instance2}")
        print(f"值: {instance1.get_value()}")
    
    async def test_async_singleton():
        """测试异步单例"""
        instance1 = await ExampleAsyncSingleton.get_instance()
        instance2 = await ExampleAsyncSingleton.get_instance()
        print(f"异步单例测试: {instance1 is instance2}")
        print(f"值: {instance1.get_value()}")
    
    async def test_async_decorator_singleton():
        """测试异步装饰器单例"""
        instance1 = await ExampleAsyncDecoratorSingleton.get_instance()
        instance2 = await ExampleAsyncDecoratorSingleton.get_instance()
        print(f"异步装饰器单例测试: {instance1 is instance2}")
        print(f"值: {instance1.get_value()}")
    
    # 运行测试
    test_singleton()
    test_decorator_singleton()
    
    asyncio.run(test_async_singleton())
    asyncio.run(test_async_decorator_singleton())