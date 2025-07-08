"""
网关控制器模块

该模块包含所有网关控制器的实现，负责处理不同类型的请求：
- 认证相关请求
- 游戏相关请求
- 聊天相关请求
"""

from .base_controller import BaseController, ControllerResponse
from .auth_controller import AuthController
from .game_controller import GameController
from .chat_controller import ChatController

__all__ = [
    'BaseController',
    'ControllerResponse',
    'AuthController',
    'GameController',
    'ChatController'
]
