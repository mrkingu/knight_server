#!/usr/bin/env python3
"""
服务启动器功能演示脚本

演示服务启动器的主要功能，包括：
- 配置管理
- 服务状态显示
- 健康检查
- 监控功能
- 启动画面
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from server_launcher import ServerLauncher
from server_launcher.banner import Banner, ServiceInfo
from server_launcher.service_config import ServiceConfigManager
from server_launcher.health_checker import HealthChecker, HealthStatus
from server_launcher.utils import get_system_info


async def demo_configuration():
    """演示配置管理功能"""
    print("🔧 配置管理演示")
    print("=" * 50)
    
    # 创建配置管理器
    config_manager = ServiceConfigManager()
    
    # 检查配置文件
    config_file = "server_launcher_config.yaml"
    if not os.path.exists(config_file):
        print(f"❌ 配置文件不存在: {config_file}")
        return
    
    try:
        # 加载配置
        config_manager.load_from_file(config_file)
        print(f"✅ 配置文件加载成功: {config_file}")
        
        # 显示配置信息
        all_configs = config_manager.get_all_configs()
        print(f"📋 总共配置了 {len(all_configs)} 个服务:")
        
        for service_name, service_config in all_configs.items():
            status = "✅ 启用" if service_config.enabled else "❌ 禁用"
            print(f"  - {service_name}: {service_config.service_type.value}:{service_config.port} {status}")
        
        # 显示启动顺序
        startup_sequence = config_manager.get_startup_sequence()
        print(f"\n🚀 启动顺序: {' → '.join(startup_sequence)}")
        
        # 验证配置
        errors = config_manager.validate_all_configs()
        if errors:
            print(f"\n❌ 配置验证发现错误:")
            for service_name, error_list in errors.items():
                for error in error_list:
                    print(f"  - {service_name}: {error}")
        else:
            print(f"\n✅ 配置验证通过")
            
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")


def demo_banner():
    """演示启动画面功能"""
    print("\n🎨 启动画面演示")
    print("=" * 50)
    
    # 创建Banner实例
    banner = Banner()
    
    # 显示Logo
    banner.show_logo()
    
    # 创建示例服务信息
    services_info = [
        ServiceInfo(
            name="gate-8001",
            service_type="gate",
            port=8001,
            status="运行中",
            pid=12345,
            memory_usage="45.2 MB",
            cpu_percent=15.3,
            uptime="2小时 15分钟",
            health_status="健康"
        ),
        ServiceInfo(
            name="logic-9001",
            service_type="logic",
            port=9001,
            status="运行中",
            pid=12346,
            memory_usage="78.5 MB",
            cpu_percent=25.7,
            uptime="2小时 14分钟",
            health_status="健康"
        ),
        ServiceInfo(
            name="chat-9101",
            service_type="chat",
            port=9101,
            status="已停止",
            pid=None,
            memory_usage=None,
            cpu_percent=None,
            uptime=None,
            health_status="未知"
        ),
        ServiceInfo(
            name="fight-9201",
            service_type="fight",
            port=9201,
            status="启动中",
            pid=12347,
            memory_usage="32.1 MB",
            cpu_percent=8.2,
            uptime="30秒",
            health_status="警告"
        )
    ]
    
    # 显示服务表格
    banner.show_service_table(services_info)
    
    # 显示系统信息
    banner.show_system_info()
    
    # 显示消息
    banner.show_success_message("演示完成!")


async def demo_health_checker():
    """演示健康检查功能"""
    print("\n🏥 健康检查演示")
    print("=" * 50)
    
    # 创建健康检查器
    health_checker = HealthChecker(check_interval=5)
    
    # 创建示例服务配置
    from server_launcher.service_config import ServiceConfig, ServiceType, HealthCheckConfig, HealthCheckType
    
    # 模拟TCP健康检查
    test_service = ServiceConfig(
        name="test-service",
        service_type=ServiceType.GATE,
        port=8080,
        health_check=HealthCheckConfig(
            type=HealthCheckType.TCP,
            interval=5,
            timeout=3,
            retries=3
        )
    )
    
    # 注册服务
    health_checker.register_service(test_service)
    
    # 启动健康检查器
    async with health_checker:
        print("✅ 健康检查器已启动")
        
        # 执行一次健康检查
        result = await health_checker.check_service_health("test-service")
        print(f"📊 健康检查结果: {result.status.value} - {result.message}")
        print(f"⏱️  响应时间: {result.response_time:.3f}秒")
        
        # 获取健康报告
        report = health_checker.get_health_report()
        print(f"📈 健康报告: {report['total_services']} 个服务")
        
        print("✅ 健康检查演示完成")


async def demo_system_info():
    """演示系统信息功能"""
    print("\n💻 系统信息演示")
    print("=" * 50)
    
    # 获取系统信息
    system_info = get_system_info()
    
    # 显示系统信息
    if system_info:
        sys_info = system_info.get('system', {})
        print(f"🖥️  操作系统: {sys_info.get('platform', 'Unknown')}")
        print(f"🏠 主机名: {sys_info.get('hostname', 'Unknown')}")
        print(f"🐍 Python版本: {sys_info.get('python_version', 'Unknown')}")
        
        cpu_info = system_info.get('cpu', {})
        print(f"⚡ CPU核心数: {cpu_info.get('count', 'Unknown')}")
        print(f"📊 CPU使用率: {cpu_info.get('percent', 0):.1f}%")
        
        memory_info = system_info.get('memory', {})
        print(f"🧠 内存总量: {memory_info.get('total_str', 'Unknown')}")
        print(f"📈 内存使用: {memory_info.get('used_str', 'Unknown')} ({memory_info.get('percent', 0):.1f}%)")
        
        print("✅ 系统信息获取成功")
    else:
        print("❌ 系统信息获取失败（可能缺少psutil依赖）")


async def demo_launcher_basic():
    """演示启动器基本功能"""
    print("\n🚀 启动器基本功能演示")
    print("=" * 50)
    
    # 创建启动器实例
    launcher = ServerLauncher()
    
    # 加载配置
    config_success = launcher.load_config("server_launcher_config.yaml")
    print(f"⚙️  配置加载: {'✅ 成功' if config_success else '❌ 失败'}")
    
    if config_success:
        # 初始化组件
        init_success = await launcher._initialize_components()
        print(f"🔧 组件初始化: {'✅ 成功' if init_success else '❌ 失败'}")
        
        if init_success:
            # 获取服务信息
            services_info = launcher.get_services_info()
            print(f"📋 服务信息: 获取到 {len(services_info)} 个服务")
            
            # 获取状态报告
            report = launcher.get_status_report()
            print(f"📊 状态报告: {len(report)} 个字段")
            
            # 获取统计信息
            stats = launcher.stats.to_dict()
            print(f"📈 统计信息: 运行时间 {stats['uptime']:.1f}秒")
            
            # 关闭组件
            await launcher._shutdown()
            print("✅ 组件关闭成功")
    
    print("✅ 启动器基本功能演示完成")


async def main():
    """主演示函数"""
    print("🎭 服务启动器功能演示")
    print("=" * 80)
    
    try:
        # 依次演示各个功能
        await demo_configuration()
        demo_banner()
        await demo_health_checker()
        await demo_system_info()
        await demo_launcher_basic()
        
        print("\n🎉 所有功能演示完成!")
        print("=" * 80)
        
        # 显示使用提示
        print("\n💡 使用提示:")
        print("  - 启动所有服务: python -m server_launcher start --all")
        print("  - 查看服务状态: python -m server_launcher status")
        print("  - 交互模式: python -m server_launcher.cli interactive")
        print("  - 生成状态报告: python -m server_launcher status --output report.json")
        
    except Exception as e:
        print(f"\n❌ 演示过程中发生异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())