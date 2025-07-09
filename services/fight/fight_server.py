"""
Fight服务器主程序

该模块实现了战斗功能的微服务服务器，继承自BaseServer，
提供战斗匹配、战斗逻辑处理、技能系统、战斗结算、战斗回放等功能。

主要功能：
- 继承自BaseServer提供完整的服务器基础功能
- 集成multiprocessing和asyncio实现高并发处理
- 自动注册到服务注册中心
- 初始化日志、数据库连接、gRPC服务
- 加载并管理所有Fight相关的控制器和服务
- 实现优雅启动和关闭机制

技术特点：
- 使用MVC架构模式
- 支持热更新配置
- 完善的异常处理和日志记录
- 高性能异步并发处理
- 支持分布式部署
"""

import asyncio
import multiprocessing
import signal
import sys
from typing import Optional, Dict, Any, List
import traceback
from dataclasses import dataclass

from services.base import BaseServer, BaseServerConfig
from common.logger import logger
from .fight_handler import FightHandler

# 导入控制器
from .controllers.battle_controller import BattleController
from .controllers.match_controller import MatchController

# 导入业务服务
from .services.battle_service import BattleService
from .services.match_service import MatchService
from .services.skill_service import SkillService

# 导入通知服务
from .services.notify_service import FightNotifyService

# 尝试导入gRPC相关模块
try:
    import grpc
    from concurrent import futures
    GRPC_AVAILABLE = True
except ImportError:
    logger.warning("gRPC相关模块未安装，将使用模拟模式")
    GRPC_AVAILABLE = False
    
    # Mock gRPC实现
    class MockGrpcServer:
        def __init__(self):
            pass
            
        def add_insecure_port(self, address):
            pass
            
        async def start(self):
            pass
            
        async def stop(self, grace=None):
            pass
            
        async def wait_for_termination(self):
            pass
    
    grpc = None
    futures = None


@dataclass
class FightServerConfig(BaseServerConfig):
    """Fight服务器配置"""
    # 战斗匹配相关配置
    max_concurrent_matches: int = 1000
    match_timeout: int = 30  # 秒
    enable_auto_match: bool = True
    match_rating_range: int = 100
    
    # 战斗系统配置
    battle_timeout: int = 600  # 10分钟战斗超时
    max_battle_duration: int = 1800  # 30分钟最大战斗时长
    enable_battle_replay: bool = True
    replay_retention_days: int = 7
    
    # 技能系统配置
    max_skills_per_character: int = 8
    skill_cooldown_precision: float = 0.1  # 技能冷却精度（秒）
    enable_skill_combo: bool = True
    
    # 战斗结算配置
    enable_experience_gain: bool = True
    enable_item_rewards: bool = True
    enable_ranking_system: bool = True
    
    # 性能配置
    max_concurrent_battles: int = 500
    battle_tick_rate: int = 20  # 每秒tick数
    enable_battle_cache: bool = True
    battle_cache_ttl: int = 300  # 5分钟


class FightServer(BaseServer):
    """Fight服务器
    
    战斗功能微服务的主服务器类，负责处理战斗匹配、战斗逻辑、
    技能系统、战斗结算、战斗回放等核心功能。
    """
    
    def __init__(self, config: Optional[FightServerConfig] = None):
        """
        初始化Fight服务器
        
        Args:
            config: 服务器配置，None时使用默认配置
        """
        # 使用默认配置
        if config is None:
            config = FightServerConfig()
        
        # 初始化基础服务器
        super().__init__(service_name="fight_server", config=config)
        
        # 保存Fight特定配置
        self.fight_config = config
        
        # 服务实例
        self.services: Dict[str, Any] = {}
        
        # 控制器实例
        self.controllers: Dict[str, Any] = {}
        
        # 消息处理器
        self.handler: Optional[FightHandler] = None
        
        # 通知服务
        self.notify_service: Optional[FightNotifyService] = None
        
        # gRPC服务器
        self.grpc_server = None
        
        # 数据库连接
        self.database = None
        
        # 缓存连接
        self.cache = None
        
        self.logger.info("Fight服务器初始化完成", 
                        service_name=self.service_name,
                        config=config)
    
    async def initialize(self):
        """初始化Fight服务器的所有组件"""
        try:
            # 初始化基础服务器
            await super().initialize()
            
            # 初始化业务服务
            await self._initialize_services()
            
            # 初始化控制器
            await self._initialize_controllers()
            
            # 初始化消息处理器
            await self._initialize_handler()
            
            # 初始化通知服务
            await self._initialize_notify_service()
            
            # 初始化gRPC服务器
            if GRPC_AVAILABLE:
                await self._initialize_grpc_server()
            
            # 初始化数据库连接
            if self.fight_config.enable_database:
                await self._initialize_database()
            
            # 初始化缓存
            if self.fight_config.enable_redis_cache:
                await self._initialize_cache()
            
            self.logger.info("Fight服务器所有组件初始化完成")
            
        except Exception as e:
            self.logger.error("Fight服务器初始化失败", 
                            error=str(e),
                            traceback=traceback.format_exc())
            raise
    
    async def _initialize_services(self):
        """初始化业务服务"""
        try:
            # 初始化战斗服务
            self.services['battle'] = BattleService(
                max_concurrent_battles=self.fight_config.max_concurrent_battles,
                battle_timeout=self.fight_config.battle_timeout,
                max_battle_duration=self.fight_config.max_battle_duration,
                battle_tick_rate=self.fight_config.battle_tick_rate,
                enable_battle_replay=self.fight_config.enable_battle_replay
            )
            
            # 初始化匹配服务
            self.services['match'] = MatchService(
                max_concurrent_matches=self.fight_config.max_concurrent_matches,
                match_timeout=self.fight_config.match_timeout,
                enable_auto_match=self.fight_config.enable_auto_match,
                match_rating_range=self.fight_config.match_rating_range
            )
            
            # 初始化技能服务
            self.services['skill'] = SkillService(
                max_skills_per_character=self.fight_config.max_skills_per_character,
                skill_cooldown_precision=self.fight_config.skill_cooldown_precision,
                enable_skill_combo=self.fight_config.enable_skill_combo
            )
            
            # 初始化所有服务
            for service_name, service in self.services.items():
                await service.initialize()
                self.logger.info(f"业务服务初始化完成: {service_name}")
            
        except Exception as e:
            self.logger.error("业务服务初始化失败", error=str(e))
            raise
    
    async def _initialize_controllers(self):
        """初始化控制器"""
        try:
            # 初始化战斗控制器
            self.controllers['battle'] = BattleController()
            self.controllers['battle'].register_service('battle_service', self.services['battle'])
            self.controllers['battle'].register_service('skill_service', self.services['skill'])
            
            # 初始化匹配控制器
            self.controllers['match'] = MatchController()
            self.controllers['match'].register_service('match_service', self.services['match'])
            self.controllers['match'].register_service('battle_service', self.services['battle'])
            
            # 初始化所有控制器
            for controller_name, controller in self.controllers.items():
                await controller.initialize()
                self.logger.info(f"控制器初始化完成: {controller_name}")
            
        except Exception as e:
            self.logger.error("控制器初始化失败", error=str(e))
            raise
    
    async def _initialize_handler(self):
        """初始化消息处理器"""
        try:
            # 创建消息处理器
            self.handler = FightHandler()
            
            # 注册控制器到处理器
            for controller_name, controller in self.controllers.items():
                self.handler.register_controller(controller_name, controller)
            
            # 初始化处理器
            await self.handler.initialize()
            
            self.logger.info("消息处理器初始化完成")
            
        except Exception as e:
            self.logger.error("消息处理器初始化失败", error=str(e))
            raise
    
    async def _initialize_notify_service(self):
        """初始化通知服务"""
        try:
            # 创建通知服务
            self.notify_service = FightNotifyService()
            
            # 初始化通知服务
            await self.notify_service.initialize()
            
            # 注册到服务中
            self.services['notify'] = self.notify_service
            
            self.logger.info("通知服务初始化完成")
            
        except Exception as e:
            self.logger.error("通知服务初始化失败", error=str(e))
            raise
    
    async def _initialize_grpc_server(self):
        """初始化gRPC服务器"""
        try:
            if GRPC_AVAILABLE:
                # 创建gRPC服务器
                self.grpc_server = grpc.aio.server(
                    futures.ThreadPoolExecutor(max_workers=10)
                )
                
                # 这里应该添加gRPC服务实现
                # add_FightServiceServicer_to_server(FightServiceServicer(), self.grpc_server)
                
                # 添加监听端口
                listen_addr = f"{self.config.host}:{self.config.port + 1000}"
                self.grpc_server.add_insecure_port(listen_addr)
                
                self.logger.info("gRPC服务器初始化完成", address=listen_addr)
            else:
                # 使用Mock实现
                self.grpc_server = MockGrpcServer()
                self.logger.info("使用Mock gRPC服务器")
            
        except Exception as e:
            self.logger.error("gRPC服务器初始化失败", error=str(e))
            raise
    
    async def _initialize_database(self):
        """初始化数据库连接"""
        try:
            # 这里应该初始化数据库连接
            # 由于没有具体的数据库配置，使用模拟实现
            self.database = {
                'connected': True,
                'type': 'mock',
                'connection_time': asyncio.get_event_loop().time()
            }
            
            self.logger.info("数据库连接初始化完成", database_type='mock')
            
        except Exception as e:
            self.logger.error("数据库连接初始化失败", error=str(e))
            raise
    
    async def _initialize_cache(self):
        """初始化缓存"""
        try:
            # 这里应该初始化Redis缓存连接
            # 由于没有具体的Redis配置，使用模拟实现
            self.cache = {
                'connected': True,
                'type': 'mock',
                'connection_time': asyncio.get_event_loop().time()
            }
            
            self.logger.info("缓存连接初始化完成", cache_type='mock')
            
        except Exception as e:
            self.logger.error("缓存连接初始化失败", error=str(e))
            raise
    
    async def start(self):
        """启动Fight服务器"""
        try:
            # 启动基础服务器
            await super().start()
            
            # 启动gRPC服务器
            if self.grpc_server and GRPC_AVAILABLE:
                await self.grpc_server.start()
                self.logger.info("gRPC服务器启动成功")
            
            # 启动业务服务
            for service_name, service in self.services.items():
                if hasattr(service, 'start'):
                    await service.start()
                    self.logger.info(f"业务服务启动完成: {service_name}")
            
            self.logger.info("Fight服务器启动完成", 
                           service_name=self.service_name,
                           host=self.config.host,
                           port=self.config.port)
            
        except Exception as e:
            self.logger.error("Fight服务器启动失败", 
                            service_name=self.service_name,
                            error=str(e))
            await self.stop()
            raise
    
    async def stop(self):
        """停止Fight服务器"""
        try:
            self.logger.info("正在停止Fight服务器...")
            
            # 停止gRPC服务器
            if self.grpc_server and GRPC_AVAILABLE:
                await self.grpc_server.stop(grace=5)
                self.logger.info("gRPC服务器停止完成")
            
            # 停止业务服务
            for service_name, service in self.services.items():
                if hasattr(service, 'stop'):
                    await service.stop()
                    self.logger.info(f"业务服务停止完成: {service_name}")
            
            # 清理资源
            await self._cleanup_resources()
            
            # 停止基础服务器
            await super().stop()
            
            self.logger.info("Fight服务器停止完成")
            
        except Exception as e:
            self.logger.error("Fight服务器停止失败", error=str(e))
            raise
    
    async def _cleanup_resources(self):
        """清理资源"""
        try:
            # 清理服务
            for service in self.services.values():
                if hasattr(service, 'cleanup'):
                    await service.cleanup()
            
            # 清理控制器
            for controller in self.controllers.values():
                if hasattr(controller, 'cleanup'):
                    await controller.cleanup()
            
            # 清理处理器
            if self.handler:
                await self.handler.cleanup()
            
            # 关闭数据库连接
            if self.database:
                self.database = None
            
            # 关闭缓存连接
            if self.cache:
                self.cache = None
            
            self.logger.info("资源清理完成")
            
        except Exception as e:
            self.logger.error("资源清理失败", error=str(e))
    
    async def get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        try:
            status = {
                'service_name': self.service_name,
                'status': 'running' if self.is_running else 'stopped',
                'start_time': self.start_time,
                'config': {
                    'host': self.config.host,
                    'port': self.config.port,
                    'max_concurrent_battles': self.fight_config.max_concurrent_battles,
                    'max_concurrent_matches': self.fight_config.max_concurrent_matches,
                    'battle_timeout': self.fight_config.battle_timeout,
                    'enable_battle_replay': self.fight_config.enable_battle_replay
                },
                'services': {},
                'controllers': {},
                'database': self.database is not None,
                'cache': self.cache is not None,
                'grpc_server': self.grpc_server is not None
            }
            
            # 获取服务状态
            for service_name, service in self.services.items():
                if hasattr(service, 'get_statistics'):
                    status['services'][service_name] = await service.get_statistics()
                else:
                    status['services'][service_name] = {'status': 'running'}
            
            # 获取控制器状态
            for controller_name, controller in self.controllers.items():
                if hasattr(controller, 'get_statistics'):
                    status['controllers'][controller_name] = await controller.get_statistics()
                else:
                    status['controllers'][controller_name] = {'status': 'running'}
            
            # 获取处理器状态
            if self.handler:
                status['handler'] = await self.handler.get_statistics()
            
            return status
            
        except Exception as e:
            self.logger.error("获取服务状态失败", error=str(e))
            return {'error': str(e)}
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        try:
            # 设置信号处理器
            def signal_handler(signum, frame):
                self.logger.info(f"收到信号 {signum}，正在优雅关闭...")
                asyncio.create_task(self.stop())
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            self.logger.info("信号处理器设置完成")
            
        except Exception as e:
            self.logger.error("信号处理器设置失败", error=str(e))


# 服务器启动函数
async def start_fight_server(config: Optional[FightServerConfig] = None):
    """启动Fight服务器"""
    server = FightServer(config)
    
    try:
        await server.initialize()
        await server.start()
        
        # 等待服务器运行
        while server.is_running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("收到键盘中断信号")
    except Exception as e:
        logger.error("服务器运行异常", error=str(e))
    finally:
        await server.stop()


# 主函数
def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Fight服务器')
    parser.add_argument('--port', type=int, help='服务端口')
    args = parser.parse_args()
    
    try:
        # 创建配置
        config = FightServerConfig()
        
        # 如果指定了端口，则覆盖配置
        if args.port:
            config.port = args.port
            logger.info(f"使用命令行指定的端口: {args.port}")
        
        # 启动服务器
        asyncio.run(start_fight_server(config))
        
    except Exception as e:
        logger.error("启动Fight服务器失败", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()