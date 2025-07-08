"""
战斗日志模块

该模块提供战斗专用日志实现，支持战斗专用字段、
高性能二进制日志、战斗回放支持、压缩存储等功能。
"""

import struct
import gzip
import json
import time
import threading
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from pathlib import Path
from collections import deque
import uuid

from .base_logger import BaseLogger
from .logger_config import LoggerConfig


@dataclass
class BattleConfig:
    """战斗日志特定配置"""
    # 二进制日志配置
    enable_binary_log: bool = False
    binary_log_dir: str = "logs/battle_binary"
    
    # 压缩配置
    enable_compression: bool = True
    compression_level: int = 6  # gzip压缩级别
    compress_threshold: int = 1024 * 10  # 10KB
    
    # 回放配置
    enable_replay: bool = True
    replay_dir: str = "logs/battle_replay"
    replay_format: str = "json"  # json 或 binary
    
    # 缓冲配置
    buffer_size: int = 1000
    flush_interval: float = 30.0  # 30秒
    
    # 战斗数据结构化字段
    battle_fields: List[str] = field(default_factory=lambda: [
        'battle_id', 'round_number', 'tick', 'event_type',
        'player_id', 'skill_id', 'target_id', 'damage',
        'position_x', 'position_y', 'timestamp'
    ])


class BattleEvent:
    """战斗事件"""
    
    def __init__(self, battle_id: str, event_type: str, **kwargs):
        self.battle_id = battle_id
        self.event_type = event_type
        self.timestamp = time.time()
        self.data = kwargs
        self.event_id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'event_id': self.event_id,
            'battle_id': self.battle_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            **self.data
        }
    
    def to_json(self) -> str:
        """转换为JSON格式"""
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    def to_binary(self) -> bytes:
        """转换为二进制格式"""
        # 简化的二进制格式：
        # [event_id_len][event_id][battle_id_len][battle_id][event_type_len][event_type]
        # [timestamp][data_len][data_json]
        
        event_id_bytes = self.event_id.encode('utf-8')
        battle_id_bytes = self.battle_id.encode('utf-8')
        event_type_bytes = self.event_type.encode('utf-8')
        data_json = json.dumps(self.data).encode('utf-8')
        
        binary_data = struct.pack(
            f'!I{len(event_id_bytes)}sI{len(battle_id_bytes)}sI{len(event_type_bytes)}sdI{len(data_json)}s',
            len(event_id_bytes), event_id_bytes,
            len(battle_id_bytes), battle_id_bytes,
            len(event_type_bytes), event_type_bytes,
            self.timestamp,
            len(data_json), data_json
        )
        
        return binary_data


class BattleReplayRecorder:
    """战斗回放记录器"""
    
    def __init__(self, config: BattleConfig):
        self.config = config
        self._battles: Dict[str, List[BattleEvent]] = {}
        self._lock = threading.Lock()
        
        # 创建回放目录
        Path(config.replay_dir).mkdir(parents=True, exist_ok=True)
    
    def record_event(self, event: BattleEvent) -> None:
        """记录战斗事件"""
        if not self.config.enable_replay:
            return
        
        with self._lock:
            if event.battle_id not in self._battles:
                self._battles[event.battle_id] = []
            
            self._battles[event.battle_id].append(event)
    
    def save_battle_replay(self, battle_id: str) -> Optional[str]:
        """保存战斗回放"""
        with self._lock:
            if battle_id not in self._battles:
                return None
            
            events = self._battles[battle_id]
            if not events:
                return None
            
            # 生成回放文件名
            timestamp = int(time.time())
            if self.config.replay_format == "binary":
                filename = f"{battle_id}_{timestamp}.breplay"
            else:
                filename = f"{battle_id}_{timestamp}.json"
            
            filepath = Path(self.config.replay_dir) / filename
            
            try:
                if self.config.replay_format == "binary":
                    self._save_binary_replay(filepath, events)
                else:
                    self._save_json_replay(filepath, events)
                
                # 清理内存中的数据
                del self._battles[battle_id]
                
                return str(filepath)
                
            except Exception as e:
                print(f"Failed to save battle replay: {e}")
                return None
    
    def _save_json_replay(self, filepath: Path, events: List[BattleEvent]) -> None:
        """保存JSON格式回放"""
        replay_data = {
            'version': '1.0',
            'battle_id': events[0].battle_id,
            'start_time': events[0].timestamp,
            'end_time': events[-1].timestamp,
            'event_count': len(events),
            'events': [event.to_dict() for event in events]
        }
        
        content = json.dumps(replay_data, ensure_ascii=False, indent=2)
        
        if self.config.enable_compression and len(content.encode()) > self.config.compress_threshold:
            # 压缩保存
            with gzip.open(f"{filepath}.gz", 'wt', encoding='utf-8', compresslevel=self.config.compression_level) as f:
                f.write(content)
        else:
            # 直接保存
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
    
    def _save_binary_replay(self, filepath: Path, events: List[BattleEvent]) -> None:
        """保存二进制格式回放"""
        # 二进制回放格式：
        # [header][event_count][events...]
        
        # 构建头部
        header_data = {
            'version': '1.0',
            'battle_id': events[0].battle_id,
            'start_time': events[0].timestamp,
            'end_time': events[-1].timestamp,
            'event_count': len(events)
        }
        header_json = json.dumps(header_data).encode('utf-8')
        
        # 构建事件数据
        events_data = b''.join(event.to_binary() for event in events)
        
        # 组合数据
        binary_data = struct.pack('!I', len(header_json)) + header_json + events_data
        
        if self.config.enable_compression and len(binary_data) > self.config.compress_threshold:
            # 压缩保存
            with gzip.open(f"{filepath}.gz", 'wb', compresslevel=self.config.compression_level) as f:
                f.write(binary_data)
        else:
            # 直接保存
            with open(filepath, 'wb') as f:
                f.write(binary_data)
    
    def get_battle_stats(self) -> Dict[str, Any]:
        """获取战斗统计信息"""
        with self._lock:
            return {
                'active_battles': len(self._battles),
                'total_events': sum(len(events) for events in self._battles.values()),
                'battles': {
                    battle_id: {
                        'event_count': len(events),
                        'start_time': events[0].timestamp if events else None,
                        'last_event': events[-1].timestamp if events else None
                    }
                    for battle_id, events in self._battles.items()
                }
            }


class BattleBinaryLogger:
    """战斗二进制日志记录器"""
    
    def __init__(self, config: BattleConfig):
        self.config = config
        self._buffer: deque = deque(maxlen=config.buffer_size)
        self._lock = threading.Lock()
        self._last_flush = time.time()
        
        # 创建二进制日志目录
        Path(config.binary_log_dir).mkdir(parents=True, exist_ok=True)
    
    def log_event(self, event: BattleEvent) -> None:
        """记录二进制事件"""
        if not self.config.enable_binary_log:
            return
        
        with self._lock:
            self._buffer.append(event)
            
            # 检查是否需要刷新
            if (len(self._buffer) >= self.config.buffer_size or 
                time.time() - self._last_flush >= self.config.flush_interval):
                self._flush_buffer()
    
    def _flush_buffer(self) -> None:
        """刷新缓冲区"""
        if not self._buffer:
            return
        
        try:
            # 生成文件名
            timestamp = int(time.time())
            filename = f"battle_events_{timestamp}.bdb"
            filepath = Path(self.config.binary_log_dir) / filename
            
            # 写入二进制数据
            with open(filepath, 'ab') as f:
                for event in self._buffer:
                    f.write(event.to_binary())
            
            self._buffer.clear()
            self._last_flush = time.time()
            
        except Exception as e:
            print(f"Failed to flush binary log buffer: {e}")
    
    def force_flush(self) -> None:
        """强制刷新缓冲区"""
        with self._lock:
            self._flush_buffer()


class BattleLogger(BaseLogger):
    """
    战斗日志器
    
    继承基础日志器，添加战斗专用功能，包括战斗事件记录、
    回放支持、二进制日志等。
    """
    
    def __init__(self, name: str, config: LoggerConfig, battle_config: Optional[BattleConfig] = None):
        """
        初始化战斗日志器
        
        Args:
            name: 日志器名称
            config: 基础日志配置
            battle_config: 战斗特定配置
        """
        super().__init__(name, config)
        
        self.battle_config = battle_config or BattleConfig()
        
        # 初始化战斗相关组件
        self._replay_recorder = BattleReplayRecorder(self.battle_config)
        self._binary_logger = BattleBinaryLogger(self.battle_config)
        
        # 当前战斗上下文
        self._current_battle_id: Optional[str] = None
        self._current_round: int = 0
        self._current_tick: int = 0
    
    def start_battle(self, battle_id: str) -> None:
        """开始新战斗"""
        self._current_battle_id = battle_id
        self._current_round = 0
        self._current_tick = 0
        
        # 记录战斗开始事件
        self.battle_event("battle_start", battle_id=battle_id)
    
    def end_battle(self, battle_id: Optional[str] = None) -> Optional[str]:
        """结束战斗"""
        battle_id = battle_id or self._current_battle_id
        if not battle_id:
            return None
        
        # 记录战斗结束事件
        self.battle_event("battle_end", battle_id=battle_id)
        
        # 保存回放
        replay_file = self._replay_recorder.save_battle_replay(battle_id)
        
        # 刷新二进制日志
        self._binary_logger.force_flush()
        
        # 清理当前战斗上下文
        if battle_id == self._current_battle_id:
            self._current_battle_id = None
            self._current_round = 0
            self._current_tick = 0
        
        return replay_file
    
    def set_battle_context(self, battle_id: str, round_number: int = 0, tick: int = 0) -> None:
        """设置战斗上下文"""
        self._current_battle_id = battle_id
        self._current_round = round_number
        self._current_tick = tick
    
    def battle_event(self, event_type: str, battle_id: Optional[str] = None, **kwargs) -> None:
        """记录战斗事件"""
        battle_id = battle_id or self._current_battle_id
        if not battle_id:
            self.warning("Battle event without battle_id", event_type=event_type, **kwargs)
            return
        
        # 添加当前上下文信息
        if self._current_round > 0:
            kwargs['round_number'] = self._current_round
        if self._current_tick > 0:
            kwargs['tick'] = self._current_tick
        
        # 创建战斗事件
        event = BattleEvent(battle_id, event_type, **kwargs)
        
        # 记录到回放
        self._replay_recorder.record_event(event)
        
        # 记录到二进制日志
        self._binary_logger.log_event(event)
        
        # 记录到常规日志
        log_data = {
            'battle_id': battle_id,
            'event_type': event_type,
            'event_id': event.event_id,
        }
        log_data.update(kwargs)
        self.info(f"Battle event: {event_type}", **log_data)
    
    # 战斗专用便捷方法
    def player_join(self, battle_id: str, player_id: str, **kwargs) -> None:
        """玩家加入战斗"""
        self.battle_event("player_join", battle_id, player_id=player_id, **kwargs)
    
    def player_leave(self, battle_id: str, player_id: str, reason: str = "normal", **kwargs) -> None:
        """玩家离开战斗"""
        self.battle_event("player_leave", battle_id, player_id=player_id, reason=reason, **kwargs)
    
    def skill_cast(self, battle_id: str, player_id: str, skill_id: str, 
                   target_id: Optional[str] = None, **kwargs) -> None:
        """技能释放"""
        self.battle_event("skill_cast", battle_id, 
                         player_id=player_id, skill_id=skill_id, target_id=target_id, **kwargs)
    
    def damage_dealt(self, battle_id: str, source_id: str, target_id: str, 
                     damage: int, damage_type: str = "normal", **kwargs) -> None:
        """伤害计算"""
        self.battle_event("damage_dealt", battle_id,
                         source_id=source_id, target_id=target_id, 
                         damage=damage, damage_type=damage_type, **kwargs)
    
    def player_move(self, battle_id: str, player_id: str, 
                    from_x: float, from_y: float, to_x: float, to_y: float, **kwargs) -> None:
        """玩家移动"""
        self.battle_event("player_move", battle_id,
                         player_id=player_id, from_x=from_x, from_y=from_y,
                         to_x=to_x, to_y=to_y, **kwargs)
    
    def round_start(self, battle_id: str, round_number: int, **kwargs) -> None:
        """回合开始"""
        self._current_round = round_number
        self.battle_event("round_start", battle_id, round_number=round_number, **kwargs)
    
    def round_end(self, battle_id: str, round_number: int, winner: Optional[str] = None, **kwargs) -> None:
        """回合结束"""
        self.battle_event("round_end", battle_id, 
                         round_number=round_number, winner=winner, **kwargs)
    
    def tick_update(self, battle_id: str, tick: int, **kwargs) -> None:
        """Tick更新"""
        self._current_tick = tick
        # Tick事件通常很频繁，只在debug级别记录
        if self.is_enabled_for("DEBUG"):
            self.battle_event("tick_update", battle_id, tick=tick, **kwargs)
    
    def get_battle_stats(self) -> Dict[str, Any]:
        """获取战斗统计信息"""
        return {
            'current_battle': {
                'battle_id': self._current_battle_id,
                'round': self._current_round,
                'tick': self._current_tick
            },
            'replay_stats': self._replay_recorder.get_battle_stats(),
            'binary_log_enabled': self.battle_config.enable_binary_log,
            'replay_enabled': self.battle_config.enable_replay,
        }
    
    def close(self) -> None:
        """关闭日志器"""
        # 结束当前战斗（如果有）
        if self._current_battle_id:
            self.end_battle()
        
        # 刷新二进制日志
        self._binary_logger.force_flush()
        
        # 调用父类关闭方法
        super().close()