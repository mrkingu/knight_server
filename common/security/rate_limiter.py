"""
限流器模块

该模块提供分布式限流功能，包括：
- 多种限流算法（令牌桶、滑动窗口、漏桶）
- 多维度限流（用户、IP、API级别）
- 基于Redis的分布式实现
- 限流降级策略
- 动态限流规则配置
"""

import time
import json
import asyncio
import math
from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

from common.logger import logger


class RateLimitAlgorithm(Enum):
    """限流算法枚举"""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    LEAKY_BUCKET = "leaky_bucket"
    FIXED_WINDOW = "fixed_window"


class RateLimitDimension(Enum):
    """限流维度枚举"""
    USER = "user"
    IP = "ip"
    API = "api"
    CUSTOM = "custom"


@dataclass
class RateLimitRule:
    """限流规则"""
    key: str
    limit: int  # 限制数量
    window: int  # 时间窗口（秒）
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    dimension: RateLimitDimension = RateLimitDimension.USER
    description: str = ""
    enabled: bool = True
    priority: int = 0  # 优先级，数字越大优先级越高


@dataclass
class RateLimitConfig:
    """限流配置"""
    default_algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    redis_key_prefix: str = "rate_limit"
    redis_key_expire: int = 3600  # Redis键过期时间
    enable_degradation: bool = True  # 启用降级
    degradation_threshold: float = 0.8  # 降级阈值
    default_limit: int = 100  # 默认限制
    default_window: int = 60  # 默认时间窗口
    enable_whitelist: bool = True  # 启用白名单
    enable_monitoring: bool = True  # 启用监控


@dataclass
class RateLimitResult:
    """限流结果"""
    allowed: bool
    remaining: int
    reset_time: int
    retry_after: Optional[int] = None
    rule_key: Optional[str] = None
    algorithm: Optional[str] = None
    dimension: Optional[str] = None


class RateLimitError(Exception):
    """限流相关异常基类"""
    pass


class RateLimitExceededError(RateLimitError):
    """超过限流异常"""
    pass


class RateLimitConfigError(RateLimitError):
    """限流配置异常"""
    pass


class BaseRateLimiter(ABC):
    """基础限流器抽象类"""
    
    def __init__(self, rule: RateLimitRule, redis_manager=None):
        self.rule = rule
        self.redis_manager = redis_manager
    
    @abstractmethod
    async def check_limit(self, key: str) -> RateLimitResult:
        """检查限流"""
        pass
    
    @abstractmethod
    async def reset_limit(self, key: str):
        """重置限流"""
        pass
    
    def _get_redis_key(self, key: str) -> str:
        """获取Redis键"""
        return f"rate_limit:{self.rule.algorithm.value}:{key}"


class TokenBucketLimiter(BaseRateLimiter):
    """令牌桶限流器"""
    
    async def check_limit(self, key: str) -> RateLimitResult:
        """检查令牌桶限流"""
        redis_key = self._get_redis_key(key)
        current_time = int(time.time())
        
        if self.redis_manager:
            try:
                # 使用Lua脚本保证原子性
                lua_script = """
                local key = KEYS[1]
                local limit = tonumber(ARGV[1])
                local window = tonumber(ARGV[2])
                local current_time = tonumber(ARGV[3])
                
                local bucket_data = redis.call('HMGET', key, 'tokens', 'last_refill')
                local tokens = tonumber(bucket_data[1]) or limit
                local last_refill = tonumber(bucket_data[2]) or current_time
                
                -- 计算需要添加的令牌数
                local time_passed = current_time - last_refill
                local tokens_to_add = math.floor(time_passed * limit / window)
                tokens = math.min(limit, tokens + tokens_to_add)
                
                -- 检查是否可以消费令牌
                local allowed = tokens > 0
                if allowed then
                    tokens = tokens - 1
                end
                
                -- 更新桶状态
                redis.call('HMSET', key, 'tokens', tokens, 'last_refill', current_time)
                redis.call('EXPIRE', key, window * 2)
                
                local reset_time = current_time + math.ceil((limit - tokens) * window / limit)
                
                return {allowed and 1 or 0, tokens, reset_time}
                """
                
                result = await self.redis_manager.eval(
                    lua_script,
                    1,
                    redis_key,
                    self.rule.limit,
                    self.rule.window,
                    current_time
                )
                
                allowed, remaining, reset_time = result
                
                return RateLimitResult(
                    allowed=bool(allowed),
                    remaining=remaining,
                    reset_time=reset_time,
                    retry_after=reset_time - current_time if not allowed else None,
                    rule_key=self.rule.key,
                    algorithm=self.rule.algorithm.value,
                    dimension=self.rule.dimension.value
                )
                
            except Exception as e:
                logger.error(f"令牌桶限流Redis操作失败: {e}")
                # 降级处理
                return RateLimitResult(
                    allowed=True,
                    remaining=self.rule.limit,
                    reset_time=current_time + self.rule.window
                )
        
        # 内存实现（降级）
        logger.warning("使用内存实现令牌桶限流（降级模式）")
        return RateLimitResult(
            allowed=True,
            remaining=self.rule.limit,
            reset_time=current_time + self.rule.window
        )
    
    async def reset_limit(self, key: str):
        """重置令牌桶"""
        redis_key = self._get_redis_key(key)
        if self.redis_manager:
            try:
                await self.redis_manager.delete(redis_key)
            except Exception as e:
                logger.error(f"重置令牌桶失败: {e}")


class SlidingWindowLimiter(BaseRateLimiter):
    """滑动窗口限流器"""
    
    async def check_limit(self, key: str) -> RateLimitResult:
        """检查滑动窗口限流"""
        redis_key = self._get_redis_key(key)
        current_time = int(time.time())
        window_start = current_time - self.rule.window
        
        if self.redis_manager:
            try:
                # 使用Lua脚本保证原子性
                lua_script = """
                local key = KEYS[1]
                local limit = tonumber(ARGV[1])
                local window = tonumber(ARGV[2])
                local current_time = tonumber(ARGV[3])
                local window_start = tonumber(ARGV[4])
                
                -- 移除过期的记录
                redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
                
                -- 获取当前窗口内的计数
                local current_count = redis.call('ZCARD', key)
                
                -- 检查是否超过限制
                local allowed = current_count < limit
                if allowed then
                    -- 添加当前请求
                    redis.call('ZADD', key, current_time, current_time)
                    current_count = current_count + 1
                end
                
                -- 设置过期时间
                redis.call('EXPIRE', key, window * 2)
                
                local remaining = math.max(0, limit - current_count)
                local reset_time = current_time + window
                
                return {allowed and 1 or 0, remaining, reset_time}
                """
                
                result = await self.redis_manager.eval(
                    lua_script,
                    1,
                    redis_key,
                    self.rule.limit,
                    self.rule.window,
                    current_time,
                    window_start
                )
                
                allowed, remaining, reset_time = result
                
                return RateLimitResult(
                    allowed=bool(allowed),
                    remaining=remaining,
                    reset_time=reset_time,
                    retry_after=1 if not allowed else None,
                    rule_key=self.rule.key,
                    algorithm=self.rule.algorithm.value,
                    dimension=self.rule.dimension.value
                )
                
            except Exception as e:
                logger.error(f"滑动窗口限流Redis操作失败: {e}")
                # 降级处理
                return RateLimitResult(
                    allowed=True,
                    remaining=self.rule.limit,
                    reset_time=current_time + self.rule.window
                )
        
        # 内存实现（降级）
        logger.warning("使用内存实现滑动窗口限流（降级模式）")
        return RateLimitResult(
            allowed=True,
            remaining=self.rule.limit,
            reset_time=current_time + self.rule.window
        )
    
    async def reset_limit(self, key: str):
        """重置滑动窗口"""
        redis_key = self._get_redis_key(key)
        if self.redis_manager:
            try:
                await self.redis_manager.delete(redis_key)
            except Exception as e:
                logger.error(f"重置滑动窗口失败: {e}")


class LeakyBucketLimiter(BaseRateLimiter):
    """漏桶限流器"""
    
    async def check_limit(self, key: str) -> RateLimitResult:
        """检查漏桶限流"""
        redis_key = self._get_redis_key(key)
        current_time = int(time.time())
        
        if self.redis_manager:
            try:
                # 使用Lua脚本保证原子性
                lua_script = """
                local key = KEYS[1]
                local limit = tonumber(ARGV[1])
                local window = tonumber(ARGV[2])
                local current_time = tonumber(ARGV[3])
                
                local bucket_data = redis.call('HMGET', key, 'volume', 'last_leak')
                local volume = tonumber(bucket_data[1]) or 0
                local last_leak = tonumber(bucket_data[2]) or current_time
                
                -- 计算漏掉的水量
                local time_passed = current_time - last_leak
                local leak_amount = time_passed * limit / window
                volume = math.max(0, volume - leak_amount)
                
                -- 检查是否可以添加新的水滴
                local allowed = volume < limit
                if allowed then
                    volume = volume + 1
                end
                
                -- 更新桶状态
                redis.call('HMSET', key, 'volume', volume, 'last_leak', current_time)
                redis.call('EXPIRE', key, window * 2)
                
                local remaining = math.max(0, limit - volume)
                local reset_time = current_time + math.ceil(volume * window / limit)
                
                return {allowed and 1 or 0, remaining, reset_time}
                """
                
                result = await self.redis_manager.eval(
                    lua_script,
                    1,
                    redis_key,
                    self.rule.limit,
                    self.rule.window,
                    current_time
                )
                
                allowed, remaining, reset_time = result
                
                return RateLimitResult(
                    allowed=bool(allowed),
                    remaining=remaining,
                    reset_time=reset_time,
                    retry_after=reset_time - current_time if not allowed else None,
                    rule_key=self.rule.key,
                    algorithm=self.rule.algorithm.value,
                    dimension=self.rule.dimension.value
                )
                
            except Exception as e:
                logger.error(f"漏桶限流Redis操作失败: {e}")
                # 降级处理
                return RateLimitResult(
                    allowed=True,
                    remaining=self.rule.limit,
                    reset_time=current_time + self.rule.window
                )
        
        # 内存实现（降级）
        logger.warning("使用内存实现漏桶限流（降级模式）")
        return RateLimitResult(
            allowed=True,
            remaining=self.rule.limit,
            reset_time=current_time + self.rule.window
        )
    
    async def reset_limit(self, key: str):
        """重置漏桶"""
        redis_key = self._get_redis_key(key)
        if self.redis_manager:
            try:
                await self.redis_manager.delete(redis_key)
            except Exception as e:
                logger.error(f"重置漏桶失败: {e}")


class FixedWindowLimiter(BaseRateLimiter):
    """固定窗口限流器"""
    
    async def check_limit(self, key: str) -> RateLimitResult:
        """检查固定窗口限流"""
        redis_key = self._get_redis_key(key)
        current_time = int(time.time())
        window_start = (current_time // self.rule.window) * self.rule.window
        window_key = f"{redis_key}:{window_start}"
        
        if self.redis_manager:
            try:
                # 使用Lua脚本保证原子性
                lua_script = """
                local key = KEYS[1]
                local limit = tonumber(ARGV[1])
                local window = tonumber(ARGV[2])
                local current_time = tonumber(ARGV[3])
                local window_start = tonumber(ARGV[4])
                
                -- 获取当前窗口的计数
                local current_count = tonumber(redis.call('GET', key)) or 0
                
                -- 检查是否超过限制
                local allowed = current_count < limit
                if allowed then
                    -- 增加计数
                    redis.call('INCR', key)
                    current_count = current_count + 1
                end
                
                -- 设置过期时间
                redis.call('EXPIRE', key, window)
                
                local remaining = math.max(0, limit - current_count)
                local reset_time = window_start + window
                
                return {allowed and 1 or 0, remaining, reset_time}
                """
                
                result = await self.redis_manager.eval(
                    lua_script,
                    1,
                    window_key,
                    self.rule.limit,
                    self.rule.window,
                    current_time,
                    window_start
                )
                
                allowed, remaining, reset_time = result
                
                return RateLimitResult(
                    allowed=bool(allowed),
                    remaining=remaining,
                    reset_time=reset_time,
                    retry_after=reset_time - current_time if not allowed else None,
                    rule_key=self.rule.key,
                    algorithm=self.rule.algorithm.value,
                    dimension=self.rule.dimension.value
                )
                
            except Exception as e:
                logger.error(f"固定窗口限流Redis操作失败: {e}")
                # 降级处理
                return RateLimitResult(
                    allowed=True,
                    remaining=self.rule.limit,
                    reset_time=window_start + self.rule.window
                )
        
        # 内存实现（降级）
        logger.warning("使用内存实现固定窗口限流（降级模式）")
        return RateLimitResult(
            allowed=True,
            remaining=self.rule.limit,
            reset_time=window_start + self.rule.window
        )
    
    async def reset_limit(self, key: str):
        """重置固定窗口"""
        redis_key = self._get_redis_key(key)
        if self.redis_manager:
            try:
                # 删除所有相关的窗口键
                pattern = f"{redis_key}:*"
                keys = await self.redis_manager.keys(pattern)
                if keys:
                    await self.redis_manager.delete(*keys)
            except Exception as e:
                logger.error(f"重置固定窗口失败: {e}")


class RateLimiter:
    """限流器主类"""
    
    def __init__(self, config: RateLimitConfig, redis_manager=None):
        """
        初始化限流器
        
        Args:
            config: 限流配置
            redis_manager: Redis管理器
        """
        self.config = config
        self.redis_manager = redis_manager
        self.rules: Dict[str, RateLimitRule] = {}
        self.limiters: Dict[str, BaseRateLimiter] = {}
        self.whitelist: List[str] = []
        self.stats: Dict[str, Any] = {
            'requests_total': 0,
            'requests_allowed': 0,
            'requests_denied': 0,
            'degradation_count': 0
        }
    
    def add_rule(self, rule: RateLimitRule):
        """
        添加限流规则
        
        Args:
            rule: 限流规则
        """
        self.rules[rule.key] = rule
        
        # 创建对应的限流器
        if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            self.limiters[rule.key] = TokenBucketLimiter(rule, self.redis_manager)
        elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            self.limiters[rule.key] = SlidingWindowLimiter(rule, self.redis_manager)
        elif rule.algorithm == RateLimitAlgorithm.LEAKY_BUCKET:
            self.limiters[rule.key] = LeakyBucketLimiter(rule, self.redis_manager)
        elif rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
            self.limiters[rule.key] = FixedWindowLimiter(rule, self.redis_manager)
        else:
            raise RateLimitConfigError(f"不支持的限流算法: {rule.algorithm}")
        
        logger.info(f"已添加限流规则: {rule.key} ({rule.algorithm.value})")
    
    def remove_rule(self, key: str):
        """
        移除限流规则
        
        Args:
            key: 规则键
        """
        if key in self.rules:
            del self.rules[key]
            del self.limiters[key]
            logger.info(f"已移除限流规则: {key}")
    
    def get_rule(self, key: str) -> Optional[RateLimitRule]:
        """
        获取限流规则
        
        Args:
            key: 规则键
            
        Returns:
            RateLimitRule: 限流规则
        """
        return self.rules.get(key)
    
    def list_rules(self) -> List[RateLimitRule]:
        """
        列出所有限流规则
        
        Returns:
            List[RateLimitRule]: 规则列表
        """
        return list(self.rules.values())
    
    def add_to_whitelist(self, identifier: str):
        """
        添加到白名单
        
        Args:
            identifier: 标识符
        """
        if identifier not in self.whitelist:
            self.whitelist.append(identifier)
            logger.info(f"已添加到限流白名单: {identifier}")
    
    def remove_from_whitelist(self, identifier: str):
        """
        从白名单移除
        
        Args:
            identifier: 标识符
        """
        if identifier in self.whitelist:
            self.whitelist.remove(identifier)
            logger.info(f"已从限流白名单移除: {identifier}")
    
    def is_whitelisted(self, identifier: str) -> bool:
        """
        检查是否在白名单中
        
        Args:
            identifier: 标识符
            
        Returns:
            bool: 是否在白名单中
        """
        return identifier in self.whitelist
    
    def _build_rate_limit_key(self, identifier: str, dimension: RateLimitDimension, 
                             context: Dict[str, Any] = None) -> str:
        """
        构建限流键
        
        Args:
            identifier: 标识符
            dimension: 限流维度
            context: 上下文信息
            
        Returns:
            str: 限流键
        """
        if dimension == RateLimitDimension.USER:
            return f"user:{identifier}"
        elif dimension == RateLimitDimension.IP:
            return f"ip:{identifier}"
        elif dimension == RateLimitDimension.API:
            return f"api:{identifier}"
        elif dimension == RateLimitDimension.CUSTOM:
            if context:
                custom_key = context.get('custom_key', identifier)
                return f"custom:{custom_key}"
            return f"custom:{identifier}"
        else:
            return identifier
    
    def _select_rule(self, dimension: RateLimitDimension, 
                    context: Dict[str, Any] = None) -> Optional[RateLimitRule]:
        """
        选择适用的限流规则
        
        Args:
            dimension: 限流维度
            context: 上下文信息
            
        Returns:
            Optional[RateLimitRule]: 适用的规则
        """
        # 查找匹配的规则
        applicable_rules = []
        
        for rule in self.rules.values():
            if not rule.enabled:
                continue
            
            if rule.dimension == dimension:
                applicable_rules.append(rule)
            elif context and rule.key in context:
                applicable_rules.append(rule)
        
        if not applicable_rules:
            return None
        
        # 按优先级排序，返回优先级最高的规则
        applicable_rules.sort(key=lambda r: r.priority, reverse=True)
        return applicable_rules[0]
    
    async def check_limit(self, identifier: str, dimension: RateLimitDimension,
                         context: Dict[str, Any] = None) -> RateLimitResult:
        """
        检查限流
        
        Args:
            identifier: 标识符
            dimension: 限流维度
            context: 上下文信息
            
        Returns:
            RateLimitResult: 限流结果
        """
        self.stats['requests_total'] += 1
        
        # 检查白名单
        if self.config.enable_whitelist and self.is_whitelisted(identifier):
            self.stats['requests_allowed'] += 1
            return RateLimitResult(
                allowed=True,
                remaining=999999,
                reset_time=int(time.time()) + 3600
            )
        
        # 选择适用的规则
        rule = self._select_rule(dimension, context)
        if not rule:
            # 使用默认规则
            rule = RateLimitRule(
                key="default",
                limit=self.config.default_limit,
                window=self.config.default_window,
                algorithm=self.config.default_algorithm,
                dimension=dimension
            )
            
            # 临时创建限流器
            if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                limiter = TokenBucketLimiter(rule, self.redis_manager)
            elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                limiter = SlidingWindowLimiter(rule, self.redis_manager)
            elif rule.algorithm == RateLimitAlgorithm.LEAKY_BUCKET:
                limiter = LeakyBucketLimiter(rule, self.redis_manager)
            else:
                limiter = FixedWindowLimiter(rule, self.redis_manager)
        else:
            limiter = self.limiters[rule.key]
        
        # 构建限流键
        rate_limit_key = self._build_rate_limit_key(identifier, dimension, context)
        
        try:
            # 检查限流
            result = await limiter.check_limit(rate_limit_key)
            
            if result.allowed:
                self.stats['requests_allowed'] += 1
            else:
                self.stats['requests_denied'] += 1
            
            return result
            
        except Exception as e:
            logger.error(f"检查限流失败: {e}")
            
            # 降级处理
            if self.config.enable_degradation:
                self.stats['degradation_count'] += 1
                self.stats['requests_allowed'] += 1
                return RateLimitResult(
                    allowed=True,
                    remaining=self.config.default_limit,
                    reset_time=int(time.time()) + self.config.default_window
                )
            else:
                self.stats['requests_denied'] += 1
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_time=int(time.time()) + self.config.default_window
                )
    
    async def reset_limit(self, identifier: str, dimension: RateLimitDimension,
                         context: Dict[str, Any] = None):
        """
        重置限流
        
        Args:
            identifier: 标识符
            dimension: 限流维度
            context: 上下文信息
        """
        # 选择适用的规则
        rule = self._select_rule(dimension, context)
        if not rule:
            logger.warning(f"未找到适用的限流规则: {identifier}")
            return
        
        limiter = self.limiters[rule.key]
        rate_limit_key = self._build_rate_limit_key(identifier, dimension, context)
        
        try:
            await limiter.reset_limit(rate_limit_key)
            logger.info(f"已重置限流: {rate_limit_key}")
        except Exception as e:
            logger.error(f"重置限流失败: {e}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        stats = self.stats.copy()
        stats['rules_count'] = len(self.rules)
        stats['whitelist_count'] = len(self.whitelist)
        stats['success_rate'] = (
            stats['requests_allowed'] / stats['requests_total'] 
            if stats['requests_total'] > 0 else 0
        )
        stats['degradation_rate'] = (
            stats['degradation_count'] / stats['requests_total'] 
            if stats['requests_total'] > 0 else 0
        )
        
        return stats
    
    async def clear_stats(self):
        """清理统计信息"""
        self.stats = {
            'requests_total': 0,
            'requests_allowed': 0,
            'requests_denied': 0,
            'degradation_count': 0
        }
        logger.info("已清理限流统计信息")


# 默认配置实例
default_config = RateLimitConfig()

# 默认限流器实例
_default_limiter = None


def get_rate_limiter(config: RateLimitConfig = None, redis_manager=None) -> RateLimiter:
    """
    获取限流器实例
    
    Args:
        config: 限流配置
        redis_manager: Redis管理器
        
    Returns:
        RateLimiter: 限流器实例
    """
    global _default_limiter
    
    if config is None:
        config = default_config
    
    if _default_limiter is None:
        _default_limiter = RateLimiter(config, redis_manager)
    
    return _default_limiter


# 便捷函数
async def check_rate_limit(identifier: str, dimension: RateLimitDimension,
                          context: Dict[str, Any] = None,
                          config: RateLimitConfig = None) -> RateLimitResult:
    """检查限流的便捷函数"""
    limiter = get_rate_limiter(config)
    return await limiter.check_limit(identifier, dimension, context)


async def reset_rate_limit(identifier: str, dimension: RateLimitDimension,
                          context: Dict[str, Any] = None,
                          config: RateLimitConfig = None):
    """重置限流的便捷函数"""
    limiter = get_rate_limiter(config)
    await limiter.reset_limit(identifier, dimension, context)


def create_rate_limit_rule(key: str, limit: int, window: int,
                          algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET,
                          dimension: RateLimitDimension = RateLimitDimension.USER,
                          description: str = "") -> RateLimitRule:
    """创建限流规则的便捷函数"""
    return RateLimitRule(
        key=key,
        limit=limit,
        window=window,
        algorithm=algorithm,
        dimension=dimension,
        description=description
    )