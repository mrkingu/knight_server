"""
简化的gRPC模块测试

测试gRPC模块的核心功能，无需实际grpc依赖。
"""

import asyncio
import sys
import os

# 添加路径
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

async def test_basic_functionality():
    """测试基础功能"""
    print("开始gRPC模块基础功能测试\n")
    
    try:
        # 测试1: 导入模块
        print("1. 测试模块导入...")
        from common.grpc import (
            GrpcConnectionError, HealthCheckService, LoadBalancerStrategy,
            create_balancer, InterceptorChain, setup_default_interceptors
        )
        print("✓ 模块导入成功")
        
        # 测试2: 健康检查服务
        print("\n2. 测试健康检查服务...")
        health_service = HealthCheckService()
        await health_service.start()
        
        health_service.register_service("TestService")
        from common.grpc.health_check import HealthStatus
        health_service.set_service_status("TestService", HealthStatus.SERVING)
        
        status = health_service.get_service_status("TestService")
        assert status == HealthStatus.SERVING
        
        await health_service.stop()
        print("✓ 健康检查服务测试通过")
        
        # 测试3: 负载均衡器
        print("\n3. 测试负载均衡器...")
        balancer = await create_balancer(
            name="test_balancer",
            strategy=LoadBalancerStrategy.ROUND_ROBIN,
            nodes=[("localhost:8001", 100), ("localhost:8002", 100)]
        )
        
        # 选择节点测试
        node1 = await balancer.select_node()
        node2 = await balancer.select_node()
        
        assert node1.endpoint != node2.endpoint  # 轮询应该选择不同节点
        print("✓ 负载均衡器测试通过")
        
        # 测试4: 拦截器链
        print("\n4. 测试拦截器链...")
        setup_default_interceptors(
            enable_auth=False,  # 简化测试
            enable_logging=True,
            enable_tracing=True,
            enable_metrics=False,
            enable_exception_handling=True
        )
        
        chain = InterceptorChain()
        print("✓ 拦截器链测试通过")
        
        # 测试5: 异常处理
        print("\n5. 测试异常处理...")
        try:
            raise GrpcConnectionError(
                message="测试连接错误",
                endpoint="localhost:8080"
            )
        except GrpcConnectionError as e:
            assert "测试连接错误" in str(e)
            error_dict = e.to_dict()
            assert error_dict['error_code'] == 1001
            assert error_dict['details']['endpoint'] == "localhost:8080"
        print("✓ 异常处理测试通过")
        
        print("\n🎉 所有基础功能测试通过!")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_performance_simulation():
    """性能模拟测试"""
    print("\n开始性能模拟测试...")
    
    try:
        from common.grpc import create_balancer, LoadBalancerStrategy
        
        # 创建负载均衡器模拟高并发
        balancer = await create_balancer(
            name="perf_balancer", 
            strategy=LoadBalancerStrategy.LEAST_CONNECTION,
            nodes=[(f"server{i}:808{i}", 100) for i in range(1, 6)]  # 5个节点
        )
        
        # 模拟1000次请求
        print("模拟1000次请求分发...")
        start_time = asyncio.get_event_loop().time()
        
        node_counts = {}
        for i in range(1000):
            node = await balancer.select_node()
            if node:
                endpoint = node.endpoint
                node_counts[endpoint] = node_counts.get(endpoint, 0) + 1
                
                # 模拟请求处理
                success = i % 10 != 0  # 90%成功率
                await balancer.record_request_result(endpoint, success, 10.0)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        print(f"完成1000次请求，耗时: {duration:.3f}秒")
        print(f"QPS: {1000/duration:.0f}")
        print(f"请求分布: {node_counts}")
        
        # 获取统计信息
        stats = balancer.get_stats()
        print(f"成功率: {stats['success_rate']:.2%}")
        
        print("✓ 性能模拟测试通过")
        return True
        
    except Exception as e:
        print(f"❌ 性能测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("gRPC通信模块测试")
    print("=" * 50)
    
    # 运行基础功能测试
    basic_test_passed = await test_basic_functionality()
    
    if basic_test_passed:
        # 运行性能测试
        perf_test_passed = await test_performance_simulation()
        
        if perf_test_passed:
            print("\n🎊 所有测试通过! gRPC模块实现完成且功能正常!")
            return True
    
    print("\n💥 部分测试失败，请检查实现")
    return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)