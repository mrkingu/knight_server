#!/usr/bin/env python3
"""
网关服务测试脚本

该脚本用于测试网关服务的基本功能，包括配置加载、服务初始化等。
"""

import asyncio
import sys
import os

# 添加项目路径到sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gate.config import create_development_config
from services.gate.websocket_manager import create_websocket_manager
from services.gate.session_manager import create_session_manager
from services.gate.route_manager import create_route_manager
from services.gate.gate_handler import create_gate_handler
from services.gate.services.auth_service import AuthService
from services.gate.services.route_service import RouteService
from services.gate.services.notify_service import NotifyService
from services.gate.services.proxy_service import ProxyService
from services.gate.middleware.auth_middleware import AuthMiddleware
from services.gate.middleware.rate_limit_middleware import RateLimitMiddleware
from services.gate.middleware.log_middleware import LogMiddleware
from services.gate.middleware.error_middleware import ErrorMiddleware


async def test_gateway_services():
    """测试网关服务"""
    print("开始测试网关服务...")
    
    try:
        # 1. 测试配置加载
        print("1. 测试配置加载...")
        config = create_development_config()
        print(f"   配置模式: {config.mode.value}")
        print(f"   WebSocket端口: {config.websocket.port}")
        print(f"   后端服务数量: {len(config.backend_services)}")
        
        # 2. 测试管理器创建
        print("2. 测试管理器创建...")
        websocket_manager = create_websocket_manager(config)
        session_manager = create_session_manager(config)
        route_manager = create_route_manager(config)
        gate_handler = create_gate_handler(config)
        
        # 3. 测试服务创建
        print("3. 测试服务创建...")
        auth_service = AuthService(config)
        route_service = RouteService(config)
        notify_service = NotifyService(config)
        proxy_service = ProxyService(config)
        
        # 4. 测试中间件创建
        print("4. 测试中间件创建...")
        auth_middleware = AuthMiddleware(config)
        rate_limit_middleware = RateLimitMiddleware(config)
        log_middleware = LogMiddleware(config)
        error_middleware = ErrorMiddleware(config)
        
        # 5. 测试初始化
        print("5. 测试初始化...")
        await session_manager.initialize()
        await route_manager.initialize()
        await gate_handler.initialize()
        await auth_service.initialize()
        await route_service.initialize()
        await notify_service.initialize()
        await proxy_service.initialize()
        
        # 6. 测试统计信息
        print("6. 测试统计信息...")
        ws_stats = websocket_manager.get_statistics()
        session_stats = session_manager.get_statistics()
        route_stats = route_manager.get_statistics()
        handler_stats = gate_handler.get_statistics()
        
        print(f"   WebSocket连接数: {ws_stats['current_connections']}")
        print(f"   活跃会话数: {session_stats['active_sessions']}")
        print(f"   路由数量: {route_stats['total_routes']}")
        print(f"   处理器统计: {handler_stats}")
        
        # 7. 测试认证服务
        print("7. 测试认证服务...")
        user_info = await auth_service.authenticate_user("admin", "admin123")
        if user_info:
            print(f"   认证成功: {user_info['username']}")
        else:
            print("   认证失败")
            
        # 8. 测试中间件统计
        print("8. 测试中间件统计...")
        auth_stats = auth_middleware.get_statistics()
        rate_limit_stats = rate_limit_middleware.get_statistics()
        log_stats = log_middleware.get_statistics()
        error_stats = error_middleware.get_error_statistics()
        
        print(f"   认证中间件: {auth_stats['auth_enabled']}")
        print(f"   限流中间件: {rate_limit_stats['enabled']}")
        print(f"   日志中间件: {log_stats['log_level']}")
        print(f"   错误中间件: {error_stats['error_handlers']}")
        
        print("网关服务测试完成！")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    print("=" * 50)
    print("网关服务测试")
    print("=" * 50)
    
    success = await test_gateway_services()
    
    if success:
        print("\n✅ 所有测试通过！")
        sys.exit(0)
    else:
        print("\n❌ 测试失败！")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())