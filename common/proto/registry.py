"""
消息注册表模块

该模块实现消息注册表 MessageRegistry，用于管理 msg_id 与消息类的映射关系。
支持消息类的注册、查找、自动扫描注册和热更新功能。
"""

import os
import importlib
import inspect
import threading
from typing import Type, Dict, Set, Optional, List, Callable
from pathlib import Path

from .base_proto import BaseMessage, BaseRequest, BaseResponse
from .exceptions import RegistryException, ValidationException, handle_proto_exception


class MessageRegistry:
    """
    消息注册表
    
    管理消息ID与消息类的映射关系，提供：
    - 消息类注册和查找
    - 自动扫描注册
    - 热更新支持
    - 线程安全操作
    
    Attributes:
        _registry: 消息ID到消息类的映射
        _reverse_registry: 消息类到消息ID的反向映射
        _lock: 线程锁，保证操作的线程安全
        _hot_reload_enabled: 是否启用热更新
        _watched_paths: 监听的路径集合
    """
    
    __slots__ = (
        '_registry', '_reverse_registry', '_lock', 
        '_hot_reload_enabled', '_watched_paths', '_change_listeners'
    )
    
    def __init__(self, hot_reload: bool = False):
        """
        初始化消息注册表
        
        Args:
            hot_reload: 是否启用热更新功能
        """
        self._registry: Dict[int, Type[BaseMessage]] = {}
        self._reverse_registry: Dict[Type[BaseMessage], int] = {}
        self._lock = threading.RLock()
        self._hot_reload_enabled = hot_reload
        self._watched_paths: Set[str] = set()
        self._change_listeners: List[Callable[[int, Type[BaseMessage]], None]] = []
    
    @handle_proto_exception
    def register(self, msg_id: int, message_class: Type[BaseMessage]) -> None:
        """
        注册消息类
        
        Args:
            msg_id: 消息ID
            message_class: 消息类，必须继承自 BaseMessage
            
        Raises:
            RegistryException: 注册失败时抛出
            ValidationException: 参数验证失败时抛出
        """
        # 参数验证
        if not isinstance(msg_id, int):
            raise ValidationException("消息ID必须是整数类型",
                                    field_name="msg_id",
                                    field_value=type(msg_id))
        
        if msg_id == 0:
            raise ValidationException("消息ID不能为0",
                                    field_name="msg_id", 
                                    field_value=msg_id)
        
        if not inspect.isclass(message_class):
            raise ValidationException("message_class必须是类类型",
                                    field_name="message_class",
                                    field_value=type(message_class))
        
        if not issubclass(message_class, BaseMessage):
            raise ValidationException("消息类必须继承自BaseMessage",
                                    field_name="message_class",
                                    field_value=message_class.__name__)
        
        # 验证消息类型与ID的一致性
        if msg_id > 0 and not issubclass(message_class, BaseRequest):
            raise ValidationException("正数消息ID应对应请求消息类（继承自BaseRequest）",
                                    field_name="msg_id",
                                    field_value=msg_id,
                                    message_class=message_class.__name__)
        
        if msg_id < 0 and not issubclass(message_class, BaseResponse):
            raise ValidationException("负数消息ID应对应响应消息类（继承自BaseResponse）",
                                    field_name="msg_id", 
                                    field_value=msg_id,
                                    message_class=message_class.__name__)
        
        with self._lock:
            # 检查消息ID冲突
            if msg_id in self._registry:
                existing_class = self._registry[msg_id]
                if existing_class != message_class:
                    raise RegistryException(
                        f"消息ID {msg_id} 已被注册为 {existing_class.__name__}，"
                        f"无法注册为 {message_class.__name__}",
                        msg_id=msg_id,
                        message_class=message_class.__name__
                    )
                return  # 相同的注册，直接返回
            
            # 检查消息类冲突
            if message_class in self._reverse_registry:
                existing_id = self._reverse_registry[message_class]
                if existing_id != msg_id:
                    raise RegistryException(
                        f"消息类 {message_class.__name__} 已被注册为ID {existing_id}，"
                        f"无法注册为ID {msg_id}",
                        msg_id=msg_id,
                        message_class=message_class.__name__
                    )
                return  # 相同的注册，直接返回
            
            # 执行注册
            self._registry[msg_id] = message_class
            self._reverse_registry[message_class] = msg_id
            
            # 通知监听器
            for listener in self._change_listeners:
                try:
                    listener(msg_id, message_class)
                except Exception:
                    # 忽略监听器异常，不影响注册过程
                    pass
    
    @handle_proto_exception
    def unregister(self, msg_id: int) -> bool:
        """
        取消注册消息类
        
        Args:
            msg_id: 要取消注册的消息ID
            
        Returns:
            bool: 是否成功取消注册
        """
        with self._lock:
            if msg_id not in self._registry:
                return False
            
            message_class = self._registry[msg_id]
            del self._registry[msg_id]
            del self._reverse_registry[message_class]
            
            return True
    
    @handle_proto_exception
    def get_message_class(self, msg_id: int) -> Type[BaseMessage]:
        """
        根据消息ID获取消息类
        
        Args:
            msg_id: 消息ID
            
        Returns:
            Type[BaseMessage]: 对应的消息类
            
        Raises:
            RegistryException: 消息ID未注册时抛出
        """
        with self._lock:
            if msg_id not in self._registry:
                raise RegistryException(f"消息ID {msg_id} 未注册",
                                      msg_id=msg_id)
            
            return self._registry[msg_id]
    
    @handle_proto_exception
    def get_message_id(self, message_class: Type[BaseMessage]) -> int:
        """
        根据消息类获取消息ID
        
        Args:
            message_class: 消息类
            
        Returns:
            int: 对应的消息ID
            
        Raises:
            RegistryException: 消息类未注册时抛出
        """
        with self._lock:
            if message_class not in self._reverse_registry:
                raise RegistryException(f"消息类 {message_class.__name__} 未注册",
                                      message_class=message_class.__name__)
            
            return self._reverse_registry[message_class]
    
    def is_registered(self, msg_id: int) -> bool:
        """
        检查消息ID是否已注册
        
        Args:
            msg_id: 消息ID
            
        Returns:
            bool: 是否已注册
        """
        with self._lock:
            return msg_id in self._registry
    
    def is_class_registered(self, message_class: Type[BaseMessage]) -> bool:
        """
        检查消息类是否已注册
        
        Args:
            message_class: 消息类
            
        Returns:
            bool: 是否已注册
        """
        with self._lock:
            return message_class in self._reverse_registry
    
    def get_registered_ids(self) -> List[int]:
        """
        获取所有已注册的消息ID
        
        Returns:
            List[int]: 消息ID列表（已排序）
        """
        with self._lock:
            return sorted(self._registry.keys())
    
    def get_registered_classes(self) -> List[Type[BaseMessage]]:
        """
        获取所有已注册的消息类
        
        Returns:
            List[Type[BaseMessage]]: 消息类列表
        """
        with self._lock:
            return list(self._reverse_registry.keys())
    
    def get_registration_count(self) -> int:
        """
        获取注册的消息数量
        
        Returns:
            int: 注册数量
        """
        with self._lock:
            return len(self._registry)
    
    def get_request_ids(self) -> List[int]:
        """
        获取所有请求消息ID（正数）
        
        Returns:
            List[int]: 请求消息ID列表
        """
        with self._lock:
            return sorted([msg_id for msg_id in self._registry.keys() if msg_id > 0])
    
    def get_response_ids(self) -> List[int]:
        """
        获取所有响应消息ID（负数）
        
        Returns:
            List[int]: 响应消息ID列表
        """
        with self._lock:
            return sorted([msg_id for msg_id in self._registry.keys() if msg_id < 0])
    
    @handle_proto_exception
    def clear(self) -> None:
        """清空所有注册的消息"""
        with self._lock:
            self._registry.clear()
            self._reverse_registry.clear()
    
    @handle_proto_exception
    def scan_and_register(self, package_path: str, recursive: bool = True) -> int:
        """
        自动扫描指定目录下的消息类并注册
        
        扫描规则：
        1. 查找所有继承自 BaseMessage 的类
        2. 检查类是否定义了 MSG_ID 类属性
        3. 自动注册到注册表中
        
        Args:
            package_path: 包路径（如 'proto.messages'）
            recursive: 是否递归扫描子包
            
        Returns:
            int: 成功注册的消息类数量
            
        Raises:
            RegistryException: 扫描失败时抛出
        """
        try:
            package = importlib.import_module(package_path)
            
            if self._hot_reload_enabled:
                # 添加到监听路径
                if hasattr(package, '__path__'):
                    for path in package.__path__:
                        self._watched_paths.add(path)
            
            registered_count = 0
            
            # 扫描当前包
            registered_count += self._scan_module(package)
            
            # 递归扫描子包
            if recursive and hasattr(package, '__path__'):
                for path in package.__path__:
                    registered_count += self._scan_directory(path, package_path)
            
            return registered_count
            
        except ImportError as e:
            raise RegistryException(f"导入包失败: {package_path}",
                                  message_class=package_path) from e
        except Exception as e:
            raise RegistryException(f"扫描注册失败: {e}",
                                  message_class=package_path) from e
    
    def _scan_module(self, module) -> int:
        """
        扫描单个模块中的消息类
        
        Args:
            module: 要扫描的模块
            
        Returns:
            int: 注册的消息类数量
        """
        registered_count = 0
        
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # 跳过导入的类
            if obj.__module__ != module.__name__:
                continue
            
            # 检查是否继承自 BaseMessage
            if not issubclass(obj, BaseMessage):
                continue
            
            # 跳过基类本身
            if obj in (BaseMessage, BaseRequest, BaseResponse):
                continue
            
            # 检查是否定义了 MSG_ID
            if not hasattr(obj, 'MSG_ID'):
                continue
            
            msg_id = getattr(obj, 'MSG_ID')
            
            try:
                self.register(msg_id, obj)
                registered_count += 1
            except (RegistryException, ValidationException):
                # 注册失败时跳过该类
                pass
        
        return registered_count
    
    def _scan_directory(self, directory: str, base_package: str) -> int:
        """
        递归扫描目录中的 Python 文件
        
        Args:
            directory: 目录路径
            base_package: 基础包名
            
        Returns:
            int: 注册的消息类数量
        """
        registered_count = 0
        
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if not file.endswith('.py') or file.startswith('__'):
                        continue
                    
                    # 计算相对路径和模块名
                    relative_path = os.path.relpath(root, directory)
                    if relative_path == '.':
                        module_path = base_package
                    else:
                        module_path = f"{base_package}.{relative_path.replace(os.sep, '.')}"
                    
                    module_name = f"{module_path}.{file[:-3]}"  # 去掉 .py 后缀
                    
                    try:
                        module = importlib.import_module(module_name)
                        registered_count += self._scan_module(module)
                    except ImportError:
                        # 导入失败时跳过该模块
                        pass
        
        except Exception:
            # 扫描失败时跳过该目录
            pass
        
        return registered_count
    
    def add_change_listener(self, listener: Callable[[int, Type[BaseMessage]], None]) -> None:
        """
        添加注册变化监听器
        
        Args:
            listener: 监听器函数，接收 (msg_id, message_class) 参数
        """
        with self._lock:
            if listener not in self._change_listeners:
                self._change_listeners.append(listener)
    
    def remove_change_listener(self, listener: Callable[[int, Type[BaseMessage]], None]) -> None:
        """
        移除注册变化监听器
        
        Args:
            listener: 要移除的监听器函数
        """
        with self._lock:
            if listener in self._change_listeners:
                self._change_listeners.remove(listener)
    
    def enable_hot_reload(self) -> None:
        """启用热更新功能"""
        self._hot_reload_enabled = True
    
    def disable_hot_reload(self) -> None:
        """禁用热更新功能"""
        self._hot_reload_enabled = False
        self._watched_paths.clear()
    
    def reload_watched_modules(self) -> int:
        """
        重新加载监听的模块
        
        Returns:
            int: 重新注册的消息类数量
        """
        if not self._hot_reload_enabled:
            return 0
        
        # 清空现有注册
        old_count = self.get_registration_count()
        self.clear()
        
        # 重新扫描注册
        new_count = 0
        for path in self._watched_paths:
            try:
                # 这里需要根据路径计算包名，简化实现
                package_name = os.path.basename(path)
                new_count += self.scan_and_register(package_name)
            except Exception:
                # 重新加载失败时跳过
                pass
        
        return new_count
    
    def get_registry_info(self) -> Dict[str, any]:
        """
        获取注册表信息
        
        Returns:
            Dict[str, any]: 注册表统计信息
        """
        with self._lock:
            return {
                'total_count': len(self._registry),
                'request_count': len(self.get_request_ids()),
                'response_count': len(self.get_response_ids()),
                'hot_reload_enabled': self._hot_reload_enabled,
                'watched_paths_count': len(self._watched_paths),
                'listeners_count': len(self._change_listeners)
            }
    
    def validate_registry(self) -> List[str]:
        """
        验证注册表的一致性
        
        Returns:
            List[str]: 发现的问题列表，空列表表示无问题
        """
        issues = []
        
        with self._lock:
            # 检查双向映射一致性
            for msg_id, message_class in self._registry.items():
                if message_class not in self._reverse_registry:
                    issues.append(f"消息类 {message_class.__name__} 在反向注册表中缺失")
                elif self._reverse_registry[message_class] != msg_id:
                    issues.append(f"消息类 {message_class.__name__} 的ID映射不一致")
            
            for message_class, msg_id in self._reverse_registry.items():
                if msg_id not in self._registry:
                    issues.append(f"消息ID {msg_id} 在主注册表中缺失")
                elif self._registry[msg_id] != message_class:
                    issues.append(f"消息ID {msg_id} 的类映射不一致")
            
            # 检查消息类型与ID的匹配
            for msg_id, message_class in self._registry.items():
                if msg_id > 0 and not issubclass(message_class, BaseRequest):
                    issues.append(f"正数消息ID {msg_id} 应对应请求消息类，但 {message_class.__name__} 不是")
                elif msg_id < 0 and not issubclass(message_class, BaseResponse):
                    issues.append(f"负数消息ID {msg_id} 应对应响应消息类，但 {message_class.__name__} 不是")
        
        return issues


# 全局默认注册表实例
_default_registry = MessageRegistry()


def get_default_registry() -> MessageRegistry:
    """
    获取默认的消息注册表实例
    
    Returns:
        MessageRegistry: 默认注册表实例
    """
    return _default_registry


def register_message(msg_id: int, message_class: Type[BaseMessage]) -> None:
    """
    在默认注册表中注册消息类
    
    Args:
        msg_id: 消息ID
        message_class: 消息类
    """
    _default_registry.register(msg_id, message_class)


def get_message_class(msg_id: int) -> Type[BaseMessage]:
    """
    从默认注册表中获取消息类
    
    Args:
        msg_id: 消息ID
        
    Returns:
        Type[BaseMessage]: 消息类
    """
    return _default_registry.get_message_class(msg_id)


def scan_and_register(package_path: str, recursive: bool = True) -> int:
    """
    在默认注册表中扫描并注册消息类
    
    Args:
        package_path: 包路径
        recursive: 是否递归扫描
        
    Returns:
        int: 注册的消息类数量
    """
    return _default_registry.scan_and_register(package_path, recursive)