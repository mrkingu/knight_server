"""
日志中间件

该模块负责请求响应日志记录，提供详细的请求链路追踪、
性能监控和调试信息。

主要功能：
- 请求响应日志记录
- 性能监控
- 请求链路追踪
- 调试信息记录
"""

import time
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger
from ..config import GatewayConfig
from ..gate_handler import RequestContext


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class RequestLog:
    """请求日志"""
    request_id: str
    connection_id: str
    protocol_id: int
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    client_ip: str = ""
    user_agent: str = ""
    request_time: float = field(default_factory=time.time)
    response_time: Optional[float] = None
    duration: Optional[float] = None
    request_size: int = 0
    response_size: int = 0
    success: bool = True
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "connection_id": self.connection_id,
            "protocol_id": self.protocol_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "request_time": self.request_time,
            "response_time": self.response_time,
            "duration": self.duration,
            "request_size": self.request_size,
            "response_size": self.response_size,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.metadata
        }


class LogMiddleware:
    """日志中间件"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化日志中间件
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.log_level = LogLevel(config.log.level)
        
        # 请求日志缓存
        self.request_logs: Dict[str, RequestLog] = {}
        
        # 统计信息
        self._total_requests = 0
        self._success_requests = 0
        self._error_requests = 0
        self._total_request_size = 0
        self._total_response_size = 0
        self._total_duration = 0.0
        
        # 性能监控
        self._slow_requests: List[RequestLog] = []
        self._slow_request_threshold = 1.0  # 1秒
        
        # 敏感信息过滤
        self._sensitive_fields = {
            "password", "token", "secret", "key", "authorization"
        }
        
        logger.info("日志中间件初始化完成")
        
    async def process_request(self, request: Any, context: RequestContext):
        """
        处理请求日志
        
        Args:
            request: 请求数据
            context: 请求上下文
        """
        try:
            # 创建请求日志
            request_log = RequestLog(
                request_id=context.request_id,
                connection_id=context.connection_id,
                protocol_id=context.protocol_id,
                user_id=context.user_id,
                session_id=context.session_id,
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                request_time=context.request_time,
                request_size=self._calculate_size(request)
            )
            
            # 保存到缓存
            self.request_logs[context.request_id] = request_log
            
            # 记录请求日志
            await self._log_request(request, context, request_log)
            
            # 更新统计
            self._total_requests += 1
            self._total_request_size += request_log.request_size
            
        except Exception as e:
            logger.error("处理请求日志失败", 
                        request_id=context.request_id,
                        error=str(e))
            
    async def process_response(self, response: Any, context: RequestContext, success: bool = True, error_message: str = ""):
        """
        处理响应日志
        
        Args:
            response: 响应数据
            context: 请求上下文
            success: 是否成功
            error_message: 错误消息
        """
        try:
            # 获取请求日志
            request_log = self.request_logs.get(context.request_id)
            if not request_log:
                logger.warning("未找到请求日志", request_id=context.request_id)
                return
                
            # 更新响应信息
            request_log.response_time = time.time()
            request_log.duration = request_log.response_time - request_log.request_time
            request_log.response_size = self._calculate_size(response)
            request_log.success = success
            request_log.error_message = error_message
            
            # 记录响应日志
            await self._log_response(response, context, request_log)
            
            # 更新统计
            if success:
                self._success_requests += 1
            else:
                self._error_requests += 1
                
            self._total_response_size += request_log.response_size
            self._total_duration += request_log.duration
            
            # 检查慢请求
            if request_log.duration > self._slow_request_threshold:
                self._slow_requests.append(request_log)
                # 保持最近的100个慢请求
                if len(self._slow_requests) > 100:
                    self._slow_requests.pop(0)
                    
            # 清理缓存
            del self.request_logs[context.request_id]
            
        except Exception as e:
            logger.error("处理响应日志失败", 
                        request_id=context.request_id,
                        error=str(e))
            
    async def _log_request(self, request: Any, context: RequestContext, request_log: RequestLog):
        """
        记录请求日志
        
        Args:
            request: 请求数据
            context: 请求上下文
            request_log: 请求日志
        """
        try:
            # 过滤敏感信息
            filtered_request = self._filter_sensitive_data(request)
            
            log_data = {
                "type": "request",
                "request_id": request_log.request_id,
                "connection_id": request_log.connection_id,
                "protocol_id": request_log.protocol_id,
                "user_id": request_log.user_id,
                "session_id": request_log.session_id,
                "client_ip": request_log.client_ip,
                "user_agent": request_log.user_agent,
                "request_time": request_log.request_time,
                "request_size": request_log.request_size,
                "request_data": filtered_request if self.log_level == LogLevel.DEBUG else None
            }
            
            # 根据日志级别决定记录详细程度
            if self.log_level in [LogLevel.DEBUG, LogLevel.INFO]:
                logger.info("请求开始", **log_data)
            elif self.log_level == LogLevel.WARNING:
                # 只记录重要信息
                logger.info("请求开始", 
                           request_id=request_log.request_id,
                           protocol_id=request_log.protocol_id,
                           user_id=request_log.user_id)
                           
        except Exception as e:
            logger.error("记录请求日志失败", 
                        request_id=context.request_id,
                        error=str(e))
            
    async def _log_response(self, response: Any, context: RequestContext, request_log: RequestLog):
        """
        记录响应日志
        
        Args:
            response: 响应数据
            context: 请求上下文
            request_log: 请求日志
        """
        try:
            # 过滤敏感信息
            filtered_response = self._filter_sensitive_data(response)
            
            log_data = {
                "type": "response",
                "request_id": request_log.request_id,
                "connection_id": request_log.connection_id,
                "protocol_id": request_log.protocol_id,
                "user_id": request_log.user_id,
                "session_id": request_log.session_id,
                "duration": request_log.duration,
                "response_size": request_log.response_size,
                "success": request_log.success,
                "error_message": request_log.error_message,
                "response_data": filtered_response if self.log_level == LogLevel.DEBUG else None
            }
            
            # 根据成功状态和日志级别记录
            if request_log.success:
                if self.log_level in [LogLevel.DEBUG, LogLevel.INFO]:
                    logger.info("请求完成", **log_data)
                elif request_log.duration > self._slow_request_threshold:
                    # 慢请求警告
                    logger.warning("慢请求", 
                                 request_id=request_log.request_id,
                                 protocol_id=request_log.protocol_id,
                                 duration=request_log.duration)
            else:
                logger.error("请求失败", **log_data)
                
        except Exception as e:
            logger.error("记录响应日志失败", 
                        request_id=context.request_id,
                        error=str(e))
            
    def _calculate_size(self, data: Any) -> int:
        """
        计算数据大小
        
        Args:
            data: 数据
            
        Returns:
            int: 数据大小(字节)
        """
        try:
            if data is None:
                return 0
            elif isinstance(data, str):
                return len(data.encode('utf-8'))
            elif isinstance(data, bytes):
                return len(data)
            elif isinstance(data, (dict, list)):
                return len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            else:
                return len(str(data).encode('utf-8'))
        except Exception:
            return 0
            
    def _filter_sensitive_data(self, data: Any) -> Any:
        """
        过滤敏感数据
        
        Args:
            data: 原始数据
            
        Returns:
            Any: 过滤后的数据
        """
        try:
            if isinstance(data, dict):
                filtered = {}
                for key, value in data.items():
                    if isinstance(key, str) and key.lower() in self._sensitive_fields:
                        filtered[key] = "***"
                    elif isinstance(value, dict):
                        filtered[key] = self._filter_sensitive_data(value)
                    elif isinstance(value, list):
                        filtered[key] = [self._filter_sensitive_data(item) for item in value]
                    else:
                        filtered[key] = value
                return filtered
            elif isinstance(data, list):
                return [self._filter_sensitive_data(item) for item in data]
            else:
                return data
        except Exception:
            return data
            
    def add_sensitive_field(self, field: str):
        """
        添加敏感字段
        
        Args:
            field: 字段名
        """
        self._sensitive_fields.add(field.lower())
        logger.info("添加敏感字段", field=field)
        
    def remove_sensitive_field(self, field: str):
        """
        移除敏感字段
        
        Args:
            field: 字段名
        """
        self._sensitive_fields.discard(field.lower())
        logger.info("移除敏感字段", field=field)
        
    def set_slow_request_threshold(self, threshold: float):
        """
        设置慢请求阈值
        
        Args:
            threshold: 阈值(秒)
        """
        self._slow_request_threshold = threshold
        logger.info("设置慢请求阈值", threshold=threshold)
        
    def get_slow_requests(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取慢请求列表
        
        Args:
            limit: 限制数量
            
        Returns:
            List[Dict[str, Any]]: 慢请求列表
        """
        return [log.to_dict() for log in self._slow_requests[-limit:]]
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        avg_duration = 0.0
        avg_request_size = 0.0
        avg_response_size = 0.0
        
        if self._total_requests > 0:
            avg_duration = self._total_duration / self._total_requests
            avg_request_size = self._total_request_size / self._total_requests
            avg_response_size = self._total_response_size / self._total_requests
            
        success_rate = 0.0
        if self._total_requests > 0:
            success_rate = self._success_requests / self._total_requests
            
        return {
            "total_requests": self._total_requests,
            "success_requests": self._success_requests,
            "error_requests": self._error_requests,
            "success_rate": success_rate,
            "avg_duration": avg_duration,
            "avg_request_size": avg_request_size,
            "avg_response_size": avg_response_size,
            "slow_requests_count": len(self._slow_requests),
            "slow_request_threshold": self._slow_request_threshold,
            "active_requests": len(self.request_logs),
            "log_level": self.log_level.value,
            "sensitive_fields": list(self._sensitive_fields)
        }
        
    def reset_statistics(self):
        """重置统计信息"""
        self._total_requests = 0
        self._success_requests = 0
        self._error_requests = 0
        self._total_request_size = 0
        self._total_response_size = 0
        self._total_duration = 0.0
        self._slow_requests.clear()
        logger.info("日志统计信息已重置")
        
    async def export_logs(self, request_ids: List[str]) -> List[Dict[str, Any]]:
        """
        导出日志
        
        Args:
            request_ids: 请求ID列表
            
        Returns:
            List[Dict[str, Any]]: 日志列表
        """
        logs = []
        for request_id in request_ids:
            request_log = self.request_logs.get(request_id)
            if request_log:
                logs.append(request_log.to_dict())
        return logs
        
    def search_logs(self, **filters) -> List[Dict[str, Any]]:
        """
        搜索日志
        
        Args:
            **filters: 过滤条件
            
        Returns:
            List[Dict[str, Any]]: 匹配的日志列表
        """
        results = []
        
        for request_log in self.request_logs.values():
            match = True
            
            for key, value in filters.items():
                if hasattr(request_log, key):
                    if getattr(request_log, key) != value:
                        match = False
                        break
                        
            if match:
                results.append(request_log.to_dict())
                
        return results