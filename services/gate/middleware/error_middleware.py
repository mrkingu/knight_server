"""
错误处理中间件

该模块负责全局异常捕获处理，提供统一的错误响应格式、
错误统计、错误恢复等功能。

主要功能：
- 全局异常捕获处理
- 统一错误响应格式
- 错误统计和监控
- 错误恢复机制
"""

import time
import traceback
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger
from ..config import GatewayConfig
from ..gate_handler import RequestContext, ResponseResult


class ErrorType(Enum):
    """错误类型枚举"""
    VALIDATION_ERROR = "validation_error"      # 验证错误
    AUTHENTICATION_ERROR = "authentication_error"  # 认证错误
    AUTHORIZATION_ERROR = "authorization_error"    # 授权错误
    RATE_LIMIT_ERROR = "rate_limit_error"         # 限流错误
    SERVICE_ERROR = "service_error"               # 服务错误
    TIMEOUT_ERROR = "timeout_error"               # 超时错误
    NETWORK_ERROR = "network_error"               # 网络错误
    SYSTEM_ERROR = "system_error"                 # 系统错误
    UNKNOWN_ERROR = "unknown_error"               # 未知错误


class ErrorSeverity(Enum):
    """错误严重级别枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ErrorInfo:
    """错误信息"""
    error_id: str
    error_type: ErrorType
    error_code: int
    error_message: str
    severity: ErrorSeverity
    request_id: str
    protocol_id: int
    user_id: Optional[str] = None
    connection_id: str = ""
    timestamp: float = field(default_factory=time.time)
    stack_trace: str = ""
    recovery_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error_id": self.error_id,
            "error_type": self.error_type.value,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "severity": self.severity.value,
            "request_id": self.request_id,
            "protocol_id": self.protocol_id,
            "user_id": self.user_id,
            "connection_id": self.connection_id,
            "timestamp": self.timestamp,
            "stack_trace": self.stack_trace,
            "recovery_action": self.recovery_action,
            "metadata": self.metadata
        }


class ErrorMiddleware:
    """错误处理中间件"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化错误处理中间件
        
        Args:
            config: 网关配置
        """
        self.config = config
        
        # 错误记录
        self.error_history: List[ErrorInfo] = []
        self.max_error_history = 1000
        
        # 错误统计
        self.error_stats: Dict[ErrorType, int] = {error_type: 0 for error_type in ErrorType}
        self.error_by_protocol: Dict[int, int] = {}
        self.error_by_severity: Dict[ErrorSeverity, int] = {severity: 0 for severity in ErrorSeverity}
        
        # 错误处理器
        self.error_handlers: Dict[ErrorType, Callable] = {}
        
        # 错误恢复策略
        self.recovery_strategies: Dict[ErrorType, Callable] = {}
        
        # 初始化默认错误处理器
        self._init_default_handlers()
        
        logger.info("错误处理中间件初始化完成")
        
    async def process(self, error: Exception, context: RequestContext) -> ResponseResult:
        """
        处理错误
        
        Args:
            error: 异常对象
            context: 请求上下文
            
        Returns:
            ResponseResult: 错误响应结果
        """
        try:
            # 生成错误ID
            error_id = f"err_{int(time.time() * 1000)}"
            
            # 分析错误类型
            error_type = self._analyze_error_type(error)
            error_code = self._get_error_code(error_type, error)
            error_message = self._get_error_message(error_type, error)
            severity = self._get_error_severity(error_type, error)
            
            # 创建错误信息
            error_info = ErrorInfo(
                error_id=error_id,
                error_type=error_type,
                error_code=error_code,
                error_message=error_message,
                severity=severity,
                request_id=context.request_id,
                protocol_id=context.protocol_id,
                user_id=context.user_id,
                connection_id=context.connection_id,
                stack_trace=traceback.format_exc(),
                metadata=context.metadata
            )
            
            # 记录错误
            await self._record_error(error_info)
            
            # 执行错误处理
            await self._handle_error(error_info, context)
            
            # 尝试错误恢复
            recovery_result = await self._attempt_recovery(error_info, context)
            if recovery_result:
                error_info.recovery_action = recovery_result
                
            # 创建错误响应
            return await self._create_error_response(error_info, context)
            
        except Exception as e:
            # 错误处理本身出错，返回基本错误响应
            logger.error("错误处理失败", 
                        original_error=str(error),
                        handler_error=str(e))
            
            return ResponseResult(
                success=False,
                error_code=500,
                error_message="服务器内部错误"
            )
            
    async def _record_error(self, error_info: ErrorInfo):
        """
        记录错误
        
        Args:
            error_info: 错误信息
        """
        try:
            # 添加到错误历史
            self.error_history.append(error_info)
            
            # 保持历史记录大小
            if len(self.error_history) > self.max_error_history:
                self.error_history.pop(0)
                
            # 更新统计
            self.error_stats[error_info.error_type] += 1
            self.error_by_protocol[error_info.protocol_id] = (
                self.error_by_protocol.get(error_info.protocol_id, 0) + 1
            )
            self.error_by_severity[error_info.severity] += 1
            
            # 记录日志
            log_func = logger.error
            if error_info.severity == ErrorSeverity.CRITICAL:
                log_func = logger.critical
            elif error_info.severity == ErrorSeverity.HIGH:
                log_func = logger.error
            elif error_info.severity == ErrorSeverity.MEDIUM:
                log_func = logger.warning
            else:
                log_func = logger.info
                
            log_func("错误记录", 
                    error_id=error_info.error_id,
                    error_type=error_info.error_type.value,
                    error_code=error_info.error_code,
                    error_message=error_info.error_message,
                    request_id=error_info.request_id,
                    protocol_id=error_info.protocol_id,
                    user_id=error_info.user_id)
            
        except Exception as e:
            logger.error("记录错误失败", error=str(e))
            
    async def _handle_error(self, error_info: ErrorInfo, context: RequestContext):
        """
        处理错误
        
        Args:
            error_info: 错误信息
            context: 请求上下文
        """
        try:
            # 查找错误处理器
            handler = self.error_handlers.get(error_info.error_type)
            if handler:
                await handler(error_info, context)
                
        except Exception as e:
            logger.error("错误处理器执行失败", 
                        error_type=error_info.error_type.value,
                        error=str(e))
            
    async def _attempt_recovery(self, error_info: ErrorInfo, context: RequestContext) -> Optional[str]:
        """
        尝试错误恢复
        
        Args:
            error_info: 错误信息
            context: 请求上下文
            
        Returns:
            Optional[str]: 恢复操作描述
        """
        try:
            # 查找恢复策略
            recovery_strategy = self.recovery_strategies.get(error_info.error_type)
            if recovery_strategy:
                return await recovery_strategy(error_info, context)
                
        except Exception as e:
            logger.error("错误恢复失败", 
                        error_type=error_info.error_type.value,
                        error=str(e))
            
        return None
        
    async def _create_error_response(self, error_info: ErrorInfo, context: RequestContext) -> ResponseResult:
        """
        创建错误响应
        
        Args:
            error_info: 错误信息
            context: 请求上下文
            
        Returns:
            ResponseResult: 错误响应
        """
        # 构建错误响应元数据
        metadata = {
            "error_id": error_info.error_id,
            "error_type": error_info.error_type.value,
            "timestamp": error_info.timestamp
        }
        
        # 在调试模式下添加更多信息
        if self.config.debug:
            metadata.update({
                "stack_trace": error_info.stack_trace,
                "recovery_action": error_info.recovery_action,
                "request_id": error_info.request_id
            })
            
        return ResponseResult(
            success=False,
            error_code=error_info.error_code,
            error_message=error_info.error_message,
            metadata=metadata
        )
        
    def _analyze_error_type(self, error: Exception) -> ErrorType:
        """
        分析错误类型
        
        Args:
            error: 异常对象
            
        Returns:
            ErrorType: 错误类型
        """
        error_class = error.__class__.__name__
        error_message = str(error).lower()
        
        # 根据异常类型分析
        if isinstance(error, ValueError):
            return ErrorType.VALIDATION_ERROR
        elif isinstance(error, PermissionError):
            return ErrorType.AUTHORIZATION_ERROR
        elif isinstance(error, TimeoutError):
            return ErrorType.TIMEOUT_ERROR
        elif isinstance(error, ConnectionError):
            return ErrorType.NETWORK_ERROR
        
        # 根据错误消息分析
        if "authentication" in error_message or "login" in error_message:
            return ErrorType.AUTHENTICATION_ERROR
        elif "authorization" in error_message or "permission" in error_message:
            return ErrorType.AUTHORIZATION_ERROR
        elif "rate limit" in error_message or "too many requests" in error_message:
            return ErrorType.RATE_LIMIT_ERROR
        elif "timeout" in error_message:
            return ErrorType.TIMEOUT_ERROR
        elif "network" in error_message or "connection" in error_message:
            return ErrorType.NETWORK_ERROR
        elif "service" in error_message:
            return ErrorType.SERVICE_ERROR
        elif "validation" in error_message or "invalid" in error_message:
            return ErrorType.VALIDATION_ERROR
        
        return ErrorType.UNKNOWN_ERROR
        
    def _get_error_code(self, error_type: ErrorType, error: Exception) -> int:
        """
        获取错误代码
        
        Args:
            error_type: 错误类型
            error: 异常对象
            
        Returns:
            int: 错误代码
        """
        error_codes = {
            ErrorType.VALIDATION_ERROR: 400,
            ErrorType.AUTHENTICATION_ERROR: 401,
            ErrorType.AUTHORIZATION_ERROR: 403,
            ErrorType.RATE_LIMIT_ERROR: 429,
            ErrorType.SERVICE_ERROR: 502,
            ErrorType.TIMEOUT_ERROR: 504,
            ErrorType.NETWORK_ERROR: 503,
            ErrorType.SYSTEM_ERROR: 500,
            ErrorType.UNKNOWN_ERROR: 500
        }
        
        return error_codes.get(error_type, 500)
        
    def _get_error_message(self, error_type: ErrorType, error: Exception) -> str:
        """
        获取错误消息
        
        Args:
            error_type: 错误类型
            error: 异常对象
            
        Returns:
            str: 错误消息
        """
        # 在生产环境中，不应该暴露详细的错误信息
        if not self.config.debug:
            generic_messages = {
                ErrorType.VALIDATION_ERROR: "请求参数无效",
                ErrorType.AUTHENTICATION_ERROR: "认证失败",
                ErrorType.AUTHORIZATION_ERROR: "权限不足",
                ErrorType.RATE_LIMIT_ERROR: "请求频率过高",
                ErrorType.SERVICE_ERROR: "服务暂时不可用",
                ErrorType.TIMEOUT_ERROR: "请求超时",
                ErrorType.NETWORK_ERROR: "网络连接失败",
                ErrorType.SYSTEM_ERROR: "系统错误",
                ErrorType.UNKNOWN_ERROR: "未知错误"
            }
            return generic_messages.get(error_type, "服务器内部错误")
        
        # 调试模式下返回详细错误信息
        return str(error)
        
    def _get_error_severity(self, error_type: ErrorType, error: Exception) -> ErrorSeverity:
        """
        获取错误严重级别
        
        Args:
            error_type: 错误类型
            error: 异常对象
            
        Returns:
            ErrorSeverity: 严重级别
        """
        severity_map = {
            ErrorType.VALIDATION_ERROR: ErrorSeverity.LOW,
            ErrorType.AUTHENTICATION_ERROR: ErrorSeverity.MEDIUM,
            ErrorType.AUTHORIZATION_ERROR: ErrorSeverity.MEDIUM,
            ErrorType.RATE_LIMIT_ERROR: ErrorSeverity.LOW,
            ErrorType.SERVICE_ERROR: ErrorSeverity.HIGH,
            ErrorType.TIMEOUT_ERROR: ErrorSeverity.MEDIUM,
            ErrorType.NETWORK_ERROR: ErrorSeverity.HIGH,
            ErrorType.SYSTEM_ERROR: ErrorSeverity.CRITICAL,
            ErrorType.UNKNOWN_ERROR: ErrorSeverity.HIGH
        }
        
        return severity_map.get(error_type, ErrorSeverity.MEDIUM)
        
    def _init_default_handlers(self):
        """初始化默认错误处理器"""
        # 限流错误处理器
        async def rate_limit_handler(error_info: ErrorInfo, context: RequestContext):
            # 记录限流日志
            logger.warning("请求被限流", 
                         user_id=context.user_id,
                         protocol_id=context.protocol_id,
                         client_ip=context.client_ip)
            
        self.error_handlers[ErrorType.RATE_LIMIT_ERROR] = rate_limit_handler
        
        # 认证错误处理器
        async def auth_error_handler(error_info: ErrorInfo, context: RequestContext):
            # 记录认证失败日志
            logger.warning("认证失败", 
                         user_id=context.user_id,
                         protocol_id=context.protocol_id,
                         client_ip=context.client_ip)
            
        self.error_handlers[ErrorType.AUTHENTICATION_ERROR] = auth_error_handler
        
        # 服务错误处理器
        async def service_error_handler(error_info: ErrorInfo, context: RequestContext):
            # 记录服务错误日志
            logger.error("服务错误", 
                        protocol_id=context.protocol_id,
                        error_message=error_info.error_message,
                        stack_trace=error_info.stack_trace)
            
        self.error_handlers[ErrorType.SERVICE_ERROR] = service_error_handler
        
        # 系统错误处理器
        async def system_error_handler(error_info: ErrorInfo, context: RequestContext):
            # 记录系统错误日志
            logger.critical("系统错误", 
                           protocol_id=context.protocol_id,
                           error_message=error_info.error_message,
                           stack_trace=error_info.stack_trace)
            
        self.error_handlers[ErrorType.SYSTEM_ERROR] = system_error_handler
        
    def add_error_handler(self, error_type: ErrorType, handler: Callable):
        """
        添加错误处理器
        
        Args:
            error_type: 错误类型
            handler: 处理器函数
        """
        self.error_handlers[error_type] = handler
        logger.info("添加错误处理器", error_type=error_type.value)
        
    def add_recovery_strategy(self, error_type: ErrorType, strategy: Callable):
        """
        添加恢复策略
        
        Args:
            error_type: 错误类型
            strategy: 恢复策略函数
        """
        self.recovery_strategies[error_type] = strategy
        logger.info("添加恢复策略", error_type=error_type.value)
        
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        total_errors = sum(self.error_stats.values())
        
        return {
            "total_errors": total_errors,
            "errors_by_type": {error_type.value: count for error_type, count in self.error_stats.items()},
            "errors_by_protocol": self.error_by_protocol,
            "errors_by_severity": {severity.value: count for severity, count in self.error_by_severity.items()},
            "recent_errors": len(self.error_history),
            "error_handlers": len(self.error_handlers),
            "recovery_strategies": len(self.recovery_strategies)
        }
        
    def get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的错误
        
        Args:
            limit: 限制数量
            
        Returns:
            List[Dict[str, Any]]: 错误列表
        """
        return [error.to_dict() for error in self.error_history[-limit:]]
        
    def get_errors_by_type(self, error_type: ErrorType) -> List[Dict[str, Any]]:
        """
        获取指定类型的错误
        
        Args:
            error_type: 错误类型
            
        Returns:
            List[Dict[str, Any]]: 错误列表
        """
        return [error.to_dict() for error in self.error_history if error.error_type == error_type]
        
    def clear_error_history(self):
        """清除错误历史"""
        self.error_history.clear()
        logger.info("错误历史已清除")
        
    def reset_statistics(self):
        """重置统计信息"""
        self.error_stats = {error_type: 0 for error_type in ErrorType}
        self.error_by_protocol.clear()
        self.error_by_severity = {severity: 0 for severity in ErrorSeverity}
        logger.info("错误统计信息已重置")