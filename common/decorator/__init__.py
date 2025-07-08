"""
common/decorator 模块

该模块提供了各类装饰器简化开发，包括gRPC、协议绑定、处理器、Celery任务和认证等装饰器。

主要功能：
- gRPC装饰器：@grpc_service, @grpc_method, @grpc_call
- 协议装饰器：@proto_message, @request_proto, @response_proto
- 处理器装饰器：@handler, @controller, @route
- Celery装饰器：@periodic_task, @delay_task, @retry_task
- 认证装饰器：@require_auth, @require_permission, @rate_limit

使用示例：
```python
# gRPC服务
@grpc_service(name="UserService")
class UserService:
    @grpc_method
    async def get_user_info(self, request):
        pass

# 消息处理器
@controller(name="UserController")
class UserController:
    @handler(request_proto=LoginRequest, response_proto=LoginResponse)
    @require_auth
    @rate_limit(max_calls=10, period=60)
    async def handle_login(self, request: LoginRequest) -> LoginResponse:
        pass

# Celery任务
@periodic_task(cron="0 0 * * *")
async def daily_reset():
    pass

@delay_task(countdown=60)
async def delayed_reward(user_id: str):
    pass
```
"""

# 导入gRPC装饰器
from .grpc_decorator import (
    grpc_service,
    grpc_method,
    grpc_call,
    grpc_stream,
    GrpcServiceType,
    GrpcMethodInfo,
    GrpcServiceInfo,
    GrpcServiceRegistry,
    get_grpc_registry,
    list_grpc_services,
    get_grpc_service_info
)

# 导入协议装饰器
from .proto_decorator import (
    proto_message,
    request_proto,
    response_proto,
    notification_proto,
    event_proto,
    proto_binding,
    ProtoType,
    ProtoMessageInfo,
    ProtoBindingInfo,
    ProtoRegistry,
    get_proto_registry,
    get_message_info,
    get_message_info_by_type,
    list_proto_messages,
    register_proto_message
)

# 导入处理器装饰器
from .handler_decorator import (
    handler,
    controller,
    route,
    middleware,
    HandlerType,
    HandlerInfo,
    ControllerInfo,
    RouteInfo,
    HandlerStatistics,
    HandlerRegistry,
    get_handler_registry,
    get_controller_info,
    get_handler_info,
    get_route_info,
    get_handler_statistics,
    list_controllers,
    list_handlers,
    list_routes,
    dispatch_message
)

# 导入Celery任务装饰器
from .celery_decorator import (
    periodic_task,
    delay_task,
    retry_task,
    priority_task,
    TaskStatus,
    TaskPriority,
    TaskInfo,
    CronSchedule,
    PeriodicTaskConfig,
    TaskStatistics,
    TaskRegistry,
    get_task_registry,
    get_task_info,
    get_task_statistics,
    list_running_tasks,
    list_periodic_tasks,
    cancel_task
)

# 导入认证装饰器
from .auth_decorator import (
    require_auth,
    require_permission,
    require_role,
    rate_limit,
    permission_level_required,
    AuthStatus,
    PermissionLevel,
    UserInfo,
    RateLimitInfo,
    AuthStatistics,
    AuthManager,
    get_auth_manager,
    authenticate_user,
    logout_user,
    get_current_user,
    get_auth_statistics
)

# 版本信息
__version__ = "1.0.0"
__author__ = "Knight Server Team"

# 模块级别的公共接口
__all__ = [
    # gRPC装饰器
    "grpc_service",
    "grpc_method", 
    "grpc_call",
    "grpc_stream",
    "GrpcServiceType",
    "GrpcMethodInfo",
    "GrpcServiceInfo",
    "GrpcServiceRegistry",
    "get_grpc_registry",
    "list_grpc_services",
    "get_grpc_service_info",
    
    # 协议装饰器
    "proto_message",
    "request_proto",
    "response_proto",
    "notification_proto",
    "event_proto",
    "proto_binding",
    "ProtoType",
    "ProtoMessageInfo",
    "ProtoBindingInfo",
    "ProtoRegistry",
    "get_proto_registry",
    "get_message_info",
    "get_message_info_by_type",
    "list_proto_messages",
    "register_proto_message",
    
    # 处理器装饰器
    "handler",
    "controller",
    "route",
    "middleware",
    "HandlerType",
    "HandlerInfo",
    "ControllerInfo",
    "RouteInfo", 
    "HandlerStatistics",
    "HandlerRegistry",
    "get_handler_registry",
    "get_controller_info",
    "get_handler_info",
    "get_route_info",
    "get_handler_statistics",
    "list_controllers",
    "list_handlers",
    "list_routes",
    "dispatch_message",
    
    # Celery任务装饰器
    "periodic_task",
    "delay_task",
    "retry_task",
    "priority_task",
    "TaskStatus",
    "TaskPriority",
    "TaskInfo",
    "CronSchedule",
    "PeriodicTaskConfig",
    "TaskStatistics",
    "TaskRegistry",
    "get_task_registry",
    "get_task_info",
    "get_task_statistics",
    "list_running_tasks",
    "list_periodic_tasks",
    "cancel_task",
    
    # 认证装饰器
    "require_auth",
    "require_permission",
    "require_role",
    "rate_limit",
    "permission_level_required",
    "AuthStatus",
    "PermissionLevel",
    "UserInfo",
    "RateLimitInfo",
    "AuthStatistics",
    "AuthManager",
    "get_auth_manager",
    "authenticate_user",
    "logout_user",
    "get_current_user",
    "get_auth_statistics",
    
    # 版本信息
    "__version__",
    "__author__"
]
