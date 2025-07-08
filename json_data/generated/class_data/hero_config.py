"""
HeroConfig 配置类

从 hero_config 配置表自动生成的Python类
适用于: 客户端和服务端

自动生成时间: 2025-07-08 16:42:15
生成器: knight_server.json_data.gen_utils.ClassGenerator
源文件: hero_config.xlsx

注意: 此文件为自动生成，请勿手动修改！
"""

from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
import json

@dataclass
class HeroConfig:
    """
    HeroConfig 配置类
    
    从 hero_config 配置表生成的数据类
    """
    hero_id: Optional[int] = None  # 英雄ID
    name: Optional[str] = None  # 英雄名称
    profession: Optional[str] = None  # 职业
    level: Optional[int] = None  # 等级
    hp: Optional[int] = None  # 血量
    attack: Optional[int] = None  # 攻击力
    defense: Optional[int] = None  # 防御力
    skills: Optional[List[Any]] = field(default_factory=list)  # 技能列表
    server_data: Optional[Dict[str, Any]] = field(default_factory=dict)  # 服务端数据

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HeroConfig':
        """
        从字典创建配置对象
        
        Args:
            data: 字典数据
            
        Returns:
            HeroConfig: 配置对象
        """
        return cls(
            hero_id=data.get('hero_id'),
            name=data.get('name'),
            profession=data.get('profession'),
            level=data.get('level'),
            hp=data.get('hp'),
            attack=data.get('attack'),
            defense=data.get('defense'),
            skills=data.get('skills'),
            server_data=data.get('server_data')
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Dict[str, Any]: 字典数据
        """
        return {
            'hero_id': self.hero_id,
            'name': self.name,
            'profession': self.profession,
            'level': self.level,
            'hp': self.hp,
            'attack': self.attack,
            'defense': self.defense,
            'skills': self.skills,
            'server_data': self.server_data
        }

    @classmethod
    def from_json(cls, json_str: str) -> 'HeroConfig':
        """
        从JSON字符串创建配置对象
        
        Args:
            json_str: JSON字符串
            
        Returns:
            HeroConfig: 配置对象
        """
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_json(self) -> str:
        """
        转换为JSON字符串
        
        Returns:
            str: JSON字符串
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)