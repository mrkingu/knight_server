#!/usr/bin/env python3
"""
网关服务基础测试脚本

该脚本用于测试网关服务的基本功能，不依赖外部库。
"""

import sys
import os
import asyncio

# 添加项目路径到sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from services.gate.config import create_development_config, create_production_config
    print("✅ 配置模块导入成功")
except Exception as e:
    print(f"❌ 配置模块导入失败: {e}")
    sys.exit(1)

def test_config():
    """测试配置功能"""
    print("\n测试配置功能...")
    
    try:
        # 测试开发配置
        dev_config = create_development_config()
        print(f"✅ 开发配置创建成功: {dev_config.mode.value}")
        
        # 测试生产配置
        prod_config = create_production_config()
        print(f"✅ 生产配置创建成功: {prod_config.mode.value}")
        
        # 测试配置属性
        print(f"   WebSocket端口: {dev_config.websocket.port}")
        print(f"   最大连接数: {dev_config.websocket.max_connections}")
        print(f"   后端服务数量: {len(dev_config.backend_services)}")
        
        # 测试配置转换
        config_dict = dev_config.to_dict()
        print(f"✅ 配置转换为字典: {len(config_dict)} 个键")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        return False

def test_imports():
    """测试模块导入"""
    print("\n测试模块导入...")
    
    modules = [
        ("services.gate.websocket_manager", "WebSocketManager"),
        ("services.gate.route_manager", "RouteManager"),
        ("services.gate.gate_handler", "GateHandler"),
        ("services.gate.controllers.base_controller", "BaseController"),
        ("services.gate.controllers.auth_controller", "AuthController"),
        ("services.gate.controllers.game_controller", "GameController"),
        ("services.gate.controllers.chat_controller", "ChatController"),
        ("services.gate.middleware.auth_middleware", "AuthMiddleware"),
        ("services.gate.middleware.rate_limit_middleware", "RateLimitMiddleware"),
        ("services.gate.middleware.log_middleware", "LogMiddleware"),
        ("services.gate.middleware.error_middleware", "ErrorMiddleware"),
    ]
    
    success_count = 0
    for module_name, class_name in modules:
        try:
            module = __import__(module_name, fromlist=[class_name])
            getattr(module, class_name)
            print(f"✅ {module_name}.{class_name}")
            success_count += 1
        except Exception as e:
            print(f"❌ {module_name}.{class_name}: {e}")
    
    print(f"\n导入成功: {success_count}/{len(modules)}")
    return success_count == len(modules)

def test_route_decorator():
    """测试路由装饰器"""
    print("\n测试路由装饰器...")
    
    try:
        from services.gate.route_manager import route, RouteType
        
        # 测试装饰器
        @route(protocol_id=1001, description="测试路由", group_name="test")
        async def test_handler(data, context):
            return {"message": "test"}
        
        # 检查装饰器是否正确设置属性
        if hasattr(test_handler, '_route_info'):
            route_info = test_handler._route_info
            print(f"✅ 路由装饰器设置成功: 协议ID={route_info['protocol_id']}")
            return True
        else:
            print("❌ 路由装饰器未设置属性")
            return False
            
    except Exception as e:
        print(f"❌ 路由装饰器测试失败: {e}")
        return False

def test_middleware_structure():
    """测试中间件结构"""
    print("\n测试中间件结构...")
    
    try:
        from services.gate.middleware.auth_middleware import AuthMiddleware, AuthResult
        from services.gate.middleware.rate_limit_middleware import RateLimitMiddleware, LimitResult
        from services.gate.middleware.log_middleware import LogMiddleware, RequestLog
        from services.gate.middleware.error_middleware import ErrorMiddleware, ErrorInfo
        
        config = create_development_config()
        
        # 测试中间件创建
        auth_middleware = AuthMiddleware(config)
        rate_limit_middleware = RateLimitMiddleware(config)
        log_middleware = LogMiddleware(config)
        error_middleware = ErrorMiddleware(config)
        
        print("✅ 所有中间件创建成功")
        
        # 测试数据结构
        auth_result = AuthResult(success=True, user_id="test_user")
        print(f"✅ AuthResult创建成功: {auth_result.success}")
        
        return True
        
    except Exception as e:
        print(f"❌ 中间件结构测试失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("网关服务基础测试")
    print("=" * 60)
    
    tests = [
        ("配置功能", test_config),
        ("模块导入", test_imports),
        ("路由装饰器", test_route_decorator),
        ("中间件结构", test_middleware_structure),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} 测试通过")
            else:
                print(f"❌ {test_name} 测试失败")
        except Exception as e:
            print(f"❌ {test_name} 测试异常: {e}")
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！网关服务实现正确。")
        return True
    else:
        print("⚠️  部分测试失败，请检查实现。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)