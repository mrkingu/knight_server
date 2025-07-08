"""
services/base 模块

该模块提供了微服务基础类的功能实现，为所有微服务（gate、logic、chat、fight）
提供统一的MVC架构支持。

主要组件：
- BaseServer: 基础服务器类，提供gRPC、多进程、异步支持
- BaseHandler: 基础消息处理器类，提供消息路由和异常处理
- BaseController: 基础控制器类，提供装饰器支持和参数解析
- BaseService: 基础业务服务类，提供事务和缓存支持
- BaseNotify: 基础通知服务类，提供消息推送功能
- BaseRepository: 基础数据访问类，提供CRUD和查询构建

使用示例：
```python
from services.base import BaseServer, BaseController, BaseService

class LogicServer(BaseServer):
    def __init__(self):
        super().__init__(service_name="logic_server")

@controller(name="UserController")
class UserController(BaseController):
    @handler(RequestLogin, ResponseLogin)
    async def handle_login(self, request, context):
        return await self.get_service("UserService").login(request.username, request.password)

class UserService(BaseService):
    async def login(self, username: str, password: str):
        return await self.get_repository("UserRepository").find_by_username(username)
```
"""

# 导入基础服务器类
from .base_server import BaseServer, BaseServerConfig

# 导入基础消息处理器类
from .base_handler import (
    BaseHandler, 
    RequestContext, 
    ResponseContext, 
    MessageType,
    HandlerStatistics
)

# 导入基础控制器类
from .base_controller import (
    BaseController,
    ControllerConfig,
    ControllerException,
    ValidationException,
    AuthorizationException,
    BusinessException
)

# 导入基础业务服务类
from .base_service import (
    BaseService,
    ServiceConfig,
    ServiceException,
    TransactionException,
    CacheException,
    ServiceCallException,
    TransactionContext,
    transactional,
    cached,
    retry,
    monitored
)

# 导入基础通知服务类
from .base_notify import (
    BaseNotify,
    NotifyConfig,
    NotifyMessage,
    NotifyTarget,
    NotifyTask,
    NotifyStatistics,
    NotifyType,
    MessagePriority,
    NotifyStatus
)

# 导入基础数据访问类
from .base_repository import (
    BaseRepository,
    RepositoryConfig,
    QueryBuilder,
    QueryCondition,
    SortCondition,
    PaginationOptions,
    CacheConfig,
    QueryOperator,
    SortOrder
)

# 版本信息
__version__ = "1.0.0"
__author__ = "Knight Server Team"

# 导出所有公共接口
__all__ = [
    # 基础服务器
    "BaseServer",
    "BaseServerConfig",
    
    # 基础消息处理器
    "BaseHandler",
    "RequestContext",
    "ResponseContext", 
    "MessageType",
    "HandlerStatistics",
    
    # 基础控制器
    "BaseController",
    "ControllerConfig",
    "ControllerException",
    "ValidationException",
    "AuthorizationException", 
    "BusinessException",
    
    # 基础业务服务
    "BaseService",
    "ServiceConfig",
    "ServiceException",
    "TransactionException",
    "CacheException",
    "ServiceCallException",
    "TransactionContext",
    "transactional",
    "cached",
    "retry",
    "monitored",
    
    # 基础通知服务
    "BaseNotify",
    "NotifyConfig",
    "NotifyMessage",
    "NotifyTarget",
    "NotifyTask",
    "NotifyStatistics",
    "NotifyType",
    "MessagePriority",
    "NotifyStatus",
    
    # 基础数据访问
    "BaseRepository",
    "RepositoryConfig", 
    "QueryBuilder",
    "QueryCondition",
    "SortCondition",
    "PaginationOptions",
    "CacheConfig",
    "QueryOperator",
    "SortOrder",
    
    # 版本信息
    "__version__",
    "__author__"
]
