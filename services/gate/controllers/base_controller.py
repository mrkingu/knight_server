"""
控制器基类

该模块定义了网关控制器的基类，提供统一的请求响应模式、
权限验证、参数校验等通用功能。

主要功能：
- 统一的请求响应模式
- 权限验证和参数校验
- 请求链路追踪
- 错误处理和日志记录
- 性能监控
"""

import time
from typing import Dict, Any, Optional, Set, List
from abc import ABC, abstractmethod
from dataclasses import dataclass

from common.logger import logger
from services.base.base_controller import BaseController as BaseBaseController
from ..config import GatewayConfig
from ..gate_handler import RequestContext, ResponseResult


@dataclass
class ControllerResponse:
    """控制器响应"""
    success: bool
    data: Any = None
    error_code: int = 0
    error_message: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
            
    def to_response_result(self) -> ResponseResult:
        """转换为响应结果"""
        return ResponseResult(
            success=self.success,
            data=self.data,
            error_code=self.error_code,
            error_message=self.error_message,
            metadata=self.metadata
        )


class BaseController(BaseBaseController, ABC):
    """网关控制器基类"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化控制器
        
        Args:
            config: 网关配置
        """
        super().__init__()
        self.config = config
        self.controller_name = self.__class__.__name__
        
        # 权限配置
        self.required_permissions: Set[str] = set()
        self.anonymous_methods: Set[str] = set()  # 允许匿名访问的方法
        
        # 性能统计
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._total_time = 0.0
        
        logger.info("控制器初始化完成", controller_name=self.controller_name)
        
    async def process_request(self, data: Any, context: RequestContext) -> ResponseResult:
        """
        处理请求的统一入口
        
        Args:
            data: 请求数据
            context: 请求上下文
            
        Returns:
            ResponseResult: 响应结果
        """
        start_time = time.time()
        method_name = f"handle_protocol_{context.protocol_id}"
        
        try:
            # 更新请求统计
            self._request_count += 1
            
            # 前置处理
            await self._before_request(data, context)
            
            # 权限验证
            if not await self._check_permissions(context, method_name):
                return ResponseResult(
                    success=False,
                    error_code=403,
                    error_message="权限不足"
                )
                
            # 参数验证
            validated_data = await self._validate_request(data, context)
            if validated_data is None:
                return ResponseResult(
                    success=False,
                    error_code=400,
                    error_message="请求参数无效"
                )
                
            # 查找并调用处理方法
            handler = getattr(self, method_name, None)
            if not handler:
                return ResponseResult(
                    success=False,
                    error_code=404,
                    error_message=f"未找到处理方法: {method_name}"
                )
                
            # 调用处理方法
            result = await handler(validated_data, context)
            
            # 后置处理
            await self._after_request(result, context)
            
            # 转换响应结果
            if isinstance(result, ControllerResponse):
                response = result.to_response_result()
            elif isinstance(result, ResponseResult):
                response = result
            elif isinstance(result, dict):
                response = ResponseResult(success=True, data=result)
            else:
                response = ResponseResult(success=True, data={"result": result})
                
            # 更新成功统计
            self._success_count += 1
            
            return response
            
        except Exception as e:
            # 更新错误统计
            self._error_count += 1
            
            logger.error("处理请求失败", 
                        controller_name=self.controller_name,
                        method_name=method_name,
                        protocol_id=context.protocol_id,
                        error=str(e))
            
            # 错误处理
            return await self._handle_error(e, context)
            
        finally:
            # 更新时间统计
            duration = time.time() - start_time
            self._total_time += duration
            
    async def _before_request(self, data: Any, context: RequestContext):
        """
        请求前置处理
        
        Args:
            data: 请求数据
            context: 请求上下文
        """
        # 记录请求日志
        logger.info("处理请求开始", 
                   controller_name=self.controller_name,
                   protocol_id=context.protocol_id,
                   connection_id=context.connection_id,
                   user_id=context.user_id)
        
        # 可以在子类中重写此方法
        pass
        
    async def _after_request(self, result: Any, context: RequestContext):
        """
        请求后置处理
        
        Args:
            result: 处理结果
            context: 请求上下文
        """
        # 记录响应日志
        logger.info("处理请求完成", 
                   controller_name=self.controller_name,
                   protocol_id=context.protocol_id,
                   connection_id=context.connection_id,
                   user_id=context.user_id)
        
        # 可以在子类中重写此方法
        pass
        
    async def _check_permissions(self, context: RequestContext, method_name: str) -> bool:
        """
        检查权限
        
        Args:
            context: 请求上下文
            method_name: 方法名称
            
        Returns:
            bool: 是否有权限
        """
        # 检查是否允许匿名访问
        if method_name in self.anonymous_methods:
            return True
            
        # 检查用户是否已登录
        if not context.user_id:
            return False
            
        # 检查方法权限
        if self.required_permissions:
            # TODO: 从会话管理器获取用户权限并检查
            # 这里可以集成权限系统
            pass
            
        return True
        
    async def _validate_request(self, data: Any, context: RequestContext) -> Optional[Any]:
        """
        验证请求数据
        
        Args:
            data: 请求数据
            context: 请求上下文
            
        Returns:
            Any: 验证后的数据，None表示验证失败
        """
        # 基本验证
        if data is None:
            return None
            
        # 可以在子类中重写此方法进行具体的参数验证
        return data
        
    async def _handle_error(self, error: Exception, context: RequestContext) -> ResponseResult:
        """
        处理错误
        
        Args:
            error: 错误对象
            context: 请求上下文
            
        Returns:
            ResponseResult: 错误响应
        """
        error_message = str(error)
        error_code = 500
        
        # 根据错误类型设置错误码
        if isinstance(error, ValueError):
            error_code = 400
        elif isinstance(error, PermissionError):
            error_code = 403
        elif isinstance(error, FileNotFoundError):
            error_code = 404
        elif isinstance(error, TimeoutError):
            error_code = 408
            
        return ResponseResult(
            success=False,
            error_code=error_code,
            error_message=error_message
        )
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        avg_time = 0.0
        if self._request_count > 0:
            avg_time = self._total_time / self._request_count
            
        success_rate = 0.0
        if self._request_count > 0:
            success_rate = self._success_count / self._request_count
            
        return {
            "controller_name": self.controller_name,
            "request_count": self._request_count,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate": success_rate,
            "average_time": avg_time
        }
        
    def add_anonymous_method(self, method_name: str):
        """添加匿名方法"""
        self.anonymous_methods.add(method_name)
        
    def add_required_permission(self, permission: str):
        """添加必需权限"""
        self.required_permissions.add(permission)
        
    def remove_required_permission(self, permission: str):
        """移除必需权限"""
        self.required_permissions.discard(permission)
        
    # 辅助方法
    def success_response(self, data: Any = None, metadata: Dict[str, Any] = None) -> ControllerResponse:
        """创建成功响应"""
        return ControllerResponse(
            success=True,
            data=data,
            metadata=metadata or {}
        )
        
    def error_response(self, error_code: int, error_message: str, 
                      metadata: Dict[str, Any] = None) -> ControllerResponse:
        """创建错误响应"""
        return ControllerResponse(
            success=False,
            error_code=error_code,
            error_message=error_message,
            metadata=metadata or {}
        )
        
    def validation_error_response(self, field: str, message: str) -> ControllerResponse:
        """创建验证错误响应"""
        return ControllerResponse(
            success=False,
            error_code=400,
            error_message=f"参数验证失败: {field} - {message}"
        )
        
    def permission_error_response(self, permission: str) -> ControllerResponse:
        """创建权限错误响应"""
        return ControllerResponse(
            success=False,
            error_code=403,
            error_message=f"缺少权限: {permission}"
        )
        
    def not_found_response(self, resource: str) -> ControllerResponse:
        """创建未找到响应"""
        return ControllerResponse(
            success=False,
            error_code=404,
            error_message=f"资源未找到: {resource}"
        )
        
    def server_error_response(self, message: str = "服务器内部错误") -> ControllerResponse:
        """创建服务器错误响应"""
        return ControllerResponse(
            success=False,
            error_code=500,
            error_message=message
        )
        
    # 抽象方法 - 子类必须实现
    @abstractmethod
    async def get_supported_protocols(self) -> List[int]:
        """
        获取支持的协议列表
        
        Returns:
            List[int]: 协议ID列表
        """
        pass
        
    @abstractmethod
    async def get_controller_info(self) -> Dict[str, Any]:
        """
        获取控制器信息
        
        Returns:
            Dict[str, Any]: 控制器信息
        """
        pass