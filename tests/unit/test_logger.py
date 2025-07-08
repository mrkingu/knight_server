"""
测试日志模块

该模块包含日志系统的单元测试。
"""

import os
import time
import json
import tempfile
import shutil
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

from common.logger import (
    LoggerConfig, LogLevel, LoggerFactory, BaseLogger,
    SLSLogger, SLSConfig, BattleLogger, BattleConfig,
    logger, sls_logger, battle_logger, initialize_logging
)


class TestLoggerConfig(TestCase):
    """测试日志配置类"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = LoggerConfig()
        
        self.assertEqual(config.level, LogLevel.INFO)
        self.assertEqual(config.log_dir, "logs")
        self.assertTrue(config.enable_file_logging)
        self.assertTrue(config.enable_console_logging)
        self.assertTrue(config.enable_async)
    
    def test_from_dict(self):
        """测试从字典创建配置"""
        config_dict = {
            'level': 'DEBUG',
            'log_dir': '/tmp/test_logs',
            'enable_async': False,
            'service_name': 'test_service',
            'service_port': 8080
        }
        
        config = LoggerConfig.from_dict(config_dict)
        
        self.assertEqual(config.level, LogLevel.DEBUG)
        self.assertEqual(config.log_dir, '/tmp/test_logs')
        self.assertFalse(config.enable_async)
        self.assertEqual(config.service_name, 'test_service')
        self.assertEqual(config.service_port, 8080)
    
    def test_from_env(self):
        """测试从环境变量创建配置"""
        with patch.dict(os.environ, {
            'LOG_LEVEL': 'ERROR',
            'LOG_DIR': '/tmp/env_logs',
            'LOG_ENABLE_ASYNC': 'false',
            'LOG_SERVICE_NAME': 'env_service',
            'LOG_SERVICE_PORT': '9090'
        }):
            config = LoggerConfig.from_env()
            
            self.assertEqual(config.level, LogLevel.ERROR)
            self.assertEqual(config.log_dir, '/tmp/env_logs')
            self.assertFalse(config.enable_async)
            self.assertEqual(config.service_name, 'env_service')
            self.assertEqual(config.service_port, 9090)
    
    def test_get_log_file_path(self):
        """测试获取日志文件路径"""
        config = LoggerConfig(
            service_name='gate',
            service_port=8001,
            log_dir='/tmp/logs'
        )
        
        path = config.get_log_file_path('general')
        expected = '/tmp/logs/gate_8001/general_{time:YYYY-MM-DD}.log'
        self.assertEqual(path, expected)


class TestBaseLogger(TestCase):
    """测试基础日志器"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        self.config = LoggerConfig(
            log_dir=self.temp_dir,
            service_name='test',
            service_port=8000
        )
    
    def tearDown(self):
        """清理测试环境"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_logger_creation(self):
        """测试日志器创建"""
        logger_instance = BaseLogger('test', self.config)
        
        self.assertEqual(logger_instance.name, 'test')
        self.assertEqual(logger_instance.config, self.config)
        self.assertTrue(logger_instance._initialized)
    
    def test_logging_methods(self):
        """测试日志记录方法"""
        logger_instance = BaseLogger('test', self.config)
        
        # 测试各种日志级别
        logger_instance.trace("trace message")
        logger_instance.debug("debug message")
        logger_instance.info("info message")
        logger_instance.success("success message")
        logger_instance.warning("warning message")
        logger_instance.error("error message")
        logger_instance.critical("critical message")
        
        # 测试异常记录
        try:
            raise ValueError("test exception")
        except ValueError:
            logger_instance.exception("exception occurred")
    
    def test_context_binding(self):
        """测试上下文绑定"""
        logger_instance = BaseLogger('test', self.config)
        
        bound_logger = logger_instance.bind(user_id=123, action="test")
        self.assertIsInstance(bound_logger, BaseLogger)
        self.assertIn('user_id', bound_logger._context)
        self.assertEqual(bound_logger._context['user_id'], 123)
    
    def test_level_setting(self):
        """测试日志级别设置"""
        logger_instance = BaseLogger('test', self.config)
        
        logger_instance.set_level('ERROR')
        self.assertEqual(logger_instance.get_level(), LogLevel.ERROR)
        
        # 测试级别检查
        self.assertTrue(logger_instance.is_enabled_for('ERROR'))
        self.assertFalse(logger_instance.is_enabled_for('INFO'))
    
    def test_decorators(self):
        """测试装饰器"""
        logger_instance = BaseLogger('test', self.config)
        
        @logger_instance.catch()
        def test_function():
            return "success"
        
        @logger_instance.timer()
        def timed_function():
            time.sleep(0.1)
            return "timed"
        
        # 测试装饰器功能
        result = test_function()
        self.assertEqual(result, "success")
        
        result = timed_function()
        self.assertEqual(result, "timed")


class TestLoggerFactory(TestCase):
    """测试日志工厂"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        # 清理单例状态
        LoggerFactory._instances.clear()
    
    def tearDown(self):
        """清理测试环境"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        LoggerFactory._instances.clear()
    
    def test_singleton(self):
        """测试单例模式"""
        factory1 = LoggerFactory()
        factory2 = LoggerFactory()
        
        self.assertIs(factory1, factory2)
    
    def test_initialization(self):
        """测试工厂初始化"""
        factory = LoggerFactory()
        factory.initialize(service_type="test_service", port=8080)
        
        info = factory.get_logger_info()
        self.assertEqual(info['service_name'], 'test_service')
        self.assertEqual(info['service_port'], 8080)
        self.assertTrue(info['initialized'])
    
    def test_get_logger(self):
        """测试获取日志器"""
        factory = LoggerFactory()
        factory.initialize(service_type="test", port=8000)
        
        # 测试获取不同类型的日志器
        general_logger = factory.get_logger("general")
        sls_logger_instance = factory.get_logger("sls")
        battle_logger_instance = factory.get_logger("battle")
        
        self.assertIsInstance(general_logger, BaseLogger)
        self.assertIsInstance(sls_logger_instance, SLSLogger)
        self.assertIsInstance(battle_logger_instance, BattleLogger)
    
    def test_custom_logger(self):
        """测试自定义日志器"""
        factory = LoggerFactory()
        config = LoggerConfig(log_dir=self.temp_dir)
        
        custom_logger = factory.create_custom_logger("custom", config)
        self.assertIsInstance(custom_logger, BaseLogger)
        self.assertEqual(custom_logger.name, "custom")
    
    def test_level_management(self):
        """测试级别管理"""
        factory = LoggerFactory()
        factory.initialize()
        
        logger_instance = factory.get_logger("general")
        
        # 测试设置特定日志器级别
        factory.set_logger_level("general", "ERROR")
        self.assertEqual(logger_instance.get_level(), LogLevel.ERROR)
        
        # 测试设置全局级别
        factory.set_global_level("DEBUG")
        self.assertEqual(logger_instance.get_level(), LogLevel.DEBUG)


class TestSLSLogger(TestCase):
    """测试SLS日志器"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        self.config = LoggerConfig(log_dir=self.temp_dir)
        self.sls_config = SLSConfig(
            project_name="test_project",
            logstore_name="test_logstore",
            batch_size=10,
            batch_timeout=1.0
        )
    
    def tearDown(self):
        """清理测试环境"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_sls_logger_creation(self):
        """测试SLS日志器创建"""
        sls_logger_instance = SLSLogger('sls', self.config, self.sls_config)
        
        self.assertIsInstance(sls_logger_instance, SLSLogger)
        self.assertEqual(sls_logger_instance.sls_config.project_name, "test_project")
    
    def test_business_methods(self):
        """测试业务方法"""
        sls_logger_instance = SLSLogger('sls', self.config, self.sls_config)
        
        # 测试业务事件
        sls_logger_instance.business_event("user_login", "User logged in", user_id=123)
        
        # 测试用户行为
        sls_logger_instance.user_action("123", "login", "User performed login")
        
        # 测试性能指标
        sls_logger_instance.performance_metric("response_time", 150.5, "ms")
        
        # 测试安全事件
        sls_logger_instance.security_event("unauthorized_access", "HIGH", "Unauthorized access attempt")
    
    def test_sls_stats(self):
        """测试SLS统计"""
        sls_logger_instance = SLSLogger('sls', self.config, self.sls_config)
        
        stats = sls_logger_instance.get_sls_stats()
        self.assertIn('status', stats)
        self.assertIn('queue_size', stats)


class TestBattleLogger(TestCase):
    """测试战斗日志器"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        self.config = LoggerConfig(log_dir=self.temp_dir)
        self.battle_config = BattleConfig(
            enable_replay=True,
            replay_dir=os.path.join(self.temp_dir, "replay"),
            enable_binary_log=True,
            binary_log_dir=os.path.join(self.temp_dir, "binary")
        )
    
    def tearDown(self):
        """清理测试环境"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_battle_logger_creation(self):
        """测试战斗日志器创建"""
        battle_logger_instance = BattleLogger('battle', self.config, self.battle_config)
        
        self.assertIsInstance(battle_logger_instance, BattleLogger)
        self.assertTrue(battle_logger_instance.battle_config.enable_replay)
    
    def test_battle_lifecycle(self):
        """测试战斗生命周期"""
        battle_logger_instance = BattleLogger('battle', self.config, self.battle_config)
        
        battle_id = "test_battle_001"
        
        # 开始战斗
        battle_logger_instance.start_battle(battle_id)
        self.assertEqual(battle_logger_instance._current_battle_id, battle_id)
        
        # 记录战斗事件
        battle_logger_instance.player_join(battle_id, "player_001")
        battle_logger_instance.skill_cast(battle_id, "player_001", "skill_001", "player_002")
        battle_logger_instance.damage_dealt(battle_id, "player_001", "player_002", 100)
        
        # 结束战斗
        replay_file = battle_logger_instance.end_battle(battle_id)
        self.assertIsNone(battle_logger_instance._current_battle_id)
        
        if replay_file:
            self.assertTrue(os.path.exists(replay_file))
    
    def test_battle_context(self):
        """测试战斗上下文"""
        battle_logger_instance = BattleLogger('battle', self.config, self.battle_config)
        
        battle_logger_instance.set_battle_context("test_battle", 1, 10)
        
        self.assertEqual(battle_logger_instance._current_battle_id, "test_battle")
        self.assertEqual(battle_logger_instance._current_round, 1)
        self.assertEqual(battle_logger_instance._current_tick, 10)
    
    def test_battle_stats(self):
        """测试战斗统计"""
        battle_logger_instance = BattleLogger('battle', self.config, self.battle_config)
        
        stats = battle_logger_instance.get_battle_stats()
        self.assertIn('current_battle', stats)
        self.assertIn('replay_stats', stats)


class TestGlobalLoggers(TestCase):
    """测试全局日志器"""
    
    def test_global_logger_access(self):
        """测试全局日志器访问"""
        # 测试延迟初始化
        logger.info("test message")
        sls_logger.info("sls test message")
        battle_logger.info("battle test message")
        
        # 验证是否正确创建了实例
        self.assertTrue(hasattr(logger, 'info'))
        self.assertTrue(hasattr(sls_logger, 'business_event'))
        self.assertTrue(hasattr(battle_logger, 'battle_event'))
    
    def test_initialize_logging(self):
        """测试全局初始化"""
        # 清理现有工厂状态
        from common.logger import LoggerFactory
        LoggerFactory._instances.clear()
        
        initialize_logging("test_service", 8080)
        
        # 验证初始化后的状态
        from common.logger import logger_factory
        info = logger_factory.get_logger_info()
        self.assertEqual(info['service_name'], 'test_service')
        self.assertEqual(info['service_port'], 8080)


if __name__ == '__main__':
    import unittest
    unittest.main()