"""
测试专用的简化版模块

该模块提供测试所需的基本功能，避免外部依赖。
"""

import asyncio
import sys
import time
import random
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar
from dataclasses import dataclass, field

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Mock logger
class MockLogger:
    def info(self, msg): print(f"INFO: {msg}")
    def debug(self, msg): print(f"DEBUG: {msg}")
    def warning(self, msg): print(f"WARNING: {msg}")
    def error(self, msg): print(f"ERROR: {msg}")

# Mock generate_id function
def generate_id():
    return str(int(time.time() * 1000000) + random.randint(1000, 9999))

# Patch the modules
sys.modules['common.logger'] = type('MockModule', (), {'logger': MockLogger()})()
sys.modules['common.utils.id_generator'] = type('MockModule', (), {'generate_id': generate_id})()
sys.modules['common.utils.singleton'] = type('MockModule', (), {
    'Singleton': type('Singleton', (), {})
})()

# Now import our database module
from common.db.redis_manager import redis_manager, RedisManager
from common.db.mongo_manager import mongo_manager, MongoManager
from common.db.base_document import BaseDocument, register_document
from common.db.base_repository import BaseRepository


T = TypeVar('T', bound=BaseDocument)


def get_repository(document_class: Type[T]) -> BaseRepository:
    """获取仓库实例"""
    return BaseRepository(document_class)


@register_document
@dataclass 
class TestUser(BaseDocument):
    """测试用户文档"""
    username: str = ""
    email: str = ""
    age: int = 0
    
    @classmethod
    def get_collection_name(cls) -> str:
        return "test_users"
    
    def validate(self) -> None:
        super().validate()
        if not self.username:
            raise ValueError("用户名不能为空")
        if not self.email:
            raise ValueError("邮箱不能为空")
        if self.age < 0:
            raise ValueError("年龄不能为负数")


async def test_redis():
    """测试Redis功能"""
    print("=== 测试Redis功能 ===")
    
    # 初始化Redis管理器
    await redis_manager.initialize()
    
    # 基础操作
    await redis_manager.set("test_key", "test_value", ttl=60)
    value = await redis_manager.get("test_key")
    print(f"Redis GET: {value}")
    
    # JSON数据
    data = {"name": "test", "value": 123}
    await redis_manager.set("test_json", data, ttl=60)
    json_value = await redis_manager.get("test_json")
    print(f"Redis JSON: {json_value}")
    
    # 批量操作
    mapping = {
        "key1": "value1",
        "key2": {"data": "value2"},
        "key3": [1, 2, 3]
    }
    await redis_manager.mset(mapping, ttl=60)
    values = await redis_manager.mget(["key1", "key2", "key3"])
    print(f"Redis MGET: {values}")
    
    # 分布式锁
    async with await redis_manager.create_lock("test_lock", timeout=10):
        print("获得分布式锁")
        await asyncio.sleep(0.1)
    print("释放分布式锁")
    
    # 健康检查
    health = await redis_manager.health_check()
    print(f"Redis健康状态: {health}")


async def test_mongodb():
    """测试MongoDB功能"""
    print("\n=== 测试MongoDB功能 ===")
    
    # 初始化MongoDB管理器
    await mongo_manager.initialize()
    
    collection_name = "test_collection"
    
    # 插入文档
    doc_data = {
        "name": "测试文档",
        "value": 42,
        "created_at": datetime.utcnow()
    }
    doc_id = await mongo_manager.insert_one(collection_name, doc_data)
    print(f"插入文档ID: {doc_id}")
    
    # 查询文档
    found_doc = await mongo_manager.find_one(collection_name, {"_id": doc_id})
    print(f"查询文档: {found_doc}")
    
    # 更新文档
    update_data = {"$set": {"value": 100, "updated": True}}
    updated = await mongo_manager.update_one(collection_name, {"_id": doc_id}, update_data)
    print(f"更新结果: {updated}")
    
    # 统计文档
    count = await mongo_manager.count_documents(collection_name)
    print(f"文档数量: {count}")
    
    # 删除文档
    deleted = await mongo_manager.delete_one(collection_name, {"_id": doc_id})
    print(f"删除结果: {deleted}")
    
    # 健康检查
    health = await mongo_manager.health_check()
    print(f"MongoDB健康状态: {health}")


async def test_document_and_repository():
    """测试文档和仓库功能"""
    print("\n=== 测试文档和仓库功能 ===")
    
    # 获取仓库
    user_repo = get_repository(TestUser)
    print(f"获取仓库: {user_repo}")
    
    # 创建用户
    user = TestUser(
        username="testuser",
        email="test@example.com",
        age=25
    )
    print(f"创建用户: {user}")
    
    # 保存用户
    saved_user = await user_repo.save(user)
    print(f"保存用户: {saved_user._id}")
    
    # 根据ID查找
    found_user = await user_repo.find_by_id(saved_user._id)
    print(f"查找用户: {found_user.username if found_user else 'Not found'}")
    
    # 更新用户
    if found_user:
        found_user.age = 26
        updated_user = await user_repo.save(found_user)
        print(f"更新用户年龄: {updated_user.age}")
    
    # 查找多个用户
    users = await user_repo.find_many({"username": "testuser"})
    print(f"查找到 {len(users)} 个用户")
    
    # 分页查询
    page_result = await user_repo.find_with_pagination(
        filter_dict={}, page=1, page_size=10
    )
    print(f"分页查询: {page_result.count} 个文档，{page_result.page_info.total_pages} 页")
    
    # 统计数量
    count = await user_repo.count()
    print(f"用户总数: {count}")
    
    # 软删除
    if found_user:
        deleted = await user_repo.delete(found_user._id, soft=True)
        print(f"软删除结果: {deleted}")


async def test_cache_integration():
    """测试缓存集成"""
    print("\n=== 测试缓存集成 ===")
    
    user_repo = get_repository(TestUser)
    
    # 创建用户
    user = TestUser(
        username="cacheuser",
        email="cache@example.com",
        age=30
    )
    
    # 保存用户（会更新缓存）
    saved_user = await user_repo.save(user, use_cache=True)
    print(f"保存用户到缓存: {saved_user._id}")
    
    # 从缓存读取（应该命中缓存）
    cached_user = await user_repo.find_by_id(saved_user._id, use_cache=True)
    print(f"从缓存读取用户: {cached_user.username if cached_user else 'Not found'}")
    
    # 直接从数据库读取（跳过缓存）
    db_user = await user_repo.find_by_id(saved_user._id, use_cache=False)
    print(f"从数据库读取用户: {db_user.username if db_user else 'Not found'}")
    
    # 删除用户（会清除缓存）
    if saved_user:
        await user_repo.delete(saved_user._id, soft=True)
        print("删除用户（清除缓存）")


async def main():
    """主测试函数"""
    try:
        print("开始数据库模块测试...")
        
        # 运行各项测试
        await test_redis()
        await test_mongodb()
        await test_document_and_repository()
        await test_cache_integration()
        
        print("\n=== 所有测试完成 ===")
        print("数据库模块功能正常!")
        
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 关闭数据库
        await redis_manager.close()
        await mongo_manager.close()
        print("数据库已关闭")


if __name__ == "__main__":
    asyncio.run(main())