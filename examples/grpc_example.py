"""
gRPC通信模块使用示例

展示如何使用knight_server的gRPC通信模块。
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

from common.grpc import (
    # 客户端
    create_simple_client,
    create_discovery_client,
    GrpcClient,
    ClientConfig,
    RetryConfig,
    
    # 服务端
    create_simple_server,
    create_secure_server,
    GrpcServer,
    ServerConfig,
    RateLimitConfig,
    setup_signal_handlers,
    
    # 连接池
    GrpcConnectionPool,
    PoolConfig,
    ConnectionConfig,
    
    # 负载均衡
    LoadBalanceStrategy,
    LoadBalancerFactory,
    ServerNode,
    
    # 拦截器
    create_default_client_interceptors,
    create_default_server_interceptors,
    create_auth_interceptors,
    
    # 健康检查
    create_default_health_service,
    HealthCheckService,
    
    # 配置
    get_grpc_config,
    update_grpc_config,
    
    # 异常
    GrpcException,
    GrpcConnectionError,
    GrpcTimeoutError
)


async def example_simple_client():
    """简单客户端示例"""
    print("\n=== 简单客户端示例 ===")
    
    # 创建简单客户端
    client = create_simple_client(
        service_addresses=["localhost:50051", "localhost:50052"],
        service_name="user_service",
        timeout=30.0,
        max_retries=3,
        load_balance_strategy=LoadBalanceStrategy.ROUND_ROBIN
    )
    
    print(f"创建客户端: {client.config.service_name}")
    print(f"服务地址: {client.config.service_addresses}")
    print(f"负载均衡策略: {client.config.load_balance_strategy.value}")
    
    # 模拟使用客户端（实际使用时需要真实的gRPC服务）
    try:
        async with client:
            # 这里应该是实际的gRPC调用
            # response = await client.call("GetUser", request)
            print("客户端初始化成功")
            
            # 获取统计信息
            stats = client.get_stats()
            print(f"客户端统计: {stats}")
            
    except Exception as e:
        print(f"客户端示例执行失败: {e}")


async def example_connection_pool():
    """连接池示例"""
    print("\n=== 连接池示例 ===")
    
    # 配置连接池
    connection_config = ConnectionConfig(
        host="localhost",
        port=50051,
        connect_timeout=10.0,
        request_timeout=30.0
    )
    
    pool_config = PoolConfig(
        connection_config=connection_config,
        min_connections=2,
        max_connections=10,
        acquire_timeout=5.0
    )
    
    # 创建连接池
    pool = GrpcConnectionPool(pool_config, "example_pool")
    
    try:
        await pool.initialize()
        print(f"连接池初始化成功: {pool.pool_id}")
        
        # 获取连接池统计
        stats = pool.get_stats()
        print(f"连接池统计: {stats}")
        
        # 模拟获取连接
        print("模拟连接池使用...")
        # async with pool.get_connection() as connection:
        #     async with connection.get_channel() as channel:
        #         # 使用channel进行gRPC调用
        #         pass
        
    except Exception as e:
        print(f"连接池示例执行失败: {e}")
    finally:
        await pool.close()


async def example_load_balancer():
    """负载均衡示例"""
    print("\n=== 负载均衡示例 ===")
    
    # 创建服务器节点
    servers = [
        ServerNode(address="localhost", port=50051, weight=1),
        ServerNode(address="localhost", port=50052, weight=2),
        ServerNode(address="localhost", port=50053, weight=3),
    ]
    
    # 测试不同的负载均衡策略
    strategies = [
        LoadBalanceStrategy.ROUND_ROBIN,
        LoadBalanceStrategy.RANDOM,
        LoadBalanceStrategy.WEIGHTED_RANDOM,
        LoadBalanceStrategy.LEAST_CONNECTIONS,
    ]
    
    for strategy in strategies:
        print(f"\n测试负载均衡策略: {strategy.value}")
        
        # 创建负载均衡器
        balancer = LoadBalancerFactory.create(strategy, servers)
        
        try:
            # 模拟选择服务器
            for i in range(5):
                server = await balancer.select_server()
                print(f"  选择服务器 {i+1}: {server.endpoint} (权重: {server.weight})")
                
                # 模拟请求完成
                balancer.record_request(server.endpoint, True, 0.1)
                
        except Exception as e:
            print(f"  负载均衡测试失败: {e}")
        finally:
            await balancer.stop_health_monitoring()


async def example_health_check():
    """健康检查示例"""
    print("\n=== 健康检查示例 ===")
    
    # 创建健康检查服务
    health_service = create_default_health_service()
    
    try:
        await health_service.start()
        print("健康检查服务启动成功")
        
        # 设置服务状态
        await health_service.set_service_status("user_service", "SERVING", "用户服务正常")
        await health_service.set_service_status("order_service", "NOT_SERVING", "订单服务维护中")
        
        # 检查服务健康状态
        user_health = await health_service.check_health("user_service")
        order_health = await health_service.check_health("order_service")
        
        print(f"用户服务健康状态: {user_health.to_dict()}")
        print(f"订单服务健康状态: {order_health.to_dict()}")
        
        # 获取所有服务状态
        all_status = await health_service.get_all_service_status()
        print(f"所有服务状态: {len(all_status)} 个服务")
        
        # 获取健康检查统计
        stats = health_service.get_stats()
        print(f"健康检查统计: {stats}")
        
    except Exception as e:
        print(f"健康检查示例执行失败: {e}")
    finally:
        await health_service.stop()


async def example_server():
    """服务器示例"""
    print("\n=== 服务器示例 ===")
    
    # 创建限流配置
    rate_limit_config = RateLimitConfig(
        enable=True,
        max_requests_per_second=100.0,
        max_concurrent_requests=50
    )
    
    # 创建服务器配置
    server_config = ServerConfig(
        host="0.0.0.0",
        port=50051,
        max_workers=10,
        rate_limit_config=rate_limit_config,
        enable_health_check=True,
        enable_metrics=True,
        service_name="example_service"
    )
    
    # 创建服务器
    server = GrpcServer(server_config)
    
    try:
        await server.initialize()
        print(f"服务器初始化成功: {server.config.host}:{server.config.port}")
        
        # 这里应该添加实际的gRPC服务
        # server.add_service(UserServiceImpl(), add_UserServiceServicer_to_server)
        
        # 获取服务器统计
        stats = server.get_stats()
        print(f"服务器统计: {stats}")
        
        print("服务器已准备就绪（实际部署时会在这里启动并等待请求）")
        
    except Exception as e:
        print(f"服务器示例执行失败: {e}")
    finally:
        await server.stop()


async def example_config():
    """配置示例"""
    print("\n=== 配置示例 ===")
    
    # 获取全局配置
    config = get_grpc_config()
    print(f"默认连接超时: {config.default_connection.connect_timeout}秒")
    print(f"默认池大小: {config.default_pool.min_connections}-{config.default_pool.max_connections}")
    print(f"监控启用: {config.metrics_enabled}")
    
    # 更新配置
    update_grpc_config({
        "connection": {
            "connect_timeout": 15.0,
            "request_timeout": 45.0
        },
        "pool": {
            "min_connections": 5,
            "max_connections": 30
        },
        "metrics_enabled": True,
        "log_grpc_calls": True
    })
    
    # 获取更新后的配置
    updated_config = get_grpc_config()
    print(f"更新后连接超时: {updated_config.default_connection.connect_timeout}秒")
    print(f"更新后池大小: {updated_config.default_pool.min_connections}-{updated_config.default_pool.max_connections}")


async def example_interceptors():
    """拦截器示例"""
    print("\n=== 拦截器示例 ===")
    
    # 创建默认拦截器
    client_interceptors = create_default_client_interceptors()
    server_interceptors = create_default_server_interceptors()
    
    print(f"客户端拦截器数量: {len(client_interceptors)}")
    print(f"服务端拦截器数量: {len(server_interceptors)}")
    
    for interceptor in client_interceptors:
        print(f"  客户端拦截器: {interceptor.name}")
    
    for interceptor in server_interceptors:
        print(f"  服务端拦截器: {interceptor.name}")
    
    # 创建认证拦截器
    auth_interceptors = create_auth_interceptors(
        jwt_secret="my_secret_key",
        required_permissions=["read", "write"]
    )
    
    print(f"认证拦截器数量: {len(auth_interceptors)}")
    for interceptor in auth_interceptors:
        print(f"  认证拦截器: {interceptor.name}")


async def main():
    """主函数"""
    print("gRPC通信模块使用示例")
    print("=" * 50)
    
    try:
        # 运行各种示例
        await example_config()
        await example_simple_client()
        await example_connection_pool()
        await example_load_balancer()
        await example_health_check()
        await example_interceptors()
        await example_server()
        
    except Exception as e:
        print(f"示例执行失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n示例执行完成!")


if __name__ == "__main__":
    # 运行示例
    asyncio.run(main())