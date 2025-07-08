"""
游戏控制器

该模块实现了游戏相关的控制器，继承自BaseController，
负责处理游戏房间管理、游戏状态同步、任务系统、排行榜等功能。

主要功能：
- 游戏房间创建和管理
- 游戏状态同步和更新
- 任务系统管理
- 排行榜查询和更新
- 游戏操作处理

支持的操作：
- 创建/加入/离开游戏房间
- 游戏状态同步
- 任务管理（获取、接受、完成任务）
- 排行榜查询
- 游戏数据统计
"""

import asyncio
import time
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from services.base import BaseController, ControllerConfig
from services.base import ValidationException, AuthorizationException, BusinessException
from common.logger import logger
from common.decorator import handler, controller

# 导入协议定义
try:
    from common.proto import BaseRequest, BaseResponse
    PROTO_AVAILABLE = True
except ImportError:
    logger.warning("协议模块不可用，使用模拟类型")
    PROTO_AVAILABLE = False
    
    @dataclass
    class BaseRequest:
        message_id: int = 0
        user_id: Optional[str] = None
        session_id: Optional[str] = None
        timestamp: float = 0.0
        data: Dict[str, Any] = None
    
    @dataclass
    class BaseResponse:
        message_id: int = 0
        status: str = "success"
        code: int = 200
        message: str = ""
        data: Dict[str, Any] = None
        timestamp: float = 0.0


class GameRoomStatus(Enum):
    """游戏房间状态"""
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"
    PAUSED = "paused"


class TaskStatus(Enum):
    """任务状态"""
    AVAILABLE = "available"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    REWARDED = "rewarded"
    EXPIRED = "expired"


# 游戏房间相关协议
@dataclass
class CreateGameRoomRequest(BaseRequest):
    """创建游戏房间请求"""
    room_name: str = ""
    game_type: str = ""
    max_players: int = 2
    room_config: Dict[str, Any] = None
    is_private: bool = False
    password: Optional[str] = None


@dataclass
class CreateGameRoomResponse(BaseResponse):
    """创建游戏房间响应"""
    room_id: str = ""
    room_info: Dict[str, Any] = None


@dataclass
class JoinGameRoomRequest(BaseRequest):
    """加入游戏房间请求"""
    room_id: str = ""
    password: Optional[str] = None
    position: Optional[int] = None


@dataclass
class JoinGameRoomResponse(BaseResponse):
    """加入游戏房间响应"""
    room_info: Dict[str, Any] = None
    player_info: Dict[str, Any] = None


@dataclass
class LeaveGameRoomRequest(BaseRequest):
    """离开游戏房间请求"""
    room_id: str = ""
    leave_reason: str = "normal"


@dataclass
class LeaveGameRoomResponse(BaseResponse):
    """离开游戏房间响应"""
    leave_time: float = 0.0


@dataclass
class GameStateSyncRequest(BaseRequest):
    """游戏状态同步请求"""
    room_id: str = ""
    action_type: str = ""
    action_data: Dict[str, Any] = None
    sequence_id: int = 0


@dataclass
class GameStateSyncResponse(BaseResponse):
    """游戏状态同步响应"""
    room_state: Dict[str, Any] = None
    updated_players: List[Dict[str, Any]] = None
    sequence_id: int = 0


# 任务系统相关协议
@dataclass
class GetTaskListRequest(BaseRequest):
    """获取任务列表请求"""
    task_type: str = "all"  # all, daily, weekly, achievement
    status: str = "all"  # all, available, accepted, completed


@dataclass
class GetTaskListResponse(BaseResponse):
    """获取任务列表响应"""
    tasks: List[Dict[str, Any]] = None
    total_count: int = 0


@dataclass
class AcceptTaskRequest(BaseRequest):
    """接受任务请求"""
    task_id: str = ""


@dataclass
class AcceptTaskResponse(BaseResponse):
    """接受任务响应"""
    task_info: Dict[str, Any] = None


@dataclass
class CompleteTaskRequest(BaseRequest):
    """完成任务请求"""
    task_id: str = ""
    completion_data: Dict[str, Any] = None


@dataclass
class CompleteTaskResponse(BaseResponse):
    """完成任务响应"""
    task_info: Dict[str, Any] = None
    rewards: List[Dict[str, Any]] = None


# 排行榜相关协议
@dataclass
class GetLeaderboardRequest(BaseRequest):
    """获取排行榜请求"""
    leaderboard_type: str = ""  # level, score, achievement
    page: int = 1
    page_size: int = 50
    season_id: Optional[str] = None


@dataclass
class GetLeaderboardResponse(BaseResponse):
    """获取排行榜响应"""
    leaderboard_data: List[Dict[str, Any]] = None
    my_rank: Optional[Dict[str, Any]] = None
    total_count: int = 0
    season_info: Optional[Dict[str, Any]] = None


@controller(name="GameController")
class GameController(BaseController):
    """游戏控制器
    
    处理所有游戏相关的请求，包括房间管理、状态同步、任务系统、排行榜等。
    """
    
    def __init__(self, config: Optional[ControllerConfig] = None):
        """初始化游戏控制器"""
        super().__init__(config)
        
        # 游戏服务
        self.game_service = None
        
        # 游戏房间管理
        self.active_rooms: Dict[str, Dict[str, Any]] = {}
        self.player_room_mapping: Dict[str, str] = {}  # user_id -> room_id
        
        # 任务系统配置
        self.max_daily_tasks = 50
        self.max_weekly_tasks = 20
        self.task_refresh_times = {
            "daily": "00:00",
            "weekly": "monday_00:00"
        }
        
        # 排行榜配置
        self.leaderboard_types = {
            "level": {"name": "等级排行榜", "field": "level"},
            "score": {"name": "积分排行榜", "field": "score"},
            "achievement": {"name": "成就排行榜", "field": "achievement_count"}
        }
        
        # 游戏状态缓存
        self.game_state_cache: Dict[str, Dict[str, Any]] = {}
        
        # 任务进度缓存
        self.task_progress_cache: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info("游戏控制器初始化完成")
    
    async def initialize(self):
        """初始化游戏控制器"""
        try:
            await super().initialize()
            
            # 获取游戏服务
            self.game_service = self.get_service("game_service")
            if not self.game_service:
                raise ValueError("游戏服务未注册")
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_inactive_rooms())
            asyncio.create_task(self._task_refresh_scheduler())
            asyncio.create_task(self._sync_game_states())
            
            self.logger.info("游戏控制器初始化完成")
            
        except Exception as e:
            self.logger.error("游戏控制器初始化失败", error=str(e))
            raise
    
    @handler(CreateGameRoomRequest, CreateGameRoomResponse)
    async def handle_create_game_room(self, request: CreateGameRoomRequest, context=None) -> CreateGameRoomResponse:
        """
        处理创建游戏房间请求
        
        Args:
            request: 创建游戏房间请求
            context: 请求上下文
            
        Returns:
            CreateGameRoomResponse: 创建游戏房间响应
        """
        try:
            # 参数验证
            if not request.room_name or not request.game_type:
                raise ValidationException("房间名称和游戏类型不能为空")
            
            if request.max_players < 1 or request.max_players > 100:
                raise ValidationException("玩家数量必须在1-100之间")
            
            # 检查用户是否已在其他房间
            if request.user_id in self.player_room_mapping:
                raise BusinessException("用户已在其他房间中")
            
            # 调用游戏服务创建房间
            room_info = await self.game_service.create_game_room(
                creator_id=request.user_id,
                room_name=request.room_name,
                game_type=request.game_type,
                max_players=request.max_players,
                room_config=request.room_config or {},
                is_private=request.is_private,
                password=request.password
            )
            
            # 记录房间信息
            self.active_rooms[room_info["room_id"]] = room_info
            self.player_room_mapping[request.user_id] = room_info["room_id"]
            
            # 构造响应
            response = CreateGameRoomResponse(
                message_id=request.message_id,
                room_id=room_info["room_id"],
                room_info=room_info,
                timestamp=time.time()
            )
            
            self.logger.info("创建游戏房间成功",
                           user_id=request.user_id,
                           room_id=room_info["room_id"],
                           game_type=request.game_type)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("创建游戏房间参数验证失败", error=str(e))
            raise
        except BusinessException as e:
            self.logger.warning("创建游戏房间业务异常", error=str(e))
            raise
        except Exception as e:
            self.logger.error("创建游戏房间处理异常", error=str(e))
            raise BusinessException(f"创建游戏房间失败: {str(e)}")
    
    @handler(JoinGameRoomRequest, JoinGameRoomResponse)
    async def handle_join_game_room(self, request: JoinGameRoomRequest, context=None) -> JoinGameRoomResponse:
        """
        处理加入游戏房间请求
        
        Args:
            request: 加入游戏房间请求
            context: 请求上下文
            
        Returns:
            JoinGameRoomResponse: 加入游戏房间响应
        """
        try:
            # 参数验证
            if not request.room_id:
                raise ValidationException("房间ID不能为空")
            
            # 检查用户是否已在其他房间
            if request.user_id in self.player_room_mapping:
                raise BusinessException("用户已在其他房间中")
            
            # 检查房间是否存在
            room_info = self.active_rooms.get(request.room_id)
            if not room_info:
                raise BusinessException("房间不存在")
            
            # 检查房间状态
            if room_info["status"] != GameRoomStatus.WAITING.value:
                raise BusinessException("房间不在等待状态")
            
            # 检查房间是否已满
            if len(room_info["players"]) >= room_info["max_players"]:
                raise BusinessException("房间已满")
            
            # 检查密码
            if room_info["is_private"] and room_info["password"] != request.password:
                raise AuthorizationException("房间密码错误")
            
            # 调用游戏服务加入房间
            player_info = await self.game_service.join_game_room(
                user_id=request.user_id,
                room_id=request.room_id,
                position=request.position
            )
            
            # 更新房间信息
            room_info["players"].append(player_info)
            self.player_room_mapping[request.user_id] = request.room_id
            
            # 构造响应
            response = JoinGameRoomResponse(
                message_id=request.message_id,
                room_info=room_info,
                player_info=player_info,
                timestamp=time.time()
            )
            
            self.logger.info("加入游戏房间成功",
                           user_id=request.user_id,
                           room_id=request.room_id)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("加入游戏房间参数验证失败", error=str(e))
            raise
        except AuthorizationException as e:
            self.logger.warning("加入游戏房间认证失败", error=str(e))
            raise
        except BusinessException as e:
            self.logger.warning("加入游戏房间业务异常", error=str(e))
            raise
        except Exception as e:
            self.logger.error("加入游戏房间处理异常", error=str(e))
            raise BusinessException(f"加入游戏房间失败: {str(e)}")
    
    @handler(LeaveGameRoomRequest, LeaveGameRoomResponse)
    async def handle_leave_game_room(self, request: LeaveGameRoomRequest, context=None) -> LeaveGameRoomResponse:
        """
        处理离开游戏房间请求
        
        Args:
            request: 离开游戏房间请求
            context: 请求上下文
            
        Returns:
            LeaveGameRoomResponse: 离开游戏房间响应
        """
        try:
            # 参数验证
            if not request.room_id:
                raise ValidationException("房间ID不能为空")
            
            # 检查用户是否在房间中
            if request.user_id not in self.player_room_mapping:
                raise BusinessException("用户不在任何房间中")
            
            current_room_id = self.player_room_mapping[request.user_id]
            if current_room_id != request.room_id:
                raise BusinessException("用户不在指定房间中")
            
            # 调用游戏服务离开房间
            await self.game_service.leave_game_room(
                user_id=request.user_id,
                room_id=request.room_id,
                leave_reason=request.leave_reason
            )
            
            # 更新房间信息
            room_info = self.active_rooms.get(request.room_id)
            if room_info:
                room_info["players"] = [
                    player for player in room_info["players"]
                    if player["user_id"] != request.user_id
                ]
                
                # 如果房间为空，标记为可清理
                if not room_info["players"]:
                    room_info["status"] = GameRoomStatus.FINISHED.value
                    room_info["finish_time"] = time.time()
            
            # 移除玩家房间映射
            del self.player_room_mapping[request.user_id]
            
            leave_time = time.time()
            
            # 构造响应
            response = LeaveGameRoomResponse(
                message_id=request.message_id,
                leave_time=leave_time,
                timestamp=leave_time
            )
            
            self.logger.info("离开游戏房间成功",
                           user_id=request.user_id,
                           room_id=request.room_id)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("离开游戏房间参数验证失败", error=str(e))
            raise
        except BusinessException as e:
            self.logger.warning("离开游戏房间业务异常", error=str(e))
            raise
        except Exception as e:
            self.logger.error("离开游戏房间处理异常", error=str(e))
            raise BusinessException(f"离开游戏房间失败: {str(e)}")
    
    @handler(GameStateSyncRequest, GameStateSyncResponse)
    async def handle_game_state_sync(self, request: GameStateSyncRequest, context=None) -> GameStateSyncResponse:
        """
        处理游戏状态同步请求
        
        Args:
            request: 游戏状态同步请求
            context: 请求上下文
            
        Returns:
            GameStateSyncResponse: 游戏状态同步响应
        """
        try:
            # 参数验证
            if not request.room_id or not request.action_type:
                raise ValidationException("房间ID和操作类型不能为空")
            
            # 检查用户是否在房间中
            if request.user_id not in self.player_room_mapping:
                raise BusinessException("用户不在任何房间中")
            
            current_room_id = self.player_room_mapping[request.user_id]
            if current_room_id != request.room_id:
                raise BusinessException("用户不在指定房间中")
            
            # 调用游戏服务同步状态
            sync_result = await self.game_service.sync_game_state(
                user_id=request.user_id,
                room_id=request.room_id,
                action_type=request.action_type,
                action_data=request.action_data or {},
                sequence_id=request.sequence_id
            )
            
            # 更新游戏状态缓存
            self.game_state_cache[request.room_id] = sync_result["room_state"]
            
            # 构造响应
            response = GameStateSyncResponse(
                message_id=request.message_id,
                room_state=sync_result["room_state"],
                updated_players=sync_result.get("updated_players", []),
                sequence_id=sync_result.get("sequence_id", request.sequence_id + 1),
                timestamp=time.time()
            )
            
            self.logger.info("游戏状态同步成功",
                           user_id=request.user_id,
                           room_id=request.room_id,
                           action_type=request.action_type)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("游戏状态同步参数验证失败", error=str(e))
            raise
        except BusinessException as e:
            self.logger.warning("游戏状态同步业务异常", error=str(e))
            raise
        except Exception as e:
            self.logger.error("游戏状态同步处理异常", error=str(e))
            raise BusinessException(f"游戏状态同步失败: {str(e)}")
    
    @handler(GetTaskListRequest, GetTaskListResponse)
    async def handle_get_task_list(self, request: GetTaskListRequest, context=None) -> GetTaskListResponse:
        """
        处理获取任务列表请求
        
        Args:
            request: 获取任务列表请求
            context: 请求上下文
            
        Returns:
            GetTaskListResponse: 获取任务列表响应
        """
        try:
            # 调用游戏服务获取任务列表
            task_result = await self.game_service.get_task_list(
                user_id=request.user_id,
                task_type=request.task_type,
                status=request.status
            )
            
            # 构造响应
            response = GetTaskListResponse(
                message_id=request.message_id,
                tasks=task_result["tasks"],
                total_count=task_result["total_count"],
                timestamp=time.time()
            )
            
            self.logger.info("获取任务列表成功",
                           user_id=request.user_id,
                           task_type=request.task_type,
                           task_count=len(task_result["tasks"]))
            
            return response
            
        except Exception as e:
            self.logger.error("获取任务列表处理异常", error=str(e))
            raise BusinessException(f"获取任务列表失败: {str(e)}")
    
    @handler(AcceptTaskRequest, AcceptTaskResponse)
    async def handle_accept_task(self, request: AcceptTaskRequest, context=None) -> AcceptTaskResponse:
        """
        处理接受任务请求
        
        Args:
            request: 接受任务请求
            context: 请求上下文
            
        Returns:
            AcceptTaskResponse: 接受任务响应
        """
        try:
            # 参数验证
            if not request.task_id:
                raise ValidationException("任务ID不能为空")
            
            # 调用游戏服务接受任务
            task_info = await self.game_service.accept_task(
                user_id=request.user_id,
                task_id=request.task_id
            )
            
            # 构造响应
            response = AcceptTaskResponse(
                message_id=request.message_id,
                task_info=task_info,
                timestamp=time.time()
            )
            
            self.logger.info("接受任务成功",
                           user_id=request.user_id,
                           task_id=request.task_id)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("接受任务参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("接受任务处理异常", error=str(e))
            raise BusinessException(f"接受任务失败: {str(e)}")
    
    @handler(CompleteTaskRequest, CompleteTaskResponse)
    async def handle_complete_task(self, request: CompleteTaskRequest, context=None) -> CompleteTaskResponse:
        """
        处理完成任务请求
        
        Args:
            request: 完成任务请求
            context: 请求上下文
            
        Returns:
            CompleteTaskResponse: 完成任务响应
        """
        try:
            # 参数验证
            if not request.task_id:
                raise ValidationException("任务ID不能为空")
            
            # 调用游戏服务完成任务
            completion_result = await self.game_service.complete_task(
                user_id=request.user_id,
                task_id=request.task_id,
                completion_data=request.completion_data or {}
            )
            
            # 构造响应
            response = CompleteTaskResponse(
                message_id=request.message_id,
                task_info=completion_result["task_info"],
                rewards=completion_result.get("rewards", []),
                timestamp=time.time()
            )
            
            self.logger.info("完成任务成功",
                           user_id=request.user_id,
                           task_id=request.task_id,
                           rewards=len(completion_result.get("rewards", [])))
            
            return response
            
        except ValidationException as e:
            self.logger.warning("完成任务参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("完成任务处理异常", error=str(e))
            raise BusinessException(f"完成任务失败: {str(e)}")
    
    @handler(GetLeaderboardRequest, GetLeaderboardResponse)
    async def handle_get_leaderboard(self, request: GetLeaderboardRequest, context=None) -> GetLeaderboardResponse:
        """
        处理获取排行榜请求
        
        Args:
            request: 获取排行榜请求
            context: 请求上下文
            
        Returns:
            GetLeaderboardResponse: 获取排行榜响应
        """
        try:
            # 参数验证
            if not request.leaderboard_type:
                raise ValidationException("排行榜类型不能为空")
            
            if request.leaderboard_type not in self.leaderboard_types:
                raise ValidationException(f"不支持的排行榜类型: {request.leaderboard_type}")
            
            if request.page < 1 or request.page_size < 1 or request.page_size > 100:
                raise ValidationException("页码和页面大小参数无效")
            
            # 调用游戏服务获取排行榜
            leaderboard_result = await self.game_service.get_leaderboard(
                user_id=request.user_id,
                leaderboard_type=request.leaderboard_type,
                page=request.page,
                page_size=request.page_size,
                season_id=request.season_id
            )
            
            # 构造响应
            response = GetLeaderboardResponse(
                message_id=request.message_id,
                leaderboard_data=leaderboard_result["leaderboard_data"],
                my_rank=leaderboard_result.get("my_rank"),
                total_count=leaderboard_result["total_count"],
                season_info=leaderboard_result.get("season_info"),
                timestamp=time.time()
            )
            
            self.logger.info("获取排行榜成功",
                           user_id=request.user_id,
                           leaderboard_type=request.leaderboard_type,
                           page=request.page)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("获取排行榜参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取排行榜处理异常", error=str(e))
            raise BusinessException(f"获取排行榜失败: {str(e)}")
    
    async def _cleanup_inactive_rooms(self):
        """清理非活跃房间"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                
                current_time = time.time()
                inactive_rooms = []
                
                for room_id, room_info in self.active_rooms.items():
                    # 检查房间是否已结束或超时
                    if (room_info["status"] == GameRoomStatus.FINISHED.value or
                        current_time - room_info.get("last_activity", 0) > 1800):  # 30分钟无活动
                        inactive_rooms.append(room_id)
                
                # 清理非活跃房间
                for room_id in inactive_rooms:
                    room_info = self.active_rooms.pop(room_id)
                    
                    # 清理玩家房间映射
                    for player in room_info.get("players", []):
                        if player["user_id"] in self.player_room_mapping:
                            del self.player_room_mapping[player["user_id"]]
                    
                    # 清理游戏状态缓存
                    if room_id in self.game_state_cache:
                        del self.game_state_cache[room_id]
                    
                    self.logger.info("清理非活跃房间",
                                   room_id=room_id,
                                   status=room_info["status"])
                
            except Exception as e:
                self.logger.error("清理非活跃房间异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _task_refresh_scheduler(self):
        """任务刷新调度器"""
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时检查一次
                
                current_time = datetime.now()
                
                # 检查日常任务刷新
                if current_time.hour == 0 and current_time.minute == 0:
                    await self.game_service.refresh_daily_tasks()
                    self.logger.info("日常任务刷新完成")
                
                # 检查周常任务刷新
                if current_time.weekday() == 0 and current_time.hour == 0 and current_time.minute == 0:
                    await self.game_service.refresh_weekly_tasks()
                    self.logger.info("周常任务刷新完成")
                
            except Exception as e:
                self.logger.error("任务刷新调度异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _sync_game_states(self):
        """同步游戏状态"""
        while True:
            try:
                await asyncio.sleep(30)  # 每30秒同步一次
                
                # 同步所有活跃房间的状态
                for room_id, room_info in self.active_rooms.items():
                    if room_info["status"] == GameRoomStatus.PLAYING.value:
                        await self.game_service.sync_room_state(room_id, room_info)
                
            except Exception as e:
                self.logger.error("同步游戏状态异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            await super().cleanup()
            
            # 清理所有房间
            for room_id, room_info in self.active_rooms.items():
                await self.game_service.cleanup_room(room_id)
            
            self.active_rooms.clear()
            self.player_room_mapping.clear()
            self.game_state_cache.clear()
            self.task_progress_cache.clear()
            
            self.logger.info("游戏控制器资源清理完成")
            
        except Exception as e:
            self.logger.error("游戏控制器资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            "active_rooms": len(self.active_rooms),
            "active_players": len(self.player_room_mapping),
            "game_state_cache": len(self.game_state_cache),
            "task_progress_cache": len(self.task_progress_cache),
            "controller_name": self.__class__.__name__,
            "leaderboard_types": list(self.leaderboard_types.keys()),
            "max_daily_tasks": self.max_daily_tasks,
            "max_weekly_tasks": self.max_weekly_tasks
        }


def create_game_controller(config: Optional[ControllerConfig] = None) -> GameController:
    """
    创建游戏控制器实例
    
    Args:
        config: 控制器配置
        
    Returns:
        GameController实例
    """
    try:
        controller = GameController(config)
        logger.info("游戏控制器创建成功")
        return controller
        
    except Exception as e:
        logger.error("创建游戏控制器失败", error=str(e))
        raise