"""
时间工具模块

该模块提供时间戳转换工具、时区处理、定时器实现、
时间格式化工具和游戏时间系统支持等功能。
"""

import time
import datetime
import asyncio
import threading
from typing import Optional, Union, Callable, Any, Dict, List
from enum import Enum
from dataclasses import dataclass
from zoneinfo import ZoneInfo
import calendar
from loguru import logger


class TimeFormat(Enum):
    """时间格式枚举"""
    ISO8601 = "%Y-%m-%dT%H:%M:%S.%fZ"
    STANDARD = "%Y-%m-%d %H:%M:%S"
    DATE_ONLY = "%Y-%m-%d"
    TIME_ONLY = "%H:%M:%S"
    CHINESE = "%Y年%m月%d日 %H时%M分%S秒"
    LOG_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
    FILE_SAFE = "%Y%m%d_%H%M%S"


class TimeUnit(Enum):
    """时间单位枚举"""
    MICROSECOND = 1e-6
    MILLISECOND = 1e-3
    SECOND = 1
    MINUTE = 60
    HOUR = 3600
    DAY = 86400
    WEEK = 604800
    MONTH = 2629746  # 平均月长度（秒）
    YEAR = 31556952  # 平均年长度（秒）


@dataclass
class TimeRange:
    """时间范围"""
    start: datetime.datetime
    end: datetime.datetime
    
    def __contains__(self, dt: datetime.datetime) -> bool:
        """检查时间是否在范围内"""
        return self.start <= dt <= self.end
    
    def duration(self) -> datetime.timedelta:
        """获取时间范围长度"""
        return self.end - self.start
    
    def duration_seconds(self) -> float:
        """获取时间范围长度（秒）"""
        return self.duration().total_seconds()
    
    def overlaps(self, other: 'TimeRange') -> bool:
        """检查与另一个时间范围是否重叠"""
        return max(self.start, other.start) < min(self.end, other.end)


class TimeZoneManager:
    """
    时区管理器
    
    处理时区转换和时区相关操作。
    """
    
    # 常用时区
    TIMEZONE_MAP = {
        'UTC': 'UTC',
        'GMT': 'UTC',
        'CST': 'Asia/Shanghai',  # 中国标准时间
        'JST': 'Asia/Tokyo',     # 日本标准时间
        'KST': 'Asia/Seoul',     # 韩国标准时间
        'EST': 'America/New_York',  # 美国东部时间
        'PST': 'America/Los_Angeles',  # 美国西部时间
        'CET': 'Europe/Paris',   # 中欧时间
    }
    
    @classmethod
    def get_timezone(cls, tz_name: str) -> ZoneInfo:
        """
        获取时区对象
        
        Args:
            tz_name: 时区名称
            
        Returns:
            ZoneInfo: 时区对象
        """
        tz_name = cls.TIMEZONE_MAP.get(tz_name, tz_name)
        return ZoneInfo(tz_name)
    
    @classmethod
    def convert_timezone(cls, dt: datetime.datetime, 
                        from_tz: Union[str, ZoneInfo], 
                        to_tz: Union[str, ZoneInfo]) -> datetime.datetime:
        """
        转换时区
        
        Args:
            dt: 时间对象
            from_tz: 源时区
            to_tz: 目标时区
            
        Returns:
            datetime.datetime: 转换后的时间
        """
        if isinstance(from_tz, str):
            from_tz = cls.get_timezone(from_tz)
        if isinstance(to_tz, str):
            to_tz = cls.get_timezone(to_tz)
        
        # 如果时间没有时区信息，假设它是源时区的时间
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=from_tz)
        
        return dt.astimezone(to_tz)
    
    @classmethod
    def now_in_timezone(cls, tz_name: str) -> datetime.datetime:
        """
        获取指定时区的当前时间
        
        Args:
            tz_name: 时区名称
            
        Returns:
            datetime.datetime: 当前时间
        """
        tz = cls.get_timezone(tz_name)
        return datetime.datetime.now(tz)


class TimestampConverter:
    """
    时间戳转换器
    
    提供各种时间戳格式之间的转换功能。
    """
    
    @staticmethod
    def timestamp_to_datetime(timestamp: Union[int, float], 
                            timezone: Optional[Union[str, ZoneInfo]] = None) -> datetime.datetime:
        """
        时间戳转datetime对象
        
        Args:
            timestamp: 时间戳（秒或毫秒）
            timezone: 时区
            
        Returns:
            datetime.datetime: 时间对象
        """
        # 判断是秒级还是毫秒级时间戳
        if timestamp > 1e10:  # 毫秒级时间戳
            timestamp = timestamp / 1000
        
        dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        
        if timezone:
            if isinstance(timezone, str):
                timezone = TimeZoneManager.get_timezone(timezone)
            dt = dt.astimezone(timezone)
        
        return dt
    
    @staticmethod
    def datetime_to_timestamp(dt: datetime.datetime, 
                            unit: TimeUnit = TimeUnit.SECOND) -> Union[int, float]:
        """
        datetime对象转时间戳
        
        Args:
            dt: 时间对象
            unit: 时间单位
            
        Returns:
            Union[int, float]: 时间戳
        """
        timestamp = dt.timestamp()
        
        if unit == TimeUnit.MILLISECOND:
            return int(timestamp * 1000)
        elif unit == TimeUnit.MICROSECOND:
            return int(timestamp * 1000000)
        else:
            return timestamp
    
    @staticmethod
    def string_to_datetime(time_str: str, 
                          format_type: Union[TimeFormat, str] = TimeFormat.STANDARD,
                          timezone: Optional[Union[str, ZoneInfo]] = None) -> datetime.datetime:
        """
        字符串转datetime对象
        
        Args:
            time_str: 时间字符串
            format_type: 时间格式
            timezone: 时区
            
        Returns:
            datetime.datetime: 时间对象
        """
        if isinstance(format_type, TimeFormat):
            format_str = format_type.value
        else:
            format_str = format_type
        
        dt = datetime.datetime.strptime(time_str, format_str)
        
        if timezone:
            if isinstance(timezone, str):
                timezone = TimeZoneManager.get_timezone(timezone)
            dt = dt.replace(tzinfo=timezone)
        
        return dt
    
    @staticmethod
    def datetime_to_string(dt: datetime.datetime, 
                          format_type: Union[TimeFormat, str] = TimeFormat.STANDARD) -> str:
        """
        datetime对象转字符串
        
        Args:
            dt: 时间对象
            format_type: 时间格式
            
        Returns:
            str: 时间字符串
        """
        if isinstance(format_type, TimeFormat):
            format_str = format_type.value
        else:
            format_str = format_type
        
        return dt.strftime(format_str)


class GameTimeSystem:
    """
    游戏时间系统
    
    提供游戏服务器时间同步和游戏内时间管理功能。
    """
    
    def __init__(self, timezone: str = 'Asia/Shanghai'):
        """
        初始化游戏时间系统
        
        Args:
            timezone: 游戏时区
        """
        self.timezone = TimeZoneManager.get_timezone(timezone)
        self._server_start_time = time.time()
        self._game_speed_multiplier = 1.0
        self._paused = False
        self._pause_start_time: Optional[float] = None
        self._total_paused_time = 0.0
        self._game_start_timestamp: Optional[float] = None
    
    def set_game_start_time(self, timestamp: Optional[float] = None) -> None:
        """
        设置游戏开始时间
        
        Args:
            timestamp: 游戏开始时间戳，为None时使用当前时间
        """
        self._game_start_timestamp = timestamp or time.time()
    
    def get_server_time(self) -> datetime.datetime:
        """
        获取服务器时间
        
        Returns:
            datetime.datetime: 服务器时间
        """
        return datetime.datetime.now(self.timezone)
    
    def get_server_timestamp(self) -> float:
        """
        获取服务器时间戳
        
        Returns:
            float: 服务器时间戳
        """
        return time.time()
    
    def get_game_time(self) -> datetime.datetime:
        """
        获取游戏时间（考虑暂停和加速）
        
        Returns:
            datetime.datetime: 游戏时间
        """
        if self._game_start_timestamp is None:
            return self.get_server_time()
        
        # 计算实际游戏运行时间
        current_time = time.time()
        if self._paused and self._pause_start_time:
            # 游戏暂停中，不计算暂停时间
            elapsed_real_time = self._pause_start_time - self._server_start_time - self._total_paused_time
        else:
            elapsed_real_time = current_time - self._server_start_time - self._total_paused_time
        
        # 应用游戏速度倍数
        elapsed_game_time = elapsed_real_time * self._game_speed_multiplier
        
        # 计算游戏时间
        game_timestamp = self._game_start_timestamp + elapsed_game_time
        return TimestampConverter.timestamp_to_datetime(game_timestamp, self.timezone)
    
    def set_game_speed(self, multiplier: float) -> None:
        """
        设置游戏速度倍数
        
        Args:
            multiplier: 速度倍数（1.0为正常速度）
        """
        self._game_speed_multiplier = max(0.1, multiplier)  # 最小0.1倍速
    
    def pause_game(self) -> None:
        """暂停游戏时间"""
        if not self._paused:
            self._paused = True
            self._pause_start_time = time.time()
    
    def resume_game(self) -> None:
        """恢复游戏时间"""
        if self._paused and self._pause_start_time:
            self._total_paused_time += time.time() - self._pause_start_time
            self._paused = False
            self._pause_start_time = None
    
    def is_paused(self) -> bool:
        """检查游戏是否暂停"""
        return self._paused
    
    def get_uptime(self) -> float:
        """
        获取服务器运行时间（秒）
        
        Returns:
            float: 运行时间
        """
        return time.time() - self._server_start_time


class Timer:
    """
    定时器实现
    
    支持一次性和重复定时器。
    """
    
    def __init__(self, interval: float, callback: Callable[[], Any], 
                 repeat: bool = False, start_immediately: bool = True):
        """
        初始化定时器
        
        Args:
            interval: 时间间隔（秒）
            callback: 回调函数
            repeat: 是否重复执行
            start_immediately: 是否立即开始
        """
        self.interval = interval
        self.callback = callback
        self.repeat = repeat
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._start_time: Optional[float] = None
        
        if start_immediately:
            self.start()
    
    def start(self) -> None:
        """启动定时器"""
        if self._running:
            return
        
        self._running = True
        self._start_time = time.time()
        self._schedule_next()
    
    def stop(self) -> None:
        """停止定时器"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
    
    def restart(self) -> None:
        """重启定时器"""
        self.stop()
        self.start()
    
    def is_running(self) -> bool:
        """检查定时器是否运行中"""
        return self._running
    
    def get_elapsed_time(self) -> float:
        """获取已运行时间"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time
    
    def _schedule_next(self) -> None:
        """调度下一次执行"""
        if not self._running:
            return
        
        def execute():
            if self._running:
                try:
                    self.callback()
                except Exception as e:
                    logger.error(f"定时器回调执行失败: {e}")
                
                if self.repeat and self._running:
                    self._schedule_next()
                else:
                    self._running = False
        
        self._timer = threading.Timer(self.interval, execute)
        self._timer.start()


class AsyncTimer:
    """
    异步定时器实现
    
    支持异步回调函数的定时器。
    """
    
    def __init__(self, interval: float, callback: Callable[[], Any], 
                 repeat: bool = False):
        """
        初始化异步定时器
        
        Args:
            interval: 时间间隔（秒）
            callback: 回调函数（可以是同步或异步）
            repeat: 是否重复执行
        """
        self.interval = interval
        self.callback = callback
        self.repeat = repeat
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._start_time: Optional[float] = None
    
    async def start(self) -> None:
        """启动定时器"""
        if self._running:
            return
        
        self._running = True
        self._start_time = time.time()
        self._task = asyncio.create_task(self._run())
    
    async def stop(self) -> None:
        """停止定时器"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
    
    async def restart(self) -> None:
        """重启定时器"""
        await self.stop()
        await self.start()
    
    def is_running(self) -> bool:
        """检查定时器是否运行中"""
        return self._running
    
    def get_elapsed_time(self) -> float:
        """获取已运行时间"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time
    
    async def _run(self) -> None:
        """定时器运行循环"""
        try:
            while self._running:
                await asyncio.sleep(self.interval)
                
                if not self._running:
                    break
                
                try:
                    if asyncio.iscoroutinefunction(self.callback):
                        await self.callback()
                    else:
                        self.callback()
                except Exception as e:
                    logger.error(f"异步定时器回调执行失败: {e}")
                
                if not self.repeat:
                    self._running = False
                    break
                    
        except asyncio.CancelledError:
            pass


class PerformanceTimer:
    """
    性能计时器
    
    用于测量代码执行时间的工具。
    """
    
    def __init__(self, name: str = "operation"):
        """
        初始化性能计时器
        
        Args:
            name: 操作名称
        """
        self.name = name
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.elapsed_time: Optional[float] = None
    
    def start(self) -> 'PerformanceTimer':
        """开始计时"""
        self.start_time = time.perf_counter()
        return self
    
    def stop(self) -> float:
        """
        停止计时
        
        Returns:
            float: 经过时间（秒）
        """
        if self.start_time is None:
            raise RuntimeError("计时器未启动")
        
        self.end_time = time.perf_counter()
        self.elapsed_time = self.end_time - self.start_time
        return self.elapsed_time
    
    def __enter__(self) -> 'PerformanceTimer':
        """上下文管理器入口"""
        return self.start()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口"""
        elapsed = self.stop()
        logger.debug(f"{self.name} 耗时: {elapsed:.6f}秒")


# 工具函数

def sleep_until(target_time: Union[datetime.datetime, float]) -> None:
    """
    睡眠直到指定时间
    
    Args:
        target_time: 目标时间（datetime对象或时间戳）
    """
    if isinstance(target_time, datetime.datetime):
        target_timestamp = target_time.timestamp()
    else:
        target_timestamp = target_time
    
    current_timestamp = time.time()
    sleep_duration = target_timestamp - current_timestamp
    
    if sleep_duration > 0:
        time.sleep(sleep_duration)


async def async_sleep_until(target_time: Union[datetime.datetime, float]) -> None:
    """
    异步睡眠直到指定时间
    
    Args:
        target_time: 目标时间（datetime对象或时间戳）
    """
    if isinstance(target_time, datetime.datetime):
        target_timestamp = target_time.timestamp()
    else:
        target_timestamp = target_time
    
    current_timestamp = time.time()
    sleep_duration = target_timestamp - current_timestamp
    
    if sleep_duration > 0:
        await asyncio.sleep(sleep_duration)


def format_duration(seconds: float, precision: int = 2) -> str:
    """
    格式化时间长度
    
    Args:
        seconds: 秒数
        precision: 小数位数
        
    Returns:
        str: 格式化的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.{precision}f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.{precision}f}分钟"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.{precision}f}小时"
    else:
        days = seconds / 86400
        return f"{days:.{precision}f}天"


def is_weekend(dt: datetime.datetime) -> bool:
    """
    检查是否为周末
    
    Args:
        dt: 时间对象
        
    Returns:
        bool: 是否为周末
    """
    return dt.weekday() >= 5  # 5=Saturday, 6=Sunday


def get_month_range(year: int, month: int, 
                   timezone: Optional[Union[str, ZoneInfo]] = None) -> TimeRange:
    """
    获取指定月份的时间范围
    
    Args:
        year: 年份
        month: 月份
        timezone: 时区
        
    Returns:
        TimeRange: 月份时间范围
    """
    if timezone:
        if isinstance(timezone, str):
            timezone = TimeZoneManager.get_timezone(timezone)
    
    # 月份开始时间
    start = datetime.datetime(year, month, 1)
    if timezone:
        start = start.replace(tzinfo=timezone)
    
    # 月份结束时间
    _, last_day = calendar.monthrange(year, month)
    end = datetime.datetime(year, month, last_day, 23, 59, 59, 999999)
    if timezone:
        end = end.replace(tzinfo=timezone)
    
    return TimeRange(start, end)


def get_week_range(dt: datetime.datetime) -> TimeRange:
    """
    获取指定日期所在周的时间范围
    
    Args:
        dt: 时间对象
        
    Returns:
        TimeRange: 周时间范围
    """
    # 周一为一周的开始
    days_from_monday = dt.weekday()
    
    # 周开始时间（周一 00:00:00）
    start = dt - datetime.timedelta(days=days_from_monday)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 周结束时间（周日 23:59:59）
    end = start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
    
    return TimeRange(start, end)


# 全局游戏时间系统实例
game_time_system = GameTimeSystem()


if __name__ == "__main__":
    # 测试代码
    def test_time_utils():
        """测试时间工具"""
        
        # 测试时间戳转换
        timestamp = time.time()
        dt = TimestampConverter.timestamp_to_datetime(timestamp, 'CST')
        print(f"当前时间: {dt}")
        
        # 测试时间格式化
        time_str = TimestampConverter.datetime_to_string(dt, TimeFormat.CHINESE)
        print(f"中文格式: {time_str}")
        
        # 测试时区转换
        utc_time = TimeZoneManager.convert_timezone(dt, 'CST', 'UTC')
        print(f"UTC时间: {utc_time}")
        
        # 测试性能计时器
        with PerformanceTimer("测试操作") as timer:
            time.sleep(0.1)
        
        # 测试游戏时间系统
        game_time_system.set_game_start_time()
        print(f"游戏时间: {game_time_system.get_game_time()}")
        
        # 测试定时器
        counter = [0]
        
        def increment():
            counter[0] += 1
            print(f"计数器: {counter[0]}")
        
        timer = Timer(1.0, increment, repeat=True)
        time.sleep(3.5)
        timer.stop()
        print(f"定时器停止，最终计数: {counter[0]}")
    
    test_time_utils()