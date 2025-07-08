"""
JWT认证模块

该模块提供完整的JWT认证功能，包括：
- JWT令牌生成、验证和刷新
- 双令牌机制（access_token和refresh_token）
- 令牌黑名单管理
- 自动续期功能
- 多种加密算法支持
- 用户权限和角色集成
"""

import time
import json
import asyncio
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from common.logger import logger


class TokenType(Enum):
    """令牌类型枚举"""
    ACCESS = "access"
    REFRESH = "refresh"


class JWTAlgorithm(Enum):
    """JWT算法枚举"""
    HS256 = "HS256"
    RS256 = "RS256"


@dataclass
class TokenConfig:
    """JWT令牌配置"""
    secret_key: str = "knight_server_secret_key"
    algorithm: JWTAlgorithm = JWTAlgorithm.HS256
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    issuer: str = "knight_server"
    audience: str = "knight_client"
    auto_refresh: bool = True
    auto_refresh_threshold_minutes: int = 5
    blacklist_enabled: bool = True
    private_key_path: Optional[str] = None
    public_key_path: Optional[str] = None


@dataclass
class TokenPayload:
    """JWT令牌载荷"""
    user_id: int
    username: str
    roles: List[str]
    permissions: List[str]
    token_type: TokenType
    issued_at: int
    expires_at: int
    issuer: str
    audience: str
    jti: str  # JWT ID


@dataclass
class TokenPair:
    """令牌对"""
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


class JWTError(Exception):
    """JWT相关异常基类"""
    pass


class TokenExpiredError(JWTError):
    """令牌过期异常"""
    pass


class TokenInvalidError(JWTError):
    """令牌无效异常"""
    pass


class TokenBlacklistedError(JWTError):
    """令牌被列入黑名单异常"""
    pass


class JWTAuth:
    """JWT认证器"""
    
    def __init__(self, config: TokenConfig, redis_manager=None):
        """
        初始化JWT认证器
        
        Args:
            config: JWT配置
            redis_manager: Redis管理器实例（用于黑名单）
        """
        self.config = config
        self.redis_manager = redis_manager
        self._private_key = None
        self._public_key = None
        
        # 如果使用RS256算法，加载密钥
        if self.config.algorithm == JWTAlgorithm.RS256:
            self._load_rsa_keys()
    
    def _load_rsa_keys(self):
        """加载RSA密钥对"""
        try:
            if self.config.private_key_path:
                with open(self.config.private_key_path, 'rb') as f:
                    self._private_key = serialization.load_pem_private_key(
                        f.read(),
                        password=None
                    )
            
            if self.config.public_key_path:
                with open(self.config.public_key_path, 'rb') as f:
                    self._public_key = serialization.load_pem_public_key(f.read())
        except Exception as e:
            logger.error(f"加载RSA密钥失败: {e}")
            # 生成临时密钥对
            self._generate_temp_keys()
    
    def _generate_temp_keys(self):
        """生成临时RSA密钥对"""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self._private_key = private_key
        self._public_key = private_key.public_key()
        logger.warning("使用临时生成的RSA密钥对")
    
    def _get_signing_key(self):
        """获取签名密钥"""
        if self.config.algorithm == JWTAlgorithm.HS256:
            return self.config.secret_key
        elif self.config.algorithm == JWTAlgorithm.RS256:
            return self._private_key
        else:
            raise JWTError(f"不支持的算法: {self.config.algorithm}")
    
    def _get_verifying_key(self):
        """获取验证密钥"""
        if self.config.algorithm == JWTAlgorithm.HS256:
            return self.config.secret_key
        elif self.config.algorithm == JWTAlgorithm.RS256:
            return self._public_key
        else:
            raise JWTError(f"不支持的算法: {self.config.algorithm}")
    
    def _generate_jti(self) -> str:
        """生成JWT ID"""
        import uuid
        return str(uuid.uuid4())
    
    async def _add_to_blacklist(self, jti: str, exp: int):
        """添加令牌到黑名单"""
        if not self.config.blacklist_enabled or not self.redis_manager:
            return
        
        try:
            # 计算TTL（到期时间）
            current_time = int(time.time())
            ttl = max(0, exp - current_time)
            
            if ttl > 0:
                # 使用Redis存储黑名单
                blacklist_key = f"jwt_blacklist:{jti}"
                await self.redis_manager.setex(blacklist_key, ttl, "1")
                logger.debug(f"令牌已添加到黑名单: {jti}")
        except Exception as e:
            logger.error(f"添加令牌到黑名单失败: {e}")
    
    async def _is_blacklisted(self, jti: str) -> bool:
        """检查令牌是否在黑名单中"""
        if not self.config.blacklist_enabled or not self.redis_manager:
            return False
        
        try:
            blacklist_key = f"jwt_blacklist:{jti}"
            result = await self.redis_manager.get(blacklist_key)
            return result is not None
        except Exception as e:
            logger.error(f"检查黑名单失败: {e}")
            return False
    
    async def generate_tokens(self, user_id: int, username: str, 
                            roles: List[str], permissions: List[str]) -> TokenPair:
        """
        生成令牌对
        
        Args:
            user_id: 用户ID
            username: 用户名
            roles: 用户角色列表
            permissions: 用户权限列表
            
        Returns:
            TokenPair: 令牌对
        """
        current_time = int(time.time())
        
        # 生成访问令牌
        access_exp = current_time + self.config.access_token_expire_minutes * 60
        access_payload = TokenPayload(
            user_id=user_id,
            username=username,
            roles=roles,
            permissions=permissions,
            token_type=TokenType.ACCESS,
            issued_at=current_time,
            expires_at=access_exp,
            issuer=self.config.issuer,
            audience=self.config.audience,
            jti=self._generate_jti()
        )
        
        # 生成刷新令牌
        refresh_exp = current_time + self.config.refresh_token_expire_days * 24 * 60 * 60
        refresh_payload = TokenPayload(
            user_id=user_id,
            username=username,
            roles=roles,
            permissions=permissions,
            token_type=TokenType.REFRESH,
            issued_at=current_time,
            expires_at=refresh_exp,
            issuer=self.config.issuer,
            audience=self.config.audience,
            jti=self._generate_jti()
        )
        
        # 编码令牌
        access_token = self._encode_token(access_payload)
        refresh_token = self._encode_token(refresh_payload)
        
        # 如果启用了黑名单，存储令牌ID用于后续撤销
        if self.config.blacklist_enabled and self.redis_manager:
            try:
                token_info = {
                    'user_id': user_id,
                    'username': username,
                    'issued_at': current_time
                }
                
                # 存储访问令牌信息
                access_key = f"jwt_token:{access_payload.jti}"
                await self.redis_manager.setex(
                    access_key, 
                    self.config.access_token_expire_minutes * 60, 
                    json.dumps(token_info)
                )
                
                # 存储刷新令牌信息
                refresh_key = f"jwt_token:{refresh_payload.jti}"
                await self.redis_manager.setex(
                    refresh_key, 
                    self.config.refresh_token_expire_days * 24 * 60 * 60, 
                    json.dumps(token_info)
                )
            except Exception as e:
                logger.error(f"存储令牌信息失败: {e}")
        
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.config.access_token_expire_minutes * 60
        )
    
    def _encode_token(self, payload: TokenPayload) -> str:
        """编码令牌"""
        try:
            jwt_payload = {
                'user_id': payload.user_id,
                'username': payload.username,
                'roles': payload.roles,
                'permissions': payload.permissions,
                'token_type': payload.token_type.value,
                'iat': payload.issued_at,
                'exp': payload.expires_at,
                'iss': payload.issuer,
                'aud': payload.audience,
                'jti': payload.jti
            }
            
            return jwt.encode(
                jwt_payload,
                self._get_signing_key(),
                algorithm=self.config.algorithm.value
            )
        except Exception as e:
            logger.error(f"编码令牌失败: {e}")
            raise JWTError(f"编码令牌失败: {e}")
    
    async def verify_token(self, token: str, token_type: TokenType = None) -> TokenPayload:
        """
        验证令牌
        
        Args:
            token: JWT令牌
            token_type: 期望的令牌类型（可选）
            
        Returns:
            TokenPayload: 解码后的令牌载荷
            
        Raises:
            TokenExpiredError: 令牌已过期
            TokenInvalidError: 令牌无效
            TokenBlacklistedError: 令牌在黑名单中
        """
        try:
            # 解码令牌
            decoded_payload = jwt.decode(
                token,
                self._get_verifying_key(),
                algorithms=[self.config.algorithm.value],
                audience=self.config.audience,
                issuer=self.config.issuer
            )
            
            # 构造载荷对象
            payload = TokenPayload(
                user_id=decoded_payload['user_id'],
                username=decoded_payload['username'],
                roles=decoded_payload['roles'],
                permissions=decoded_payload['permissions'],
                token_type=TokenType(decoded_payload['token_type']),
                issued_at=decoded_payload['iat'],
                expires_at=decoded_payload['exp'],
                issuer=decoded_payload['iss'],
                audience=decoded_payload['aud'],
                jti=decoded_payload['jti']
            )
            
            # 检查令牌类型
            if token_type and payload.token_type != token_type:
                raise TokenInvalidError(f"令牌类型不匹配: 期望{token_type.value}, 实际{payload.token_type.value}")
            
            # 检查黑名单
            if await self._is_blacklisted(payload.jti):
                raise TokenBlacklistedError("令牌已被撤销")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("令牌已过期")
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError(f"令牌无效: {e}")
        except Exception as e:
            logger.error(f"验证令牌失败: {e}")
            raise TokenInvalidError(f"验证令牌失败: {e}")
    
    async def refresh_token(self, refresh_token: str) -> TokenPair:
        """
        刷新令牌
        
        Args:
            refresh_token: 刷新令牌
            
        Returns:
            TokenPair: 新的令牌对
        """
        # 验证刷新令牌
        payload = await self.verify_token(refresh_token, TokenType.REFRESH)
        
        # 将旧的刷新令牌添加到黑名单
        await self._add_to_blacklist(payload.jti, payload.expires_at)
        
        # 生成新的令牌对
        return await self.generate_tokens(
            user_id=payload.user_id,
            username=payload.username,
            roles=payload.roles,
            permissions=payload.permissions
        )
    
    async def revoke_token(self, token: str):
        """
        撤销令牌
        
        Args:
            token: 要撤销的令牌
        """
        try:
            payload = await self.verify_token(token)
            await self._add_to_blacklist(payload.jti, payload.expires_at)
            logger.info(f"令牌已撤销: {payload.jti}")
        except Exception as e:
            logger.error(f"撤销令牌失败: {e}")
    
    async def revoke_all_tokens(self, user_id: int):
        """
        撤销用户的所有令牌
        
        Args:
            user_id: 用户ID
        """
        if not self.redis_manager:
            return
        
        try:
            # 查找用户的所有令牌
            pattern = "jwt_token:*"
            keys = await self.redis_manager.keys(pattern)
            
            revoked_count = 0
            for key in keys:
                try:
                    token_info = await self.redis_manager.get(key)
                    if token_info:
                        info = json.loads(token_info)
                        if info.get('user_id') == user_id:
                            # 提取JTI并添加到黑名单
                            jti = key.split(':')[1]
                            # 设置一个较长的过期时间
                            await self._add_to_blacklist(jti, int(time.time()) + 86400)
                            revoked_count += 1
                except Exception as e:
                    logger.error(f"处理令牌{key}失败: {e}")
            
            logger.info(f"已撤销用户{user_id}的{revoked_count}个令牌")
        except Exception as e:
            logger.error(f"撤销用户令牌失败: {e}")
    
    async def check_auto_refresh(self, token: str) -> Optional[TokenPair]:
        """
        检查是否需要自动刷新令牌
        
        Args:
            token: 访问令牌
            
        Returns:
            Optional[TokenPair]: 如果需要刷新返回新令牌对，否则返回None
        """
        if not self.config.auto_refresh:
            return None
        
        try:
            payload = await self.verify_token(token, TokenType.ACCESS)
            current_time = int(time.time())
            
            # 检查是否接近过期
            time_to_expire = payload.expires_at - current_time
            threshold = self.config.auto_refresh_threshold_minutes * 60
            
            if time_to_expire <= threshold:
                # 生成新令牌
                return await self.generate_tokens(
                    user_id=payload.user_id,
                    username=payload.username,
                    roles=payload.roles,
                    permissions=payload.permissions
                )
            
            return None
        except Exception as e:
            logger.error(f"检查自动刷新失败: {e}")
            return None
    
    async def get_token_info(self, token: str) -> Dict[str, Any]:
        """
        获取令牌信息
        
        Args:
            token: JWT令牌
            
        Returns:
            Dict[str, Any]: 令牌信息
        """
        try:
            payload = await self.verify_token(token)
            return {
                'user_id': payload.user_id,
                'username': payload.username,
                'roles': payload.roles,
                'permissions': payload.permissions,
                'token_type': payload.token_type.value,
                'issued_at': payload.issued_at,
                'expires_at': payload.expires_at,
                'issuer': payload.issuer,
                'audience': payload.audience,
                'jti': payload.jti,
                'is_expired': payload.expires_at < int(time.time())
            }
        except Exception as e:
            logger.error(f"获取令牌信息失败: {e}")
            raise JWTError(f"获取令牌信息失败: {e}")


# 默认配置实例
default_config = TokenConfig()

# 默认JWT认证实例
_default_jwt_auth = None


def get_jwt_auth(config: TokenConfig = None, redis_manager=None) -> JWTAuth:
    """
    获取JWT认证实例
    
    Args:
        config: JWT配置
        redis_manager: Redis管理器
        
    Returns:
        JWTAuth: JWT认证实例
    """
    global _default_jwt_auth
    
    if config is None:
        config = default_config
    
    if _default_jwt_auth is None:
        _default_jwt_auth = JWTAuth(config, redis_manager)
    
    return _default_jwt_auth


# 便捷函数
async def generate_tokens(user_id: int, username: str, roles: List[str], 
                         permissions: List[str], config: TokenConfig = None) -> TokenPair:
    """生成令牌对的便捷函数"""
    jwt_auth = get_jwt_auth(config)
    return await jwt_auth.generate_tokens(user_id, username, roles, permissions)


async def verify_token(token: str, token_type: TokenType = None, 
                      config: TokenConfig = None) -> TokenPayload:
    """验证令牌的便捷函数"""
    jwt_auth = get_jwt_auth(config)
    return await jwt_auth.verify_token(token, token_type)


async def refresh_token(refresh_token: str, config: TokenConfig = None) -> TokenPair:
    """刷新令牌的便捷函数"""
    jwt_auth = get_jwt_auth(config)
    return await jwt_auth.refresh_token(refresh_token)


async def revoke_token(token: str, config: TokenConfig = None):
    """撤销令牌的便捷函数"""
    jwt_auth = get_jwt_auth(config)
    await jwt_auth.revoke_token(token)