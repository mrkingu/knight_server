"""
common/security 模块

该模块提供了完整的安全功能实现，包括：
- JWT认证和授权
- 请求签名验证
- 分布式限流
- 熔断器保护
"""

# JWT认证模块
from .jwt_auth import (
    JWTAuth,
    TokenConfig,
    TokenPayload,
    TokenPair,
    TokenType,
    JWTAlgorithm,
    JWTError,
    TokenExpiredError,
    TokenInvalidError,
    TokenBlacklistedError,
    generate_tokens,
    verify_token,
    refresh_token,
    revoke_token,
    get_jwt_auth,
    default_config as jwt_default_config
)

# 签名验证模块
from .signature import (
    SignatureVerifier,
    SignatureConfig,
    SignatureRequest,
    SignatureResult,
    SignatureMethod,
    SignatureVersion,
    SignatureError,
    TimestampError,
    NonceError,
    SignatureInvalidError,
    verify_signature,
    generate_signature,
    get_signature_verifier,
    default_config as signature_default_config
)

# 限流器模块
from .rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitRule,
    RateLimitResult,
    RateLimitAlgorithm,
    RateLimitDimension,
    RateLimitError,
    RateLimitExceededError,
    RateLimitConfigError,
    TokenBucketLimiter,
    SlidingWindowLimiter,
    LeakyBucketLimiter,
    FixedWindowLimiter,
    check_rate_limit,
    reset_rate_limit,
    create_rate_limit_rule,
    get_rate_limiter,
    default_config as rate_limit_default_config
)

# 熔断器模块
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitBreakerConfig,
    CircuitBreakerMetrics,
    CircuitBreakerEvent,
    CallResult,
    CircuitState,
    CircuitBreakerStrategy,
    CircuitBreakerError,
    CircuitOpenError,
    CircuitHalfOpenError,
    create_circuit_breaker,
    get_circuit_breaker,
    circuit_breaker_call,
    circuit_breaker_decorator,
    get_circuit_breaker_manager,
    default_config as circuit_breaker_default_config
)

# 导出所有模块
__all__ = [
    # JWT认证
    'JWTAuth',
    'TokenConfig',
    'TokenPayload',
    'TokenPair',
    'TokenType',
    'JWTAlgorithm',
    'JWTError',
    'TokenExpiredError',
    'TokenInvalidError',
    'TokenBlacklistedError',
    'generate_tokens',
    'verify_token',
    'refresh_token',
    'revoke_token',
    'get_jwt_auth',
    'jwt_default_config',
    
    # 签名验证
    'SignatureVerifier',
    'SignatureConfig',
    'SignatureRequest',
    'SignatureResult',
    'SignatureMethod',
    'SignatureVersion',
    'SignatureError',
    'TimestampError',
    'NonceError',
    'SignatureInvalidError',
    'verify_signature',
    'generate_signature',
    'get_signature_verifier',
    'signature_default_config',
    
    # 限流器
    'RateLimiter',
    'RateLimitConfig',
    'RateLimitRule',
    'RateLimitResult',
    'RateLimitAlgorithm',
    'RateLimitDimension',
    'RateLimitError',
    'RateLimitExceededError',
    'RateLimitConfigError',
    'TokenBucketLimiter',
    'SlidingWindowLimiter',
    'LeakyBucketLimiter',
    'FixedWindowLimiter',
    'check_rate_limit',
    'reset_rate_limit',
    'create_rate_limit_rule',
    'get_rate_limiter',
    'rate_limit_default_config',
    
    # 熔断器
    'CircuitBreaker',
    'CircuitBreakerManager',
    'CircuitBreakerConfig',
    'CircuitBreakerMetrics',
    'CircuitBreakerEvent',
    'CallResult',
    'CircuitState',
    'CircuitBreakerStrategy',
    'CircuitBreakerError',
    'CircuitOpenError',
    'CircuitHalfOpenError',
    'create_circuit_breaker',
    'get_circuit_breaker',
    'circuit_breaker_call',
    'circuit_breaker_decorator',
    'get_circuit_breaker_manager',
    'circuit_breaker_default_config'
]
