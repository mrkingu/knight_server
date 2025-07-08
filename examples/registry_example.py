"""
服务注册发现模块使用示例

演示如何使用服务注册发现模块的各种功能，包括服务注册、发现、
健康监控和负载均衡。
"""

import asyncio
import time
from typing import List

# 从注册模块导入所需的组件
from common.registry import (
    # 核心功能
    ServiceInfo, ServiceStatus, LoadBalanceStrategy,
    ServiceRegistry, ServiceDiscovery, HealthMonitor, LoadBalancer,
    
    # 配置和工厂
    RegistryFactory, generate_etcd_config, generate_consul_config,
    
    # 健康检查
    HealthCheckType, HealthCheckConfig,
    
    # 异常
    ServiceRegistrationError, ServiceDiscoveryError
)

from loguru import logger


async def example_service_registration():
    """服务注册示例"""
    print("\n=== 服务注册示例 ===")
    
    try:
        # 1. 创建注册中心配置
        registry_config = generate_etcd_config()
        
        # 2. 获取服务注册器实例
        registry = await ServiceRegistry.get_instance()
        
        # 3. 创建并添加适配器
        factory = await RegistryFactory.get_instance()
        adapter = factory.create_adapter(
            adapter_type="etcd",
            config=registry_config["config"],
            name="primary"
        )
        registry.add_adapter("primary", adapter)
        
        # 4. 创建服务信息
        service_info = ServiceInfo(
            name="logic_service",
            host="192.168.1.100",
            port=8001,
            tags=["game", "logic"],
            metadata={"version": "1.0.0", "weight": 100},
            health_check_url="http://192.168.1.100:8001/health"
        )
        
        # 5. 注册服务
        results = await registry.register(service_info)
        
        for adapter_name, result in results.items():
            if result.success:
                print(f"✅ 服务注册成功: {adapter_name} -> {result.service_id}")
            else:
                print(f"❌ 服务注册失败: {adapter_name} -> {result.error}")
        
        # 6. 获取已注册的服务列表
        registered_services = await registry.get_registered_services()
        print(f"📝 已注册服务数量: {len(registered_services)}")
        
        return service_info.id
        
    except Exception as e:
        print(f"❌ 服务注册示例失败: {e}")
        return None


async def example_service_discovery():
    """服务发现示例"""
    print("\n=== 服务发现示例 ===")
    
    try:
        # 1. 获取服务发现器实例
        discovery = await ServiceDiscovery.get_instance()
        
        # 2. 创建并添加适配器
        registry_config = generate_etcd_config()
        factory = await RegistryFactory.get_instance()
        adapter = factory.create_adapter(
            adapter_type="etcd",
            config=registry_config["config"],
            name="discovery"
        )
        discovery.add_adapter("discovery", adapter)
        
        # 3. 发现服务
        services = await discovery.discover(
            service_name="logic_service",
            tags=["game"],
            healthy_only=True,
            use_cache=True
        )
        
        print(f"🔍 发现服务: logic_service -> {len(services)} 个实例")
        for service in services:
            print(f"   - {service.id}: {service.address} (状态: {service.status.value})")
        
        # 4. 获取服务实例数量
        total_instances = await discovery.get_service_instances("logic_service")
        healthy_instances = await discovery.get_healthy_instances("logic_service")
        
        print(f"📊 服务统计: 总实例 {total_instances}, 健康实例 {healthy_instances}")
        
        # 5. 获取统计信息
        stats = discovery.get_stats()
        print(f"📈 发现器统计: {stats}")
        
        return services
        
    except Exception as e:
        print(f"❌ 服务发现示例失败: {e}")
        return []


async def example_health_monitoring(service_id: str):
    """健康监控示例"""
    print("\n=== 健康监控示例 ===")
    
    try:
        # 1. 获取健康监控器实例
        monitor = await HealthMonitor.get_instance()
        
        # 2. 创建并添加适配器
        registry_config = generate_etcd_config()
        factory = await RegistryFactory.get_instance()
        adapter = factory.create_adapter(
            adapter_type="etcd",
            config=registry_config["config"],
            name="health"
        )
        monitor.add_adapter("health", adapter)
        
        # 3. 创建服务信息
        service = ServiceInfo(
            name="logic_service",
            id=service_id,
            host="192.168.1.100",
            port=8001,
            health_check_url="http://192.168.1.100:8001/health"
        )
        
        # 4. 创建健康检查配置
        health_config = HealthCheckConfig(
            check_type=HealthCheckType.HTTP,
            interval=5.0,
            timeout=3.0,
            max_failures=3
        )
        
        # 5. 开始监控
        await monitor.start_monitoring(service, health_config)
        print(f"🔧 开始健康监控: {service.name}/{service.id}")
        
        # 6. 等待一段时间查看监控结果
        await asyncio.sleep(2)
        
        # 7. 获取健康状态
        health_state = monitor.get_service_health(service_id)
        if health_state:
            print(f"💗 健康状态: {health_state.current_status.value}")
            print(f"   - 检查次数: {health_state.total_checks}")
            print(f"   - 失败次数: {health_state.total_failures}")
            print(f"   - 成功率: {health_state.get_success_rate():.2%}")
        
        # 8. 获取统计信息
        stats = monitor.get_stats()
        print(f"📈 监控器统计: {stats}")
        
        # 9. 停止监控
        await monitor.stop_monitoring(service_id)
        print(f"⏹️ 停止健康监控: {service_id}")
        
    except Exception as e:
        print(f"❌ 健康监控示例失败: {e}")


async def example_load_balancing(services: List[ServiceInfo]):
    """负载均衡示例"""
    print("\n=== 负载均衡示例 ===")
    
    if not services:
        print("⚠️ 没有可用的服务进行负载均衡演示")
        return
    
    try:
        # 测试不同的负载均衡策略
        strategies = [
            LoadBalanceStrategy.ROUND_ROBIN,
            LoadBalanceStrategy.RANDOM,
            LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN,
            LoadBalanceStrategy.LEAST_CONNECTIONS
        ]
        
        for strategy in strategies:
            print(f"\n🎯 测试负载均衡策略: {strategy.value}")
            
            # 创建负载均衡器
            balancer = LoadBalancer(strategy)
            
            # 连续选择5次
            for i in range(5):
                try:
                    selected = await balancer.select(services)
                    if selected:
                        print(f"   选择 {i+1}: {selected.id} ({selected.address})")
                        
                        # 模拟请求处理
                        await balancer.start_request(selected.id)
                        await asyncio.sleep(0.1)  # 模拟处理时间
                        await balancer.end_request(selected.id, response_time=100.0, success=True)
                    else:
                        print(f"   选择 {i+1}: 无可用服务")
                        
                except Exception as e:
                    print(f"   选择 {i+1}: 失败 - {e}")
            
            # 获取统计信息
            stats = balancer.get_stats()
            print(f"   📊 统计: {stats}")
        
    except Exception as e:
        print(f"❌ 负载均衡示例失败: {e}")


async def example_service_watching():
    """服务变更监听示例"""
    print("\n=== 服务变更监听示例 ===")
    
    try:
        # 1. 获取服务发现器实例
        discovery = await ServiceDiscovery.get_instance()
        
        # 2. 定义变更回调函数
        def on_service_change(event):
            print(f"🔔 服务变更事件: {event.event_type} -> "
                  f"{event.service.name}/{event.service.id}")
        
        # 3. 开始监听服务变更
        await discovery.watch_service_changes(
            service_name="logic_service",
            callback=on_service_change
        )
        
        print("👂 开始监听服务变更...")
        
        # 等待一段时间（在实际应用中，这将是长期运行的）
        await asyncio.sleep(2)
        
    except Exception as e:
        print(f"❌ 服务变更监听示例失败: {e}")


async def example_cleanup(service_id: str):
    """清理示例"""
    print("\n=== 清理资源 ===")
    
    try:
        # 1. 注销服务
        registry = await ServiceRegistry.get_instance()
        results = await registry.deregister(service_id)
        
        for adapter_name, success in results.items():
            if success:
                print(f"✅ 服务注销成功: {adapter_name}")
            else:
                print(f"❌ 服务注销失败: {adapter_name}")
        
        # 2. 关闭所有组件
        await registry.shutdown()
        
        discovery = await ServiceDiscovery.get_instance()
        await discovery.shutdown()
        
        monitor = await HealthMonitor.get_instance()
        await monitor.shutdown()
        
        factory = await RegistryFactory.get_instance()
        await factory.close_all_adapters()
        
        print("🧹 资源清理完成")
        
    except Exception as e:
        print(f"❌ 清理资源失败: {e}")


async def main():
    """主函数，运行所有示例"""
    print("🚀 开始服务注册发现模块示例演示...")
    
    service_id = None
    services = []
    
    try:
        # 1. 服务注册示例
        service_id = await example_service_registration()
        
        # 2. 服务发现示例
        services = await example_service_discovery()
        
        # 3. 健康监控示例
        if service_id:
            await example_health_monitoring(service_id)
        
        # 4. 负载均衡示例
        if services:
            await example_load_balancing(services)
        
        # 5. 服务变更监听示例
        await example_service_watching()
        
    except Exception as e:
        print(f"❌ 示例演示失败: {e}")
        
    finally:
        # 6. 清理资源
        if service_id:
            await example_cleanup(service_id)


if __name__ == "__main__":
    # 配置日志
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        level="INFO"
    )
    
    # 运行示例
    asyncio.run(main())