"""
services 模块

该模块提供了services相关的功能实现。
"""

# 导入所有服务
from .base import *

# 服务类的简单实现用于测试
class GateServer:
    """网关服务"""
    def __init__(self):
        self.name = "gate_server"
        self.port = 8080
        
    async def start(self):
        """启动服务"""
        return True
        
    async def stop(self):
        """停止服务"""
        return True


class LogicServer:
    """逻辑服务"""
    def __init__(self):
        self.name = "logic_server"
        self.port = 8081
        
    async def start(self):
        """启动服务"""
        return True
        
    async def stop(self):
        """停止服务"""
        return True


class ChatServer:
    """聊天服务"""
    def __init__(self):
        self.name = "chat_server"
        self.port = 8082
        
    async def start(self):
        """启动服务"""
        return True
        
    async def stop(self):
        """停止服务"""
        return True


class FightServer:
    """战斗服务"""
    def __init__(self):
        self.name = "fight_server"
        self.port = 8083
        
    async def start(self):
        """启动服务"""
        return True
        
    async def stop(self):
        """停止服务"""
        return True


# 导出所有服务
__all__ = [
    "GateServer",
    "LogicServer", 
    "ChatServer",
    "FightServer"
]
