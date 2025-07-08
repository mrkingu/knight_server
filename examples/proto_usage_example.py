#!/usr/bin/env python3
"""
Proto 模块使用示例

演示如何使用 common/proto 模块进行消息编解码、对象池管理和网络通信。
"""

import asyncio
import sys
import time

# 添加项目路径
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

from common.proto import *
from google.protobuf.message import Message


# 模拟的 Protobuf 消息类
class UserProto(Message):
    """用户信息 Protobuf 消息（模拟）"""
    
    def __init__(self):
        super().__init__()
        self.user_id = 0
        self.username = ""
        self.email = ""
        self.level = 1
    
    def SerializeToString(self) -> bytes:
        data = f"{self.user_id}|{self.username}|{self.email}|{self.level}".encode('utf-8')
        return data
    
    def ParseFromString(self, data: bytes) -> None:
        parts = data.decode('utf-8').split('|')
        self.user_id = int(parts[0]) if parts[0].isdigit() else 0
        self.username = parts[1] if len(parts) > 1 else ""
        self.email = parts[2] if len(parts) > 2 else ""
        self.level = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1


# 定义消息类
class LoginRequest(BaseRequest):
    """登录请求消息"""
    _proto_class = UserProto
    MSG_ID = 1001
    
    def __init__(self):
        super().__init__()
        self.username = ""
        self.password = ""
    
    def _validate_message(self) -> None:
        super()._validate_message()
    
    def to_protobuf(self) -> Message:
        proto = UserProto()
        proto.username = self.username
        proto.email = self.password  # 复用字段
        return proto
    
    @classmethod
    def from_protobuf(cls, proto_msg: Message, header: MessageHeader):
        instance = cls()
        instance.header = header
        instance.username = proto_msg.username
        instance.password = proto_msg.email
        return instance


class LoginResponse(BaseResponse):
    """登录响应消息"""
    _proto_class = UserProto
    MSG_ID = -1001
    
    def __init__(self, code: int = 0, message: str = "", user_id: int = 0, token: str = ""):
        super().__init__(code, message)
        self.user_id = user_id
        self.token = token
    
    def to_protobuf(self) -> Message:
        proto = UserProto()
        proto.user_id = self.user_id
        proto.username = self.token
        return proto
    
    @classmethod
    def from_protobuf(cls, proto_msg: Message, header: MessageHeader):
        instance = cls(user_id=proto_msg.user_id, token=proto_msg.username)
        instance.header = header
        return instance


async def basic_usage_example():
    """基础使用示例"""
    print("=== 基础使用示例 ===")
    
    # 1. 注册消息类
    registry = get_default_registry()
    registry.register(1001, LoginRequest)
    registry.register(-1001, LoginResponse)
    
    # 2. 创建编解码器
    codec = ProtoCodec(compression=CompressionType.ZSTD)
    
    # 3. 创建请求消息
    request = LoginRequest.create_request(1001)
    request.username = "player123"
    request.password = "secret123"
    
    print(f"创建请求: {request}")
    print(f"消息头: {request.header}")
    
    # 4. 编码消息
    encoded_data = codec.encode(request)
    print(f"编码后大小: {len(encoded_data)} 字节")
    
    # 5. 解码消息
    decoded_request = codec.decode(encoded_data)
    print(f"解码请求: 用户名={decoded_request.username}, 密码={decoded_request.password}")
    
    # 6. 创建响应消息
    response = LoginResponse.create_response(
        decoded_request.header,
        code=0,
        message="登录成功",
        user_id=12345,
        token="jwt_token_abc123"
    )
    
    print(f"创建响应: {response}")
    
    # 7. 编码响应
    encoded_response = codec.encode(response)
    decoded_response = codec.decode(encoded_response)
    print(f"解码响应: 用户ID={decoded_response.user_id}, 令牌={decoded_response.token}")


async def buffer_usage_example():
    """缓冲区使用示例"""
    print("\n=== 缓冲区使用示例 ===")
    
    # 创建环形缓冲区
    buffer = RingBuffer(capacity=4096)
    print(f"创建缓冲区: {buffer}")
    
    # 模拟网络数据接收
    messages = [
        b"Hello, World!",
        b"This is a test message",
        b"Protocol Buffers are awesome"
    ]
    
    # 写入消息（带长度头）
    for i, msg in enumerate(messages):
        await buffer.write_message(msg)
        print(f"写入消息 {i+1}: {len(msg)} 字节")
    
    print(f"缓冲区状态: {buffer}")
    
    # 读取消息
    while buffer.available_read > 0:
        try:
            message = await buffer.read_message()
            if message:
                print(f"读取消息: {message.decode('utf-8')}")
            else:
                break
        except:
            break
    
    print(f"读取完成，缓冲区状态: {buffer}")


async def pool_usage_example():
    """对象池使用示例"""
    print("\n=== 对象池使用示例 ===")
    
    # 创建消息对象池
    pool = MessagePool(LoginRequest, size=5, max_size=20)
    await pool.initialize()
    
    print(f"创建对象池: {pool}")
    print(f"池统计: {pool.get_statistics()}")
    
    # 使用上下文管理器获取对象
    async with pool.get_message() as message:
        message.header = MessageHeader.create_request(1001)
        message.username = "pooled_user"
        message.password = "pooled_pass"
        print(f"从池中获取消息: {message}")
        print(f"当前池状态: 可用={pool.available_count}, 已获取={pool.acquired_count}")
    
    print(f"归还后池状态: 可用={pool.available_count}, 已获取={pool.acquired_count}")
    
    # 获取健康状态
    health = pool.get_health_status()
    print(f"池健康状态: {health['status']} (得分: {health['health_score']})")


async def integration_example():
    """完整集成示例"""
    print("\n=== 完整集成示例 ===")
    
    # 设置组件
    registry = get_default_registry()
    registry.register(1001, LoginRequest)
    registry.register(-1001, LoginResponse)
    
    codec = ProtoCodec(
        registry=registry,
        compression=CompressionType.ZSTD,
        compression_threshold=100
    )
    
    pool = MessagePool(LoginRequest, size=10)
    await pool.initialize()
    
    buffer = RingBuffer(capacity=8192)
    
    print("所有组件初始化完成")
    
    # 模拟客户端发送请求
    async with pool.get_message() as request:
        request.header = MessageHeader.create_request(1001)
        request.username = "integration_test"
        request.password = "test_password"
        
        # 编码并通过缓冲区传输
        encoded_request = codec.encode(request)
        await buffer.write_message(encoded_request)
        
        print(f"客户端发送请求: {request.username}")
    
    # 模拟服务器接收处理
    received_data = await buffer.read_message()
    if received_data:
        decoded_request = codec.decode(received_data)
        print(f"服务器接收请求: {decoded_request.username}")
        
        # 创建响应
        response = LoginResponse.create_response(
            decoded_request.header,
            code=0,
            message="登录成功",
            user_id=99999,
            token="integration_token"
        )
        
        # 发送响应
        encoded_response = codec.encode(response)
        await buffer.write_message(encoded_response)
        
        print(f"服务器发送响应: 用户ID={response.user_id}")
    
    # 模拟客户端接收响应
    response_data = await buffer.read_message()
    if response_data:
        decoded_response = codec.decode(response_data)
        print(f"客户端接收响应: 令牌={decoded_response.token}")
    
    # 打印统计信息
    codec_stats = codec.get_statistics()
    print(f"\n编解码统计:")
    print(f"  - 编码次数: {codec_stats['total_encoded']}")
    print(f"  - 解码次数: {codec_stats['total_decoded']}")
    print(f"  - 平均编码时间: {codec_stats['avg_encode_time']*1000:.2f}ms")
    print(f"  - 平均解码时间: {codec_stats['avg_decode_time']*1000:.2f}ms")
    
    pool_stats = pool.get_statistics()
    print(f"\n对象池统计:")
    print(f"  - 总获取次数: {pool_stats['total_acquired']}")
    print(f"  - 总释放次数: {pool_stats['total_released']}")
    print(f"  - 使用率: {pool_stats['utilization']:.1%}")
    
    buffer_stats = buffer.get_statistics()
    print(f"\n缓冲区统计:")
    print(f"  - 容量: {buffer_stats['capacity']} 字节")
    print(f"  - 使用率: {buffer_stats['utilization']:.1%}")


async def performance_benchmark():
    """性能基准测试"""
    print("\n=== 性能基准测试 ===")
    
    # 设置测试环境
    registry = get_default_registry()
    registry.register(1001, LoginRequest)
    
    codec = ProtoCodec(registry=registry)
    pool = MessagePool(LoginRequest, size=100)
    await pool.initialize()
    
    # 测试编解码性能
    test_count = 1000
    start_time = time.time()
    
    for i in range(test_count):
        async with pool.get_message() as request:
            request.header = MessageHeader.create_request(1001)
            request.username = f"user_{i}"
            request.password = f"pass_{i}"
            
            # 编码
            encoded = codec.encode(request)
            
            # 解码
            decoded = codec.decode(encoded)
    
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"性能测试结果:")
    print(f"  - 测试次数: {test_count}")
    print(f"  - 总耗时: {total_time:.3f}秒")
    print(f"  - 平均每次: {total_time/test_count*1000:.3f}ms")
    print(f"  - QPS: {test_count/total_time:.0f}")
    
    # 获取详细性能报告
    performance_report = codec.get_performance_report()
    print(f"  - 性能等级: {performance_report['performance_grade']}")
    print(f"  - 建议: {', '.join(performance_report['recommendations'])}")


async def main():
    """主函数"""
    print("Knight Server Proto 模块使用示例")
    print("=" * 50)
    
    try:
        await basic_usage_example()
        await buffer_usage_example()
        await pool_usage_example()
        await integration_example()
        await performance_benchmark()
        
        print("\n" + "=" * 50)
        print("所有示例运行完成！")
        
    except Exception as e:
        print(f"运行示例时发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())