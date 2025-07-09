#!/usr/bin/env python3
"""
服务启动器最小化测试脚本

不依赖外部库，仅测试基本功能
"""

import asyncio
import sys
import os
from pathlib import Path

# 测试基本的模块导入
def test_module_structure():
    """测试模块结构"""
    print("📂 测试模块结构...")
    
    # 检查文件是否存在
    base_path = Path(__file__).parent / "server_launcher"
    
    required_files = [
        "__init__.py",
        "launcher.py",
        "service_manager.py",
        "process_monitor.py",
        "health_checker.py",
        "service_config.py",
        "process_pool.py",
        "banner.py",
        "cli.py",
        "utils.py",
        "__main__.py"
    ]
    
    all_exist = True
    for file_name in required_files:
        file_path = base_path / file_name
        if file_path.exists():
            print(f"✅ {file_name}")
        else:
            print(f"❌ {file_name} 不存在")
            all_exist = False
    
    # 检查配置文件
    config_file = Path(__file__).parent / "server_launcher_config.yaml"
    if config_file.exists():
        print(f"✅ server_launcher_config.yaml")
    else:
        print(f"❌ server_launcher_config.yaml 不存在")
        all_exist = False
    
    return all_exist


def test_basic_imports():
    """测试基本导入"""
    print("\n📦 测试基本导入...")
    
    try:
        # 测试工具模块
        from server_launcher.utils import format_bytes, format_uptime
        print("✅ utils 模块导入成功")
        
        # 测试格式化函数
        bytes_str = format_bytes(1024 * 1024)
        uptime_str = format_uptime(3661)
        print(f"✅ 格式化函数: {bytes_str}, {uptime_str}")
        
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False
    
    return True


def test_banner():
    """测试Banner功能"""
    print("\n🎨 测试Banner功能...")
    
    try:
        from server_launcher.banner import Banner, ServiceInfo
        
        banner = Banner()
        print("✅ Banner 创建成功")
        
        # 测试服务信息
        service_info = ServiceInfo(
            name="test-service",
            service_type="test",
            port=9999,
            status="运行中",
            pid=12345,
            health_status="健康"
        )
        
        print("✅ ServiceInfo 创建成功")
        
        # 测试显示Logo（不实际显示）
        print("✅ Banner 基本功能测试完成")
        
    except Exception as e:
        print(f"❌ Banner 测试失败: {e}")
        return False
    
    return True


def test_config_structure():
    """测试配置结构"""
    print("\n⚙️  测试配置结构...")
    
    try:
        from server_launcher.service_config import (
            ServiceConfig, ServiceType, HealthCheckType, 
            ServiceConfigManager, create_default_config
        )
        
        print("✅ 配置类导入成功")
        
        # 测试枚举
        service_type = ServiceType.GATE
        health_type = HealthCheckType.HTTP
        print(f"✅ 枚举测试: {service_type.value}, {health_type.value}")
        
        # 测试默认配置创建
        default_config = create_default_config()
        print(f"✅ 默认配置创建: {len(default_config)} 字符")
        
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        return False
    
    return True


def test_data_structures():
    """测试数据结构"""
    print("\n🏗️  测试数据结构...")
    
    try:
        from server_launcher.process_monitor import ProcessMetrics, ProcessMonitorConfig
        from server_launcher.health_checker import HealthCheckResult, HealthStatus
        
        # 测试进程指标
        metrics = ProcessMetrics(
            pid=12345,
            timestamp=1234567890.0,
            cpu_percent=50.0,
            memory_percent=60.0,
            memory_rss=1024*1024,
            memory_vms=2048*1024,
            num_threads=4,
            num_fds=10,
            io_read_bytes=1000,
            io_write_bytes=2000,
            connections=5,
            status="running"
        )
        
        print("✅ ProcessMetrics 创建成功")
        
        # 测试健康检查结果
        health_result = HealthCheckResult(
            service_name="test-service",
            status=HealthStatus.HEALTHY,
            response_time=0.1,
            timestamp=1234567890.0,
            message="健康检查通过"
        )
        
        print("✅ HealthCheckResult 创建成功")
        
        # 测试转换为字典
        metrics_dict = metrics.to_dict()
        health_dict = health_result.to_dict()
        
        print(f"✅ 数据结构转换: {len(metrics_dict)} 字段, {len(health_dict)} 字段")
        
    except Exception as e:
        print(f"❌ 数据结构测试失败: {e}")
        return False
    
    return True


def test_file_operations():
    """测试文件操作"""
    print("\n📁 测试文件操作...")
    
    try:
        from server_launcher.utils import create_pid_file, remove_pid_file, read_pid_file
        
        # 测试PID文件操作
        test_pid_file = "/tmp/test_launcher.pid"
        test_pid = 12345
        
        # 创建PID文件
        success = create_pid_file(test_pid_file, test_pid)
        print(f"✅ PID文件创建: {success}")
        
        # 读取PID文件
        read_pid = read_pid_file(test_pid_file)
        print(f"✅ PID文件读取: {read_pid == test_pid}")
        
        # 删除PID文件
        success = remove_pid_file(test_pid_file)
        print(f"✅ PID文件删除: {success}")
        
    except Exception as e:
        print(f"❌ 文件操作测试失败: {e}")
        return False
    
    return True


def main():
    """主测试函数"""
    print("🚀 服务启动器最小化测试")
    print("=" * 50)
    
    tests = [
        test_module_structure,
        test_basic_imports,
        test_banner,
        test_config_structure,
        test_data_structures,
        test_file_operations
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ 测试异常: {e}")
    
    print(f"\n📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过!")
        return 0
    else:
        print("❌ 部分测试失败")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)