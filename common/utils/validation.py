"""
验证工具模块

该模块提供参数验证装饰器、数据类型检查、业务规则验证
和错误信息格式化等功能。
"""

import re
import functools
import inspect
from typing import (
    Any, Dict, List, Optional, Union, Callable, Type, TypeVar, 
    get_type_hints, get_origin, get_args
)
from dataclasses import dataclass
from enum import Enum
import email.utils
from loguru import logger

F = TypeVar('F', bound=Callable[..., Any])


class ValidationError(Exception):
    """验证错误异常"""
    
    def __init__(self, message: str, field: Optional[str] = None, 
                 value: Any = None, code: Optional[str] = None):
        """
        初始化验证错误
        
        Args:
            message: 错误消息
            field: 字段名
            value: 错误值
            code: 错误代码
        """
        super().__init__(message)
        self.message = message
        self.field = field
        self.value = value
        self.code = code
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'message': self.message,
            'field': self.field,
            'value': self.value,
            'code': self.code
        }


class ValidationLevel(Enum):
    """验证级别"""
    STRICT = "strict"      # 严格验证，发现错误立即抛出异常
    LOOSE = "loose"        # 宽松验证，收集所有错误后一起抛出
    WARNING = "warning"    # 警告模式，记录警告但不抛出异常


@dataclass
class ValidationRule:
    """验证规则"""
    validator: Callable[[Any], bool]
    message: str
    code: Optional[str] = None
    level: ValidationLevel = ValidationLevel.STRICT


class Validator:
    """
    验证器基类
    
    提供各种数据验证功能。
    """
    
    # 常用正则表达式
    PATTERNS = {
        'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        'phone': r'^1[3-9]\d{9}$',  # 中国手机号
        'id_card': r'^\d{17}[\dXx]$',  # 中国身份证号
        'ip_v4': r'^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)$',
        'ip_v6': r'^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$',
        'url': r'^https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*)?(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?$',
        'username': r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$',  # 字母开头，包含字母数字下划线，3-20位
        'password': r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d@$!%*?&]{8,}$',  # 至少8位，包含大小写字母和数字
        'chinese': r'^[\u4e00-\u9fa5]+$',  # 纯中文
        'alphanumeric': r'^[a-zA-Z0-9]+$',  # 字母数字
    }
    
    @classmethod
    def is_valid_type(cls, value: Any, expected_type: Type) -> bool:
        """
        验证值是否为指定类型
        
        Args:
            value: 要验证的值
            expected_type: 期望的类型
            
        Returns:
            bool: 是否为指定类型
        """
        if expected_type is Any:
            return True
        
        # 处理Union类型
        origin = get_origin(expected_type)
        if origin is Union:
            return any(cls.is_valid_type(value, arg) for arg in get_args(expected_type))
        
        # 处理Optional类型
        if origin is Union and len(get_args(expected_type)) == 2 and type(None) in get_args(expected_type):
            if value is None:
                return True
            non_none_type = next(arg for arg in get_args(expected_type) if arg is not type(None))
            return cls.is_valid_type(value, non_none_type)
        
        # 处理泛型类型
        if origin is not None:
            if origin is list:
                if not isinstance(value, list):
                    return False
                args = get_args(expected_type)
                if args:
                    return all(cls.is_valid_type(item, args[0]) for item in value)
                return True
            elif origin is dict:
                if not isinstance(value, dict):
                    return False
                args = get_args(expected_type)
                if len(args) == 2:
                    key_type, value_type = args
                    return all(
                        cls.is_valid_type(k, key_type) and cls.is_valid_type(v, value_type)
                        for k, v in value.items()
                    )
                return True
        
        return isinstance(value, expected_type)
    
    @classmethod
    def is_valid_range(cls, value: Union[int, float], 
                      min_val: Optional[Union[int, float]] = None,
                      max_val: Optional[Union[int, float]] = None) -> bool:
        """
        验证数值是否在指定范围内
        
        Args:
            value: 要验证的值
            min_val: 最小值
            max_val: 最大值
            
        Returns:
            bool: 是否在范围内
        """
        if not isinstance(value, (int, float)):
            return False
        
        if min_val is not None and value < min_val:
            return False
        
        if max_val is not None and value > max_val:
            return False
        
        return True
    
    @classmethod
    def is_valid_length(cls, value: Union[str, list, dict], 
                       min_len: Optional[int] = None,
                       max_len: Optional[int] = None) -> bool:
        """
        验证长度是否在指定范围内
        
        Args:
            value: 要验证的值
            min_len: 最小长度
            max_len: 最大长度
            
        Returns:
            bool: 长度是否有效
        """
        try:
            length = len(value)
        except TypeError:
            return False
        
        if min_len is not None and length < min_len:
            return False
        
        if max_len is not None and length > max_len:
            return False
        
        return True
    
    @classmethod
    def is_valid_pattern(cls, value: str, pattern: Union[str, re.Pattern]) -> bool:
        """
        验证字符串是否匹配指定模式
        
        Args:
            value: 要验证的字符串
            pattern: 正则表达式模式
            
        Returns:
            bool: 是否匹配模式
        """
        if not isinstance(value, str):
            return False
        
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        
        return bool(pattern.match(value))
    
    @classmethod
    def is_valid_email(cls, email: str) -> bool:
        """
        验证邮箱地址
        
        Args:
            email: 邮箱地址
            
        Returns:
            bool: 是否为有效邮箱
        """
        if not isinstance(email, str):
            return False
        
        # 使用正则表达式进行基本验证
        if not cls.is_valid_pattern(email, cls.PATTERNS['email']):
            return False
        
        # 使用email.utils进行更严格的验证
        try:
            parsed = email.utils.parseaddr(email)
            return '@' in parsed[1]
        except Exception:
            return False
    
    @classmethod
    def is_valid_phone(cls, phone: str, country_code: str = 'CN') -> bool:
        """
        验证手机号
        
        Args:
            phone: 手机号
            country_code: 国家代码
            
        Returns:
            bool: 是否为有效手机号
        """
        if not isinstance(phone, str):
            return False
        
        # 移除非数字字符
        phone_digits = re.sub(r'\D', '', phone)
        
        if country_code == 'CN':
            return cls.is_valid_pattern(phone_digits, cls.PATTERNS['phone'])
        
        # 其他国家的手机号验证可以在这里扩展
        return len(phone_digits) >= 7  # 基本长度验证
    
    @classmethod
    def is_valid_url(cls, url: str) -> bool:
        """
        验证URL
        
        Args:
            url: URL地址
            
        Returns:
            bool: 是否为有效URL
        """
        if not isinstance(url, str):
            return False
        
        return cls.is_valid_pattern(url, cls.PATTERNS['url'])
    
    @classmethod
    def is_valid_id_card(cls, id_card: str) -> bool:
        """
        验证身份证号（中国）
        
        Args:
            id_card: 身份证号
            
        Returns:
            bool: 是否为有效身份证号
        """
        if not isinstance(id_card, str):
            return False
        
        if not cls.is_valid_pattern(id_card, cls.PATTERNS['id_card']):
            return False
        
        # 验证校验位
        try:
            coefficients = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
            check_digits = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
            
            sum_val = sum(int(id_card[i]) * coefficients[i] for i in range(17))
            remainder = sum_val % 11
            
            return id_card[17].upper() == check_digits[remainder]
        except (ValueError, IndexError):
            return False
    
    @classmethod
    def is_strong_password(cls, password: str) -> bool:
        """
        验证强密码
        
        Args:
            password: 密码
            
        Returns:
            bool: 是否为强密码
        """
        if not isinstance(password, str):
            return False
        
        return cls.is_valid_pattern(password, cls.PATTERNS['password'])


class BusinessValidator:
    """
    业务规则验证器
    
    提供特定业务场景的验证功能。
    """
    
    @staticmethod
    def is_valid_user_id(user_id: Union[str, int]) -> bool:
        """验证用户ID"""
        if isinstance(user_id, int):
            return user_id > 0
        elif isinstance(user_id, str):
            return user_id.isdigit() and int(user_id) > 0
        return False
    
    @staticmethod
    def is_valid_game_score(score: Union[int, float]) -> bool:
        """验证游戏分数"""
        return isinstance(score, (int, float)) and 0 <= score <= 999999999
    
    @staticmethod
    def is_valid_level(level: int) -> bool:
        """验证等级"""
        return isinstance(level, int) and 1 <= level <= 1000
    
    @staticmethod
    def is_valid_currency_amount(amount: Union[int, float]) -> bool:
        """验证货币金额"""
        return isinstance(amount, (int, float)) and amount >= 0
    
    @staticmethod
    def is_valid_username(username: str) -> bool:
        """验证用户名"""
        if not isinstance(username, str):
            return False
        
        return Validator.is_valid_pattern(username, Validator.PATTERNS['username'])
    
    @staticmethod
    def is_valid_nickname(nickname: str) -> bool:
        """验证昵称"""
        if not isinstance(nickname, str):
            return False
        
        # 昵称可以包含中文、字母、数字，长度2-20
        pattern = r'^[\u4e00-\u9fa5a-zA-Z0-9_]{2,20}$'
        return Validator.is_valid_pattern(nickname, pattern)


def validate_params(**validators: Union[Callable[[Any], bool], ValidationRule]):
    """
    参数验证装饰器
    
    Args:
        **validators: 参数名到验证器的映射
        
    Example:
        @validate_params(
            user_id=lambda x: isinstance(x, int) and x > 0,
            email=Validator.is_valid_email,
            age=ValidationRule(
                lambda x: isinstance(x, int) and 0 <= x <= 150,
                "年龄必须在0-150之间"
            )
        )
        def register_user(user_id: int, email: str, age: int):
            pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 获取函数签名
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            errors = []
            
            # 验证每个参数
            for param_name, validator in validators.items():
                if param_name not in bound_args.arguments:
                    continue
                
                value = bound_args.arguments[param_name]
                
                if isinstance(validator, ValidationRule):
                    if not validator.validator(value):
                        error = ValidationError(
                            validator.message, 
                            param_name, 
                            value, 
                            validator.code
                        )
                        
                        if validator.level == ValidationLevel.STRICT:
                            raise error
                        elif validator.level == ValidationLevel.LOOSE:
                            errors.append(error)
                        elif validator.level == ValidationLevel.WARNING:
                            logger.warning(f"参数验证警告: {error.message}")
                
                elif callable(validator):
                    if not validator(value):
                        error = ValidationError(
                            f"参数 {param_name} 验证失败",
                            param_name,
                            value
                        )
                        raise error
            
            # 如果有累积的错误，抛出异常
            if errors:
                messages = [error.message for error in errors]
                raise ValidationError(f"参数验证失败: {'; '.join(messages)}")
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def validate_types(func: F) -> F:
    """
    类型验证装饰器
    
    基于函数的类型提示自动验证参数类型。
    
    Example:
        @validate_types
        def process_user(user_id: int, name: str, scores: List[float]) -> bool:
            return True
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 获取类型提示
        type_hints = get_type_hints(func)
        
        # 获取函数签名
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        
        # 验证每个参数的类型
        for param_name, param_value in bound_args.arguments.items():
            if param_name in type_hints:
                expected_type = type_hints[param_name]
                
                if not Validator.is_valid_type(param_value, expected_type):
                    raise ValidationError(
                        f"参数 {param_name} 类型错误，期望 {expected_type}，实际 {type(param_value)}",
                        param_name,
                        param_value
                    )
        
        return func(*args, **kwargs)
    
    return wrapper


def validate_range(min_val: Optional[Union[int, float]] = None, 
                  max_val: Optional[Union[int, float]] = None):
    """
    数值范围验证装饰器
    
    Args:
        min_val: 最小值
        max_val: 最大值
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(value, *args, **kwargs):
            if not Validator.is_valid_range(value, min_val, max_val):
                raise ValidationError(
                    f"值 {value} 超出范围 [{min_val}, {max_val}]",
                    "value",
                    value
                )
            return func(value, *args, **kwargs)
        return wrapper
    return decorator


def validate_length(min_len: Optional[int] = None, 
                   max_len: Optional[int] = None):
    """
    长度验证装饰器
    
    Args:
        min_len: 最小长度
        max_len: 最大长度
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(value, *args, **kwargs):
            if not Validator.is_valid_length(value, min_len, max_len):
                raise ValidationError(
                    f"长度 {len(value)} 超出范围 [{min_len}, {max_len}]",
                    "value",
                    value
                )
            return func(value, *args, **kwargs)
        return wrapper
    return decorator


class ValidationContext:
    """
    验证上下文
    
    收集和管理验证过程中的错误和警告。
    """
    
    def __init__(self, level: ValidationLevel = ValidationLevel.STRICT):
        """
        初始化验证上下文
        
        Args:
            level: 验证级别
        """
        self.level = level
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
    
    def validate(self, value: Any, validator: Callable[[Any], bool], 
                message: str, field: Optional[str] = None, 
                code: Optional[str] = None) -> bool:
        """
        执行验证
        
        Args:
            value: 要验证的值
            validator: 验证器函数
            message: 错误消息
            field: 字段名
            code: 错误代码
            
        Returns:
            bool: 验证是否通过
        """
        if validator(value):
            return True
        
        error = ValidationError(message, field, value, code)
        
        if self.level == ValidationLevel.STRICT:
            raise error
        elif self.level == ValidationLevel.LOOSE:
            self.errors.append(error)
        elif self.level == ValidationLevel.WARNING:
            self.warnings.append(error)
            logger.warning(f"验证警告: {message}")
        
        return False
    
    def has_errors(self) -> bool:
        """检查是否有错误"""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """检查是否有警告"""
        return len(self.warnings) > 0
    
    def get_error_messages(self) -> List[str]:
        """获取错误消息列表"""
        return [error.message for error in self.errors]
    
    def get_warning_messages(self) -> List[str]:
        """获取警告消息列表"""
        return [warning.message for warning in self.warnings]
    
    def raise_if_errors(self) -> None:
        """如果有错误则抛出异常"""
        if self.errors:
            messages = self.get_error_messages()
            raise ValidationError(f"验证失败: {'; '.join(messages)}")
    
    def clear(self) -> None:
        """清空错误和警告"""
        self.errors.clear()
        self.warnings.clear()


# 常用验证器实例

# 用户相关验证器
user_id_validator = ValidationRule(
    BusinessValidator.is_valid_user_id,
    "用户ID必须为正整数",
    "INVALID_USER_ID"
)

username_validator = ValidationRule(
    BusinessValidator.is_valid_username,
    "用户名必须以字母开头，包含字母数字下划线，长度3-20位",
    "INVALID_USERNAME"
)

nickname_validator = ValidationRule(
    BusinessValidator.is_valid_nickname,
    "昵称可以包含中文、字母、数字，长度2-20位",
    "INVALID_NICKNAME"
)

email_validator = ValidationRule(
    Validator.is_valid_email,
    "邮箱地址格式不正确",
    "INVALID_EMAIL"
)

password_validator = ValidationRule(
    Validator.is_strong_password,
    "密码必须至少8位，包含大小写字母和数字",
    "WEAK_PASSWORD"
)

phone_validator = ValidationRule(
    Validator.is_valid_phone,
    "手机号格式不正确",
    "INVALID_PHONE"
)

# 游戏相关验证器
game_score_validator = ValidationRule(
    BusinessValidator.is_valid_game_score,
    "游戏分数必须在0-999999999之间",
    "INVALID_SCORE"
)

level_validator = ValidationRule(
    BusinessValidator.is_valid_level,
    "等级必须在1-1000之间",
    "INVALID_LEVEL"
)

currency_validator = ValidationRule(
    BusinessValidator.is_valid_currency_amount,
    "货币金额必须大于等于0",
    "INVALID_CURRENCY"
)


if __name__ == "__main__":
    # 测试代码
    def test_validation():
        """测试验证功能"""
        
        # 测试基本验证器
        print("测试邮箱验证:")
        print(f"valid@example.com: {Validator.is_valid_email('valid@example.com')}")
        print(f"invalid-email: {Validator.is_valid_email('invalid-email')}")
        
        # 测试装饰器
        @validate_params(
            user_id=user_id_validator,
            email=email_validator,
            age=ValidationRule(
                lambda x: isinstance(x, int) and 0 <= x <= 150,
                "年龄必须在0-150之间"
            )
        )
        def register_user(user_id: int, email: str, age: int):
            return f"用户 {user_id} 注册成功"
        
        try:
            result = register_user(123, "test@example.com", 25)
            print(f"注册成功: {result}")
        except ValidationError as e:
            print(f"注册失败: {e.message}")
        
        # 测试类型验证
        @validate_types
        def process_scores(scores: List[float]) -> float:
            return sum(scores)
        
        try:
            result = process_scores([1.0, 2.5, 3.2])
            print(f"分数处理成功: {result}")
        except ValidationError as e:
            print(f"分数处理失败: {e.message}")
        
        # 测试验证上下文
        context = ValidationContext(ValidationLevel.LOOSE)
        
        context.validate(
            "invalid-email", 
            Validator.is_valid_email,
            "邮箱格式不正确",
            "email"
        )
        
        context.validate(
            -1,
            lambda x: x > 0,
            "值必须大于0",
            "value"
        )
        
        print(f"错误数量: {len(context.errors)}")
        print(f"错误消息: {context.get_error_messages()}")
    
    test_validation()