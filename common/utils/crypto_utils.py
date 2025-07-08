"""
加密工具模块

该模块提供加密解密工具、哈希工具、签名验证和密码强度检查等功能。
"""

import hashlib
import hmac
import secrets
import base64
import os
import re
from typing import Optional, Union, Dict, Any, Tuple
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
import argon2
from loguru import logger


class CryptoError(Exception):
    """加密相关异常"""
    pass


class HashAlgorithm:
    """哈希算法常量"""
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA512 = "sha512"
    BLAKE2B = "blake2b"
    BLAKE2S = "blake2s"


class SymmetricAlgorithm:
    """对称加密算法常量"""
    AES_128_CBC = "aes_128_cbc"
    AES_256_CBC = "aes_256_cbc"
    AES_128_GCM = "aes_128_gcm"
    AES_256_GCM = "aes_256_gcm"


class HashUtils:
    """
    哈希工具类
    
    提供各种哈希算法的计算功能。
    """
    
    @staticmethod
    def hash_data(data: Union[str, bytes], algorithm: str = HashAlgorithm.SHA256,
                  salt: Optional[bytes] = None, iterations: int = 1) -> str:
        """
        计算数据哈希值
        
        Args:
            data: 要哈希的数据
            algorithm: 哈希算法
            salt: 盐值
            iterations: 迭代次数
            
        Returns:
            str: 十六进制哈希值
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        if salt:
            data = salt + data
        
        try:
            # 创建哈希对象
            if algorithm == HashAlgorithm.MD5:
                hasher = hashlib.md5()
            elif algorithm == HashAlgorithm.SHA1:
                hasher = hashlib.sha1()
            elif algorithm == HashAlgorithm.SHA256:
                hasher = hashlib.sha256()
            elif algorithm == HashAlgorithm.SHA512:
                hasher = hashlib.sha512()
            elif algorithm == HashAlgorithm.BLAKE2B:
                hasher = hashlib.blake2b()
            elif algorithm == HashAlgorithm.BLAKE2S:
                hasher = hashlib.blake2s()
            else:
                raise CryptoError(f"不支持的哈希算法: {algorithm}")
            
            # 计算哈希
            hasher.update(data)
            result = hasher.hexdigest()
            
            # 多次迭代
            for _ in range(iterations - 1):
                hasher = hashlib.new(algorithm.replace('_', ''))
                hasher.update(result.encode('utf-8'))
                result = hasher.hexdigest()
            
            return result
        
        except Exception as e:
            raise CryptoError(f"哈希计算失败: {e}")
    
    @staticmethod
    def hash_file(file_path: str, algorithm: str = HashAlgorithm.SHA256,
                  chunk_size: int = 8192) -> str:
        """
        计算文件哈希值
        
        Args:
            file_path: 文件路径
            algorithm: 哈希算法
            chunk_size: 块大小
            
        Returns:
            str: 十六进制哈希值
        """
        try:
            if algorithm == HashAlgorithm.MD5:
                hasher = hashlib.md5()
            elif algorithm == HashAlgorithm.SHA1:
                hasher = hashlib.sha1()
            elif algorithm == HashAlgorithm.SHA256:
                hasher = hashlib.sha256()
            elif algorithm == HashAlgorithm.SHA512:
                hasher = hashlib.sha512()
            elif algorithm == HashAlgorithm.BLAKE2B:
                hasher = hashlib.blake2b()
            elif algorithm == HashAlgorithm.BLAKE2S:
                hasher = hashlib.blake2s()
            else:
                raise CryptoError(f"不支持的哈希算法: {algorithm}")
            
            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            
            return hasher.hexdigest()
        
        except Exception as e:
            raise CryptoError(f"文件哈希计算失败: {e}")
    
    @staticmethod
    def hmac_hash(data: Union[str, bytes], key: Union[str, bytes],
                  algorithm: str = HashAlgorithm.SHA256) -> str:
        """
        计算HMAC哈希值
        
        Args:
            data: 要哈希的数据
            key: 密钥
            algorithm: 哈希算法
            
        Returns:
            str: 十六进制HMAC值
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        if isinstance(key, str):
            key = key.encode('utf-8')
        
        try:
            if algorithm == HashAlgorithm.SHA256:
                hasher = hmac.new(key, data, hashlib.sha256)
            elif algorithm == HashAlgorithm.SHA512:
                hasher = hmac.new(key, data, hashlib.sha512)
            elif algorithm == HashAlgorithm.SHA1:
                hasher = hmac.new(key, data, hashlib.sha1)
            else:
                raise CryptoError(f"HMAC不支持的哈希算法: {algorithm}")
            
            return hasher.hexdigest()
        
        except Exception as e:
            raise CryptoError(f"HMAC计算失败: {e}")
    
    @staticmethod
    def verify_hash(data: Union[str, bytes], hash_value: str,
                   algorithm: str = HashAlgorithm.SHA256,
                   salt: Optional[bytes] = None) -> bool:
        """
        验证哈希值
        
        Args:
            data: 原始数据
            hash_value: 要验证的哈希值
            algorithm: 哈希算法
            salt: 盐值
            
        Returns:
            bool: 是否匹配
        """
        try:
            computed_hash = HashUtils.hash_data(data, algorithm, salt)
            return secrets.compare_digest(computed_hash, hash_value)
        except Exception:
            return False


class PasswordUtils:
    """
    密码工具类
    
    提供密码哈希、验证和强度检查功能。
    """
    
    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None,
                     algorithm: str = "argon2") -> Tuple[str, bytes]:
        """
        哈希密码
        
        Args:
            password: 明文密码
            salt: 盐值，为None时自动生成
            algorithm: 哈希算法 (argon2, pbkdf2, scrypt)
            
        Returns:
            Tuple[str, bytes]: (哈希值, 盐值)
        """
        if salt is None:
            salt = secrets.token_bytes(32)
        
        try:
            if algorithm == "argon2":
                ph = argon2.PasswordHasher(
                    time_cost=3,      # 时间成本
                    memory_cost=65536, # 内存成本 (64MB)
                    parallelism=1,    # 并行度
                    hash_len=32,      # 哈希长度
                    salt_len=32       # 盐长度
                )
                hash_value = ph.hash(password, salt=salt)
                return hash_value, salt
            
            elif algorithm == "pbkdf2":
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                    backend=default_backend()
                )
                key = kdf.derive(password.encode('utf-8'))
                hash_value = base64.b64encode(key).decode('utf-8')
                return hash_value, salt
            
            elif algorithm == "scrypt":
                kdf = Scrypt(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    n=2**14,  # CPU/内存成本参数
                    r=8,      # 块大小参数
                    p=1,      # 并行参数
                    backend=default_backend()
                )
                key = kdf.derive(password.encode('utf-8'))
                hash_value = base64.b64encode(key).decode('utf-8')
                return hash_value, salt
            
            else:
                raise CryptoError(f"不支持的密码哈希算法: {algorithm}")
        
        except Exception as e:
            raise CryptoError(f"密码哈希失败: {e}")
    
    @staticmethod
    def verify_password(password: str, hash_value: str, salt: bytes,
                       algorithm: str = "argon2") -> bool:
        """
        验证密码
        
        Args:
            password: 明文密码
            hash_value: 存储的哈希值
            salt: 盐值
            algorithm: 哈希算法
            
        Returns:
            bool: 是否匹配
        """
        try:
            if algorithm == "argon2":
                ph = argon2.PasswordHasher()
                ph.verify(hash_value, password)
                return True
            
            elif algorithm in ["pbkdf2", "scrypt"]:
                # 重新计算哈希
                computed_hash, _ = PasswordUtils.hash_password(password, salt, algorithm)
                return secrets.compare_digest(computed_hash, hash_value)
            
            else:
                return False
        
        except Exception:
            return False
    
    @staticmethod
    def check_password_strength(password: str) -> Dict[str, Any]:
        """
        检查密码强度
        
        Args:
            password: 密码
            
        Returns:
            Dict[str, Any]: 强度检查结果
        """
        result = {
            'score': 0,
            'length': len(password),
            'has_lowercase': bool(re.search(r'[a-z]', password)),
            'has_uppercase': bool(re.search(r'[A-Z]', password)),
            'has_digits': bool(re.search(r'\d', password)),
            'has_special': bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password)),
            'has_spaces': ' ' in password,
            'is_common': False,  # 简化实现，实际应检查常见密码字典
            'strength': 'weak'
        }
        
        # 计算分数
        if result['length'] >= 8:
            result['score'] += 1
        if result['length'] >= 12:
            result['score'] += 1
        if result['has_lowercase']:
            result['score'] += 1
        if result['has_uppercase']:
            result['score'] += 1
        if result['has_digits']:
            result['score'] += 1
        if result['has_special']:
            result['score'] += 1
        if not result['has_spaces']:
            result['score'] += 1
        
        # 判断强度
        if result['score'] >= 6:
            result['strength'] = 'strong'
        elif result['score'] >= 4:
            result['strength'] = 'medium'
        else:
            result['strength'] = 'weak'
        
        return result
    
    @staticmethod
    def generate_password(length: int = 16, include_special: bool = True) -> str:
        """
        生成随机密码
        
        Args:
            length: 密码长度
            include_special: 是否包含特殊字符
            
        Returns:
            str: 生成的密码
        """
        import string
        
        chars = string.ascii_letters + string.digits
        if include_special:
            chars += "!@#$%^&*"
        
        password = ''.join(secrets.choice(chars) for _ in range(length))
        return password


class SymmetricCrypto:
    """
    对称加密工具类
    
    提供AES等对称加密算法的加密解密功能。
    """
    
    @staticmethod
    def generate_key(algorithm: str = SymmetricAlgorithm.AES_256_GCM) -> bytes:
        """
        生成加密密钥
        
        Args:
            algorithm: 加密算法
            
        Returns:
            bytes: 密钥
        """
        if algorithm in [SymmetricAlgorithm.AES_128_CBC, SymmetricAlgorithm.AES_128_GCM]:
            return secrets.token_bytes(16)  # 128位
        elif algorithm in [SymmetricAlgorithm.AES_256_CBC, SymmetricAlgorithm.AES_256_GCM]:
            return secrets.token_bytes(32)  # 256位
        else:
            raise CryptoError(f"不支持的算法: {algorithm}")
    
    @staticmethod
    def encrypt(plaintext: Union[str, bytes], key: bytes,
               algorithm: str = SymmetricAlgorithm.AES_256_GCM) -> Tuple[bytes, bytes]:
        """
        对称加密
        
        Args:
            plaintext: 明文
            key: 密钥
            algorithm: 加密算法
            
        Returns:
            Tuple[bytes, bytes]: (密文, IV/nonce)
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode('utf-8')
        
        try:
            if algorithm == SymmetricAlgorithm.AES_128_CBC:
                return SymmetricCrypto._aes_cbc_encrypt(plaintext, key, 128)
            elif algorithm == SymmetricAlgorithm.AES_256_CBC:
                return SymmetricCrypto._aes_cbc_encrypt(plaintext, key, 256)
            elif algorithm == SymmetricAlgorithm.AES_128_GCM:
                return SymmetricCrypto._aes_gcm_encrypt(plaintext, key, 128)
            elif algorithm == SymmetricAlgorithm.AES_256_GCM:
                return SymmetricCrypto._aes_gcm_encrypt(plaintext, key, 256)
            else:
                raise CryptoError(f"不支持的加密算法: {algorithm}")
        
        except Exception as e:
            raise CryptoError(f"加密失败: {e}")
    
    @staticmethod
    def decrypt(ciphertext: bytes, key: bytes, iv_or_nonce: bytes,
               algorithm: str = SymmetricAlgorithm.AES_256_GCM) -> bytes:
        """
        对称解密
        
        Args:
            ciphertext: 密文
            key: 密钥
            iv_or_nonce: IV或nonce
            algorithm: 加密算法
            
        Returns:
            bytes: 明文
        """
        try:
            if algorithm == SymmetricAlgorithm.AES_128_CBC:
                return SymmetricCrypto._aes_cbc_decrypt(ciphertext, key, iv_or_nonce)
            elif algorithm == SymmetricAlgorithm.AES_256_CBC:
                return SymmetricCrypto._aes_cbc_decrypt(ciphertext, key, iv_or_nonce)
            elif algorithm == SymmetricAlgorithm.AES_128_GCM:
                return SymmetricCrypto._aes_gcm_decrypt(ciphertext, key, iv_or_nonce)
            elif algorithm == SymmetricAlgorithm.AES_256_GCM:
                return SymmetricCrypto._aes_gcm_decrypt(ciphertext, key, iv_or_nonce)
            else:
                raise CryptoError(f"不支持的解密算法: {algorithm}")
        
        except Exception as e:
            raise CryptoError(f"解密失败: {e}")
    
    @staticmethod
    def _aes_cbc_encrypt(plaintext: bytes, key: bytes, key_size: int) -> Tuple[bytes, bytes]:
        """AES CBC模式加密"""
        iv = secrets.token_bytes(16)  # AES块大小为16字节
        
        # 填充
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext)
        padded_data += padder.finalize()
        
        # 加密
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        
        return ciphertext, iv
    
    @staticmethod
    def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
        """AES CBC模式解密"""
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        # 去除填充
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext)
        plaintext += unpadder.finalize()
        
        return plaintext
    
    @staticmethod
    def _aes_gcm_encrypt(plaintext: bytes, key: bytes, key_size: int) -> Tuple[bytes, bytes]:
        """AES GCM模式加密"""
        nonce = secrets.token_bytes(12)  # GCM推荐12字节nonce
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        
        # GCM模式返回密文+认证标签
        return ciphertext + encryptor.tag, nonce
    
    @staticmethod
    def _aes_gcm_decrypt(ciphertext_with_tag: bytes, key: bytes, nonce: bytes) -> bytes:
        """AES GCM模式解密"""
        # 分离密文和认证标签
        ciphertext = ciphertext_with_tag[:-16]  # 最后16字节是认证标签
        tag = ciphertext_with_tag[-16:]
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        return plaintext


class AsymmetricCrypto:
    """
    非对称加密工具类
    
    提供RSA等非对称加密算法的加密解密和签名验证功能。
    """
    
    @staticmethod
    def generate_rsa_keypair(key_size: int = 2048) -> Tuple[bytes, bytes]:
        """
        生成RSA密钥对
        
        Args:
            key_size: 密钥大小
            
        Returns:
            Tuple[bytes, bytes]: (私钥PEM, 公钥PEM)
        """
        try:
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=key_size,
                backend=default_backend()
            )
            
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            public_key = private_key.public_key()
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            return private_pem, public_pem
        
        except Exception as e:
            raise CryptoError(f"RSA密钥对生成失败: {e}")
    
    @staticmethod
    def rsa_encrypt(plaintext: Union[str, bytes], public_key_pem: bytes) -> bytes:
        """
        RSA公钥加密
        
        Args:
            plaintext: 明文
            public_key_pem: 公钥PEM格式
            
        Returns:
            bytes: 密文
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode('utf-8')
        
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem, backend=default_backend()
            )
            
            ciphertext = public_key.encrypt(
                plaintext,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            return ciphertext
        
        except Exception as e:
            raise CryptoError(f"RSA加密失败: {e}")
    
    @staticmethod
    def rsa_decrypt(ciphertext: bytes, private_key_pem: bytes) -> bytes:
        """
        RSA私钥解密
        
        Args:
            ciphertext: 密文
            private_key_pem: 私钥PEM格式
            
        Returns:
            bytes: 明文
        """
        try:
            private_key = serialization.load_pem_private_key(
                private_key_pem, password=None, backend=default_backend()
            )
            
            plaintext = private_key.decrypt(
                ciphertext,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            return plaintext
        
        except Exception as e:
            raise CryptoError(f"RSA解密失败: {e}")
    
    @staticmethod
    def rsa_sign(message: Union[str, bytes], private_key_pem: bytes) -> bytes:
        """
        RSA签名
        
        Args:
            message: 要签名的消息
            private_key_pem: 私钥PEM格式
            
        Returns:
            bytes: 签名
        """
        if isinstance(message, str):
            message = message.encode('utf-8')
        
        try:
            private_key = serialization.load_pem_private_key(
                private_key_pem, password=None, backend=default_backend()
            )
            
            signature = private_key.sign(
                message,
                asym_padding.PSS(
                    mgf=asym_padding.MGF1(hashes.SHA256()),
                    salt_length=asym_padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return signature
        
        except Exception as e:
            raise CryptoError(f"RSA签名失败: {e}")
    
    @staticmethod
    def rsa_verify(message: Union[str, bytes], signature: bytes, public_key_pem: bytes) -> bool:
        """
        RSA签名验证
        
        Args:
            message: 原始消息
            signature: 签名
            public_key_pem: 公钥PEM格式
            
        Returns:
            bool: 签名是否有效
        """
        if isinstance(message, str):
            message = message.encode('utf-8')
        
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem, backend=default_backend()
            )
            
            public_key.verify(
                signature,
                message,
                asym_padding.PSS(
                    mgf=asym_padding.MGF1(hashes.SHA256()),
                    salt_length=asym_padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
        
        except Exception:
            return False


class TokenUtils:
    """
    令牌工具类
    
    提供安全令牌的生成和验证功能。
    """
    
    @staticmethod
    def generate_token(length: int = 32) -> str:
        """
        生成安全令牌
        
        Args:
            length: 令牌长度
            
        Returns:
            str: Base64编码的令牌
        """
        token_bytes = secrets.token_bytes(length)
        return base64.urlsafe_b64encode(token_bytes).decode('utf-8').rstrip('=')
    
    @staticmethod
    def generate_api_key(prefix: str = "ak", length: int = 32) -> str:
        """
        生成API密钥
        
        Args:
            prefix: 前缀
            length: 长度
            
        Returns:
            str: API密钥
        """
        token = TokenUtils.generate_token(length)
        return f"{prefix}_{token}"
    
    @staticmethod
    def time_safe_compare(a: str, b: str) -> bool:
        """
        时间安全的字符串比较
        
        Args:
            a: 字符串A
            b: 字符串B
            
        Returns:
            bool: 是否相等
        """
        return secrets.compare_digest(a, b)


if __name__ == "__main__":
    # 测试代码
    def test_crypto_utils():
        """测试加密工具"""
        
        # 测试哈希
        print("测试哈希功能:")
        data = "Hello, World!"
        hash_value = HashUtils.hash_data(data, HashAlgorithm.SHA256)
        print(f"SHA256哈希: {hash_value}")
        
        # 测试HMAC
        hmac_value = HashUtils.hmac_hash(data, "secret_key")
        print(f"HMAC: {hmac_value}")
        
        # 测试密码
        print("\n测试密码功能:")
        password = "MySecurePassword123!"
        strength = PasswordUtils.check_password_strength(password)
        print(f"密码强度: {strength}")
        
        hash_value, salt = PasswordUtils.hash_password(password)
        print(f"密码哈希: {hash_value[:50]}...")
        
        is_valid = PasswordUtils.verify_password(password, hash_value, salt)
        print(f"密码验证: {is_valid}")
        
        # 测试对称加密
        print("\n测试对称加密:")
        key = SymmetricCrypto.generate_key()
        plaintext = "这是要加密的数据"
        
        ciphertext, iv = SymmetricCrypto.encrypt(plaintext, key)
        print(f"加密成功，密文长度: {len(ciphertext)} 字节")
        
        decrypted = SymmetricCrypto.decrypt(ciphertext, key, iv)
        print(f"解密结果: {decrypted.decode('utf-8')}")
        
        # 测试非对称加密
        print("\n测试非对称加密:")
        private_key, public_key = AsymmetricCrypto.generate_rsa_keypair(1024)  # 使用小密钥以加快测试
        
        message = "RSA加密测试消息"
        encrypted = AsymmetricCrypto.rsa_encrypt(message, public_key)
        print(f"RSA加密成功，密文长度: {len(encrypted)} 字节")
        
        decrypted = AsymmetricCrypto.rsa_decrypt(encrypted, private_key)
        print(f"RSA解密结果: {decrypted.decode('utf-8')}")
        
        # 测试签名
        signature = AsymmetricCrypto.rsa_sign(message, private_key)
        is_valid = AsymmetricCrypto.rsa_verify(message, signature, public_key)
        print(f"RSA签名验证: {is_valid}")
        
        # 测试令牌
        print("\n测试令牌生成:")
        token = TokenUtils.generate_token()
        api_key = TokenUtils.generate_api_key("game")
        print(f"安全令牌: {token}")
        print(f"API密钥: {api_key}")
    
    test_crypto_utils()