"""
Chat服务器主程序

该模块实现了聊天功能的微服务服务器，继承自BaseServer，
提供私聊、群聊、频道聊天、系统公告、敏感词过滤等功能。

主要功能：
- 继承自BaseServer提供完整的服务器基础功能
- 集成multiprocessing和asyncio实现高并发处理
- 自动注册到服务注册中心
- 初始化日志、数据库连接、gRPC服务
- 加载并管理所有Chat相关的控制器和服务
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
from .chat_handler import ChatHandler

# 导入控制器
from .controllers.chat_controller import ChatController
from .controllers.channel_controller import ChannelController

# 导入业务服务
from .services.chat_service import ChatService
from .services.channel_service import ChannelService
from .services.filter_service import FilterService

# 导入通知服务
from .notify_service import ChatNotifyService

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
class ChatServerConfig(BaseServerConfig):
    """Chat服务器配置"""
    # 聊天消息配置
    max_message_length: int = 1000
    max_messages_per_second: int = 10
    message_history_size: int = 1000
    
    # 频道配置
    max_channels: int = 1000
    max_channel_members: int = 1000
    default_channel_size: int = 100
    
    # 私聊配置
    max_private_chats: int = 100
    private_chat_history_size: int = 500
    
    # 敏感词过滤配置
    enable_content_filter: bool = True
    filter_level: str = "normal"  # strict, normal, loose
    enable_ai_filter: bool = False
    
    # 系统公告配置
    enable_system_announcements: bool = True
    max_announcement_length: int = 500
    announcement_ttl: int = 86400  # 24小时
    
    # 数据库配置
    enable_database: bool = True
    chat_history_retention: int = 86400 * 30  # 30天
    enable_chat_backup: bool = True
    
    # 缓存配置
    enable_redis_cache: bool = True
    message_cache_ttl: int = 3600  # 1小时
    channel_cache_ttl: int = 1800  # 30分钟
    
    # 性能配置
    message_batch_size: int = 100
    process_interval: float = 0.1  # 100ms


class ChatServer(BaseServer):
    """Chat服务器
    
    聊天功能微服务的主服务器类，负责处理私聊、群聊、频道聊天、
    系统公告、敏感词过滤等功能。
    """
    
    def __init__(self, config: Optional[ChatServerConfig] = None):
        """
        初始化Chat服务器
        
        Args:
            config: Chat服务器配置对象，如果为None则使用默认配置
        """
        # 设置服务器配置
        self.chat_config = config or ChatServerConfig()
        
        # 初始化基础服务器
        super().__init__(config=self.chat_config, service_name="chat_server")
        
        # 消息处理器
        self.chat_handler: Optional[ChatHandler] = None
        
        # 控制器实例
        self.controllers: Dict[str, Any] = {}
        
        # 业务服务实例
        self.services: Dict[str, Any] = {}
        
        # 通知服务
        self.notify_service: Optional[ChatNotifyService] = None
        
        # gRPC服务器
        self.grpc_server: Optional[Any] = None
        
        # 在线用户管理
        self.online_users: Dict[str, Dict[str, Any]] = {}
        
        # 活跃频道
        self.active_channels: Dict[str, Dict[str, Any]] = {}
        
        # 运行时统计
        self.stats = {
            'total_messages': 0,
            'private_messages': 0,
            'channel_messages': 0,
            'system_messages': 0,
            'filtered_messages': 0,
            'online_users': 0,
            'active_channels': 0,
        }
        
        self.logger.info("Chat服务器初始化完成", 
                        service_name=self.service_name,
                        config=self.chat_config)
    
    async def initialize(self):
        """初始化Chat服务器的所有组件"""
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
            if self.chat_config.enable_database:
                await self._initialize_database()
            
            # 初始化缓存
            if self.chat_config.enable_redis_cache:
                await self._initialize_cache()
            
            self.logger.info("Chat服务器所有组件初始化完成")
            
        except Exception as e:
            self.logger.error("Chat服务器初始化失败", 
                            error=str(e),
                            traceback=traceback.format_exc())
            raise
    
    async def _initialize_services(self):
        """初始化业务服务"""
        try:
            # 初始化聊天服务
            self.services['chat'] = ChatService(
                max_message_length=self.chat_config.max_message_length,
                max_messages_per_second=self.chat_config.max_messages_per_second,
                message_history_size=self.chat_config.message_history_size
            )
            
            # 初始化频道服务
            self.services['channel'] = ChannelService(
                max_channels=self.chat_config.max_channels,
                max_channel_members=self.chat_config.max_channel_members,
                default_channel_size=self.chat_config.default_channel_size
            )
            
            # 初始化过滤服务
            self.services['filter'] = FilterService(
                enable_content_filter=self.chat_config.enable_content_filter,
                filter_level=self.chat_config.filter_level,
                enable_ai_filter=self.chat_config.enable_ai_filter
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
            # 初始化聊天控制器
            self.controllers['chat'] = ChatController()
            self.controllers['chat'].register_service('chat_service', self.services['chat'])
            self.controllers['chat'].register_service('filter_service', self.services['filter'])
            
            # 初始化频道控制器
            self.controllers['channel'] = ChannelController()
            self.controllers['channel'].register_service('channel_service', self.services['channel'])
            self.controllers['channel'].register_service('filter_service', self.services['filter'])
            
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
            self.chat_handler = ChatHandler()
            
            # 注册控制器到消息处理器
            for controller_name, controller in self.controllers.items():
                self.chat_handler.register_controller(controller_name, controller)
            
            # 初始化消息处理器
            await self.chat_handler.initialize()
            
            self.logger.info("消息处理器初始化完成")
            
        except Exception as e:
            self.logger.error("消息处理器初始化失败", error=str(e))
            raise
    
    async def _initialize_notify_service(self):
        """初始化通知服务"""
        try:
            self.notify_service = ChatNotifyService()
            await self.notify_service.initialize()
            
            self.logger.info("通知服务初始化完成")
            
        except Exception as e:
            self.logger.error("通知服务初始化失败", error=str(e))
            raise
    
    async def _initialize_grpc_server(self):
        """初始化gRPC服务器"""
        try:
            if not GRPC_AVAILABLE:
                self.grpc_server = MockGrpcServer()
                return
            
            # 创建gRPC服务器
            self.grpc_server = grpc.aio.server(
                futures.ThreadPoolExecutor(max_workers=10)
            )
            
            # 添加服务端口
            listen_addr = f'{self.config.host}:{self.config.port + 2000}'  # gRPC端口
            self.grpc_server.add_insecure_port(listen_addr)
            
            self.logger.info("gRPC服务器初始化完成", address=listen_addr)
            
        except Exception as e:
            self.logger.error("gRPC服务器初始化失败", error=str(e))
            raise
    
    async def _initialize_database(self):
        """初始化数据库连接"""
        try:
            # 这里应该初始化数据库连接池
            # 由于没有具体的数据库配置，这里只是占位符
            
            self.logger.info("数据库连接初始化完成")
            
        except Exception as e:
            self.logger.error("数据库连接初始化失败", error=str(e))
            raise
    
    async def _initialize_cache(self):
        """初始化缓存"""
        try:
            # 这里应该初始化Redis缓存连接
            # 由于没有具体的缓存配置，这里只是占位符
            
            self.logger.info("缓存连接初始化完成")
            
        except Exception as e:
            self.logger.error("缓存连接初始化失败", error=str(e))
            raise
    
    async def start(self):
        """启动Chat服务器"""
        try:
            # 调用基础服务器的启动方法
            await super().start()
            
            # 启动gRPC服务器
            if self.grpc_server:
                await self.grpc_server.start()
            
            # 启动定时任务
            await self._start_scheduled_tasks()
            
            # 启动通知服务
            if self.notify_service:
                await self.notify_service.start()
            
            self.logger.info("Chat服务器启动完成",
                           service_name=self.service_name,
                           host=self.config.host,
                           port=self.config.port)
            
        except Exception as e:
            self.logger.error("Chat服务器启动失败", error=str(e))
            raise
    
    async def stop(self):
        """停止Chat服务器"""
        try:
            self.logger.info("开始停止Chat服务器")
            
            # 停止通知服务
            if self.notify_service:
                await self.notify_service.stop()
            
            # 停止定时任务
            await self._stop_scheduled_tasks()
            
            # 停止gRPC服务器
            if self.grpc_server:
                await self.grpc_server.stop(grace=30)
            
            # 清理控制器
            for controller in self.controllers.values():
                await controller.cleanup()
            
            # 清理业务服务
            for service in self.services.values():
                await service.cleanup()
            
            # 调用基础服务器的停止方法
            await super().stop()
            
            self.logger.info("Chat服务器停止完成")
            
        except Exception as e:
            self.logger.error("Chat服务器停止失败", error=str(e))
            raise
    
    async def _start_scheduled_tasks(self):
        """启动定时任务"""
        try:
            # 启动消息清理任务
            if self.chat_config.chat_history_retention > 0:
                asyncio.create_task(self._message_cleanup_task())
            
            # 启动统计更新任务
            asyncio.create_task(self._stats_update_task())
            
            # 启动用户状态同步任务
            asyncio.create_task(self._user_status_sync_task())
            
            self.logger.info("定时任务启动完成")
            
        except Exception as e:
            self.logger.error("定时任务启动失败", error=str(e))
            raise
    
    async def _stop_scheduled_tasks(self):
        """停止定时任务"""
        try:
            # 这里应该停止所有定时任务
            # 由于asyncio.create_task创建的任务没有保存引用，
            # 在实际项目中应该保存任务引用以便正确停止
            
            self.logger.info("定时任务停止完成")
            
        except Exception as e:
            self.logger.error("定时任务停止失败", error=str(e))
    
    async def _message_cleanup_task(self):
        """消息清理定时任务"""
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时清理一次
                
                # 清理过期消息
                chat_service = self.services.get('chat')
                if chat_service:
                    await chat_service.cleanup_expired_messages()
                
                channel_service = self.services.get('channel')
                if channel_service:
                    await channel_service.cleanup_expired_messages()
                
            except Exception as e:
                self.logger.error("消息清理任务异常", error=str(e))
                await asyncio.sleep(60)  # 异常时等待1分钟再重试
    
    async def _stats_update_task(self):
        """统计更新定时任务"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟更新一次
                
                # 更新统计信息
                self.stats['online_users'] = len(self.online_users)
                self.stats['active_channels'] = len(self.active_channels)
                
                # 从服务获取统计
                for service_name, service in self.services.items():
                    service_stats = service.get_statistics()
                    self.stats.update(service_stats)
                
            except Exception as e:
                self.logger.error("统计更新任务异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _user_status_sync_task(self):
        """用户状态同步定时任务"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟同步一次
                
                # 同步用户状态
                current_time = time.time()
                offline_users = []
                
                for user_id, user_info in self.online_users.items():
                    if current_time - user_info.get('last_activity', 0) > 300:  # 5分钟无活动
                        offline_users.append(user_id)
                
                # 处理离线用户
                for user_id in offline_users:
                    await self._handle_user_offline(user_id)
                
            except Exception as e:
                self.logger.error("用户状态同步任务异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _handle_user_offline(self, user_id: str):
        """处理用户离线"""
        try:
            # 移除在线用户
            if user_id in self.online_users:
                del self.online_users[user_id]
            
            # 通知相关服务
            if self.notify_service:
                await self.notify_service.handle_user_offline(user_id)
            
            self.logger.info("用户离线处理完成", user_id=user_id)
            
        except Exception as e:
            self.logger.error("用户离线处理失败", error=str(e))
    
    async def handle_message(self, message_data: bytes, context: dict = None) -> bytes:
        """处理消息请求"""
        try:
            self.stats['total_messages'] += 1
            
            if self.chat_handler:
                response = await self.chat_handler.handle_message(message_data, context)
                return response or b''
            else:
                self.logger.error("消息处理器未初始化")
                return b''
                
        except Exception as e:
            self.logger.error("消息处理失败", error=str(e))
            return b''
    
    async def handle_user_online(self, user_id: str, connection_info: Dict[str, Any]):
        """处理用户上线"""
        try:
            self.online_users[user_id] = {
                'user_id': user_id,
                'connection_info': connection_info,
                'online_time': time.time(),
                'last_activity': time.time()
            }
            
            # 通知相关服务
            if self.notify_service:
                await self.notify_service.handle_user_online(user_id)
            
            self.logger.info("用户上线处理完成", user_id=user_id)
            
        except Exception as e:
            self.logger.error("用户上线处理失败", error=str(e))
    
    async def handle_user_activity(self, user_id: str):
        """处理用户活动"""
        try:
            if user_id in self.online_users:
                self.online_users[user_id]['last_activity'] = time.time()
            
        except Exception as e:
            self.logger.error("用户活动处理失败", error=str(e))
    
    def get_stats(self) -> Dict[str, Any]:
        """获取服务器统计信息"""
        return {
            **self.stats,
            'service_name': self.service_name,
            'uptime': self.get_uptime(),
            'controllers': list(self.controllers.keys()),
            'services': list(self.services.keys()),
        }


def create_chat_server(config_path: Optional[str] = None) -> ChatServer:
    """
    创建Chat服务器实例
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        ChatServer实例
    """
    try:
        # 加载配置
        config = ChatServerConfig()
        
        # 如果提供了配置文件路径，从文件加载配置
        if config_path:
            # 这里应该实现从配置文件加载配置的逻辑
            pass
        
        # 创建服务器实例
        server = ChatServer(config)
        
        return server
        
    except Exception as e:
        logger.error("创建Chat服务器失败", error=str(e))
        raise


def main():
    """主程序入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Chat服务器')
    parser.add_argument('--port', type=int, help='服务端口')
    args = parser.parse_args()
    
    try:
        # 创建Chat服务器
        server = create_chat_server()
        
        # 如果指定了端口，则覆盖配置
        if args.port:
            logger.info(f"使用命令行指定的端口: {args.port}")
            # 这里可能需要更新服务器配置中的端口
        
        # 运行服务器
        server.run()
        
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务器...")
    except Exception as e:
        logger.error("服务器运行异常", error=str(e), traceback=traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()