"""
SLS日志模块

该模块提供SLS（阿里云日志服务）专用日志实现，
支持批量上报、失败重试、本地缓存队列等功能。
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from collections import deque
from dataclasses import dataclass, field
import threading

from .base_logger import BaseLogger
from .logger_config import LoggerConfig


@dataclass
class SLSConfig:
    """SLS特定配置"""
    # SLS基础配置
    project_name: str = "knight_server"
    logstore_name: str = "app_logs"
    endpoint: str = "https://cn-hangzhou.log.aliyuncs.com"
    access_key_id: str = ""
    access_key_secret: str = ""
    
    # 批量上报配置
    batch_size: int = 100
    batch_timeout: float = 5.0  # 5秒
    max_queue_size: int = 10000
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    
    # 压缩配置
    enable_compression: bool = True
    compression_threshold: int = 1024  # 1KB
    
    # 标签配置
    common_tags: Dict[str, str] = field(default_factory=lambda: {
        "service": "knight_server",
        "environment": "development"
    })


class SLSLogEntry:
    """SLS日志条目"""
    
    def __init__(self, timestamp: float, level: str, message: str, 
                 tags: Optional[Dict[str, str]] = None, **kwargs):
        self.timestamp = timestamp
        self.level = level
        self.message = message
        self.tags = tags or {}
        self.extra = kwargs
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'timestamp': int(self.timestamp),
            'level': self.level,
            'message': self.message,
            'tags': self.tags,
            **self.extra
        }
    
    def to_json(self) -> str:
        """转换为JSON格式"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class SLSBatchUploader:
    """SLS批量上传器"""
    
    def __init__(self, sls_config: SLSConfig):
        self.config = sls_config
        self._queue: deque = deque(maxlen=sls_config.max_queue_size)
        self._lock = threading.Lock()
        self._upload_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
        # 启动批量上传任务
        self._start_upload_task()
    
    def _start_upload_task(self) -> None:
        """启动批量上传任务"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # 如果没有事件循环，创建一个新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if not loop.is_running():
            # 如果循环未运行，在后台线程中运行
            def run_upload_task():
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._upload_worker())
            
            upload_thread = threading.Thread(target=run_upload_task, daemon=True)
            upload_thread.start()
        else:
            # 如果循环正在运行，创建任务
            self._upload_task = loop.create_task(self._upload_worker())
    
    async def _upload_worker(self) -> None:
        """批量上传工作线程"""
        while not self._stop_event.is_set():
            try:
                # 等待批量超时或队列满
                await asyncio.wait_for(
                    self._stop_event.wait(), 
                    timeout=self.config.batch_timeout
                )
            except asyncio.TimeoutError:
                pass  # 超时正常，继续处理
            
            # 收集批量数据
            batch = self._collect_batch()
            if batch:
                await self._upload_batch(batch)
    
    def _collect_batch(self) -> List[SLSLogEntry]:
        """收集批量数据"""
        batch = []
        with self._lock:
            for _ in range(min(self.config.batch_size, len(self._queue))):
                if self._queue:
                    batch.append(self._queue.popleft())
        return batch
    
    async def _upload_batch(self, batch: List[SLSLogEntry]) -> None:
        """上传批量数据"""
        for attempt in range(self.config.max_retries):
            try:
                await self._send_to_sls(batch)
                return  # 成功上传，退出重试循环
            except Exception as e:
                print(f"SLS upload attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (self.config.retry_backoff ** attempt)
                    await asyncio.sleep(delay)
        
        # 所有重试都失败，记录到本地日志
        print(f"Failed to upload {len(batch)} log entries to SLS after {self.config.max_retries} attempts")
        self._fallback_to_local(batch)
    
    async def _send_to_sls(self, batch: List[SLSLogEntry]) -> None:
        """发送数据到SLS"""
        # 这里应该实现真正的SLS API调用
        # 由于没有真实的SLS SDK，这里使用模拟实现
        
        # 构造SLS请求数据
        log_data = {
            'project': self.config.project_name,
            'logstore': self.config.logstore_name,
            'logs': [entry.to_dict() for entry in batch]
        }
        
        # 模拟网络请求
        await asyncio.sleep(0.1)  # 模拟网络延迟
        
        # 在实际实现中，这里应该使用SLS SDK发送数据
        # 例如：
        # from aliyun.log import LogClient
        # client = LogClient(self.config.endpoint, self.config.access_key_id, self.config.access_key_secret)
        # client.put_logs(self.config.project_name, self.config.logstore_name, log_data['logs'])
        
        print(f"Simulated SLS upload: {len(batch)} entries")
    
    def _fallback_to_local(self, batch: List[SLSLogEntry]) -> None:
        """回退到本地日志"""
        try:
            # 将失败的日志写入本地文件
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_file = f"logs/sls_fallback_{timestamp}.json"
            
            # 确保目录存在
            from pathlib import Path
            Path(fallback_file).parent.mkdir(parents=True, exist_ok=True)
            
            with open(fallback_file, 'w', encoding='utf-8') as f:
                for entry in batch:
                    f.write(entry.to_json() + '\n')
                    
        except Exception as e:
            print(f"Failed to write fallback logs: {e}")
    
    def add_log(self, entry: SLSLogEntry) -> None:
        """添加日志条目"""
        with self._lock:
            if len(self._queue) >= self.config.max_queue_size:
                # 队列满了，移除最老的条目
                self._queue.popleft()
            self._queue.append(entry)
    
    def stop(self) -> None:
        """停止上传器"""
        self._stop_event.set()
        
        # 上传剩余的日志
        remaining_batch = self._collect_batch()
        if remaining_batch:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._upload_batch(remaining_batch))
                else:
                    loop.run_until_complete(self._upload_batch(remaining_batch))
            except Exception as e:
                print(f"Failed to upload remaining logs: {e}")
                self._fallback_to_local(remaining_batch)


class SLSLogger(BaseLogger):
    """
    SLS日志器
    
    继承基础日志器，添加SLS特定功能，包括批量上报、
    失败重试、本地缓存队列等。
    """
    
    def __init__(self, name: str, config: LoggerConfig, sls_config: Optional[SLSConfig] = None):
        """
        初始化SLS日志器
        
        Args:
            name: 日志器名称
            config: 基础日志配置
            sls_config: SLS特定配置
        """
        super().__init__(name, config)
        
        self.sls_config = sls_config or SLSConfig()
        self._uploader: Optional[SLSBatchUploader] = None
        self._init_uploader()
    
    def _init_uploader(self) -> None:
        """初始化上传器"""
        try:
            self._uploader = SLSBatchUploader(self.sls_config)
        except Exception as e:
            print(f"Failed to initialize SLS uploader: {e}")
            self._uploader = None
    
    def _log(self, level: str, message: str, *args, **kwargs) -> None:
        """重写日志记录方法，同时发送到SLS"""
        # 先调用父类方法记录到本地
        super()._log(level, message, *args, **kwargs)
        
        # 发送到SLS
        self._send_to_sls(level, message, *args, **kwargs)
    
    def _send_to_sls(self, level: str, message: str, *args, **kwargs) -> None:
        """发送日志到SLS"""
        if not self._uploader:
            return
        
        try:
            # 格式化消息
            formatted_message = self._format_message(message, *args)
            
            # 准备标签
            tags = {**self.sls_config.common_tags}
            if 'tags' in kwargs:
                tags.update(kwargs.pop('tags'))
            
            # 添加服务信息到标签
            if self.config.service_name:
                tags['service_name'] = self.config.service_name
            if self.config.service_port:
                tags['service_port'] = str(self.config.service_port)
            
            # 创建SLS日志条目
            entry = SLSLogEntry(
                timestamp=time.time(),
                level=level,
                message=formatted_message,
                tags=tags,
                **self._prepare_extra(**kwargs)
            )
            
            # 添加到上传队列
            self._uploader.add_log(entry)
            
        except Exception as e:
            # SLS发送失败不应影响正常日志记录
            print(f"Failed to send log to SLS: {e}")
    
    def set_sls_config(self, sls_config: SLSConfig) -> None:
        """设置SLS配置"""
        self.sls_config = sls_config
        
        # 重新初始化上传器
        if self._uploader:
            self._uploader.stop()
        self._init_uploader()
    
    def flush_sls(self) -> None:
        """强制刷新SLS队列"""
        if self._uploader:
            # 触发立即上传
            remaining_batch = self._uploader._collect_batch()
            if remaining_batch:
                try:
                    loop = asyncio.get_event_loop()
                    loop.create_task(self._uploader._upload_batch(remaining_batch))
                except Exception as e:
                    print(f"Failed to flush SLS logs: {e}")
    
    def get_sls_stats(self) -> Dict[str, Any]:
        """获取SLS统计信息"""
        if not self._uploader:
            return {'status': 'disabled'}
        
        with self._uploader._lock:
            queue_size = len(self._uploader._queue)
        
        return {
            'status': 'enabled',
            'queue_size': queue_size,
            'max_queue_size': self.sls_config.max_queue_size,
            'batch_size': self.sls_config.batch_size,
            'project_name': self.sls_config.project_name,
            'logstore_name': self.sls_config.logstore_name,
        }
    
    def close(self) -> None:
        """关闭日志器"""
        # 停止SLS上传器
        if self._uploader:
            self._uploader.stop()
            self._uploader = None
        
        # 调用父类关闭方法
        super().close()
    
    # SLS特定的便捷方法
    def business_event(self, event_type: str, message: str, **kwargs) -> None:
        """记录业务事件"""
        kwargs['event_type'] = event_type
        kwargs['tags'] = kwargs.get('tags', {})
        kwargs['tags']['event_category'] = 'business'
        self.info(message, **kwargs)
    
    def user_action(self, user_id: str, action: str, message: str, **kwargs) -> None:
        """记录用户行为"""
        kwargs['user_id'] = user_id
        kwargs['action'] = action
        kwargs['tags'] = kwargs.get('tags', {})
        kwargs['tags']['event_category'] = 'user_action'
        self.info(message, **kwargs)
    
    def performance_metric(self, metric_name: str, value: float, unit: str = "ms", **kwargs) -> None:
        """记录性能指标"""
        kwargs['metric_name'] = metric_name
        kwargs['metric_value'] = value
        kwargs['metric_unit'] = unit
        kwargs['tags'] = kwargs.get('tags', {})
        kwargs['tags']['event_category'] = 'performance'
        self.info(f"Performance metric: {metric_name}={value}{unit}", **kwargs)
    
    def security_event(self, event_type: str, severity: str, message: str, **kwargs) -> None:
        """记录安全事件"""
        kwargs['security_event_type'] = event_type
        kwargs['severity'] = severity
        kwargs['tags'] = kwargs.get('tags', {})
        kwargs['tags']['event_category'] = 'security'
        
        # 根据严重性选择日志级别
        if severity.upper() in ['HIGH', 'CRITICAL']:
            self.error(message, **kwargs)
        elif severity.upper() == 'MEDIUM':
            self.warning(message, **kwargs)
        else:
            self.info(message, **kwargs)