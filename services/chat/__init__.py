"""
services/chat 模块

该模块提供了chat相关的功能实现。
"""

from ..base import BaseServer


class ChatServer(BaseServer):
    """聊天服务"""
    
    def __init__(self):
        super().__init__()
        self.name = "chat_server"
        self.port = 8082
        
    async def start(self):
        """启动服务"""
        return True
        
    async def stop(self):
        """停止服务"""
        return True


# 导出服务
__all__ = ["ChatServer"]
