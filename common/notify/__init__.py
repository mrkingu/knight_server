"""
common/notify 模块

该模块提供了高性能的通知推送服务，支持向客户端主动推送消息。
主要功能包括：
- 用户连接管理
- 消息推送服务
- 消息队列缓冲
- 协议自动转换
- 批量推送优化

使用示例：
```python
from common.notify import get_notify_manager, MessagePriority

# 获取通知管理器
notify_manager = await get_notify_manager()

# 推送给单个用户
await notify_manager.push_to_user(
    user_id="user123", 
    message={"type": "reward", "data": {"coins": 100}},
    priority=MessagePriority.HIGH
)

# 推送给多个用户
await notify_manager.push_to_users(
    user_ids=["user1", "user2"], 
    message={"type": "broadcast", "content": "服务器维护通知"}
)

# 全服广播
await notify_manager.broadcast(
    message={"type": "system", "content": "系统更新完成"}
)
```
"""

# 导入核心类
from .notify_manager import (
    NotifyManager, 
    UserConnection, 
    ConnectionStatus,
    NotifyStatistics,
    get_notify_manager,
    initialize_notify_manager
)

from .push_service import (
    PushService,
    PushResult,
    PushStatistics,
    MessageType,
    create_push_service
)

from .notify_queue import (
    NotifyQueue,
    MessageItem,
    MessagePriority,
    QueueStatistics,
    create_notify_queue
)

from .protocol_adapter import (
    ProtocolAdapter,
    ProtocolConfig,
    MessageFormat,
    CompressionType,
    ConversionResult,
    create_protocol_adapter
)

# 版本信息
__version__ = "1.0.0"
__author__ = "Knight Server Team"

# 模块级别的公共接口
__all__ = [
    # 通知管理器
    "NotifyManager",
    "UserConnection", 
    "ConnectionStatus",
    "NotifyStatistics",
    "get_notify_manager",
    "initialize_notify_manager",
    
    # 推送服务
    "PushService",
    "PushResult",
    "PushStatistics", 
    "MessageType",
    "create_push_service",
    
    # 通知队列
    "NotifyQueue",
    "MessageItem",
    "MessagePriority",
    "QueueStatistics",
    "create_notify_queue",
    
    # 协议适配器
    "ProtocolAdapter",
    "ProtocolConfig",
    "MessageFormat",
    "CompressionType",
    "ConversionResult",
    "create_protocol_adapter",
    
    # 版本信息
    "__version__",
    "__author__"
]
