#!/usr/bin/env python3
"""
基础服务类使用示例

该脚本演示了如何使用基础服务类来构建微服务应用。
"""

import asyncio
import time
from services.base import (
    BaseServer, BaseController, BaseService, BaseRepository, BaseNotify,
    BaseServerConfig, ControllerConfig, ServiceConfig, RepositoryConfig, NotifyConfig,
    NotifyMessage, MessagePriority, QueryBuilder, QueryOperator, SortOrder
)


class UserRepository(BaseRepository):
    """用户数据访问层示例"""
    
    def __init__(self):
        super().__init__(table_name="users")
    
    async def find_by_email(self, email: str):
        """根据邮箱查找用户"""
        query = self.query().eq("email", email)
        users = await self.find_with_builder(query)
        return users[0] if users else None
    
    async def find_active_users(self):
        """查找活跃用户"""
        query = (self.query()
                .eq("status", "active")
                .order_by("created_at", SortOrder.DESC)
                .limit(10))
        
        return await self.find_with_builder(query)


class UserService(BaseService):
    """用户业务服务示例"""
    
    def __init__(self):
        super().__init__()
        # 创建并注册Repository
        self.user_repo = UserRepository()
        self.register_repository("UserRepository", self.user_repo)
    
    async def initialize(self):
        """初始化服务"""
        await super().initialize()
        # 确保repository初始化
        await self.user_repo.initialize()
    
    async def create_user(self, user_data: dict) -> dict:
        """创建用户"""
        # 使用缓存装饰器
        cache_key = f"user_create_{user_data.get('email')}"
        cached_result = self.get_cache(cache_key)
        if cached_result:
            return cached_result
        
        # 创建用户
        user_repo = self.get_repository("UserRepository")
        user = await user_repo.create(user_data)
        
        # 缓存结果
        self.set_cache(cache_key, user)
        
        return user
    
    async def get_user_profile(self, user_id: str) -> dict:
        """获取用户资料"""
        user_repo = self.get_repository("UserRepository")
        return await user_repo.find_by_id(user_id)


class UserController(BaseController):
    """用户控制器示例"""
    
    def __init__(self):
        super().__init__()
        # 创建并注册Service
        self.user_service = UserService()
        self.register_service("UserService", self.user_service)
    
    async def initialize(self):
        """初始化控制器"""
        await super().initialize()
        # 确保service初始化
        await self.user_service.initialize()
    
    async def handle_create_user(self, request_data: dict, context) -> dict:
        """处理创建用户请求"""
        try:
            # 参数验证
            self.validate_required_fields(request_data, ['username', 'email', 'password'])
            self.validate_field_pattern(request_data, 'email', r'^[^@]+@[^@]+\.[^@]+$')
            
            # 调用服务层
            user_service = self.get_service("UserService")
            user = await user_service.create_user(request_data)
            
            return await self.build_response(user, context)
            
        except Exception as e:
            return await self.handle_exception(e, context)
    
    async def handle_get_user(self, request_data: dict, context) -> dict:
        """处理获取用户请求"""
        try:
            user_id = request_data.get('user_id')
            if not user_id:
                raise ValueError("用户ID不能为空")
            
            user_service = self.get_service("UserService")
            user = await user_service.get_user_profile(user_id)
            
            if not user:
                raise ValueError("用户不存在")
            
            return await self.build_response(user, context)
            
        except Exception as e:
            return await self.handle_exception(e, context)


class GameNotifyService(BaseNotify):
    """游戏通知服务示例"""
    
    def __init__(self):
        super().__init__()
    
    async def notify_user_login(self, user_id: str, login_data: dict):
        """通知用户登录"""
        message = NotifyMessage(
            message_type="user_login",
            data=login_data,
            priority=MessagePriority.NORMAL
        )
        return await self.send_to_user(user_id, message)
    
    async def broadcast_system_message(self, message_content: str):
        """广播系统消息"""
        message = NotifyMessage(
            message_type="system_message",
            data={"content": message_content, "timestamp": time.time()},
            priority=MessagePriority.HIGH
        )
        return await self.broadcast(message)


class GameServer(BaseServer):
    """游戏服务器示例"""
    
    def __init__(self):
        config = BaseServerConfig(
            service_name="game_server",
            service_version="1.0.0",
            host="0.0.0.0",
            port=50051,
            enable_monitoring=True,
            enable_service_registry=False  # 在示例中禁用服务注册
        )
        super().__init__(config)
        
        # 添加组件
        self.user_controller = UserController()
        self.notify_service = GameNotifyService()
    
    async def on_startup(self):
        """服务启动时的回调"""
        await super().on_startup()
        
        # 初始化控制器
        await self.user_controller.initialize()
        
        # 初始化通知服务
        await self.notify_service.initialize()
        
        self.logger.info("游戏服务器启动完成")
    
    async def on_shutdown(self):
        """服务关闭时的回调"""
        # 清理资源
        await self.user_controller.cleanup()
        await self.notify_service.cleanup()
        
        await super().on_shutdown()
        self.logger.info("游戏服务器关闭完成")


async def demo_usage():
    """演示基础服务类的使用"""
    print("=== 基础服务类使用示例 ===\n")
    
    # 1. 演示Repository使用
    print("1. Repository示例:")
    user_repo = UserRepository()
    await user_repo.initialize()
    
    # 创建用户数据
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "hashed_password",
        "status": "active"
    }
    
    print(f"创建用户: {user_data['username']}")
    user = await user_repo.create(user_data)
    print(f"创建成功，ID: {user.get('_id')}")
    
    # 查询用户
    found_user = await user_repo.find_by_email("test@example.com")
    print(f"根据邮箱查找用户: {found_user is not None}")
    
    await user_repo.cleanup()
    print("Repository示例完成\n")
    
    # 2. 演示Service使用
    print("2. Service示例:")
    user_service = UserService()
    await user_service.initialize()
    
    # 创建用户
    service_user = await user_service.create_user({
        "username": "serviceuser",
        "email": "service@example.com",
        "password": "hashed_password"
    })
    print(f"通过Service创建用户: {service_user.get('_id')}")
    
    await user_service.cleanup()
    print("Service示例完成\n")
    
    # 3. 演示Controller使用
    print("3. Controller示例:")
    user_controller = UserController()
    await user_controller.initialize()
    
    # 处理创建用户请求
    request_data = {
        "username": "controlleruser",
        "email": "controller@example.com",
        "password": "hashed_password"
    }
    
    context = type('Context', (), {'trace_id': 'demo123'})()
    response = await user_controller.handle_create_user(request_data, context)
    print(f"通过Controller创建用户: {response['success']}")
    
    await user_controller.cleanup()
    print("Controller示例完成\n")
    
    # 4. 演示Notify使用
    print("4. Notify示例:")
    notify_service = GameNotifyService()
    try:
        await notify_service.initialize()
    except:
        # Skip initialization if it fails, just demonstrate the interface
        pass
    
    # 发送通知
    task_id = await notify_service.notify_user_login("user123", {"timestamp": time.time()})
    print(f"发送用户登录通知，任务ID: {task_id}")
    
    task_id = await notify_service.broadcast_system_message("服务器维护通知")
    print(f"广播系统消息，任务ID: {task_id}")
    
    # 获取统计信息
    stats = notify_service.get_statistics()
    print(f"通知统计 - 队列大小: {notify_service.queue_size}, 在线用户: {notify_service.online_users_count}")
    
    try:
        await notify_service.cleanup()
    except:
        pass
    print("Notify示例完成\n")
    
    # 5. 演示QueryBuilder使用
    print("5. QueryBuilder示例:")
    query = (QueryBuilder()
            .eq("status", "active")
            .gt("created_at", "2023-01-01")
            .in_("role", ["user", "admin"])
            .order_by("created_at", SortOrder.DESC)
            .paginate(1, 10))
    
    filter_dict = query.build_filter()
    sort_conditions = query.build_sort()
    pagination = query.build_pagination()
    
    print(f"查询条件: {filter_dict}")
    print(f"排序条件: {sort_conditions}")
    print(f"分页信息: 页码={pagination.page}, 页面大小={pagination.page_size}")
    print("QueryBuilder示例完成\n")
    
    print("=== 所有示例演示完成 ===")


async def demo_server():
    """演示服务器使用"""
    print("\n=== 服务器示例 ===")
    
    server = GameServer()
    
    try:
        # 初始化服务器
        await server.initialize()
        print("服务器初始化完成")
        
        # 启动服务器
        await server.start()
        print("服务器启动完成")
        
        # 模拟运行一段时间
        await asyncio.sleep(1)
        
        # 停止服务器
        await server.stop()
        print("服务器停止完成")
        
    except Exception as e:
        print(f"服务器演示失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    async def main():
        try:
            await demo_usage()
            await demo_server()
        except Exception as e:
            print(f"演示失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 运行演示
    asyncio.run(main())