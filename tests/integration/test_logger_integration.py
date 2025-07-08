"""
集成测试：日志模块与配置系统集成

该测试验证日志模块与现有配置系统的集成。
"""

import os
import tempfile
import shutil
from pathlib import Path
import sys
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

from common.logger import LoggerFactory, initialize_logging, logger, sls_logger, battle_logger


def test_logger_integration():
    """测试日志系统集成"""
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 设置环境变量
        os.environ['LOG_DIR'] = temp_dir
        os.environ['LOG_LEVEL'] = 'DEBUG'
        os.environ['LOG_SERVICE_NAME'] = 'gate'
        os.environ['LOG_SERVICE_PORT'] = '8001'
        
        # 初始化日志系统
        initialize_logging("gate", 8001)
        
        # 测试普通日志
        logger.info("服务启动", service="gate", port=8001)
        logger.debug("调试信息", user_id=12345)
        logger.warning("警告信息", warning_msg="某个警告")
        
        # 测试SLS日志
        sls_logger.user_action("user123", "login", "用户登录成功", ip="192.168.1.1")
        sls_logger.business_event("payment", "支付完成", order_id="ORDER001", amount=99.99)
        sls_logger.performance_metric("response_time", 150.5, "ms", endpoint="/api/login")
        
        # 测试战斗日志
        battle_logger.start_battle("BATTLE001")
        battle_logger.player_join("BATTLE001", "player001", player_level=10, class_type="warrior")
        battle_logger.skill_cast("BATTLE001", "player001", "skill_fireball", "player002", damage=50)
        battle_logger.damage_dealt("BATTLE001", "player001", "player002", 50, "magic")
        battle_logger.round_start("BATTLE001", 1, players=["player001", "player002"])
        battle_logger.round_end("BATTLE001", 1, winner="player001")
        replay_file = battle_logger.end_battle("BATTLE001")
        
        # 验证日志目录结构
        service_dir = Path(temp_dir) / "gate_8001"
        print(f"检查日志目录: {service_dir}")
        
        if service_dir.exists():
            print("✓ 服务日志目录创建成功")
            
            # 列出目录内容
            for file_path in service_dir.iterdir():
                print(f"  - {file_path.name}")
        else:
            print("✗ 服务日志目录未创建")
        
        # 验证回放文件
        if replay_file and Path(replay_file).exists():
            print(f"✓ 战斗回放文件创建成功: {replay_file}")
        else:
            print("✗ 战斗回放文件未创建")
        
        # 测试性能装饰器
        @logger.timer("测试函数")
        def test_function():
            import time
            time.sleep(0.01)
            return "完成"
        
        result = test_function()
        print(f"✓ 性能装饰器测试: {result}")
        
        # 测试异常捕获装饰器
        @logger.catch(reraise=False)
        def error_function():
            raise ValueError("测试异常")
            return "不会执行"
        
        result = error_function()
        print(f"✓ 异常捕获装饰器测试: {result}")
        
        # 测试上下文管理器
        with logger.context(operation="context_test", step=1) as ctx_logger:
            ctx_logger.info("在上下文中记录日志", data="test_data")
        
        print("✓ 上下文管理器测试完成")
        
        # 测试工厂统计信息
        factory = LoggerFactory()
        stats = factory.get_logger_info()
        print(f"✓ 工厂统计信息: {stats}")
        
        # 测试战斗统计信息
        battle_stats = battle_logger.get_battle_stats()
        print(f"✓ 战斗统计信息: {battle_stats}")
        
        # 测试SLS统计信息
        sls_stats = sls_logger.get_sls_stats()
        print(f"✓ SLS统计信息: {sls_stats}")
        
        print("\n🎉 所有集成测试通过!")
        
    finally:
        # 清理环境
        for key in ['LOG_DIR', 'LOG_LEVEL', 'LOG_SERVICE_NAME', 'LOG_SERVICE_PORT']:
            os.environ.pop(key, None)
        
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_configuration_loading():
    """测试配置加载"""
    
    # 模拟现有配置系统的配置
    logging_config = {
        'default': {
            'level': 'INFO',
            'log_dir': 'logs',
            'enable_async': True,
            'enable_json_format': False,
            'colorize': True,
            'rotation': {
                'size': '100 MB',
                'retention': '10 days',
                'compression': 'zip'
            }
        },
        'sls': {
            'level': 'WARNING',
            'enable_json_format': True,
        },
        'battle': {
            'level': 'DEBUG',
            'enable_compression': True,
        }
    }
    
    # 初始化带配置的日志系统
    initialize_logging("test_service", 8080, logging_config)
    
    # 获取工厂并验证配置
    factory = LoggerFactory()
    
    # 测试默认配置
    general_logger = factory.get_logger("general")
    print(f"✓ 通用日志器级别: {general_logger.get_level()}")
    
    # 测试SLS配置  
    sls_logger_instance = factory.get_logger("sls")
    print(f"✓ SLS日志器级别: {sls_logger_instance.get_level()}")
    
    # 测试战斗配置
    battle_logger_instance = factory.get_logger("battle")
    print(f"✓ 战斗日志器级别: {battle_logger_instance.get_level()}")
    
    print("✓ 配置加载测试完成!")


def main():
    """运行所有集成测试"""
    print("开始日志系统集成测试...\n")
    
    print("=" * 50)
    print("测试1: 日志系统基本集成")
    print("=" * 50)
    test_logger_integration()
    
    print("\n" + "=" * 50)
    print("测试2: 配置系统集成")
    print("=" * 50)
    test_configuration_loading()
    
    print("\n🎯 所有集成测试完成!")


if __name__ == '__main__':
    main()