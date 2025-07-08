"""
配置热更新模块

实现配置文件的热更新功能，监控文件变化并自动重新加载。
"""

import os
import time
import asyncio
import threading
from typing import Dict, Any, List, Optional, Callable, Set
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import fnmatch

from common.logger import logger

from .types import HotReloadConfig, ConfigMetadata
from .exceptions import HotReloadError

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog未安装，热更新功能将使用轮询模式")
    
    # 创建模拟类以避免导入错误
    class FileSystemEventHandler:
        pass
    
    class FileSystemEvent:
        pass
    
    class Observer:
        pass


class ReloadEventType(Enum):
    """重载事件类型"""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class ReloadEvent:
    """重载事件"""
    event_type: ReloadEventType
    file_path: str
    timestamp: float
    old_path: Optional[str] = None  # 用于移动事件


class FileWatcher:
    """
    文件监控器基类
    
    提供文件监控的基础功能
    """
    
    def __init__(self, config: HotReloadConfig):
        """
        初始化文件监控器
        
        Args:
            config: 热更新配置
        """
        self.config = config
        self._callbacks: List[Callable[[ReloadEvent], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def add_callback(self, callback: Callable[[ReloadEvent], None]) -> None:
        """
        添加重载回调函数
        
        Args:
            callback: 回调函数
        """
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[ReloadEvent], None]) -> None:
        """
        移除重载回调函数
        
        Args:
            callback: 回调函数
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _should_ignore(self, file_path: str) -> bool:
        """
        检查是否应该忽略文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否忽略
        """
        filename = os.path.basename(file_path)
        
        for pattern in self.config.ignore_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True
        
        return False
    
    def _notify_callbacks(self, event: ReloadEvent) -> None:
        """
        通知所有回调函数
        
        Args:
            event: 重载事件
        """
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"重载回调执行失败: {e}")
    
    def start(self) -> None:
        """启动文件监控"""
        if self._running:
            logger.warning("文件监控已在运行中")
            return
        
        self._running = True
        logger.info("启动文件监控")
    
    def stop(self) -> None:
        """停止文件监控"""
        if not self._running:
            return
        
        self._running = False
        logger.info("停止文件监控")
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running


class WatchdogFileWatcher(FileWatcher):
    """
    基于watchdog的文件监控器
    
    提供高效的文件系统事件监控
    """
    
    def __init__(self, config: HotReloadConfig, watch_path: str):
        """
        初始化监控器
        
        Args:
            config: 热更新配置
            watch_path: 监控路径
        """
        super().__init__(config)
        self.watch_path = watch_path
        self._observer: Optional[Observer] = None
        self._event_handler: Optional[FileSystemEventHandler] = None
        self._debounce_timer: Optional[threading.Timer] = None
        self._pending_events: Dict[str, ReloadEvent] = {}
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """启动监控"""
        super().start()
        
        if not WATCHDOG_AVAILABLE:
            raise HotReloadError(self.watch_path, "watchdog不可用")
        
        try:
            self._observer = Observer()
            self._event_handler = self._create_event_handler()
            
            self._observer.schedule(
                self._event_handler,
                self.watch_path,
                recursive=self.config.watch_recursive
            )
            
            self._observer.start()
            logger.info(f"启动watchdog监控: {self.watch_path}")
            
        except Exception as e:
            raise HotReloadError(self.watch_path, f"启动监控失败: {str(e)}")
    
    def stop(self) -> None:
        """停止监控"""
        super().stop()
        
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
    
    def _create_event_handler(self) -> FileSystemEventHandler:
        """创建事件处理器"""
        
        class ConfigFileHandler(FileSystemEventHandler):
            def __init__(self, watcher: 'WatchdogFileWatcher'):
                self.watcher = watcher
            
            def on_created(self, event: FileSystemEvent):
                if not event.is_directory and event.src_path.endswith('.json'):
                    self.watcher._handle_event(ReloadEventType.CREATED, event.src_path)
            
            def on_modified(self, event: FileSystemEvent):
                if not event.is_directory and event.src_path.endswith('.json'):
                    self.watcher._handle_event(ReloadEventType.MODIFIED, event.src_path)
            
            def on_deleted(self, event: FileSystemEvent):
                if not event.is_directory and event.src_path.endswith('.json'):
                    self.watcher._handle_event(ReloadEventType.DELETED, event.src_path)
            
            def on_moved(self, event: FileSystemEvent):
                if not event.is_directory and event.dest_path.endswith('.json'):
                    self.watcher._handle_event(ReloadEventType.MOVED, event.dest_path, event.src_path)
        
        return ConfigFileHandler(self)
    
    def _handle_event(self, event_type: ReloadEventType, file_path: str, old_path: str = None) -> None:
        """
        处理文件事件
        
        Args:
            event_type: 事件类型
            file_path: 文件路径
            old_path: 旧路径（用于移动事件）
        """
        # 检查是否忽略
        if self._should_ignore(file_path):
            return
        
        # 创建重载事件
        reload_event = ReloadEvent(
            event_type=event_type,
            file_path=file_path,
            timestamp=time.time(),
            old_path=old_path
        )
        
        # 使用防抖处理
        with self._lock:
            self._pending_events[file_path] = reload_event
            
            # 取消之前的定时器
            if self._debounce_timer:
                self._debounce_timer.cancel()
            
            # 设置新的定时器
            self._debounce_timer = threading.Timer(
                self.config.debounce_delay,
                self._process_pending_events
            )
            self._debounce_timer.start()
    
    def _process_pending_events(self) -> None:
        """处理待处理的事件"""
        with self._lock:
            events = list(self._pending_events.values())
            self._pending_events.clear()
            self._debounce_timer = None
        
        # 处理每个事件
        for event in events:
            try:
                logger.info(f"处理文件事件: {event.event_type.value} - {event.file_path}")
                self._notify_callbacks(event)
            except Exception as e:
                logger.error(f"处理文件事件失败: {e}")


class PollingFileWatcher(FileWatcher):
    """
    轮询文件监控器
    
    在没有watchdog时使用轮询方式监控文件变化
    """
    
    def __init__(self, config: HotReloadConfig, watch_path: str):
        """
        初始化监控器
        
        Args:
            config: 热更新配置
            watch_path: 监控路径
        """
        super().__init__(config)
        self.watch_path = watch_path
        self._file_states: Dict[str, float] = {}
        self._poll_interval = max(config.debounce_delay, 1.0)
    
    def start(self) -> None:
        """启动监控"""
        super().start()
        
        # 初始化文件状态
        self._scan_files()
        
        # 启动轮询线程
        self._thread = threading.Thread(target=self._poll_files, daemon=True)
        self._thread.start()
        
        logger.info(f"启动轮询监控: {self.watch_path}")
    
    def stop(self) -> None:
        """停止监控"""
        super().stop()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
    
    def _scan_files(self) -> None:
        """扫描文件并记录状态"""
        try:
            for root, dirs, files in os.walk(self.watch_path):
                for file in files:
                    if file.endswith('.json'):
                        file_path = os.path.join(root, file)
                        if not self._should_ignore(file_path):
                            try:
                                stat = os.stat(file_path)
                                self._file_states[file_path] = stat.st_mtime
                            except OSError:
                                pass
        except Exception as e:
            logger.error(f"扫描文件失败: {e}")
    
    def _poll_files(self) -> None:
        """轮询文件变化"""
        while self._running:
            try:
                self._check_file_changes()
                time.sleep(self._poll_interval)
            except Exception as e:
                logger.error(f"轮询文件变化失败: {e}")
                time.sleep(self._poll_interval)
    
    def _check_file_changes(self) -> None:
        """检查文件变化"""
        current_states = {}
        
        # 扫描当前文件状态
        try:
            for root, dirs, files in os.walk(self.watch_path):
                for file in files:
                    if file.endswith('.json'):
                        file_path = os.path.join(root, file)
                        if not self._should_ignore(file_path):
                            try:
                                stat = os.stat(file_path)
                                current_states[file_path] = stat.st_mtime
                            except OSError:
                                pass
        except Exception as e:
            logger.error(f"检查文件变化失败: {e}")
            return
        
        # 检查新增文件
        for file_path, mtime in current_states.items():
            if file_path not in self._file_states:
                # 新增文件
                event = ReloadEvent(
                    event_type=ReloadEventType.CREATED,
                    file_path=file_path,
                    timestamp=time.time()
                )
                self._notify_callbacks(event)
            elif self._file_states[file_path] != mtime:
                # 修改文件
                event = ReloadEvent(
                    event_type=ReloadEventType.MODIFIED,
                    file_path=file_path,
                    timestamp=time.time()
                )
                self._notify_callbacks(event)
        
        # 检查删除文件
        for file_path in self._file_states:
            if file_path not in current_states:
                # 删除文件
                event = ReloadEvent(
                    event_type=ReloadEventType.DELETED,
                    file_path=file_path,
                    timestamp=time.time()
                )
                self._notify_callbacks(event)
        
        # 更新文件状态
        self._file_states = current_states


class HotReloadManager:
    """
    热更新管理器
    
    管理配置文件的热更新功能
    """
    
    def __init__(self, config: HotReloadConfig, watch_path: str):
        """
        初始化热更新管理器
        
        Args:
            config: 热更新配置
            watch_path: 监控路径
        """
        self.config = config
        self.watch_path = watch_path
        self._watcher: Optional[FileWatcher] = None
        self._reload_callbacks: List[Callable[[str], None]] = []
        self._enabled = config.enabled
    
    def add_reload_callback(self, callback: Callable[[str], None]) -> None:
        """
        添加重载回调函数
        
        Args:
            callback: 回调函数，接收文件路径参数
        """
        self._reload_callbacks.append(callback)
    
    def remove_reload_callback(self, callback: Callable[[str], None]) -> None:
        """
        移除重载回调函数
        
        Args:
            callback: 回调函数
        """
        if callback in self._reload_callbacks:
            self._reload_callbacks.remove(callback)
    
    def start(self) -> None:
        """启动热更新"""
        if not self._enabled:
            logger.info("热更新功能已禁用")
            return
        
        if self._watcher and self._watcher.is_running():
            logger.warning("热更新已在运行中")
            return
        
        try:
            # 创建文件监控器
            if WATCHDOG_AVAILABLE:
                self._watcher = WatchdogFileWatcher(self.config, self.watch_path)
            else:
                self._watcher = PollingFileWatcher(self.config, self.watch_path)
            
            # 添加事件处理器
            self._watcher.add_callback(self._handle_reload_event)
            
            # 启动监控
            self._watcher.start()
            
            logger.info("热更新管理器启动成功")
            
        except Exception as e:
            raise HotReloadError(self.watch_path, f"启动热更新失败: {str(e)}")
    
    def stop(self) -> None:
        """停止热更新"""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        
        logger.info("热更新管理器已停止")
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._watcher is not None and self._watcher.is_running()
    
    def enable(self) -> None:
        """启用热更新"""
        self._enabled = True
        self.config.enabled = True
        logger.info("热更新已启用")
    
    def disable(self) -> None:
        """禁用热更新"""
        self._enabled = False
        self.config.enabled = False
        self.stop()
        logger.info("热更新已禁用")
    
    def _handle_reload_event(self, event: ReloadEvent) -> None:
        """
        处理重载事件
        
        Args:
            event: 重载事件
        """
        if not self._enabled:
            return
        
        try:
            # 只处理JSON文件
            if not event.file_path.endswith('.json'):
                return
            
            # 记录事件
            logger.info(f"检测到文件变化: {event.event_type.value} - {event.file_path}")
            
            # 通知所有回调函数
            for callback in self._reload_callbacks:
                try:
                    callback(event.file_path)
                except Exception as e:
                    logger.error(f"重载回调执行失败: {e}")
        
        except Exception as e:
            logger.error(f"处理重载事件失败: {e}")
    
    def force_reload(self, file_path: str) -> None:
        """
        强制重新加载指定文件
        
        Args:
            file_path: 文件路径
        """
        try:
            logger.info(f"强制重新加载文件: {file_path}")
            
            for callback in self._reload_callbacks:
                try:
                    callback(file_path)
                except Exception as e:
                    logger.error(f"强制重载回调执行失败: {e}")
        
        except Exception as e:
            logger.error(f"强制重新加载失败: {e}")
    
    def get_watched_files(self) -> List[str]:
        """
        获取被监控的文件列表
        
        Returns:
            List[str]: 文件路径列表
        """
        files = []
        
        try:
            for root, dirs, filenames in os.walk(self.watch_path):
                for filename in filenames:
                    if filename.endswith('.json'):
                        file_path = os.path.join(root, filename)
                        if not self._should_ignore(file_path):
                            files.append(file_path)
        except Exception as e:
            logger.error(f"获取监控文件列表失败: {e}")
        
        return files
    
    def _should_ignore(self, file_path: str) -> bool:
        """
        检查是否应该忽略文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否忽略
        """
        filename = os.path.basename(file_path)
        
        for pattern in self.config.ignore_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True
        
        return False