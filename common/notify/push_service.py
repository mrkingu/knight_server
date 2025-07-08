"""
推送服务模块

该模块实现了推送服务，处理实际的消息推送逻辑。
支持WebSocket连接管理、消息发送和心跳检测。

主要功能：
- WebSocket消息发送
- 连接状态管理
- 心跳保活机制
- 推送失败重试
- 消息发送统计
"""

import asyncio
import time
import json
from typing import Any, Dict, Optional, Union, List
from dataclasses import dataclass
from enum import Enum

from common.logger import logger


class MessageType(Enum):
    """消息类型枚举"""
    DATA = "data"
    HEARTBEAT = "heartbeat"
    CONTROL = "control"
    ERROR = "error"


@dataclass
class PushResult:
    """推送结果"""
    success: bool
    message: str = ""
    latency: float = 0.0
    retry_count: int = 0


@dataclass
class PushStatistics:
    """推送统计信息"""
    total_sent: int = 0
    total_failed: int = 0
    total_bytes: int = 0
    average_latency: float = 0.0
    max_latency: float = 0.0
    min_latency: float = float('inf')


class PushService:
    """
    推送服务
    
    负责处理实际的消息推送操作，包括WebSocket连接管理、
    消息发送、心跳检测和重试机制。
    
    Attributes:
        _statistics: 推送统计信息
        _retry_attempts: 重试次数
        _retry_delay: 重试延迟
        _heartbeat_interval: 心跳间隔
        _timeout: 发送超时时间
    """
    
    def __init__(self, 
                 retry_attempts: int = 3,
                 retry_delay: float = 1.0,
                 heartbeat_interval: float = 30.0,
                 timeout: float = 10.0):
        """
        初始化推送服务
        
        Args:
            retry_attempts: 重试次数
            retry_delay: 重试延迟(秒)
            heartbeat_interval: 心跳间隔(秒)
            timeout: 发送超时时间(秒)
        """
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay
        self._heartbeat_interval = heartbeat_interval
        self._timeout = timeout
        
        # 统计信息
        self._statistics = PushStatistics()
        
        # 运行状态
        self._running = False
        
        logger.info("推送服务初始化完成",
                   retry_attempts=retry_attempts,
                   retry_delay=retry_delay,
                   timeout=timeout)
    
    async def start(self):
        """启动推送服务"""
        if self._running:
            logger.warning("推送服务已经在运行中")
            return
        
        self._running = True
        logger.info("推送服务启动成功")
    
    async def stop(self):
        """停止推送服务"""
        if not self._running:
            return
        
        self._running = False
        logger.info("推送服务停止成功")
    
    async def send_message(self, websocket: Any, message_data: Union[str, bytes], 
                          message_type: MessageType = MessageType.DATA,
                          retry_count: int = 0) -> PushResult:
        """
        发送消息到WebSocket连接
        
        Args:
            websocket: WebSocket连接对象
            message_data: 消息数据
            message_type: 消息类型
            retry_count: 重试次数
            
        Returns:
            PushResult: 推送结果
        """
        start_time = time.time()
        
        try:
            # 构造消息包
            message_packet = self._build_message_packet(message_data, message_type)
            
            # 发送消息
            await self._send_with_timeout(websocket, message_packet)
            
            # 计算延迟
            latency = time.time() - start_time
            
            # 更新统计
            self._update_statistics(True, len(message_packet), latency)
            
            logger.debug("消息发送成功", 
                        message_type=message_type.value,
                        size=len(message_packet),
                        latency=latency)
            
            return PushResult(success=True, latency=latency, retry_count=retry_count)
            
        except Exception as e:
            logger.error("消息发送失败", 
                        message_type=message_type.value,
                        error=str(e),
                        retry_count=retry_count)
            
            # 更新失败统计
            self._update_statistics(False, 0, 0)
            
            # 重试逻辑
            if retry_count < self._retry_attempts:
                await asyncio.sleep(self._retry_delay * (retry_count + 1))
                return await self.send_message(websocket, message_data, message_type, retry_count + 1)
            
            return PushResult(
                success=False, 
                message=str(e), 
                retry_count=retry_count
            )
    
    async def send_heartbeat(self, websocket: Any) -> PushResult:
        """
        发送心跳消息
        
        Args:
            websocket: WebSocket连接对象
            
        Returns:
            PushResult: 推送结果
        """
        heartbeat_data = {
            "type": "heartbeat",
            "timestamp": time.time()
        }
        
        return await self.send_message(
            websocket, 
            json.dumps(heartbeat_data), 
            MessageType.HEARTBEAT
        )
    
    async def send_control_message(self, websocket: Any, control_type: str, 
                                  data: Optional[Dict] = None) -> PushResult:
        """
        发送控制消息
        
        Args:
            websocket: WebSocket连接对象
            control_type: 控制类型
            data: 控制数据
            
        Returns:
            PushResult: 推送结果
        """
        control_data = {
            "type": "control",
            "control_type": control_type,
            "data": data or {},
            "timestamp": time.time()
        }
        
        return await self.send_message(
            websocket,
            json.dumps(control_data),
            MessageType.CONTROL
        )
    
    async def send_error_message(self, websocket: Any, error_code: str, 
                                error_message: str) -> PushResult:
        """
        发送错误消息
        
        Args:
            websocket: WebSocket连接对象
            error_code: 错误代码
            error_message: 错误信息
            
        Returns:
            PushResult: 推送结果
        """
        error_data = {
            "type": "error",
            "error_code": error_code,
            "error_message": error_message,
            "timestamp": time.time()
        }
        
        return await self.send_message(
            websocket,
            json.dumps(error_data),
            MessageType.ERROR
        )
    
    async def broadcast_to_connections(self, websockets: List[Any], 
                                     message_data: Union[str, bytes],
                                     message_type: MessageType = MessageType.DATA) -> List[PushResult]:
        """
        向多个连接广播消息
        
        Args:
            websockets: WebSocket连接列表
            message_data: 消息数据
            message_type: 消息类型
            
        Returns:
            List[PushResult]: 推送结果列表
        """
        tasks = []
        for websocket in websockets:
            task = asyncio.create_task(
                self.send_message(websocket, message_data, message_type)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        push_results = []
        for result in results:
            if isinstance(result, PushResult):
                push_results.append(result)
            else:
                push_results.append(PushResult(
                    success=False,
                    message=str(result) if result else "Unknown error"
                ))
        
        return push_results
    
    async def check_connection_alive(self, websocket: Any) -> bool:
        """
        检查连接是否存活
        
        Args:
            websocket: WebSocket连接对象
            
        Returns:
            bool: 连接是否存活
        """
        try:
            # 发送Ping帧检测连接
            await self._send_ping(websocket)
            return True
        except Exception as e:
            logger.debug("连接检测失败", error=str(e))
            return False
    
    def get_statistics(self) -> PushStatistics:
        """获取推送统计信息"""
        return self._statistics
    
    def reset_statistics(self):
        """重置统计信息"""
        self._statistics = PushStatistics()
        logger.info("推送服务统计信息已重置")
    
    def _build_message_packet(self, message_data: Union[str, bytes], 
                             message_type: MessageType) -> str:
        """
        构造消息包
        
        Args:
            message_data: 消息数据
            message_type: 消息类型
            
        Returns:
            str: 消息包
        """
        if isinstance(message_data, bytes):
            # 对于二进制数据，进行base64编码
            import base64
            encoded_data = base64.b64encode(message_data).decode('utf-8')
            packet = {
                "type": message_type.value,
                "data": encoded_data,
                "encoding": "base64",
                "timestamp": time.time()
            }
        else:
            # 对于字符串数据，直接使用
            packet = {
                "type": message_type.value,
                "data": message_data,
                "encoding": "utf-8",
                "timestamp": time.time()
            }
        
        return json.dumps(packet)
    
    async def _send_with_timeout(self, websocket: Any, message: str):
        """
        带超时的消息发送
        
        Args:
            websocket: WebSocket连接对象
            message: 消息内容
        """
        try:
            # 尝试使用WebSocket的send方法
            if hasattr(websocket, 'send'):
                await asyncio.wait_for(websocket.send(message), timeout=self._timeout)
            elif hasattr(websocket, 'send_text'):
                await asyncio.wait_for(websocket.send_text(message), timeout=self._timeout)
            else:
                # 如果没有标准方法，抛出异常
                raise AttributeError("WebSocket对象缺少send方法")
                
        except asyncio.TimeoutError:
            raise Exception(f"消息发送超时 ({self._timeout}秒)")
        except Exception as e:
            raise Exception(f"消息发送失败: {str(e)}")
    
    async def _send_ping(self, websocket: Any):
        """
        发送Ping帧
        
        Args:
            websocket: WebSocket连接对象
        """
        try:
            if hasattr(websocket, 'ping'):
                await asyncio.wait_for(websocket.ping(), timeout=5.0)
            elif hasattr(websocket, 'send'):
                # 发送ping类型的JSON消息
                ping_message = json.dumps({"type": "ping", "timestamp": time.time()})
                await asyncio.wait_for(websocket.send(ping_message), timeout=5.0)
            else:
                raise AttributeError("WebSocket对象不支持ping操作")
                
        except Exception as e:
            raise Exception(f"Ping发送失败: {str(e)}")
    
    def _update_statistics(self, success: bool, message_size: int, latency: float):
        """
        更新统计信息
        
        Args:
            success: 是否成功
            message_size: 消息大小
            latency: 延迟时间
        """
        if success:
            self._statistics.total_sent += 1
            self._statistics.total_bytes += message_size
            
            # 更新延迟统计
            if latency > 0:
                if self._statistics.total_sent == 1:
                    self._statistics.average_latency = latency
                    self._statistics.max_latency = latency
                    self._statistics.min_latency = latency
                else:
                    # 使用指数移动平均
                    self._statistics.average_latency = (
                        self._statistics.average_latency * 0.9 + latency * 0.1
                    )
                    self._statistics.max_latency = max(self._statistics.max_latency, latency)
                    self._statistics.min_latency = min(self._statistics.min_latency, latency)
        else:
            self._statistics.total_failed += 1


# 工厂函数
def create_push_service(**kwargs) -> PushService:
    """
    创建推送服务实例
    
    Args:
        **kwargs: 配置参数
        
    Returns:
        PushService: 推送服务实例
    """
    return PushService(**kwargs)