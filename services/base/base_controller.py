"""
基础控制器类模块

该模块提供了所有控制器的基础类，支持装饰器绑定、请求参数自动解析、
响应对象构建、业务异常处理、Service层调用、请求上下文管理等功能。

主要功能：
- 装饰器支持（用于绑定消息ID到处理方法）
- 请求参数自动解析
- 响应对象自动构建
- 业务异常处理
- 调用Service层的标准接口
- 请求上下文管理
- 权限验证接入点
- 参数验证

使用示例：
```python
from services.base.base_controller import BaseController
from common.decorator.handler_decorator import handler, controller

@controller(name="UserController")
class UserController(BaseController):
    def __init__(self):
        super().__init__()
        self.user_service = self.get_service("UserService")
    
    @handler(RequestLogin, ResponseLogin)
    async def handle_login(self, request: RequestLogin, context: RequestContext) -> ResponseLogin:
        # 参数验证
        self.validate_required_fields(request, ['username', 'password'])
        
        # 调用服务层
        user_info = await self.user_service.authenticate_user(
            request.username, request.password
        )
        
        # 构建响应
        return ResponseLogin(
            success=True,
            user_id=user_info.user_id,
            token=user_info.token
        )
```
"""

import asyncio
import time
import functools
from typing import Dict, List, Optional, Any, Callable, Type, Union, get_type_hints
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager

from common.logger import logger
from common.decorator.handler_decorator import handler, controller, get_handler_registry
try:
    from common.security import SecurityManager, check_permission, validate_token
except ImportError:
    class SecurityManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
    
    async def check_permission(user_id, permission):
        return True
    
    async def validate_token(token, user_id):
        return True

try:
    from common.proto import BaseRequest, BaseResponse
except ImportError:
    # Mock proto base classes if not available
    class BaseRequest:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    class BaseResponse:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)


class ControllerException(Exception):
    """控制器异常基类"""
    def __init__(self, message: str, error_code: int = 400, details: dict = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class ValidationException(ControllerException):
    """参数验证异常"""
    def __init__(self, message: str, field_name: str = None):
        super().__init__(message, error_code=400)
        self.field_name = field_name


class AuthorizationException(ControllerException):
    """权限验证异常"""
    def __init__(self, message: str = "权限不足"):
        super().__init__(message, error_code=403)


class BusinessException(ControllerException):
    """业务逻辑异常"""
    def __init__(self, message: str, error_code: int = 500):
        super().__init__(message, error_code=error_code)


@dataclass
class RequestContext:
    """请求上下文（从base_handler传递而来）"""
    trace_id: str
    message_id: int
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    client_id: Optional[str] = None
    ip_address: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseContext:
    """响应上下文"""
    trace_id: str
    message_id: int
    success: bool = True
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ControllerConfig:
    """控制器配置"""
    # 验证配置
    enable_validation: bool = True
    enable_authorization: bool = True
    enable_rate_limiting: bool = True
    
    # 性能配置
    enable_caching: bool = True
    cache_ttl: int = 300  # 5分钟
    
    # 日志配置
    enable_request_logging: bool = True
    enable_response_logging: bool = True
    
    # 其他配置
    max_request_size: int = 1024 * 1024  # 1MB
    request_timeout: float = 30.0


class BaseController:
    """
    基础控制器类
    
    所有控制器的基类，提供：
    - 装饰器支持
    - 请求参数解析
    - 响应构建
    - 异常处理
    - Service层调用
    - 上下文管理
    - 权限验证
    - 参数验证
    """
    
    def __init__(self, config: Optional[ControllerConfig] = None):
        """
        初始化基础控制器
        
        Args:
            config: 控制器配置
        """
        self.config = config or ControllerConfig()
        self.logger = logger
        
        # 核心组件
        self._security_manager = SecurityManager()
        self._handler_registry = get_handler_registry()
        
        # 服务依赖
        self._services: Dict[str, Any] = {}
        
        # 验证器
        self._validators: Dict[str, Callable] = {}
        
        # 中间件
        self._before_middlewares: List[Callable] = []
        self._after_middlewares: List[Callable] = []
        self._error_middlewares: List[Callable] = []
        
        # 缓存
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        
        # 权限配置
        self._permission_rules: Dict[str, List[str]] = {}
        
        self.logger.info("基础控制器初始化完成", 
                        controller_name=self.__class__.__name__)
    
    async def initialize(self):
        """初始化控制器"""
        try:
            # 初始化安全管理器
            await self._security_manager.initialize()
            
            # 注册默认验证器
            self._register_default_validators()
            
            # 加载权限配置
            await self._load_permission_rules()
            
            self.logger.info("控制器初始化完成", 
                           controller_name=self.__class__.__name__)
            
        except Exception as e:
            self.logger.error("控制器初始化失败", 
                            controller_name=self.__class__.__name__,
                            error=str(e))
            raise
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            # 清理缓存
            self._cache.clear()
            self._cache_timestamps.clear()
            
            # 清理服务依赖
            for service in self._services.values():
                if hasattr(service, 'cleanup'):
                    await service.cleanup()
            
            self.logger.info("控制器清理完成", 
                           controller_name=self.__class__.__name__)
            
        except Exception as e:
            self.logger.error("控制器清理失败", 
                            controller_name=self.__class__.__name__,
                            error=str(e))
    
    def get_service(self, service_name: str) -> Any:
        """
        获取服务实例
        
        Args:
            service_name: 服务名称
            
        Returns:
            Any: 服务实例
        """
        if service_name not in self._services:
            raise BusinessException(f"服务 {service_name} 未找到")
        
        return self._services[service_name]
    
    def register_service(self, service_name: str, service: Any):
        """
        注册服务
        
        Args:
            service_name: 服务名称
            service: 服务实例
        """
        self._services[service_name] = service
        self.logger.info("服务注册成功", 
                        controller_name=self.__class__.__name__,
                        service_name=service_name)
    
    async def validate_request(self, request: Any, context: RequestContext = None) -> bool:
        """
        验证请求
        
        Args:
            request: 请求对象
            context: 请求上下文
            
        Returns:
            bool: 验证是否通过
        """
        if not self.config.enable_validation:
            return True
        
        try:
            # 基本验证
            await self._validate_basic_request(request, context)
            
            # 类型验证
            await self._validate_request_types(request)
            
            # 业务验证
            await self._validate_business_rules(request, context)
            
            return True
            
        except ValidationException:
            raise
        except Exception as e:
            raise ValidationException(f"请求验证失败: {str(e)}")
    
    async def validate_authorization(self, request: Any, context: RequestContext = None) -> bool:
        """
        验证权限
        
        Args:
            request: 请求对象
            context: 请求上下文
            
        Returns:
            bool: 权限验证是否通过
        """
        if not self.config.enable_authorization:
            return True
        
        try:
            # 验证用户身份
            if context and context.user_id:
                if not await self._verify_user_identity(context.user_id, context):
                    raise AuthorizationException("用户身份验证失败")
            
            # 验证权限
            handler_name = getattr(request, '_handler_name', None)
            if handler_name:
                required_permissions = self._permission_rules.get(handler_name, [])
                if required_permissions:
                    for permission in required_permissions:
                        if not await check_permission(context.user_id, permission):
                            raise AuthorizationException(f"缺少权限: {permission}")
            
            return True
            
        except AuthorizationException:
            raise
        except Exception as e:
            raise AuthorizationException(f"权限验证失败: {str(e)}")
    
    async def build_response(self, result: Any, context: RequestContext = None) -> Any:
        """
        构建响应
        
        Args:
            result: 处理结果
            context: 请求上下文
            
        Returns:
            Any: 响应对象
        """
        try:
            # 如果结果已经是响应对象，直接返回
            if isinstance(result, BaseResponse):
                return result
            
            # 根据结果类型构建响应
            if isinstance(result, dict):
                return self._build_dict_response(result, context)
            elif isinstance(result, list):
                return self._build_list_response(result, context)
            else:
                return self._build_generic_response(result, context)
            
        except Exception as e:
            self.logger.error("构建响应失败", 
                            controller_name=self.__class__.__name__,
                            error=str(e))
            raise BusinessException(f"构建响应失败: {str(e)}")
    
    async def handle_exception(self, error: Exception, context: RequestContext = None) -> Any:
        """
        处理异常
        
        Args:
            error: 异常对象
            context: 请求上下文
            
        Returns:
            Any: 错误响应
        """
        # 记录异常日志
        self.logger.error("控制器异常", 
                        controller_name=self.__class__.__name__,
                        error=str(error),
                        trace_id=context.trace_id if context else None)
        
        # 根据异常类型处理
        if isinstance(error, ControllerException):
            return self._build_error_response(error, context)
        else:
            # 其他异常转换为业务异常
            business_error = BusinessException(f"服务器内部错误: {str(error)}")
            return self._build_error_response(business_error, context)
    
    def validate_required_fields(self, request: Any, fields: List[str]):
        """
        验证必填字段
        
        Args:
            request: 请求对象
            fields: 必填字段列表
        """
        for field in fields:
            # 支持字典和对象两种形式
            if hasattr(request, field):
                value = getattr(request, field)
            elif isinstance(request, dict) and field in request:
                value = request[field]
            else:
                raise ValidationException(f"缺少必填字段: {field}", field_name=field)
            
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValidationException(f"字段 {field} 不能为空", field_name=field)
    
    def validate_field_type(self, request: Any, field: str, expected_type: Type):
        """
        验证字段类型
        
        Args:
            request: 请求对象
            field: 字段名
            expected_type: 期望的类型
        """
        if not hasattr(request, field):
            return
        
        value = getattr(request, field)
        if value is not None and not isinstance(value, expected_type):
            raise ValidationException(
                f"字段 {field} 类型错误，期望 {expected_type.__name__}，实际 {type(value).__name__}",
                field_name=field
            )
    
    def validate_field_range(self, request: Any, field: str, min_value: Any = None, max_value: Any = None):
        """
        验证字段范围
        
        Args:
            request: 请求对象
            field: 字段名
            min_value: 最小值
            max_value: 最大值
        """
        if not hasattr(request, field):
            return
        
        value = getattr(request, field)
        if value is None:
            return
        
        if min_value is not None and value < min_value:
            raise ValidationException(
                f"字段 {field} 值过小，最小值为 {min_value}",
                field_name=field
            )
        
        if max_value is not None and value > max_value:
            raise ValidationException(
                f"字段 {field} 值过大，最大值为 {max_value}",
                field_name=field
            )
    
    def validate_field_length(self, request: Any, field: str, min_length: int = None, max_length: int = None):
        """
        验证字段长度
        
        Args:
            request: 请求对象
            field: 字段名
            min_length: 最小长度
            max_length: 最大长度
        """
        if not hasattr(request, field):
            return
        
        value = getattr(request, field)
        if value is None:
            return
        
        length = len(value)
        
        if min_length is not None and length < min_length:
            raise ValidationException(
                f"字段 {field} 长度过短，最小长度为 {min_length}",
                field_name=field
            )
        
        if max_length is not None and length > max_length:
            raise ValidationException(
                f"字段 {field} 长度过长，最大长度为 {max_length}",
                field_name=field
            )
    
    def validate_field_pattern(self, request: Any, field: str, pattern: str):
        """
        验证字段格式
        
        Args:
            request: 请求对象
            field: 字段名
            pattern: 正则表达式模式
        """
        import re
        
        if hasattr(request, field):
            value = getattr(request, field)
        elif isinstance(request, dict) and field in request:
            value = request[field]
        else:
            return  # 字段不存在，跳过验证
        
        if value is None:
            return
        
        if not re.match(pattern, str(value)):
            raise ValidationException(
                f"字段 {field} 格式不正确",
                field_name=field
            )
    
    @asynccontextmanager
    async def request_context(self, context: RequestContext):
        """
        请求上下文管理器
        
        Args:
            context: 请求上下文
        """
        start_time = time.time()
        
        try:
            # 执行前置中间件
            for middleware in self._before_middlewares:
                await middleware(context)
            
            yield context
            
        except Exception as e:
            # 执行错误中间件
            for middleware in self._error_middlewares:
                await middleware(context, e)
            raise
            
        finally:
            # 执行后置中间件
            for middleware in self._after_middlewares:
                await middleware(context)
            
            # 记录请求耗时
            elapsed_time = time.time() - start_time
            self.logger.debug("请求处理完成", 
                            controller_name=self.__class__.__name__,
                            trace_id=context.trace_id,
                            elapsed_time=elapsed_time)
    
    async def _validate_basic_request(self, request: Any, context: RequestContext = None):
        """验证基本请求"""
        if request is None:
            raise ValidationException("请求对象不能为空")
        
        # 检查请求大小
        if hasattr(request, '__sizeof__'):
            size = request.__sizeof__()
            if size > self.config.max_request_size:
                raise ValidationException(f"请求大小超过限制: {size} > {self.config.max_request_size}")
    
    async def _validate_request_types(self, request: Any):
        """验证请求类型"""
        # 获取类型提示
        type_hints = get_type_hints(request.__class__)
        
        for field_name, field_type in type_hints.items():
            if hasattr(request, field_name):
                value = getattr(request, field_name)
                if value is not None and not isinstance(value, field_type):
                    raise ValidationException(
                        f"字段 {field_name} 类型错误，期望 {field_type}，实际 {type(value)}",
                        field_name=field_name
                    )
    
    async def _validate_business_rules(self, request: Any, context: RequestContext = None):
        """验证业务规则"""
        # 子类可以重写此方法来添加自定义的业务规则验证
        pass
    
    async def _verify_user_identity(self, user_id: str, context: RequestContext) -> bool:
        """验证用户身份"""
        try:
            # 验证token
            if context.metadata.get('token'):
                return await validate_token(context.metadata['token'], user_id)
            
            # 验证session
            if context.session_id:
                return await self._verify_session(context.session_id, user_id)
            
            return False
            
        except Exception as e:
            self.logger.error("用户身份验证失败", 
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def _verify_session(self, session_id: str, user_id: str) -> bool:
        """验证会话"""
        # 这里应该实现会话验证逻辑
        # 可以连接Redis或其他存储来验证会话
        return True
    
    def _build_dict_response(self, result: dict, context: RequestContext = None) -> dict:
        """构建字典响应"""
        response = {
            "success": True,
            "data": result,
            "timestamp": time.time()
        }
        
        if context:
            response["trace_id"] = context.trace_id
        
        return response
    
    def _build_list_response(self, result: list, context: RequestContext = None) -> dict:
        """构建列表响应"""
        response = {
            "success": True,
            "data": result,
            "count": len(result),
            "timestamp": time.time()
        }
        
        if context:
            response["trace_id"] = context.trace_id
        
        return response
    
    def _build_generic_response(self, result: Any, context: RequestContext = None) -> dict:
        """构建通用响应"""
        response = {
            "success": True,
            "data": result,
            "timestamp": time.time()
        }
        
        if context:
            response["trace_id"] = context.trace_id
        
        return response
    
    def _build_error_response(self, error: ControllerException, context: RequestContext = None) -> dict:
        """构建错误响应"""
        response = {
            "success": False,
            "error_code": error.error_code,
            "error_message": str(error),
            "timestamp": time.time()
        }
        
        if error.details:
            response["details"] = error.details
        
        if context:
            response["trace_id"] = context.trace_id
        
        return response
    
    def _register_default_validators(self):
        """注册默认验证器"""
        # 邮箱验证器
        def email_validator(value: str) -> bool:
            import re
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            return re.match(pattern, value) is not None
        
        # 手机号验证器
        def phone_validator(value: str) -> bool:
            import re
            pattern = r'^1[3-9]\d{9}$'
            return re.match(pattern, value) is not None
        
        # 密码强度验证器
        def password_validator(value: str) -> bool:
            import re
            # 至少8位，包含字母和数字
            pattern = r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d@$!%*#?&]{8,}$'
            return re.match(pattern, value) is not None
        
        self._validators.update({
            'email': email_validator,
            'phone': phone_validator,
            'password': password_validator
        })
    
    async def _load_permission_rules(self):
        """加载权限规则"""
        # 这里可以从配置文件或数据库加载权限规则
        # 示例权限规则
        self._permission_rules = {
            'handle_login': [],  # 登录无需权限
            'handle_logout': ['user:logout'],
            'handle_user_info': ['user:read'],
            'handle_update_user': ['user:write'],
            'handle_delete_user': ['user:delete']
        }
    
    def add_before_middleware(self, middleware: Callable):
        """添加前置中间件"""
        self._before_middlewares.append(middleware)
    
    def add_after_middleware(self, middleware: Callable):
        """添加后置中间件"""
        self._after_middlewares.append(middleware)
    
    def add_error_middleware(self, middleware: Callable):
        """添加错误中间件"""
        self._error_middlewares.append(middleware)
    
    def set_permission_rules(self, rules: Dict[str, List[str]]):
        """设置权限规则"""
        self._permission_rules.update(rules)
    
    def get_cache(self, key: str) -> Any:
        """获取缓存"""
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
    
    def set_cache(self, key: str, value: Any):
        """设置缓存"""
        if not self.config.enable_caching:
            return
        
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()
    
    def clear_cache(self, key: str = None):
        """清除缓存"""
        if key:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
    
    @property
    def services(self) -> Dict[str, Any]:
        """获取已注册的服务"""
        return self._services.copy()
    
    @property
    def validators(self) -> Dict[str, Callable]:
        """获取验证器"""
        return self._validators.copy()
    
    @property
    def permission_rules(self) -> Dict[str, List[str]]:
        """获取权限规则"""
        return self._permission_rules.copy()