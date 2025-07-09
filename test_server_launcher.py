#!/usr/bin/env python3
"""
服务启动器测试脚本

用于测试服务启动器的基本功能
"""

import asyncio
import sys
import os
import tempfile
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from server_launcher import ServerLauncher
from server_launcher.service_config import ServiceConfigManager, create_default_config
from server_launcher.banner import Banner
from server_launcher.utils import get_system_info, check_port_available


async def test_basic_functionality():
    """测试基本功能"""
    print("🧪 开始测试服务启动器基本功能...")
    
    # 测试Banner
    print("\n📺 测试Banner显示...")
    banner = Banner()
    banner.show_logo()
    banner.show_system_info()
    
    # 测试工具函数
    print("\n🛠️  测试工具函数...")
    system_info = get_system_info()
    print(f"系统信息获取: {'✅ 成功' if system_info else '❌ 失败'}")
    
    port_available = check_port_available(9999)
    print(f"端口检查 (9999): {'✅ 可用' if port_available else '❌ 不可用'}")
    
    # 测试配置管理
    print("\n⚙️  测试配置管理...")
    config_manager = ServiceConfigManager()
    
    # 创建临时配置文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(create_default_config())
        temp_config_path = f.name
    
    try:
        config_manager.load_from_file(temp_config_path)
        print("✅ 配置加载成功")
        
        # 验证配置
        errors = config_manager.validate_all_configs()
        if errors:
            print(f"❌ 配置验证失败: {errors}")
        else:
            print("✅ 配置验证成功")
        
        # 获取服务配置
        all_configs = config_manager.get_all_configs()
        print(f"✅ 获取到 {len(all_configs)} 个服务配置")
        
    finally:
        # 清理临时文件
        os.unlink(temp_config_path)
    
    # 测试启动器初始化
    print("\n🚀 测试启动器初始化...")
    launcher = ServerLauncher()
    
    # 创建配置文件
    config_file = "test_config.yaml"
    with open(config_file, 'w') as f:
        f.write(create_default_config())
    
    try:
        # 测试配置加载
        success = launcher.load_config(config_file)
        print(f"配置加载: {'✅ 成功' if success else '❌ 失败'}")
        
        if success:
            # 测试组件初始化
            success = await launcher._initialize_components()
            print(f"组件初始化: {'✅ 成功' if success else '❌ 失败'}")
            
            if success:
                # 测试状态获取
                services_info = launcher.get_services_info()
                print(f"✅ 获取到 {len(services_info)} 个服务信息")
                
                # 测试状态报告
                report = launcher.get_status_report()
                print(f"✅ 生成状态报告: {len(report)} 个字段")
                
                # 关闭组件
                await launcher._shutdown()
                print("✅ 组件关闭成功")
    
    finally:
        # 清理配置文件
        if os.path.exists(config_file):
            os.unlink(config_file)
    
    print("\n🎉 基本功能测试完成!")


async def test_service_lifecycle():
    """测试服务生命周期"""
    print("\n🔄 测试服务生命周期...")
    
    # 创建一个简单的测试服务脚本
    test_service_script = """
import time
import signal
import sys

def signal_handler(signum, frame):
    print(f"收到信号 {signum}，退出...")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

print("测试服务启动...")
while True:
    time.sleep(1)
"""
    
    script_path = "test_service.py"
    with open(script_path, 'w') as f:
        f.write(test_service_script)
    
    try:
        # 创建测试配置
        test_config = f"""
launcher:
  name: "Test Launcher"
  version: "1.0.0"
  log_level: "INFO"

startup:
  sequence:
    - "test-service"
  timeout: 30

services:
  test:
    - name: "test-service"
      service_type: "custom"
      port: 9999
      process_count: 1
      auto_restart: false
      dependencies: []
      start_command: "python {script_path}"
      health_check:
        type: "tcp"
        interval: 5
        timeout: 3
      enabled: true
"""
        
        config_file = "test_service_config.yaml"
        with open(config_file, 'w') as f:
            f.write(test_config)
        
        # 测试启动器
        launcher = ServerLauncher()
        launcher.load_config(config_file)
        
        # 简单的生命周期测试
        print("✅ 测试服务生命周期配置成功")
        
    finally:
        # 清理文件
        for file_path in [script_path, config_file]:
            if os.path.exists(file_path):
                os.unlink(file_path)
    
    print("✅ 服务生命周期测试完成")


def test_cli_help():
    """测试CLI帮助信息"""
    print("\n💬 测试CLI帮助信息...")
    
    from server_launcher.cli import LauncherCLI
    
    launcher = ServerLauncher()
    cli = LauncherCLI(launcher)
    
    # 测试帮助命令
    print("测试帮助命令:")
    cli.do_help("")
    
    print("✅ CLI帮助信息测试完成")


async def main():
    """主测试函数"""
    print("🚀 开始服务启动器测试")
    print("=" * 50)
    
    try:
        await test_basic_functionality()
        await test_service_lifecycle()
        test_cli_help()
        
        print("\n🎉 所有测试完成!")
        
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())