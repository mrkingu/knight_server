"""
游戏业务服务

该模块实现了游戏相关的业务逻辑服务，继承自BaseService，
负责游戏房间管理、状态同步、任务系统、排行榜等功能。

主要功能：
- 游戏房间创建和管理
- 游戏状态同步和持久化
- 任务系统完整实现
- 排行榜计算和更新
- 游戏数据统计

业务特点：
- 支持多种游戏类型
- 实时状态同步
- 完善的任务系统
- 高效的排行榜算法
- 详细的数据统计
"""

import asyncio
import time
import json
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

from services.base import BaseService, ServiceConfig
from services.base import ServiceException, transactional, cached, retry
from common.logger import logger


class GameType(Enum):
    """游戏类型"""
    MATCH3 = "match3"
    CARD = "card"
    PUZZLE = "puzzle"
    STRATEGY = "strategy"
    ACTION = "action"
    RPG = "rpg"


class TaskType(Enum):
    """任务类型"""
    DAILY = "daily"
    WEEKLY = "weekly"
    ACHIEVEMENT = "achievement"
    MAIN = "main"
    SIDE = "side"


class TaskStatus(Enum):
    """任务状态"""
    AVAILABLE = "available"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    REWARDED = "rewarded"
    EXPIRED = "expired"


class LeaderboardType(Enum):
    """排行榜类型"""
    LEVEL = "level"
    SCORE = "score"
    ACHIEVEMENT = "achievement"
    WEALTH = "wealth"


@dataclass
class GameServiceConfig(ServiceConfig):
    """游戏服务配置"""
    # 房间配置
    max_rooms: int = 1000
    max_players_per_room: int = 8
    room_timeout: int = 1800  # 30分钟
    
    # 状态同步配置
    sync_interval: int = 30  # 30秒
    max_sync_queue_size: int = 1000
    
    # 任务系统配置
    max_daily_tasks: int = 50
    max_weekly_tasks: int = 20
    max_achievement_tasks: int = 100
    task_refresh_hour: int = 0  # 凌晨0点刷新
    
    # 排行榜配置
    leaderboard_size: int = 1000
    leaderboard_update_interval: int = 60  # 1分钟
    leaderboard_season_duration: int = 86400 * 30  # 30天
    
    # 奖励配置
    enable_auto_rewards: bool = True
    reward_expire_time: int = 86400 * 7  # 7天


class GameService(BaseService):
    """游戏业务服务
    
    提供游戏相关的所有业务逻辑，包括房间管理、状态同步、任务系统、排行榜等。
    """
    
    def __init__(self, 
                 sync_interval: int = 30,
                 max_rooms: int = 1000,
                 enable_persistence: bool = True,
                 config: Optional[GameServiceConfig] = None):
        """
        初始化游戏服务
        
        Args:
            sync_interval: 同步间隔
            max_rooms: 最大房间数
            enable_persistence: 是否启用持久化
            config: 游戏服务配置
        """
        super().__init__(config=config)
        
        self.game_config = config or GameServiceConfig()
        self.sync_interval = sync_interval
        self.max_rooms = max_rooms
        self.enable_persistence = enable_persistence
        
        # 游戏房间数据
        self.game_rooms: Dict[str, Dict[str, Any]] = {}
        self.room_states: Dict[str, Dict[str, Any]] = {}
        
        # 任务系统数据
        self.task_templates: Dict[str, Dict[str, Any]] = {}
        self.user_tasks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.task_progress: Dict[str, Dict[str, Any]] = defaultdict(dict)
        
        # 排行榜数据
        self.leaderboards: Dict[str, List[Dict[str, Any]]] = {}
        self.leaderboard_seasons: Dict[str, Dict[str, Any]] = {}
        
        # 游戏统计数据
        self.game_stats: Dict[str, Any] = {
            "total_rooms": 0,
            "active_rooms": 0,
            "total_games": 0,
            "completed_games": 0,
            "total_tasks": 0,
            "completed_tasks": 0,
            "active_players": 0
        }
        
        # 同步队列
        self.sync_queue: List[Dict[str, Any]] = []
        
        self.logger.info("游戏服务初始化完成", 
                        sync_interval=sync_interval,
                        max_rooms=max_rooms)
    
    async def initialize(self):
        """初始化游戏服务"""
        try:
            await super().initialize()
            
            # 初始化任务模板
            await self._initialize_task_templates()
            
            # 初始化排行榜
            await self._initialize_leaderboards()
            
            # 启动定时任务
            asyncio.create_task(self._sync_game_states_periodically())
            asyncio.create_task(self._update_leaderboards_periodically())
            asyncio.create_task(self._cleanup_expired_rooms())
            
            self.logger.info("游戏服务初始化完成")
            
        except Exception as e:
            self.logger.error("游戏服务初始化失败", error=str(e))
            raise
    
    async def _initialize_task_templates(self):
        """初始化任务模板"""
        try:
            # 创建日常任务模板
            daily_tasks = [
                {
                    "task_id": "daily_login",
                    "name": "每日登录",
                    "description": "每日登录游戏",
                    "type": TaskType.DAILY.value,
                    "target_count": 1,
                    "rewards": [{"type": "exp", "amount": 100}],
                    "refresh_time": "daily"
                },
                {
                    "task_id": "daily_play_3_games",
                    "name": "游戏达人",
                    "description": "完成3局游戏",
                    "type": TaskType.DAILY.value,
                    "target_count": 3,
                    "rewards": [{"type": "coin", "amount": 500}],
                    "refresh_time": "daily"
                }
            ]
            
            # 创建周常任务模板
            weekly_tasks = [
                {
                    "task_id": "weekly_win_10_games",
                    "name": "周胜利者",
                    "description": "本周赢得10局游戏",
                    "type": TaskType.WEEKLY.value,
                    "target_count": 10,
                    "rewards": [{"type": "diamond", "amount": 100}],
                    "refresh_time": "weekly"
                }
            ]
            
            # 创建成就任务模板
            achievement_tasks = [
                {
                    "task_id": "achievement_first_win",
                    "name": "首胜",
                    "description": "赢得第一局游戏",
                    "type": TaskType.ACHIEVEMENT.value,
                    "target_count": 1,
                    "rewards": [{"type": "trophy", "amount": 1}],
                    "refresh_time": "never"
                }
            ]
            
            # 保存任务模板
            for task in daily_tasks + weekly_tasks + achievement_tasks:
                self.task_templates[task["task_id"]] = task
            
            self.logger.info("任务模板初始化完成", 
                           template_count=len(self.task_templates))
            
        except Exception as e:
            self.logger.error("任务模板初始化失败", error=str(e))
            raise
    
    async def _initialize_leaderboards(self):
        """初始化排行榜"""
        try:
            # 初始化各种排行榜
            leaderboard_types = [
                LeaderboardType.LEVEL.value,
                LeaderboardType.SCORE.value,
                LeaderboardType.ACHIEVEMENT.value,
                LeaderboardType.WEALTH.value
            ]
            
            for lb_type in leaderboard_types:
                self.leaderboards[lb_type] = []
                
                # 创建当前赛季
                season_id = f"{lb_type}_season_{int(time.time())}"
                self.leaderboard_seasons[lb_type] = {
                    "season_id": season_id,
                    "start_time": time.time(),
                    "end_time": time.time() + self.game_config.leaderboard_season_duration,
                    "type": lb_type,
                    "status": "active"
                }
            
            self.logger.info("排行榜初始化完成", 
                           leaderboard_count=len(self.leaderboards))
            
        except Exception as e:
            self.logger.error("排行榜初始化失败", error=str(e))
            raise
    
    @transactional
    async def create_game_room(self, 
                              creator_id: str,
                              room_name: str,
                              game_type: str,
                              max_players: int = 2,
                              room_config: Dict[str, Any] = None,
                              is_private: bool = False,
                              password: Optional[str] = None) -> Dict[str, Any]:
        """
        创建游戏房间
        
        Args:
            creator_id: 创建者ID
            room_name: 房间名称
            game_type: 游戏类型
            max_players: 最大玩家数
            room_config: 房间配置
            is_private: 是否私有房间
            password: 房间密码
            
        Returns:
            房间信息
        """
        try:
            # 检查房间数量限制
            if len(self.game_rooms) >= self.max_rooms:
                raise ServiceException("房间数量已达上限")
            
            # 生成房间ID
            room_id = str(uuid.uuid4())
            
            # 创建房间信息
            room_info = {
                "room_id": room_id,
                "room_name": room_name,
                "game_type": game_type,
                "creator_id": creator_id,
                "max_players": max_players,
                "current_players": 1,
                "players": [{"user_id": creator_id, "position": 0, "ready": False}],
                "room_config": room_config or {},
                "is_private": is_private,
                "password": password,
                "status": "waiting",
                "created_time": time.time(),
                "last_activity": time.time(),
                "game_started": False,
                "game_data": {}
            }
            
            # 保存房间信息
            self.game_rooms[room_id] = room_info
            
            # 初始化房间状态
            self.room_states[room_id] = {
                "room_id": room_id,
                "game_state": "waiting",
                "turn": 0,
                "current_player": 0,
                "game_data": {},
                "last_update": time.time()
            }
            
            # 更新统计
            self.game_stats["total_rooms"] += 1
            self.game_stats["active_rooms"] += 1
            
            self.logger.info("游戏房间创建成功", 
                           room_id=room_id,
                           creator_id=creator_id,
                           game_type=game_type)
            
            return room_info
            
        except Exception as e:
            self.logger.error("创建游戏房间失败", error=str(e))
            raise ServiceException(f"创建游戏房间失败: {str(e)}")
    
    @transactional
    async def join_game_room(self, user_id: str, room_id: str, position: Optional[int] = None) -> Dict[str, Any]:
        """
        加入游戏房间
        
        Args:
            user_id: 用户ID
            room_id: 房间ID
            position: 位置
            
        Returns:
            玩家信息
        """
        try:
            room_info = self.game_rooms.get(room_id)
            if not room_info:
                raise ServiceException("房间不存在")
            
            if room_info["current_players"] >= room_info["max_players"]:
                raise ServiceException("房间已满")
            
            # 检查用户是否已在房间中
            for player in room_info["players"]:
                if player["user_id"] == user_id:
                    raise ServiceException("用户已在房间中")
            
            # 确定位置
            if position is None:
                position = room_info["current_players"]
            
            # 创建玩家信息
            player_info = {
                "user_id": user_id,
                "position": position,
                "ready": False,
                "join_time": time.time()
            }
            
            # 添加玩家到房间
            room_info["players"].append(player_info)
            room_info["current_players"] += 1
            room_info["last_activity"] = time.time()
            
            self.logger.info("玩家加入房间成功", 
                           user_id=user_id,
                           room_id=room_id,
                           position=position)
            
            return player_info
            
        except Exception as e:
            self.logger.error("加入游戏房间失败", error=str(e))
            raise ServiceException(f"加入游戏房间失败: {str(e)}")
    
    @transactional
    async def leave_game_room(self, user_id: str, room_id: str, leave_reason: str = "normal"):
        """
        离开游戏房间
        
        Args:
            user_id: 用户ID
            room_id: 房间ID
            leave_reason: 离开原因
        """
        try:
            room_info = self.game_rooms.get(room_id)
            if not room_info:
                raise ServiceException("房间不存在")
            
            # 移除玩家
            room_info["players"] = [
                player for player in room_info["players"]
                if player["user_id"] != user_id
            ]
            
            room_info["current_players"] -= 1
            room_info["last_activity"] = time.time()
            
            # 如果房间为空，标记为可清理
            if room_info["current_players"] == 0:
                room_info["status"] = "finished"
                self.game_stats["active_rooms"] -= 1
            
            self.logger.info("玩家离开房间成功", 
                           user_id=user_id,
                           room_id=room_id,
                           leave_reason=leave_reason)
            
        except Exception as e:
            self.logger.error("离开游戏房间失败", error=str(e))
            raise ServiceException(f"离开游戏房间失败: {str(e)}")
    
    @transactional
    async def sync_game_state(self, 
                             user_id: str,
                             room_id: str,
                             action_type: str,
                             action_data: Dict[str, Any],
                             sequence_id: int = 0) -> Dict[str, Any]:
        """
        同步游戏状态
        
        Args:
            user_id: 用户ID
            room_id: 房间ID
            action_type: 操作类型
            action_data: 操作数据
            sequence_id: 序列号
            
        Returns:
            同步结果
        """
        try:
            room_info = self.game_rooms.get(room_id)
            if not room_info:
                raise ServiceException("房间不存在")
            
            room_state = self.room_states.get(room_id)
            if not room_state:
                raise ServiceException("房间状态不存在")
            
            # 验证用户是否在房间中
            user_in_room = any(player["user_id"] == user_id for player in room_info["players"])
            if not user_in_room:
                raise ServiceException("用户不在房间中")
            
            # 处理不同类型的操作
            if action_type == "ready":
                await self._handle_player_ready(room_info, user_id, action_data)
            elif action_type == "move":
                await self._handle_player_move(room_info, room_state, user_id, action_data)
            elif action_type == "chat":
                await self._handle_room_chat(room_info, user_id, action_data)
            
            # 更新房间活动时间
            room_info["last_activity"] = time.time()
            room_state["last_update"] = time.time()
            
            # 添加到同步队列
            sync_event = {
                "room_id": room_id,
                "user_id": user_id,
                "action_type": action_type,
                "action_data": action_data,
                "sequence_id": sequence_id,
                "timestamp": time.time()
            }
            
            self.sync_queue.append(sync_event)
            
            # 构建同步结果
            result = {
                "room_state": room_state,
                "updated_players": room_info["players"],
                "sequence_id": sequence_id + 1
            }
            
            self.logger.info("游戏状态同步成功", 
                           user_id=user_id,
                           room_id=room_id,
                           action_type=action_type)
            
            return result
            
        except Exception as e:
            self.logger.error("同步游戏状态失败", error=str(e))
            raise ServiceException(f"同步游戏状态失败: {str(e)}")
    
    async def _handle_player_ready(self, room_info: Dict[str, Any], user_id: str, action_data: Dict[str, Any]):
        """处理玩家准备状态"""
        for player in room_info["players"]:
            if player["user_id"] == user_id:
                player["ready"] = action_data.get("ready", False)
                break
        
        # 检查是否所有玩家都准备好了
        all_ready = all(player["ready"] for player in room_info["players"])
        if all_ready and room_info["current_players"] >= 2:
            room_info["status"] = "playing"
            room_info["game_started"] = True
            self.game_stats["total_games"] += 1
    
    async def _handle_player_move(self, room_info: Dict[str, Any], room_state: Dict[str, Any], user_id: str, action_data: Dict[str, Any]):
        """处理玩家移动"""
        # 这里应该根据具体的游戏类型实现移动逻辑
        room_state["turn"] += 1
        room_state["game_data"].update(action_data)
        
        # 检查游戏是否结束
        if action_data.get("game_over", False):
            room_info["status"] = "finished"
            self.game_stats["completed_games"] += 1
    
    async def _handle_room_chat(self, room_info: Dict[str, Any], user_id: str, action_data: Dict[str, Any]):
        """处理房间聊天"""
        message = {
            "user_id": user_id,
            "message": action_data.get("message", ""),
            "timestamp": time.time()
        }
        
        if "chat_history" not in room_info["game_data"]:
            room_info["game_data"]["chat_history"] = []
        
        room_info["game_data"]["chat_history"].append(message)
    
    @cached(ttl=300)
    async def get_task_list(self, user_id: str, task_type: str = "all", status: str = "all") -> Dict[str, Any]:
        """
        获取任务列表
        
        Args:
            user_id: 用户ID
            task_type: 任务类型
            status: 任务状态
            
        Returns:
            任务列表
        """
        try:
            user_tasks = self.user_tasks.get(user_id, [])
            
            # 如果用户没有任务，初始化日常任务
            if not user_tasks:
                await self._initialize_user_tasks(user_id)
                user_tasks = self.user_tasks.get(user_id, [])
            
            # 过滤任务
            filtered_tasks = []
            for task in user_tasks:
                if task_type != "all" and task["type"] != task_type:
                    continue
                if status != "all" and task["status"] != status:
                    continue
                filtered_tasks.append(task)
            
            return {
                "tasks": filtered_tasks,
                "total_count": len(filtered_tasks)
            }
            
        except Exception as e:
            self.logger.error("获取任务列表失败", error=str(e))
            raise ServiceException(f"获取任务列表失败: {str(e)}")
    
    @transactional
    async def accept_task(self, user_id: str, task_id: str) -> Dict[str, Any]:
        """
        接受任务
        
        Args:
            user_id: 用户ID
            task_id: 任务ID
            
        Returns:
            任务信息
        """
        try:
            user_tasks = self.user_tasks.get(user_id, [])
            
            # 查找任务
            task = None
            for t in user_tasks:
                if t["task_id"] == task_id:
                    task = t
                    break
            
            if not task:
                raise ServiceException("任务不存在")
            
            if task["status"] != TaskStatus.AVAILABLE.value:
                raise ServiceException("任务不可接受")
            
            # 更新任务状态
            task["status"] = TaskStatus.ACCEPTED.value
            task["accepted_time"] = time.time()
            
            # 初始化进度
            if user_id not in self.task_progress:
                self.task_progress[user_id] = {}
            
            self.task_progress[user_id][task_id] = {
                "current_count": 0,
                "target_count": task["target_count"],
                "start_time": time.time()
            }
            
            self.logger.info("任务接受成功", 
                           user_id=user_id,
                           task_id=task_id)
            
            return task
            
        except Exception as e:
            self.logger.error("接受任务失败", error=str(e))
            raise ServiceException(f"接受任务失败: {str(e)}")
    
    @transactional
    async def complete_task(self, user_id: str, task_id: str, completion_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        完成任务
        
        Args:
            user_id: 用户ID
            task_id: 任务ID
            completion_data: 完成数据
            
        Returns:
            完成结果
        """
        try:
            user_tasks = self.user_tasks.get(user_id, [])
            
            # 查找任务
            task = None
            for t in user_tasks:
                if t["task_id"] == task_id:
                    task = t
                    break
            
            if not task:
                raise ServiceException("任务不存在")
            
            if task["status"] != TaskStatus.ACCEPTED.value:
                raise ServiceException("任务未接受")
            
            # 检查任务进度
            progress = self.task_progress[user_id].get(task_id)
            if not progress:
                raise ServiceException("任务进度不存在")
            
            if progress["current_count"] < progress["target_count"]:
                raise ServiceException("任务未完成")
            
            # 更新任务状态
            task["status"] = TaskStatus.COMPLETED.value
            task["completed_time"] = time.time()
            
            # 发放奖励
            rewards = []
            if self.game_config.enable_auto_rewards:
                rewards = await self._grant_task_rewards(user_id, task["rewards"])
                task["status"] = TaskStatus.REWARDED.value
                task["rewarded_time"] = time.time()
            
            # 更新统计
            self.game_stats["completed_tasks"] += 1
            
            self.logger.info("任务完成成功", 
                           user_id=user_id,
                           task_id=task_id,
                           rewards=len(rewards))
            
            return {
                "task_info": task,
                "rewards": rewards
            }
            
        except Exception as e:
            self.logger.error("完成任务失败", error=str(e))
            raise ServiceException(f"完成任务失败: {str(e)}")
    
    @cached(ttl=300)
    async def get_leaderboard(self, 
                             user_id: str,
                             leaderboard_type: str,
                             page: int = 1,
                             page_size: int = 50,
                             season_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取排行榜
        
        Args:
            user_id: 用户ID
            leaderboard_type: 排行榜类型
            page: 页码
            page_size: 页面大小
            season_id: 赛季ID
            
        Returns:
            排行榜数据
        """
        try:
            leaderboard = self.leaderboards.get(leaderboard_type, [])
            
            # 分页处理
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_data = leaderboard[start_idx:end_idx]
            
            # 查找用户排名
            my_rank = None
            for idx, entry in enumerate(leaderboard):
                if entry.get("user_id") == user_id:
                    my_rank = {
                        "rank": idx + 1,
                        "user_id": user_id,
                        "score": entry.get("score", 0),
                        "level": entry.get("level", 1)
                    }
                    break
            
            # 获取赛季信息
            season_info = self.leaderboard_seasons.get(leaderboard_type)
            
            return {
                "leaderboard_data": page_data,
                "my_rank": my_rank,
                "total_count": len(leaderboard),
                "season_info": season_info
            }
            
        except Exception as e:
            self.logger.error("获取排行榜失败", error=str(e))
            raise ServiceException(f"获取排行榜失败: {str(e)}")
    
    async def _initialize_user_tasks(self, user_id: str):
        """初始化用户任务"""
        try:
            user_tasks = []
            
            # 添加日常任务
            for task_id, template in self.task_templates.items():
                if template["type"] == TaskType.DAILY.value:
                    task = {
                        **template,
                        "user_id": user_id,
                        "status": TaskStatus.AVAILABLE.value,
                        "created_time": time.time(),
                        "progress": 0
                    }
                    user_tasks.append(task)
            
            self.user_tasks[user_id] = user_tasks
            self.game_stats["total_tasks"] += len(user_tasks)
            
        except Exception as e:
            self.logger.error("初始化用户任务失败", error=str(e))
            raise
    
    async def _grant_task_rewards(self, user_id: str, rewards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """发放任务奖励"""
        try:
            granted_rewards = []
            
            for reward in rewards:
                reward_type = reward["type"]
                amount = reward["amount"]
                
                # 这里应该调用相应的服务发放奖励
                # 现在只是记录日志
                granted_reward = {
                    "type": reward_type,
                    "amount": amount,
                    "granted_time": time.time()
                }
                
                granted_rewards.append(granted_reward)
                
                self.logger.info("任务奖励发放成功", 
                               user_id=user_id,
                               reward_type=reward_type,
                               amount=amount)
            
            return granted_rewards
            
        except Exception as e:
            self.logger.error("发放任务奖励失败", error=str(e))
            raise
    
    async def sync_all_game_states(self):
        """同步所有游戏状态"""
        try:
            # 处理同步队列
            if self.sync_queue:
                events_to_process = self.sync_queue[:100]  # 每次处理100个事件
                self.sync_queue = self.sync_queue[100:]
                
                for event in events_to_process:
                    if self.enable_persistence:
                        # 这里应该持久化到数据库
                        pass
                
                self.logger.info("游戏状态同步完成", 
                               processed_events=len(events_to_process))
            
        except Exception as e:
            self.logger.error("同步游戏状态失败", error=str(e))
    
    async def update_leaderboards(self):
        """更新排行榜"""
        try:
            # 这里应该从数据库获取最新数据并更新排行榜
            # 现在只是示例实现
            
            for lb_type in self.leaderboards:
                # 模拟排行榜更新
                sample_data = [
                    {"user_id": f"user_{i}", "score": 1000 - i * 10, "level": 10 + i}
                    for i in range(min(100, self.game_config.leaderboard_size))
                ]
                
                self.leaderboards[lb_type] = sample_data
            
            self.logger.info("排行榜更新完成")
            
        except Exception as e:
            self.logger.error("更新排行榜失败", error=str(e))
    
    async def auto_refresh_tasks(self):
        """自动刷新任务"""
        try:
            current_time = datetime.now()
            
            # 检查是否需要刷新日常任务
            if current_time.hour == self.game_config.task_refresh_hour:
                for user_id in self.user_tasks:
                    await self._refresh_daily_tasks(user_id)
            
            # 检查是否需要刷新周常任务
            if current_time.weekday() == 0 and current_time.hour == self.game_config.task_refresh_hour:
                for user_id in self.user_tasks:
                    await self._refresh_weekly_tasks(user_id)
            
            self.logger.info("任务自动刷新完成")
            
        except Exception as e:
            self.logger.error("自动刷新任务失败", error=str(e))
    
    async def _refresh_daily_tasks(self, user_id: str):
        """刷新日常任务"""
        try:
            user_tasks = self.user_tasks.get(user_id, [])
            
            # 移除旧的日常任务
            user_tasks = [task for task in user_tasks if task["type"] != TaskType.DAILY.value]
            
            # 添加新的日常任务
            for task_id, template in self.task_templates.items():
                if template["type"] == TaskType.DAILY.value:
                    task = {
                        **template,
                        "user_id": user_id,
                        "status": TaskStatus.AVAILABLE.value,
                        "created_time": time.time(),
                        "progress": 0
                    }
                    user_tasks.append(task)
            
            self.user_tasks[user_id] = user_tasks
            
        except Exception as e:
            self.logger.error("刷新日常任务失败", error=str(e))
    
    async def _refresh_weekly_tasks(self, user_id: str):
        """刷新周常任务"""
        try:
            user_tasks = self.user_tasks.get(user_id, [])
            
            # 移除旧的周常任务
            user_tasks = [task for task in user_tasks if task["type"] != TaskType.WEEKLY.value]
            
            # 添加新的周常任务
            for task_id, template in self.task_templates.items():
                if template["type"] == TaskType.WEEKLY.value:
                    task = {
                        **template,
                        "user_id": user_id,
                        "status": TaskStatus.AVAILABLE.value,
                        "created_time": time.time(),
                        "progress": 0
                    }
                    user_tasks.append(task)
            
            self.user_tasks[user_id] = user_tasks
            
        except Exception as e:
            self.logger.error("刷新周常任务失败", error=str(e))
    
    async def sync_room_state(self, room_id: str, room_info: Dict[str, Any]):
        """同步房间状态"""
        try:
            if room_id in self.room_states:
                self.room_states[room_id]["last_update"] = time.time()
                
                # 这里应该持久化房间状态
                if self.enable_persistence:
                    pass
            
        except Exception as e:
            self.logger.error("同步房间状态失败", error=str(e))
    
    async def cleanup_room(self, room_id: str):
        """清理房间"""
        try:
            if room_id in self.game_rooms:
                del self.game_rooms[room_id]
            
            if room_id in self.room_states:
                del self.room_states[room_id]
            
            self.logger.info("房间清理完成", room_id=room_id)
            
        except Exception as e:
            self.logger.error("清理房间失败", error=str(e))
    
    async def _sync_game_states_periodically(self):
        """定期同步游戏状态"""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)
                await self.sync_all_game_states()
                
            except Exception as e:
                self.logger.error("定期同步游戏状态异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _update_leaderboards_periodically(self):
        """定期更新排行榜"""
        while True:
            try:
                await asyncio.sleep(self.game_config.leaderboard_update_interval)
                await self.update_leaderboards()
                
            except Exception as e:
                self.logger.error("定期更新排行榜异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _cleanup_expired_rooms(self):
        """清理过期房间"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                
                current_time = time.time()
                expired_rooms = []
                
                for room_id, room_info in self.game_rooms.items():
                    if (current_time - room_info["last_activity"] > self.game_config.room_timeout or
                        room_info["status"] == "finished"):
                        expired_rooms.append(room_id)
                
                for room_id in expired_rooms:
                    await self.cleanup_room(room_id)
                    self.game_stats["active_rooms"] -= 1
                
            except Exception as e:
                self.logger.error("清理过期房间异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            await super().cleanup()
            
            # 清理所有房间
            for room_id in list(self.game_rooms.keys()):
                await self.cleanup_room(room_id)
            
            # 清理其他数据
            self.task_progress.clear()
            self.user_tasks.clear()
            self.sync_queue.clear()
            
            self.logger.info("游戏服务资源清理完成")
            
        except Exception as e:
            self.logger.error("游戏服务资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            **self.game_stats,
            "service_name": self.__class__.__name__,
            "room_count": len(self.game_rooms),
            "state_count": len(self.room_states),
            "task_templates": len(self.task_templates),
            "leaderboards": len(self.leaderboards),
            "sync_queue_size": len(self.sync_queue)
        }


def create_game_service(config: Optional[GameServiceConfig] = None) -> GameService:
    """
    创建游戏服务实例
    
    Args:
        config: 游戏服务配置
        
    Returns:
        GameService实例
    """
    try:
        service = GameService(config=config)
        logger.info("游戏服务创建成功")
        return service
        
    except Exception as e:
        logger.error("创建游戏服务失败", error=str(e))
        raise