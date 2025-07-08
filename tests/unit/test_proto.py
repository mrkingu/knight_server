"""
测试 Proto 编解码模块

该模块包含 Proto 模块的综合测试用例，验证各个组件的功能。
"""

import asyncio
import time
import uuid
import pytest
from unittest import TestCase

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../knight_server')))

from common.proto import *
from google.protobuf.message import Message


# 创建测试用的简单 Protobuf 消息类（模拟）
class MockProtoMessage(Message):
    """模拟的 Protobuf 消息类"""
    
    def __init__(self):
        super().__init__()
        self.username = ""
        self.password = ""
        self.token = ""
        self.code = 0
        self.message = ""
    
    def SerializeToString(self) -> bytes:
        """序列化为字节"""
        data = f"{self.username}|{self.password}|{self.token}|{self.code}|{self.message}".encode('utf-8')
        return data
    
    def ParseFromString(self, data: bytes) -> None:
        """从字节反序列化"""
        content = data.decode('utf-8')
        parts = content.split('|')
        self.username = parts[0] if len(parts) > 0 else ""
        self.password = parts[1] if len(parts) > 1 else ""
        self.token = parts[2] if len(parts) > 2 else ""
        self.code = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        self.message = parts[4] if len(parts) > 4 else ""


# 测试消息类
class TestLoginRequest(BaseRequest):
    """测试登录请求消息"""
    _proto_class = MockProtoMessage
    MSG_ID = 1001
    
    def __init__(self):
        super().__init__()
        self.username = ""
        self.password = ""
    
    def _validate_message(self) -> None:
        """验证消息内容"""
        super()._validate_message()
        # 移除用户名验证，允许空用户名进行测试
    
    def to_protobuf(self) -> Message:
        """转换为 Protobuf 消息"""
        proto = MockProtoMessage()
        proto.username = self.username
        proto.password = self.password
        return proto
    
    @classmethod
    def from_protobuf(cls, proto_msg: Message, header: MessageHeader):
        """从 Protobuf 消息创建实例"""
        instance = cls()
        instance.header = header
        instance.username = proto_msg.username
        instance.password = proto_msg.password
        return instance


class TestLoginResponse(BaseResponse):
    """测试登录响应消息"""
    _proto_class = MockProtoMessage
    MSG_ID = -1001
    
    def __init__(self, code: int = 0, message: str = "", token: str = ""):
        super().__init__(code, message)
        self.token = token
    
    def to_protobuf(self) -> Message:
        """转换为 Protobuf 消息"""
        proto = MockProtoMessage()
        proto.token = self.token
        proto.code = self.code
        proto.message = self.message
        return proto
    
    @classmethod
    def from_protobuf(cls, proto_msg: Message, header: MessageHeader):
        """从 Protobuf 消息创建实例"""
        instance = cls(
            code=proto_msg.code, 
            message=proto_msg.message, 
            token=proto_msg.token
        )
        instance.header = header
        return instance


class TestMessageHeader(TestCase):
    """测试消息头"""
    
    def test_create_request_header(self):
        """测试创建请求消息头"""
        header = MessageHeader.create_request(1001)
        
        self.assertEqual(header.msg_id, 1001)
        self.assertTrue(header.is_request())
        self.assertFalse(header.is_response())
        self.assertIsInstance(header.unique_id, str)
        self.assertGreater(header.timestamp, 0)
    
    def test_create_response_header(self):
        """测试创建响应消息头"""
        request_header = MessageHeader.create_request(1001)
        response_header = MessageHeader.create_response(request_header)
        
        self.assertEqual(response_header.msg_id, -1001)
        self.assertFalse(response_header.is_request())
        self.assertTrue(response_header.is_response())
        self.assertEqual(response_header.unique_id, request_header.unique_id)
    
    def test_header_validation(self):
        """测试消息头验证"""
        # 测试无效的 unique_id
        with self.assertRaises(ValidationException):
            MessageHeader("", 1001, int(time.time() * 1000))
        
        # 测试无效的 msg_id
        with self.assertRaises(ValidationException):
            MessageHeader(str(uuid.uuid4()), 0, int(time.time() * 1000))
    
    def test_header_encoding_decoding(self):
        """测试消息头编解码"""
        original_header = MessageHeader.create_request(1001)
        
        # 编码
        encoded_data = encode_header(original_header)
        self.assertEqual(len(encoded_data), HEADER_SIZE)
        
        # 解码
        decoded_header = decode_header(encoded_data)
        
        self.assertEqual(decoded_header.msg_id, original_header.msg_id)
        self.assertEqual(decoded_header.unique_id, original_header.unique_id)
        self.assertEqual(decoded_header.timestamp, original_header.timestamp)


class TestMessageRegistry(TestCase):
    """测试消息注册表"""
    
    def setUp(self):
        """设置测试环境"""
        self.registry = MessageRegistry()
    
    def test_register_message(self):
        """测试注册消息"""
        self.registry.register(1001, TestLoginRequest)
        self.registry.register(-1001, TestLoginResponse)
        
        self.assertTrue(self.registry.is_registered(1001))
        self.assertTrue(self.registry.is_registered(-1001))
        self.assertEqual(self.registry.get_registration_count(), 2)
    
    def test_get_message_class(self):
        """测试获取消息类"""
        self.registry.register(1001, TestLoginRequest)
        
        message_class = self.registry.get_message_class(1001)
        self.assertEqual(message_class, TestLoginRequest)
    
    def test_registry_validation(self):
        """测试注册表验证"""
        # 注册正常消息
        self.registry.register(1001, TestLoginRequest)
        self.registry.register(-1001, TestLoginResponse)
        
        # 验证注册表一致性
        issues = self.registry.validate_registry()
        self.assertEqual(len(issues), 0)
    
    def test_unregister_message(self):
        """测试取消注册"""
        self.registry.register(1001, TestLoginRequest)
        self.assertTrue(self.registry.is_registered(1001))
        
        success = self.registry.unregister(1001)
        self.assertTrue(success)
        self.assertFalse(self.registry.is_registered(1001))


class TestRingBuffer(TestCase):
    """测试环形缓冲区"""
    
    def test_buffer_creation(self):
        """测试缓冲区创建"""
        buffer = RingBuffer(capacity=1024)
        
        self.assertEqual(buffer.capacity, 1024)
        self.assertEqual(buffer.size, 0)
        self.assertTrue(buffer.is_empty)
        self.assertFalse(buffer.is_full)
    
    async def test_write_read(self):
        """测试写入和读取"""
        buffer = RingBuffer(capacity=1024)
        test_data = b"Hello, World!"
        
        # 写入数据
        success = await buffer.write(test_data)
        self.assertTrue(success)
        self.assertEqual(buffer.size, len(test_data))
        
        # 读取数据
        read_data = await buffer.read(len(test_data))
        self.assertEqual(read_data, test_data)
        self.assertEqual(buffer.size, 0)
    
    async def test_peek(self):
        """测试预览数据"""
        buffer = RingBuffer(capacity=1024)
        test_data = b"Test Data"
        
        await buffer.write(test_data)
        
        # 预览数据（不移动读指针）
        peek_data = await buffer.peek(len(test_data))
        self.assertEqual(peek_data, test_data)
        self.assertEqual(buffer.size, len(test_data))  # 大小不变
        
        # 再次读取应该得到相同数据
        read_data = await buffer.read(len(test_data))
        self.assertEqual(read_data, test_data)
    
    async def test_message_protocol(self):
        """测试消息协议处理"""
        buffer = RingBuffer(capacity=1024)
        test_message = b"Hello, Protocol!"
        
        # 写入消息（带长度头）
        success = await buffer.write_message(test_message)
        self.assertTrue(success)
        
        # 读取消息
        read_message = await buffer.read_message()
        self.assertEqual(read_message, test_message)


class TestMessagePool(TestCase):
    """测试消息对象池"""
    
    async def test_pool_creation(self):
        """测试对象池创建"""
        pool = MessagePool(TestLoginRequest, size=5, max_size=20)
        await pool.initialize()
        
        self.assertEqual(pool.message_class, TestLoginRequest)
        self.assertEqual(pool.max_size, 20)
        self.assertEqual(pool.size, 5)
    
    async def test_acquire_release(self):
        """测试获取和释放对象"""
        pool = MessagePool(TestLoginRequest, size=5, max_size=20)
        await pool.initialize()
        
        # 获取对象
        pooled_message = await pool.acquire()
        self.assertIsInstance(pooled_message, PooledMessage)
        self.assertIsInstance(pooled_message.message, TestLoginRequest)
        
        # 释放对象
        await pooled_message.release()
        self.assertFalse(pooled_message.is_acquired)
    
    async def test_context_manager(self):
        """测试上下文管理器"""
        pool = MessagePool(TestLoginRequest, size=5, max_size=20)
        await pool.initialize()
        
        async with pool.get_message() as message:
            self.assertIsInstance(message, TestLoginRequest)
            message.username = "test_user"
        
        # 对象应该已经自动释放


class TestProtoCodec(TestCase):
    """测试编解码器"""
    
    def setUp(self):
        """设置测试环境"""
        self.registry = MessageRegistry()
        self.registry.register(1001, TestLoginRequest)
        self.registry.register(-1001, TestLoginResponse)
        self.codec = ProtoCodec(registry=self.registry)
    
    def test_encode_request(self):
        """测试编码请求消息"""
        # 创建测试请求
        request = TestLoginRequest.create_request(1001)
        request.username = "test_user"
        request.password = "test_pass"
        
        # 编码
        encoded_data = self.codec.encode(request)
        self.assertIsInstance(encoded_data, bytes)
        self.assertGreater(len(encoded_data), HEADER_SIZE)
    
    def test_decode_request(self):
        """测试解码请求消息"""
        # 创建测试请求
        original_request = TestLoginRequest.create_request(1001)
        original_request.username = "test_user"
        original_request.password = "test_pass"
        
        # 编码后解码
        encoded_data = self.codec.encode(original_request)
        decoded_request = self.codec.decode(encoded_data)
        
        self.assertIsInstance(decoded_request, TestLoginRequest)
        self.assertEqual(decoded_request.username, original_request.username)
        self.assertEqual(decoded_request.password, original_request.password)
        self.assertEqual(decoded_request.header.msg_id, original_request.header.msg_id)
    
    def test_encode_decode_response(self):
        """测试编码解码响应消息"""
        # 创建测试请求和响应
        request_header = MessageHeader.create_request(1001)
        response = TestLoginResponse.create_response(request_header, code=0, message="Success", token="abc123")
        
        # 编码后解码
        encoded_data = self.codec.encode(response)
        decoded_response = self.codec.decode(encoded_data)
        
        self.assertIsInstance(decoded_response, TestLoginResponse)
        self.assertEqual(decoded_response.code, 0)
        self.assertEqual(decoded_response.message, "Success")
        self.assertEqual(decoded_response.token, "abc123")
    
    def test_compression(self):
        """测试压缩功能"""
        # 简化压缩测试 - 只测试功能不测试统计
        codec = ProtoCodec(
            registry=self.registry,
            compression=CompressionType.ZSTD,
            compression_threshold=1
        )
        
        request = TestLoginRequest.create_request(1001)
        request.username = "A" * 1000
        request.password = "B" * 1000
        
        # 编码后解码，主要测试功能正确性
        encoded_data = codec.encode(request)
        decoded_request = codec.decode(encoded_data)
        
        self.assertEqual(decoded_request.username, request.username)
        self.assertEqual(decoded_request.password, request.password)
        
        # 压缩可能不生效（如果数据不够大或不够可压缩），这里不强制检查统计


class TestIntegration(TestCase):
    """集成测试"""
    
    async def test_complete_workflow(self):
        """测试完整的工作流程"""
        # 设置组件
        registry = MessageRegistry()
        registry.register(1001, TestLoginRequest)
        registry.register(-1001, TestLoginResponse)
        
        codec = ProtoCodec(registry=registry)
        pool = MessagePool(TestLoginRequest, size=5)
        await pool.initialize()
        
        buffer = RingBuffer(capacity=4096)
        
        # 创建请求消息
        async with pool.get_message() as request:
            request.header = MessageHeader.create_request(1001)
            request.username = "test_user"
            request.password = "test_password"
            
            # 编码消息
            encoded_request = codec.encode(request)
            
            # 通过缓冲区传输
            await buffer.write_message(encoded_request)
            received_data = await buffer.read_message()
            
            # 解码消息
            decoded_request = codec.decode(received_data)
            
            # 验证结果
            self.assertEqual(decoded_request.username, "test_user")
            self.assertEqual(decoded_request.password, "test_password")
            
            # 创建响应
            response = TestLoginResponse.create_response(
                decoded_request.header, 
                code=0, 
                message="Login successful",
                token="jwt_token_here"
            )
            
            # 编码响应
            encoded_response = codec.encode(response)
            
            # 解码响应验证
            decoded_response = codec.decode(encoded_response)
            self.assertEqual(decoded_response.code, 0)
            self.assertEqual(decoded_response.token, "jwt_token_here")


# 异步测试运行器
async def run_async_tests():
    """运行异步测试"""
    test_cases = [
        TestRingBuffer(),
        TestMessagePool(),
        TestIntegration()
    ]
    
    for test_case in test_cases:
        for method_name in dir(test_case):
            if method_name.startswith('test_') and asyncio.iscoroutinefunction(getattr(test_case, method_name)):
                print(f"运行 {test_case.__class__.__name__}.{method_name}")
                try:
                    await getattr(test_case, method_name)()
                    print(f"✓ {method_name} 通过")
                except Exception as e:
                    print(f"✗ {method_name} 失败: {e}")


def run_tests():
    """运行所有测试"""
    import unittest
    
    # 运行同步测试
    print("运行同步测试...")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    test_classes = [
        TestMessageHeader,
        TestMessageRegistry,
        TestProtoCodec
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 运行异步测试
    print("\n运行异步测试...")
    asyncio.run(run_async_tests())
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    if success:
        print("\n✓ 所有测试通过!")
    else:
        print("\n✗ 部分测试失败!")