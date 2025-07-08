"""
gRPC通信模块使用示例

该文件展示了如何使用gRPC通信模块的各种功能，包括：
- 服务端创建和服务注册
- 客户端创建和调用
- 拦截器使用
- 连接池配置
- 负载均衡策略
- 健康检查
"""

import asyncio
import time
from typing import Any

# 导入gRPC模块
from common.grpc import (
    # 服务端
    create_server, grpc_service, ServerConfig,
    
    # 客户端
    create_client, ClientConfig, RetryConfig,
    
    # 连接池
    PoolConfig,
    
    # 负载均衡
    LoadBalancerStrategy, create_balancer,
    
    # 拦截器
    setup_default_interceptors, AuthInterceptor, LoggingInterceptor,
    
    # 健康检查
    create_health_service,
    
    # 异常
    GrpcConnectionError, GrpcTimeoutError
)


# ==================== 模拟服务定义 ====================

class GameServicer:
    """游戏服务实现"""
    
    async def GetPlayerInfo(self, request):
        """获取玩家信息"""
        # 模拟处理
        await asyncio.sleep(0.01)
        return {
            "player_id": request.get("player_id", "12345"),
            "name": "TestPlayer",
            "level": 10,
            "exp": 1500
        }
    
    async def UpdatePlayerLevel(self, request):
        """更新玩家等级"""
        await asyncio.sleep(0.02)
        return {
            "success": True,
            "new_level": request.get("level", 1)
        }


def add_GameServicer_to_server(servicer, server):
    """将游戏服务添加到服务器（模拟函数）"""
    # 在实际使用中，这里会是由protobuf生成的函数
    print(f"Added GameServicer to server: {servicer}")


# ==================== 服务端示例 ====================

async def example_server():
    """服务端使用示例"""
    print("\n=== gRPC服务端示例 ===")
    
    try:
        # 1. 创建服务器配置
        server_config = ServerConfig(
            host="127.0.0.1",
            port=50051,
            max_workers=10,
            enable_health_check=True,
            enable_reflection=True,
            enable_rate_limiting=True,
            max_requests_per_second=1000.0
        )
        
        # 2. 创建服务器
        server = await create_server("game_server", **server_config.__dict__)
        print(f"创建服务器: {server.address}")
        
        # 3. 添加服务
        game_servicer = GameServicer()
        server.add_service(
            service_name="GameService",
            servicer=game_servicer,
            add_to_server_func=add_GameServicer_to_server,
            description="游戏核心服务",
            version="1.0.0"
        )
        
        # 4. 启动服务器
        await server.start()
        print("服务器启动成功")
        
        # 5. 模拟运行一段时间
        print("服务器运行中...")
        await asyncio.sleep(2)
        
        # 6. 获取统计信息
        stats = server.get_stats()
        print(f"服务器统计: {stats}")
        
        # 7. 停止服务器
        await server.stop()
        print("服务器已停止")
        
    except Exception as e:
        print(f"服务端示例失败: {e}")


# ==================== 客户端示例 ====================

async def example_client():
    """客户端使用示例"""
    print("\n=== gRPC客户端示例 ===")
    
    try:
        # 1. 创建重试配置
        retry_config = RetryConfig(
            max_attempts=3,
            initial_backoff=1.0,
            max_backoff=5.0,
            backoff_multiplier=2.0
        )
        
        # 2. 创建客户端配置
        client_config = ClientConfig(
            service_name="GameService",
            default_timeout=30.0,
            retry_config=retry_config,
            enable_retry=True,
            enable_load_balancing=True,
            load_balancer_strategy=LoadBalancerStrategy.ROUND_ROBIN,
            default_metadata={"client_version": "1.0.0"}
        )
        
        # 3. 创建客户端
        endpoints = ["127.0.0.1:50051", "127.0.0.1:50052"]
        client = await create_client(
            service_name="GameService",
            endpoints=endpoints,
            default_timeout=client_config.default_timeout,
            retry_config=client_config.retry_config,
            enable_retry=client_config.enable_retry,
            enable_load_balancing=client_config.enable_load_balancing,
            load_balancer_strategy=client_config.load_balancer_strategy,
            default_metadata=client_config.default_metadata
        )
        print(f"创建客户端，端点: {endpoints}")
        
        # 4. 发起调用
        request = {"player_id": "12345"}
        
        try:
            response = await client.call(
                method="GetPlayerInfo",
                request=request,
                timeout=10.0,
                metadata={"trace_id": "test_trace_123"}
            )
            print(f"调用成功: {response}")
        except GrpcTimeoutError as e:
            print(f"调用超时: {e}")
        except GrpcConnectionError as e:
            print(f"连接错误: {e}")
        
        # 5. 获取客户端统计
        stats = client.get_stats()
        print(f"客户端统计: {stats}")
        
        # 6. 关闭客户端
        await client.close()
        print("客户端已关闭")
        
    except Exception as e:
        print(f"客户端示例失败: {e}")


# ==================== 连接池示例 ====================

async def example_connection_pool():
    """连接池使用示例"""
    print("\n=== 连接池示例 ===")
    
    try:
        # 导入连接池创建函数
        from common.grpc import create_pool
        
        # 1. 创建连接池
        pool = await create_pool(
            name="test_pool",
            target="127.0.0.1",
            port=50051,
            min_size=2,
            max_size=10,
            idle_timeout=300,
            enable_health_check=True
        )
        print(f"创建连接池: {pool.name}")
        
        # 2. 获取连接并使用
        async with pool.get_connection(timeout=5.0) as conn:
            print(f"获取连接: {conn.endpoint}")
            # 模拟使用连接
            await asyncio.sleep(0.1)
        
        # 3. 获取连接池统计
        stats = pool.get_stats_dict()
        print(f"连接池统计: {stats}")
        
        # 4. 关闭连接池
        await pool.close()
        print("连接池已关闭")
        
    except Exception as e:
        print(f"连接池示例失败: {e}")


# ==================== 负载均衡示例 ====================

async def example_load_balancer():
    """负载均衡使用示例"""
    print("\n=== 负载均衡示例 ===")
    
    try:
        # 1. 创建负载均衡器
        nodes = [
            ("127.0.0.1:50051", 100),
            ("127.0.0.1:50052", 200),
            ("127.0.0.1:50053", 150)
        ]
        
        balancer = await create_balancer(
            name="game_balancer",
            strategy=LoadBalancerStrategy.WEIGHTED_ROUND_ROBIN,
            nodes=nodes
        )
        print(f"创建负载均衡器: {balancer.config.strategy.value}")
        
        # 2. 选择节点
        for i in range(5):
            node = await balancer.select_node()
            if node:
                print(f"选择节点 {i+1}: {node.endpoint} (权重: {node.weight})")
                
                # 模拟请求结果
                success = i % 4 != 0  # 模拟偶尔失败
                response_time = 10 + i * 2
                await balancer.record_request_result(
                    node.endpoint, success, response_time
                )
        
        # 3. 获取统计信息
        stats = balancer.get_stats()
        print(f"负载均衡器统计: {stats}")
        
    except Exception as e:
        print(f"负载均衡示例失败: {e}")


# ==================== 拦截器示例 ====================

async def example_interceptors():
    """拦截器使用示例"""
    print("\n=== 拦截器示例 ===")
    
    try:
        # 1. 自定义token验证器
        def custom_token_validator(token: str):
            # 简单验证逻辑
            if token and token.startswith("Bearer valid_"):
                user_id = token.replace("Bearer valid_", "")
                return True, user_id
            return False, None
        
        # 2. 设置拦截器
        setup_default_interceptors(
            enable_auth=True,
            enable_logging=True,
            enable_tracing=True,
            enable_metrics=True,
            enable_exception_handling=True,
            auth={
                'token_validator': custom_token_validator,
                'excluded_methods': ['HealthCheck']
            },
            logging={
                'log_requests': True,
                'log_responses': True,
                'sensitive_fields': ['password', 'token']
            }
        )
        
        print("拦截器配置完成")
        
        # 3. 模拟拦截器工作
        from common.grpc.interceptor import get_default_chain, InterceptorContext
        
        chain = get_default_chain()
        
        async def mock_handler(request):
            await asyncio.sleep(0.01)
            return {"result": "success", "data": request}
        
        # 模拟有效token的请求
        try:
            response, context = await chain.execute(
                method_name="GetPlayerInfo",
                request={"player_id": "12345"},
                handler=mock_handler,
                headers={"authorization": "Bearer valid_user123"},
                metadata={"client_id": "test_client"}
            )
            print(f"拦截器处理成功: {response}")
            print(f"上下文信息: trace_id={context.trace_id}, user_id={context.user_id}")
        except Exception as e:
            print(f"拦截器处理失败: {e}")
        
        # 模拟无效token的请求
        try:
            response, context = await chain.execute(
                method_name="GetPlayerInfo",
                request={"player_id": "12345"},
                handler=mock_handler,
                headers={"authorization": "Bearer invalid_token"},
                metadata={"client_id": "test_client"}
            )
        except Exception as e:
            print(f"认证失败（预期）: {e}")
        
    except Exception as e:
        print(f"拦截器示例失败: {e}")


# ==================== 健康检查示例 ====================

async def example_health_check():
    """健康检查使用示例"""
    print("\n=== 健康检查示例 ===")
    
    try:
        # 1. 创建健康检查服务
        health_service = create_health_service()
        await health_service.start()
        print("健康检查服务启动")
        
        # 2. 注册服务
        services = ["GameService", "PlayerService", "MatchService"]
        for service in services:
            health_service.register_service(service)
            print(f"注册服务: {service}")
        
        # 3. 设置服务状态
        from common.grpc.health_check import HealthStatus
        
        health_service.set_service_status("GameService", HealthStatus.SERVING)
        health_service.set_service_status("PlayerService", HealthStatus.SERVING)
        health_service.set_service_status("MatchService", HealthStatus.NOT_SERVING)
        
        # 4. 获取服务状态
        for service in services:
            status = health_service.get_service_status(service)
            print(f"{service} 状态: {status.value}")
        
        # 5. 获取健康服务列表
        healthy_services = health_service.get_healthy_services()
        unhealthy_services = health_service.get_unhealthy_services()
        
        print(f"健康服务: {healthy_services}")
        print(f"不健康服务: {unhealthy_services}")
        
        # 6. 获取统计摘要
        summary = health_service.get_stats_summary()
        print(f"健康检查统计: {summary}")
        
        # 7. 停止健康检查服务
        await health_service.stop()
        print("健康检查服务已停止")
        
    except Exception as e:
        print(f"健康检查示例失败: {e}")


# ==================== 完整流程示例 ====================

async def example_complete_flow():
    """完整流程示例"""
    print("\n=== 完整流程示例 ===")
    
    try:
        # 1. 启动服务端
        print("1. 启动服务端...")
        server = await create_server(
            "complete_server",
            host="127.0.0.1",
            port=50053,
            enable_health_check=True,
            enable_rate_limiting=True
        )
        
        game_servicer = GameServicer()
        server.add_service(
            "GameService",
            game_servicer,
            add_GameServicer_to_server,
            description="完整示例游戏服务"
        )
        
        await server.start()
        print("服务端启动完成")
        
        # 2. 创建客户端
        print("2. 创建客户端...")
        client = await create_client(
            service_name="GameService",
            endpoints=["127.0.0.1:50053"],
            enable_retry=True,
            default_timeout=5.0
        )
        print("客户端创建完成")
        
        # 3. 发起多个并发请求
        print("3. 发起并发请求...")
        
        async def make_request(i):
            try:
                request = {"player_id": f"player_{i}"}
                response = await client.call("GetPlayerInfo", request)
                return f"请求 {i} 成功: {response}"
            except Exception as e:
                return f"请求 {i} 失败: {e}"
        
        # 并发发起10个请求
        tasks = [make_request(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            print(result)
        
        # 4. 获取统计信息
        print("4. 统计信息:")
        client_stats = client.get_stats()
        server_stats = server.get_stats()
        
        print(f"客户端请求总数: {client_stats['total_requests']}")
        print(f"客户端成功率: {client_stats.get('success_rate', 0):.2%}")
        print(f"服务端请求总数: {server_stats['total_requests']}")
        print(f"服务端成功率: {server_stats.get('success_rate', 0):.2%}")
        
        # 5. 清理资源
        print("5. 清理资源...")
        await client.close()
        await server.stop()
        print("完整流程示例完成")
        
    except Exception as e:
        print(f"完整流程示例失败: {e}")


# ==================== 主函数 ====================

async def main():
    """主函数，运行所有示例"""
    print("gRPC通信模块使用示例")
    print("=" * 50)
    
    # 运行各个示例
    await example_health_check()
    await example_interceptors()
    await example_connection_pool()
    await example_load_balancer()
    await example_server()
    await example_client()
    await example_complete_flow()
    
    print("\n所有示例执行完成!")


if __name__ == "__main__":
    # 运行示例
    asyncio.run(main())