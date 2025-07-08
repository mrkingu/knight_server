"""
限流中间件

该模块负责基于令牌桶算法的限流控制，防止系统过载，
支持多维度限流（全局、用户、IP等）。

主要功能：
- 基于令牌桶的限流
- 多维度限流支持
- 动态限流配置
- 限流统计和监控
"""

import asyncio
import time
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger
from common.security import get_rate_limiter, RateLimitResult
from ..config import GatewayConfig
from ..gate_handler import RequestContext


class LimitDimension(Enum):
    """限流维度枚举"""
    GLOBAL = "global"        # 全局限流
    USER = "user"           # 用户限流
    IP = "ip"               # IP限流
    PROTOCOL = "protocol"   # 协议限流
    CONNECTION = "connection"  # 连接限流


@dataclass
class RateLimitRule:
    """限流规则"""
    dimension: LimitDimension
    key: str
    limit: int              # 限制数量
    window_seconds: int     # 时间窗口(秒)
    burst_limit: int        # 突发限制
    
    # 令牌桶参数
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.time)
    
    def refill_tokens(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self.last_refill
        
        if elapsed > 0:
            # 计算应该添加的令牌数
            tokens_to_add = elapsed * (self.limit / self.window_seconds)
            self.tokens = min(self.burst_limit, self.tokens + tokens_to_add)
            self.last_refill = now
            
    def consume_token(self) -> bool:
        """消耗令牌"""
        self.refill_tokens()
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
        
    def get_available_tokens(self) -> int:
        """获取可用令牌数"""
        self.refill_tokens()
        return int(self.tokens)


@dataclass
class LimitResult:
    """限流结果"""
    allowed: bool
    dimension: LimitDimension
    key: str
    limit: int
    remaining: int
    reset_time: float
    retry_after: float = 0.0


class RateLimitMiddleware:
    """限流中间件"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化限流中间件
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.rate_limiter = None
        
        # 限流规则
        self.rate_limit_rules: Dict[str, RateLimitRule] = {}
        
        # 限流统计
        self._total_requests = 0
        self._blocked_requests = 0
        self._blocked_by_dimension: Dict[LimitDimension, int] = {}
        
        # 初始化限流规则
        self._init_rate_limit_rules()
        
        logger.info("限流中间件初始化完成")
        
    async def process(self, request: Any, context: RequestContext) -> bool:
        """
        处理限流
        
        Args:
            request: 请求数据
            context: 请求上下文
            
        Returns:
            bool: 是否通过限流检查
        """
        try:
            # 检查是否启用限流
            if not self.config.rate_limit.enabled:
                return True
                
            # 更新请求统计
            self._total_requests += 1
            
            # 检查各维度限流
            limit_checks = [
                await self._check_global_limit(context),
                await self._check_user_limit(context),
                await self._check_ip_limit(context),
                await self._check_protocol_limit(context),
                await self._check_connection_limit(context)
            ]
            
            # 检查是否有任何限流被触发
            for result in limit_checks:
                if not result.allowed:
                    self._blocked_requests += 1
                    self._blocked_by_dimension[result.dimension] = (
                        self._blocked_by_dimension.get(result.dimension, 0) + 1
                    )
                    
                    logger.warning("请求被限流", 
                                 dimension=result.dimension.value,
                                 key=result.key,
                                 limit=result.limit,
                                 remaining=result.remaining,
                                 retry_after=result.retry_after)
                    
                    # 记录限流信息到上下文
                    context.metadata["rate_limit_blocked"] = True
                    context.metadata["rate_limit_dimension"] = result.dimension.value
                    context.metadata["rate_limit_retry_after"] = result.retry_after
                    
                    return False
                    
            return True
            
        except Exception as e:
            logger.error("限流处理失败", 
                        protocol_id=context.protocol_id,
                        connection_id=context.connection_id,
                        error=str(e))
            # 限流异常时默认放行
            return True
            
    async def _check_global_limit(self, context: RequestContext) -> LimitResult:
        """
        检查全局限流
        
        Args:
            context: 请求上下文
            
        Returns:
            LimitResult: 限流结果
        """
        rule_key = "global"
        rule = self.rate_limit_rules.get(rule_key)
        
        if not rule:
            rule = RateLimitRule(
                dimension=LimitDimension.GLOBAL,
                key=rule_key,
                limit=self.config.rate_limit.global_limit,
                window_seconds=self.config.rate_limit.window_size,
                burst_limit=self.config.rate_limit.burst_size,
                tokens=self.config.rate_limit.burst_size
            )
            self.rate_limit_rules[rule_key] = rule
            
        allowed = rule.consume_token()
        
        return LimitResult(
            allowed=allowed,
            dimension=LimitDimension.GLOBAL,
            key=rule_key,
            limit=rule.limit,
            remaining=rule.get_available_tokens(),
            reset_time=rule.last_refill + rule.window_seconds,
            retry_after=1.0 if not allowed else 0.0
        )
        
    async def _check_user_limit(self, context: RequestContext) -> LimitResult:
        """
        检查用户限流
        
        Args:
            context: 请求上下文
            
        Returns:
            LimitResult: 限流结果
        """
        if not context.user_id:
            # 未认证用户直接通过
            return LimitResult(
                allowed=True,
                dimension=LimitDimension.USER,
                key="anonymous",
                limit=0,
                remaining=0,
                reset_time=time.time()
            )
            
        rule_key = f"user:{context.user_id}"
        rule = self.rate_limit_rules.get(rule_key)
        
        if not rule:
            rule = RateLimitRule(
                dimension=LimitDimension.USER,
                key=rule_key,
                limit=self.config.rate_limit.user_limit,
                window_seconds=self.config.rate_limit.window_size,
                burst_limit=self.config.rate_limit.burst_size,
                tokens=self.config.rate_limit.burst_size
            )
            self.rate_limit_rules[rule_key] = rule
            
        allowed = rule.consume_token()
        
        return LimitResult(
            allowed=allowed,
            dimension=LimitDimension.USER,
            key=rule_key,
            limit=rule.limit,
            remaining=rule.get_available_tokens(),
            reset_time=rule.last_refill + rule.window_seconds,
            retry_after=1.0 if not allowed else 0.0
        )
        
    async def _check_ip_limit(self, context: RequestContext) -> LimitResult:
        """
        检查IP限流
        
        Args:
            context: 请求上下文
            
        Returns:
            LimitResult: 限流结果
        """
        client_ip = context.client_ip or "unknown"
        rule_key = f"ip:{client_ip}"
        rule = self.rate_limit_rules.get(rule_key)
        
        if not rule:
            rule = RateLimitRule(
                dimension=LimitDimension.IP,
                key=rule_key,
                limit=self.config.rate_limit.ip_limit,
                window_seconds=self.config.rate_limit.window_size,
                burst_limit=self.config.rate_limit.burst_size,
                tokens=self.config.rate_limit.burst_size
            )
            self.rate_limit_rules[rule_key] = rule
            
        allowed = rule.consume_token()
        
        return LimitResult(
            allowed=allowed,
            dimension=LimitDimension.IP,
            key=rule_key,
            limit=rule.limit,
            remaining=rule.get_available_tokens(),
            reset_time=rule.last_refill + rule.window_seconds,
            retry_after=1.0 if not allowed else 0.0
        )
        
    async def _check_protocol_limit(self, context: RequestContext) -> LimitResult:
        """
        检查协议限流
        
        Args:
            context: 请求上下文
            
        Returns:
            LimitResult: 限流结果
        """
        rule_key = f"protocol:{context.protocol_id}"
        rule = self.rate_limit_rules.get(rule_key)
        
        if not rule:
            # 获取协议特定限制，如果没有则使用默认值
            protocol_limit = self._get_protocol_limit(context.protocol_id)
            
            rule = RateLimitRule(
                dimension=LimitDimension.PROTOCOL,
                key=rule_key,
                limit=protocol_limit,
                window_seconds=self.config.rate_limit.window_size,
                burst_limit=protocol_limit * 2,  # 突发限制是正常限制的2倍
                tokens=protocol_limit * 2
            )
            self.rate_limit_rules[rule_key] = rule
            
        allowed = rule.consume_token()
        
        return LimitResult(
            allowed=allowed,
            dimension=LimitDimension.PROTOCOL,
            key=rule_key,
            limit=rule.limit,
            remaining=rule.get_available_tokens(),
            reset_time=rule.last_refill + rule.window_seconds,
            retry_after=1.0 if not allowed else 0.0
        )
        
    async def _check_connection_limit(self, context: RequestContext) -> LimitResult:
        """
        检查连接限流
        
        Args:
            context: 请求上下文
            
        Returns:
            LimitResult: 限流结果
        """
        rule_key = f"connection:{context.connection_id}"
        rule = self.rate_limit_rules.get(rule_key)
        
        if not rule:
            # 单个连接的限制相对较小
            connection_limit = min(100, self.config.rate_limit.user_limit)
            
            rule = RateLimitRule(
                dimension=LimitDimension.CONNECTION,
                key=rule_key,
                limit=connection_limit,
                window_seconds=self.config.rate_limit.window_size,
                burst_limit=connection_limit * 2,
                tokens=connection_limit * 2
            )
            self.rate_limit_rules[rule_key] = rule
            
        allowed = rule.consume_token()
        
        return LimitResult(
            allowed=allowed,
            dimension=LimitDimension.CONNECTION,
            key=rule_key,
            limit=rule.limit,
            remaining=rule.get_available_tokens(),
            reset_time=rule.last_refill + rule.window_seconds,
            retry_after=1.0 if not allowed else 0.0
        )
        
    def _get_protocol_limit(self, protocol_id: int) -> int:
        """
        获取协议限制
        
        Args:
            protocol_id: 协议ID
            
        Returns:
            int: 限制数量
        """
        # 不同协议的限制策略
        protocol_limits = {
            1005: 30,   # 心跳协议限制较高
            1001: 10,   # 登录协议限制较低
            1002: 5,    # 注册协议限制很低
            3001: 60,   # 聊天发送限制较高
            2006: 120,  # 游戏操作限制很高
        }
        
        return protocol_limits.get(protocol_id, 50)  # 默认限制
        
    def _init_rate_limit_rules(self):
        """初始化限流规则"""
        # 初始化全局限流规则
        self.rate_limit_rules["global"] = RateLimitRule(
            dimension=LimitDimension.GLOBAL,
            key="global",
            limit=self.config.rate_limit.global_limit,
            window_seconds=self.config.rate_limit.window_size,
            burst_limit=self.config.rate_limit.burst_size,
            tokens=self.config.rate_limit.burst_size
        )
        
        # 初始化维度统计
        for dimension in LimitDimension:
            self._blocked_by_dimension[dimension] = 0
            
    def update_rate_limit_config(self, **kwargs):
        """
        更新限流配置
        
        Args:
            **kwargs: 配置参数
        """
        for key, value in kwargs.items():
            if hasattr(self.config.rate_limit, key):
                setattr(self.config.rate_limit, key, value)
                logger.info("更新限流配置", key=key, value=value)
                
        # 重新初始化规则
        self._init_rate_limit_rules()
        
    def add_custom_rule(self, rule: RateLimitRule):
        """
        添加自定义限流规则
        
        Args:
            rule: 限流规则
        """
        self.rate_limit_rules[rule.key] = rule
        logger.info("添加自定义限流规则", 
                   key=rule.key,
                   limit=rule.limit,
                   window_seconds=rule.window_seconds)
        
    def remove_rule(self, rule_key: str):
        """
        移除限流规则
        
        Args:
            rule_key: 规则键
        """
        if rule_key in self.rate_limit_rules:
            del self.rate_limit_rules[rule_key]
            logger.info("移除限流规则", rule_key=rule_key)
            
    def get_rule_status(self, rule_key: str) -> Optional[Dict[str, Any]]:
        """
        获取规则状态
        
        Args:
            rule_key: 规则键
            
        Returns:
            Optional[Dict[str, Any]]: 规则状态
        """
        rule = self.rate_limit_rules.get(rule_key)
        if not rule:
            return None
            
        return {
            "key": rule.key,
            "dimension": rule.dimension.value,
            "limit": rule.limit,
            "window_seconds": rule.window_seconds,
            "burst_limit": rule.burst_limit,
            "available_tokens": rule.get_available_tokens(),
            "last_refill": rule.last_refill
        }
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        blocked_rate = 0.0
        if self._total_requests > 0:
            blocked_rate = self._blocked_requests / self._total_requests
            
        return {
            "total_requests": self._total_requests,
            "blocked_requests": self._blocked_requests,
            "blocked_rate": blocked_rate,
            "blocked_by_dimension": {
                dim.value: count for dim, count in self._blocked_by_dimension.items()
            },
            "active_rules": len(self.rate_limit_rules),
            "enabled": self.config.rate_limit.enabled,
            "global_limit": self.config.rate_limit.global_limit,
            "user_limit": self.config.rate_limit.user_limit,
            "ip_limit": self.config.rate_limit.ip_limit
        }
        
    def reset_statistics(self):
        """重置统计信息"""
        self._total_requests = 0
        self._blocked_requests = 0
        self._blocked_by_dimension = {dim: 0 for dim in LimitDimension}
        logger.info("限流统计信息已重置")
        
    async def cleanup_expired_rules(self):
        """清理过期规则"""
        current_time = time.time()
        expired_rules = []
        
        for rule_key, rule in self.rate_limit_rules.items():
            # 如果规则长时间未使用，可以考虑清理
            if current_time - rule.last_refill > 3600:  # 1小时未使用
                # 跳过全局规则
                if rule.dimension != LimitDimension.GLOBAL:
                    expired_rules.append(rule_key)
                    
        for rule_key in expired_rules:
            del self.rate_limit_rules[rule_key]
            
        if expired_rules:
            logger.info("清理过期限流规则", count=len(expired_rules))