"""
认证服务

该模块负责用户认证相关功能，包括JWT Token生成验证、用户认证、
密码管理等功能。

主要功能：
- JWT Token生成验证
- 用户认证
- 密码管理
- 用户信息管理
- 邮件发送
"""

import asyncio
import time
import hashlib
import secrets
from typing import Dict, Any, Optional, List
import json

from common.logger import logger
from common.security import JWTAuth, TokenConfig, generate_tokens, verify_token, refresh_token
from common.db.redis_manager import redis_manager
from ..config import GatewayConfig


class AuthService:
    """认证服务"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化认证服务
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.jwt_auth: Optional[JWTAuth] = None
        self.redis_manager = None
        
        # 用户数据存储（生产环境应该使用数据库）
        self.users: Dict[str, Dict[str, Any]] = {}
        self.user_emails: Dict[str, str] = {}  # email -> user_id
        self.reset_tokens: Dict[str, Dict[str, Any]] = {}  # token -> {user_id, expire_time}
        
        # 登录尝试限制
        self.login_attempts: Dict[str, List[float]] = {}  # user_id -> [timestamp, ...]
        
        logger.info("认证服务初始化完成")
        
    async def initialize(self):
        """初始化认证服务"""
        # 初始化JWT认证
        token_config = TokenConfig(
            secret_key=self.config.auth.jwt_secret,
            algorithm=self.config.auth.jwt_algorithm,
            access_token_expire_minutes=self.config.auth.token_expire_time // 60,
            refresh_token_expire_days=self.config.auth.refresh_token_expire_time // (60 * 24)
        )
        self.jwt_auth = JWTAuth(token_config)
        
        # 初始化Redis管理器
        self.redis_manager = redis_manager
        
        # 初始化测试用户
        await self._init_test_users()
        
        logger.info("认证服务初始化完成")
        
    async def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        用户认证
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            Dict[str, Any]: 用户信息，认证失败返回None
        """
        try:
            # 检查登录尝试次数
            if not await self._check_login_attempts(username):
                logger.warning("登录尝试次数过多", username=username)
                return None
                
            # 查找用户
            user_info = None
            for user_id, user_data in self.users.items():
                if user_data.get("username") == username:
                    user_info = user_data.copy()
                    user_info["user_id"] = user_id
                    break
                    
            if not user_info:
                await self._record_login_attempt(username)
                return None
                
            # 验证密码
            if not await self._verify_password(password, user_info.get("password", "")):
                await self._record_login_attempt(username)
                return None
                
            # 检查用户状态
            if not user_info.get("is_active", True):
                return None
                
            # 更新最后登录时间
            user_info["last_login"] = time.time()
            self.users[user_info["user_id"]]["last_login"] = user_info["last_login"]
            
            # 清除登录尝试记录
            self.login_attempts.pop(username, None)
            
            return user_info
            
        except Exception as e:
            logger.error("用户认证失败", username=username, error=str(e))
            return None
            
    async def create_user(self, user_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        创建用户
        
        Args:
            user_data: 用户数据
            
        Returns:
            Dict[str, Any]: 创建的用户信息
        """
        try:
            # 生成用户ID
            user_id = f"user_{int(time.time() * 1000)}"
            
            # 密码哈希
            password_hash = await self._hash_password(user_data["password"])
            
            # 创建用户记录
            user_record = {
                "username": user_data["username"],
                "password": password_hash,
                "email": user_data.get("email", ""),
                "nickname": user_data.get("nickname", user_data["username"]),
                "avatar": user_data.get("avatar", ""),
                "is_active": user_data.get("is_active", True),
                "created_at": time.time(),
                "last_login": 0,
                "permissions": user_data.get("permissions", ["user:basic"])
            }
            
            # 保存用户
            self.users[user_id] = user_record
            
            # 保存邮箱映射
            if user_record["email"]:
                self.user_emails[user_record["email"]] = user_id
                
            # 保存到Redis
            await self._save_user_to_redis(user_id, user_record)
            
            logger.info("用户创建成功", 
                       user_id=user_id,
                       username=user_data["username"])
            
            # 返回用户信息（不包含密码）
            result = user_record.copy()
            result["user_id"] = user_id
            del result["password"]
            
            return result
            
        except Exception as e:
            logger.error("创建用户失败", 
                        username=user_data.get("username"),
                        error=str(e))
            return None
            
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        通过用户ID获取用户信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict[str, Any]: 用户信息
        """
        try:
            # 首先从内存中获取
            user_data = self.users.get(user_id)
            
            # 如果内存中没有，从Redis中获取
            if not user_data:
                user_data = await self._load_user_from_redis(user_id)
                if user_data:
                    self.users[user_id] = user_data
                    
            if user_data:
                result = user_data.copy()
                result["user_id"] = user_id
                # 移除密码字段
                result.pop("password", None)
                return result
                
            return None
            
        except Exception as e:
            logger.error("获取用户信息失败", user_id=user_id, error=str(e))
            return None
            
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        通过邮箱获取用户信息
        
        Args:
            email: 邮箱
            
        Returns:
            Dict[str, Any]: 用户信息
        """
        user_id = self.user_emails.get(email)
        if user_id:
            return await self.get_user_by_id(user_id)
        return None
        
    async def check_username_exists(self, username: str) -> bool:
        """
        检查用户名是否存在
        
        Args:
            username: 用户名
            
        Returns:
            bool: 是否存在
        """
        for user_data in self.users.values():
            if user_data.get("username") == username:
                return True
        return False
        
    async def check_email_exists(self, email: str) -> bool:
        """
        检查邮箱是否存在
        
        Args:
            email: 邮箱
            
        Returns:
            bool: 是否存在
        """
        return email in self.user_emails
        
    async def generate_user_tokens(self, token_payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        生成用户Token
        
        Args:
            token_payload: Token负载
            
        Returns:
            Dict[str, str]: Token对
        """
        try:
            tokens = await generate_tokens(token_payload, self.jwt_auth)
            return tokens
        except Exception as e:
            logger.error("生成Token失败", error=str(e))
            return None
            
    async def verify_user_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证用户Token
        
        Args:
            token: Token
            
        Returns:
            Dict[str, Any]: Token负载
        """
        try:
            payload = await verify_token(token, self.jwt_auth)
            return payload
        except Exception as e:
            logger.error("验证Token失败", error=str(e))
            return None
            
    async def refresh_token(self, refresh_token: str) -> Optional[Dict[str, str]]:
        """
        刷新Token
        
        Args:
            refresh_token: 刷新Token
            
        Returns:
            Dict[str, str]: 新的Token对
        """
        try:
            tokens = await refresh_token(refresh_token, self.jwt_auth)
            return tokens
        except Exception as e:
            logger.error("刷新Token失败", error=str(e))
            return None
            
    async def save_reset_token(self, user_id: str, reset_token: str, expire_time: float):
        """
        保存重置Token
        
        Args:
            user_id: 用户ID
            reset_token: 重置Token
            expire_time: 过期时间
        """
        self.reset_tokens[reset_token] = {
            "user_id": user_id,
            "expire_time": expire_time
        }
        
        # 保存到Redis
        if self.redis_manager:
            try:
                key = f"reset_token:{reset_token}"
                data = json.dumps({"user_id": user_id, "expire_time": expire_time})
                expire_seconds = int(expire_time - time.time())
                if expire_seconds > 0:
                    await self.redis_manager.set(key, data, expire=expire_seconds)
            except Exception as e:
                logger.error("保存重置Token到Redis失败", error=str(e))
                
    async def verify_reset_token(self, reset_token: str) -> Optional[str]:
        """
        验证重置Token
        
        Args:
            reset_token: 重置Token
            
        Returns:
            str: 用户ID，验证失败返回None
        """
        token_info = self.reset_tokens.get(reset_token)
        
        if not token_info:
            # 从Redis中获取
            if self.redis_manager:
                try:
                    key = f"reset_token:{reset_token}"
                    data = await self.redis_manager.get(key)
                    if data:
                        token_info = json.loads(data)
                        self.reset_tokens[reset_token] = token_info
                except Exception as e:
                    logger.error("从Redis获取重置Token失败", error=str(e))
                    
        if token_info:
            if time.time() <= token_info["expire_time"]:
                return token_info["user_id"]
            else:
                # Token已过期，删除它
                self.reset_tokens.pop(reset_token, None)
                
        return None
        
    async def send_reset_email(self, email: str, reset_token: str):
        """
        发送重置邮件
        
        Args:
            email: 邮箱
            reset_token: 重置Token
        """
        # 这里应该集成实际的邮件发送服务
        # 目前只是记录日志
        logger.info("发送密码重置邮件", 
                   email=email,
                   reset_token=reset_token)
        
        # TODO: 集成邮件发送服务
        pass
        
    async def _init_test_users(self):
        """初始化测试用户"""
        test_users = [
            {
                "username": "admin",
                "password": "admin123",
                "email": "admin@example.com",
                "nickname": "管理员",
                "is_active": True,
                "permissions": ["admin", "user:basic", "game:play", "chat:send"]
            },
            {
                "username": "player1",
                "password": "player123",
                "email": "player1@example.com",
                "nickname": "玩家1",
                "is_active": True,
                "permissions": ["user:basic", "game:play", "chat:send"]
            },
            {
                "username": "player2",
                "password": "player123",
                "email": "player2@example.com",
                "nickname": "玩家2",
                "is_active": True,
                "permissions": ["user:basic", "game:play", "chat:send"]
            }
        ]
        
        for user_data in test_users:
            await self.create_user(user_data)
            
    async def _check_login_attempts(self, username: str) -> bool:
        """
        检查登录尝试次数
        
        Args:
            username: 用户名
            
        Returns:
            bool: 是否允许登录
        """
        if username not in self.login_attempts:
            return True
            
        attempts = self.login_attempts[username]
        current_time = time.time()
        
        # 清除过期的尝试记录
        attempts = [t for t in attempts if current_time - t < self.config.auth.login_cooldown]
        self.login_attempts[username] = attempts
        
        # 检查是否超过最大尝试次数
        return len(attempts) < self.config.auth.max_login_attempts
        
    async def _record_login_attempt(self, username: str):
        """
        记录登录尝试
        
        Args:
            username: 用户名
        """
        if username not in self.login_attempts:
            self.login_attempts[username] = []
            
        self.login_attempts[username].append(time.time())
        
    async def _hash_password(self, password: str) -> str:
        """
        密码哈希
        
        Args:
            password: 原始密码
            
        Returns:
            str: 哈希后的密码
        """
        # 使用简单的哈希方法，生产环境应该使用更安全的方法
        salt = secrets.token_hex(16)
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return f"{salt}:{password_hash}"
        
    async def _verify_password(self, password: str, password_hash: str) -> bool:
        """
        验证密码
        
        Args:
            password: 原始密码
            password_hash: 哈希后的密码
            
        Returns:
            bool: 是否匹配
        """
        try:
            salt, hash_value = password_hash.split(":", 1)
            computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
            return computed_hash == hash_value
        except Exception:
            return False
            
    async def _save_user_to_redis(self, user_id: str, user_data: Dict[str, Any]):
        """保存用户到Redis"""
        if not self.redis_manager:
            return
            
        try:
            key = f"user:{user_id}"
            data = json.dumps(user_data)
            await self.redis_manager.set(key, data)
        except Exception as e:
            logger.error("保存用户到Redis失败", 
                        user_id=user_id,
                        error=str(e))
            
    async def _load_user_from_redis(self, user_id: str) -> Optional[Dict[str, Any]]:
        """从Redis加载用户"""
        if not self.redis_manager:
            return None
            
        try:
            key = f"user:{user_id}"
            data = await self.redis_manager.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error("从Redis加载用户失败", 
                        user_id=user_id,
                        error=str(e))
            
        return None