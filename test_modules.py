#!/usr/bin/env python3
"""
测试通知和装饰器模块的基本功能
"""

import asyncio
import time
from dataclasses import dataclass

# 测试通知模块
from common.notify import get_notify_manager, MessagePriority

# 测试装饰器模块
from common.decorator import (
    grpc_service, grpc_method, GrpcServiceType,
    proto_message, request_proto, response_proto, ProtoType,
    handler, controller, route, HandlerType,
    periodic_task, delay_task, retry_task,
    require_auth, rate_limit, PermissionLevel
)


# 测试协议定义
@request_proto(message_id=1001)
@dataclass
class LoginRequest:
    username: str
    password: str


@response_proto(message_id=1002)
@dataclass
class LoginResponse:
    success: bool
    token: str = ""
    message: str = ""


# 测试gRPC服务
@grpc_service(name="TestService", port=50051)
class TestService:
    @grpc_method(service_type=GrpcServiceType.UNARY)
    async def test_method(self, request):
        return {"result": "success"}


# 测试控制器
@controller(name="TestController")
class TestController:
    @route(route_key=1001)
    @handler(request_proto=LoginRequest, response_proto=LoginResponse)
    @require_auth(user_id_param="user_id")
    @rate_limit(max_calls=5, period=60)
    async def handle_login(self, request: LoginRequest, user_id: str = None, _current_user=None) -> LoginResponse:
        print(f"处理登录请求: {request.username}")
        return LoginResponse(success=True, token="test_token", message="登录成功")


# 测试Celery任务
@periodic_task(cron="0 0 * * *")
async def daily_reset():
    print("执行每日重置任务")
    return "daily_reset_completed"


@delay_task(countdown=5)
async def delayed_task(message: str):
    print(f"延时任务执行: {message}")
    return f"processed: {message}"


@retry_task(max_retries=3, retry_delay=1.0)
async def unreliable_task():
    import random
    if random.random() < 0.7:  # 70%失败率
        raise Exception("模拟任务失败")
    print("任务执行成功")
    return "success"


async def test_notification_system():
    """测试通知系统"""
    print("\n=== 测试通知系统 ===")
    
    # 获取通知管理器
    notify_manager = await get_notify_manager()
    
    # 模拟添加用户连接
    class MockWebSocket:
        async def send(self, data):
            print(f"WebSocket发送: {data}")
        
        async def close(self):
            print("WebSocket连接关闭")
    
    # 添加用户连接
    websocket = MockWebSocket()
    await notify_manager.add_connection("user123", "conn1", websocket)
    
    # 推送消息给单个用户
    message = {"type": "notification", "content": "欢迎登录"}
    await notify_manager.push_to_user("user123", message, MessagePriority.HIGH)
    
    # 等待消息处理
    await asyncio.sleep(0.1)
    
    # 获取统计信息
    stats = await notify_manager.get_statistics()
    print(f"通知统计: 连接数={stats.connections_count}, 发送数={stats.total_sent}")


async def test_decorators():
    """测试装饰器功能"""
    print("\n=== 测试装饰器功能 ===")
    
    # 测试协议序列化
    login_req = LoginRequest(username="test_user", password="test_pass")
    serialized = login_req.serialize()
    print(f"协议序列化: {len(serialized)} bytes")
    
    # 测试控制器
    controller = TestController()
    
    # 这里我们模拟一个简单的调用，实际使用中会有更复杂的参数处理
    try:
        # 模拟认证用户
        from common.decorator.auth_decorator import authenticate_user
        await authenticate_user("user123", "test_user", permissions=["login"])
        
        response = await controller.handle_login(login_req, user_id="user123")
        print(f"控制器响应: {response}")
    except Exception as e:
        print(f"控制器调用失败: {e}")
    
    # 测试定时任务
    result = await daily_reset()
    print(f"定时任务结果: {result}")
    
    # 测试延时任务
    task_id, task = await delayed_task.apply_async(args=["test message"])
    print(f"延时任务ID: {task_id}")
    
    # 测试重试任务
    try:
        result = await unreliable_task()
        print(f"重试任务结果: {result}")
    except Exception as e:
        print(f"重试任务最终失败: {e}")


async def test_integration():
    """集成测试"""
    print("\n=== 集成测试 ===")
    
    # 启动认证管理器
    from common.decorator import get_auth_manager
    auth_manager = get_auth_manager()
    await auth_manager.start()
    
    # 测试通知和认证的集成
    notify_manager = await get_notify_manager()
    
    # 认证用户
    from common.decorator.auth_decorator import authenticate_user
    user = await authenticate_user("user456", "integration_user", 
                                  permissions=["notification.receive"],
                                  session_id="session123")
    print(f"用户认证成功: {user.username}")
    
    # 发送通知
    await notify_manager.push_to_user("user456", {
        "type": "system",
        "message": "集成测试通知"
    })
    
    print("集成测试完成")
    
    # 停止服务
    await auth_manager.stop()


async def main():
    """主测试函数"""
    print("开始测试通知和装饰器模块...")
    
    try:
        await test_notification_system()
        await test_decorators()
        await test_integration()
        
        print("\n✅ 所有测试完成！")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())