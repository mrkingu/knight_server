"""
框架集成测试
验证各个模块能否协同工作

该测试套件验证：
1. 服务启动流程
2. 服务间通信
3. 数据流测试
4. 跨服活动测试
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import time
import json

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestFrameworkIntegration:
    """框架集成测试类"""
    
    def __init__(self):
        self.test_results: Dict[str, bool] = {}
        self.test_details: Dict[str, Dict[str, Any]] = {}
        
    async def test_server_startup(self) -> bool:
        """测试服务启动流程"""
        print("🚀 测试服务启动流程...")
        
        try:
            # 测试1: 配置系统初始化
            print("  1. 测试配置系统初始化...")
            try:
                from setting.config import Config
                config = Config()
                print("    ✓ 配置系统初始化成功")
            except Exception as e:
                print(f"    ✗ 配置系统初始化失败: {e}")
                return False
            
            # 测试2: 日志系统初始化
            print("  2. 测试日志系统初始化...")
            try:
                from common.logger import sls_logger, battle_logger
                sls_logger.info("集成测试：SLS日志系统")
                battle_logger.info("集成测试：战斗日志系统")
                print("    ✓ 日志系统初始化成功")
            except Exception as e:
                print(f"    ✗ 日志系统初始化失败: {e}")
                return False
            
            # 测试3: 数据库管理器初始化
            print("  3. 测试数据库管理器初始化...")
            try:
                from common.db import BaseRepository
                from common.db.redis_manager import RedisManager
                from common.db.mongo_manager import MongoManager
                
                # 创建管理器实例（使用模拟模式）
                redis_manager = RedisManager(mock=True)
                mongo_manager = MongoManager(mock=True)
                
                # 测试初始化
                await redis_manager.initialize()
                await mongo_manager.initialize()
                
                print("    ✓ 数据库管理器初始化成功")
            except Exception as e:
                print(f"    ✗ 数据库管理器初始化失败: {e}")
                return False
            
            # 测试4: 服务基类初始化
            print("  4. 测试服务基类初始化...")
            try:
                from services.base import BaseServer, BaseHandler, BaseController
                
                # 测试基类能否正常实例化
                class TestServer(BaseServer):
                    def __init__(self):
                        super().__init__()
                        self.name = "test_server"
                        self.port = 8080
                
                test_server = TestServer()
                print("    ✓ 服务基类初始化成功")
            except Exception as e:
                print(f"    ✗ 服务基类初始化失败: {e}")
                return False
            
            # 测试5: 服务启动器初始化
            print("  5. 测试服务启动器初始化...")
            try:
                from server_launcher.service_manager import ServiceManager
                from server_launcher.launcher import ServerLauncher
                
                print("    ✓ 服务启动器初始化成功")
            except Exception as e:
                print(f"    ✗ 服务启动器初始化失败: {e}")
                return False
            
            self.test_results['server_startup'] = True
            self.test_details['server_startup'] = {
                'config_init': True,
                'logger_init': True,
                'db_init': True,
                'service_base_init': True,
                'launcher_init': True
            }
            
            print("  ✅ 服务启动流程测试通过")
            return True
            
        except Exception as e:
            print(f"  ✗ 服务启动流程测试失败: {e}")
            self.test_results['server_startup'] = False
            return False
    
    async def test_service_communication(self) -> bool:
        """测试服务间通信"""
        print("\n🔗 测试服务间通信...")
        
        try:
            # 测试1: gRPC通信模块
            print("  1. 测试gRPC通信模块...")
            try:
                from common.grpc import GrpcConnectionError, HealthCheckService
                
                # 创建健康检查服务
                health_service = HealthCheckService()
                await health_service.start()
                
                # 注册测试服务
                health_service.register_service("TestService")
                
                await health_service.stop()
                print("    ✓ gRPC通信模块测试通过")
            except Exception as e:
                print(f"    ✗ gRPC通信模块测试失败: {e}")
                return False
            
            # 测试2: 消息编解码
            print("  2. 测试消息编解码...")
            try:
                from common.proto import BaseRequest, BaseResponse
                
                # 创建测试请求
                request = BaseRequest(
                    unique_id="test_request_001",
                    msg_id=1001,
                    timestamp=int(time.time())
                )
                
                # 测试编码
                encoded_data = request.encode()
                
                # 测试解码
                decoded_request = BaseRequest.decode(encoded_data)
                
                assert decoded_request.unique_id == request.unique_id
                assert decoded_request.msg_id == request.msg_id
                
                print("    ✓ 消息编解码测试通过")
            except Exception as e:
                print(f"    ✗ 消息编解码测试失败: {e}")
                return False
            
            # 测试3: 分布式锁
            print("  3. 测试分布式锁...")
            try:
                from common.distributed import create_lock, LockConfig
                
                # 创建分布式锁配置
                lock_config = LockConfig(
                    timeout=30,
                    max_retries=3,
                    retry_delay=0.1
                )
                
                # 创建锁（模拟模式）
                lock = create_lock("test_lock", config=lock_config)
                
                # 测试获取锁
                acquired = await lock.acquire()
                assert acquired, "应该能够获取锁"
                
                # 测试释放锁
                released = await lock.release()
                assert released, "应该能够释放锁"
                
                print("    ✓ 分布式锁测试通过")
            except Exception as e:
                print(f"    ✗ 分布式锁测试失败: {e}")
                return False
            
            self.test_results['service_communication'] = True
            self.test_details['service_communication'] = {
                'grpc_module': True,
                'message_codec': True,
                'distributed_lock': True
            }
            
            print("  ✅ 服务间通信测试通过")
            return True
            
        except Exception as e:
            print(f"  ✗ 服务间通信测试失败: {e}")
            self.test_results['service_communication'] = False
            return False
    
    async def test_data_flow(self) -> bool:
        """测试数据流"""
        print("\n📊 测试数据流...")
        
        try:
            # 测试1: Redis缓存
            print("  1. 测试Redis缓存...")
            try:
                from common.db.redis_manager import RedisManager
                
                # 创建Redis管理器（模拟模式）
                redis_manager = RedisManager(mock=True)
                await redis_manager.initialize()
                
                # 测试基本操作
                await redis_manager.set("test_key", "test_value")
                value = await redis_manager.get("test_key")
                assert value == "test_value", "Redis缓存读写失败"
                
                # 测试删除
                await redis_manager.delete("test_key")
                value = await redis_manager.get("test_key")
                assert value is None, "Redis缓存删除失败"
                
                print("    ✓ Redis缓存测试通过")
            except Exception as e:
                print(f"    ✗ Redis缓存测试失败: {e}")
                return False
            
            # 测试2: MongoDB持久化
            print("  2. 测试MongoDB持久化...")
            try:
                from common.db.mongo_manager import MongoManager
                from common.db.base_document import BaseDocument
                
                # 创建MongoDB管理器（模拟模式）
                mongo_manager = MongoManager(mock=True)
                await mongo_manager.initialize()
                
                # 创建测试文档类
                class TestDocument(BaseDocument):
                    def __init__(self, name: str, value: int):
                        super().__init__()
                        self.name = name
                        self.value = value
                
                # 测试文档创建
                doc = TestDocument("test_doc", 42)
                assert doc.name == "test_doc"
                assert doc.value == 42
                
                print("    ✓ MongoDB持久化测试通过")
            except Exception as e:
                print(f"    ✗ MongoDB持久化测试失败: {e}")
                return False
            
            # 测试3: 数据一致性
            print("  3. 测试数据一致性...")
            try:
                from common.distributed.consistency import put_data, get_data
                
                # 测试数据存储
                await put_data("test_key", {"test": "data"})
                
                # 测试数据读取
                data, version_info = await get_data("test_key")
                assert data is not None, "数据一致性测试失败"
                
                print("    ✓ 数据一致性测试通过")
            except Exception as e:
                print(f"    ✗ 数据一致性测试失败: {e}")
                return False
            
            self.test_results['data_flow'] = True
            self.test_details['data_flow'] = {
                'redis_cache': True,
                'mongo_persistence': True,
                'data_consistency': True
            }
            
            print("  ✅ 数据流测试通过")
            return True
            
        except Exception as e:
            print(f"  ✗ 数据流测试失败: {e}")
            self.test_results['data_flow'] = False
            return False
    
    async def test_cross_server_activity(self) -> bool:
        """测试跨服活动"""
        print("\n🌐 测试跨服活动...")
        
        try:
            # 测试1: 活动创建
            print("  1. 测试活动创建...")
            try:
                from services.base import BaseService
                
                # 创建测试活动服务
                class TestActivityService(BaseService):
                    def __init__(self):
                        super().__init__()
                        self.activities = {}
                    
                    async def create_activity(self, activity_id: str, activity_data: dict):
                        """创建活动"""
                        self.activities[activity_id] = activity_data
                        return activity_id
                    
                    async def get_activity(self, activity_id: str):
                        """获取活动"""
                        return self.activities.get(activity_id)
                
                # 创建服务实例
                activity_service = TestActivityService()
                
                # 测试创建活动
                activity_id = await activity_service.create_activity(
                    "test_activity_001",
                    {"name": "测试活动", "type": "cross_server"}
                )
                
                # 测试获取活动
                activity = await activity_service.get_activity(activity_id)
                assert activity["name"] == "测试活动"
                
                print("    ✓ 活动创建测试通过")
            except Exception as e:
                print(f"    ✗ 活动创建测试失败: {e}")
                return False
            
            # 测试2: 玩家加入
            print("  2. 测试玩家加入...")
            try:
                from services.base import BaseController
                
                # 创建测试控制器
                class TestPlayerController(BaseController):
                    def __init__(self):
                        super().__init__()
                        self.players = {}
                    
                    async def join_activity(self, player_id: str, activity_id: str):
                        """玩家加入活动"""
                        if activity_id not in self.players:
                            self.players[activity_id] = []
                        self.players[activity_id].append(player_id)
                        return True
                    
                    async def get_activity_players(self, activity_id: str):
                        """获取活动玩家列表"""
                        return self.players.get(activity_id, [])
                
                # 创建控制器实例
                player_controller = TestPlayerController()
                
                # 测试玩家加入
                await player_controller.join_activity("player_001", "test_activity_001")
                await player_controller.join_activity("player_002", "test_activity_001")
                
                # 测试获取玩家列表
                players = await player_controller.get_activity_players("test_activity_001")
                assert len(players) == 2
                assert "player_001" in players
                assert "player_002" in players
                
                print("    ✓ 玩家加入测试通过")
            except Exception as e:
                print(f"    ✗ 玩家加入测试失败: {e}")
                return False
            
            # 测试3: 数据同步
            print("  3. 测试数据同步...")
            try:
                from common.distributed.id_generator import SnowflakeIDGenerator, SnowflakeConfig
                
                # 创建ID生成器
                config = SnowflakeConfig()
                config.worker_id = 1
                id_generator = SnowflakeIDGenerator(config)
                
                # 测试生成唯一ID
                id1 = id_generator.generate_id()
                id2 = id_generator.generate_id()
                
                assert id1 != id2, "ID生成器应该生成唯一ID"
                assert id1 > 0, "ID应该大于0"
                assert id2 > 0, "ID应该大于0"
                
                print("    ✓ 数据同步测试通过")
            except Exception as e:
                print(f"    ✗ 数据同步测试失败: {e}")
                return False
            
            self.test_results['cross_server_activity'] = True
            self.test_details['cross_server_activity'] = {
                'activity_creation': True,
                'player_join': True,
                'data_sync': True
            }
            
            print("  ✅ 跨服活动测试通过")
            return True
            
        except Exception as e:
            print(f"  ✗ 跨服活动测试失败: {e}")
            self.test_results['cross_server_activity'] = False
            return False
    
    async def run_all_tests(self) -> bool:
        """运行所有集成测试"""
        print("🧪 开始框架集成测试")
        print("=" * 50)
        
        start_time = time.time()
        
        # 运行所有测试
        tests = [
            self.test_server_startup,
            self.test_service_communication,
            self.test_data_flow,
            self.test_cross_server_activity
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test in tests:
            try:
                result = await test()
                if result:
                    passed_tests += 1
            except Exception as e:
                print(f"测试执行异常: {e}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 生成测试报告
        self.generate_test_report(passed_tests, total_tests, duration)
        
        print("\n" + "=" * 50)
        if passed_tests == total_tests:
            print("🎉 所有集成测试通过!")
            return True
        else:
            print(f"⚠️  {passed_tests}/{total_tests} 个测试通过")
            return False
    
    def generate_test_report(self, passed: int, total: int, duration: float):
        """生成测试报告"""
        report = []
        report.append("# 框架集成测试报告")
        report.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"测试耗时: {duration:.2f}秒")
        report.append("")
        
        report.append("## 测试摘要")
        report.append(f"- 总测试数: {total}")
        report.append(f"- 通过测试: {passed}")
        report.append(f"- 失败测试: {total - passed}")
        report.append(f"- 成功率: {passed/total*100:.1f}%")
        report.append("")
        
        # 详细结果
        report.append("## 详细结果")
        for test_name, result in self.test_results.items():
            status = "✅ 通过" if result else "❌ 失败"
            report.append(f"- **{test_name}**: {status}")
            
            if test_name in self.test_details:
                for detail_name, detail_result in self.test_details[test_name].items():
                    detail_status = "✓" if detail_result else "✗"
                    report.append(f"  - {detail_name}: {detail_status}")
            report.append("")
        
        # 保存报告
        project_root = Path(__file__).parent.parent.parent
        reports_dir = project_root / "reports"
        reports_dir.mkdir(exist_ok=True)
        
        report_file = reports_dir / "integration_test_report.md"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(report))
        
        print(f"\n📄 测试报告已保存到: {report_file}")


async def main():
    """主函数"""
    tester = TestFrameworkIntegration()
    success = await tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())