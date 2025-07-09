"""
services/logic 模块

该模块提供了logic相关的功能实现。
"""

from ..base import BaseServer


class LogicServer(BaseServer):
    """逻辑服务"""
    
    def __init__(self):
        super().__init__()
        self.name = "logic_server"
        self.port = 8081
        
    async def start(self):
        """启动服务"""
        return True
        
    async def stop(self):
        """停止服务"""
        return True


# 导出服务
__all__ = ["LogicServer"]
