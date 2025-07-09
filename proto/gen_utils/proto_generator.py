"""
Proto文件生成器模块

负责根据扫描到的Python类生成Protocol Buffers文件。
支持生成客户端和服务端分离的.proto文件。
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from common.logger import logger
from .proto_scanner import ProtoClassInfo, ProtoFieldInfo
from .type_converter import TypeConverter


class ProtoGenerator:
    """
    Proto文件生成器
    
    负责根据扫描到的Python类生成Protocol Buffers文件
    """
    
    def __init__(self, output_dir: str = "proto/proto"):
        """
        初始化生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        self.logger = logger
        self.type_converter = TypeConverter()
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_proto_files(self, class_infos: List[ProtoClassInfo]) -> List[str]:
        """
        生成Proto文件
        
        Args:
            class_infos: 类信息列表
            
        Returns:
            List[str]: 生成的Proto文件路径列表
        """
        generated_files = []
        
        try:
            self.logger.info("开始生成Proto文件...")
            
            # 分离请求和响应类
            request_classes = [cls for cls in class_infos if cls.is_request]
            response_classes = [cls for cls in class_infos if cls.is_response]
            
            # 生成客户端Proto文件
            if request_classes or response_classes:
                client_proto_path = self._generate_client_proto(request_classes, response_classes)
                generated_files.append(client_proto_path)
            
            # 生成服务端Proto文件
            if request_classes or response_classes:
                server_proto_path = self._generate_server_proto(request_classes, response_classes)
                generated_files.append(server_proto_path)
            
            self.logger.info(f"Proto文件生成完成，共生成{len(generated_files)}个文件")
            return generated_files
            
        except Exception as e:
            self.logger.error(f"生成Proto文件失败: {str(e)}")
            raise
    
    def _generate_client_proto(self, request_classes: List[ProtoClassInfo], 
                              response_classes: List[ProtoClassInfo]) -> str:
        """
        生成客户端Proto文件
        
        Args:
            request_classes: 请求类列表
            response_classes: 响应类列表
            
        Returns:
            str: 生成的Proto文件路径
        """
        file_path = os.path.join(self.output_dir, "client_messages.proto")
        
        # 生成Proto内容
        proto_content = self._generate_proto_content(
            "client_messages",
            request_classes,
            response_classes,
            "客户端消息定义"
        )
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(proto_content)
        
        self.logger.info(f"生成客户端Proto文件: {file_path}")
        return file_path
    
    def _generate_server_proto(self, request_classes: List[ProtoClassInfo], 
                              response_classes: List[ProtoClassInfo]) -> str:
        """
        生成服务端Proto文件
        
        Args:
            request_classes: 请求类列表
            response_classes: 响应类列表
            
        Returns:
            str: 生成的Proto文件路径
        """
        file_path = os.path.join(self.output_dir, "server_messages.proto")
        
        # 生成Proto内容
        proto_content = self._generate_proto_content(
            "server_messages",
            request_classes,
            response_classes,
            "服务端消息定义"
        )
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(proto_content)
        
        self.logger.info(f"生成服务端Proto文件: {file_path}")
        return file_path
    
    def _generate_proto_content(self, package_name: str, 
                               request_classes: List[ProtoClassInfo],
                               response_classes: List[ProtoClassInfo],
                               description: str) -> str:
        """
        生成Proto文件内容
        
        Args:
            package_name: 包名
            request_classes: 请求类列表
            response_classes: 响应类列表
            description: 文件描述
            
        Returns:
            str: Proto文件内容
        """
        # 生成文件头部
        header = self._generate_proto_header(package_name, description)
        
        # 生成请求消息
        request_messages = []
        for cls_info in request_classes:
            message = self._generate_message_definition(cls_info)
            request_messages.append(message)
        
        # 生成响应消息
        response_messages = []
        for cls_info in response_classes:
            message = self._generate_message_definition(cls_info)
            response_messages.append(message)
        
        # 组合完整内容
        parts = [header]
        
        if request_messages:
            parts.append("// 请求消息定义")
            parts.extend(request_messages)
        
        if response_messages:
            parts.append("// 响应消息定义")
            parts.extend(response_messages)
        
        return '\n\n'.join(parts)
    
    def _generate_proto_header(self, package_name: str, description: str) -> str:
        """
        生成Proto文件头部
        
        Args:
            package_name: 包名
            description: 文件描述
            
        Returns:
            str: Proto文件头部
        """
        return f'''/*
 * {description}
 * 
 * 自动生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
 * 生成器: knight_server.proto.gen_utils.ProtoGenerator
 * 
 * 注意: 此文件为自动生成，请勿手动修改！
 */

syntax = "proto3";

package {package_name};

option java_package = "com.knight.server.proto.{package_name}";
option java_outer_classname = "{package_name.title()}Proto";
option csharp_namespace = "KnightServer.Proto.{package_name.title()}";
option go_package = "github.com/knight-server/proto/{package_name}";'''
    
    def _generate_message_definition(self, class_info: ProtoClassInfo) -> str:
        """
        生成消息定义
        
        Args:
            class_info: 类信息
            
        Returns:
            str: 消息定义内容
        """
        # 生成消息注释
        comment_lines = []
        if class_info.doc_string:
            comment_lines.append(f"// {class_info.doc_string}")
        
        # 添加消息ID注释
        if class_info.msg_id is not None:
            comment_lines.append(f"// 消息ID: {class_info.msg_id}")
        
        comment_lines.append(f"// 基类: {class_info.base_class}")
        comment_lines.append(f"// 模块: {class_info.module}")
        
        # 生成消息声明
        message_header = f"message {class_info.name} {{"
        
        # 生成字段定义
        field_definitions = []
        for field_info in class_info.fields:
            field_def = self._generate_field_definition(field_info)
            field_definitions.append(field_def)
        
        # 如果没有字段，添加一个占位符
        if not field_definitions:
            field_definitions.append("    // 无字段")
        
        # 生成消息结束
        message_footer = "}"
        
        # 组合完整消息定义
        parts = comment_lines + [message_header] + field_definitions + [message_footer]
        return '\n'.join(parts)
    
    def _generate_field_definition(self, field_info: ProtoFieldInfo) -> str:
        """
        生成字段定义
        
        Args:
            field_info: 字段信息
            
        Returns:
            str: 字段定义内容
        """
        # 转换字段类型
        proto_type = self.type_converter.convert_python_type_to_proto(field_info.type)
        
        # 生成字段名
        field_name = self.type_converter.get_safe_field_name(field_info.name)
        
        # 生成字段定义
        field_def = self.type_converter.get_proto_field_definition(
            field_name, proto_type, field_info.number
        )
        
        # 添加注释
        if field_info.comment:
            field_def += f"  // {field_info.comment}"
        
        return field_def
    
    def generate_service_definition(self, class_infos: List[ProtoClassInfo]) -> str:
        """
        生成服务定义
        
        Args:
            class_infos: 类信息列表
            
        Returns:
            str: 服务定义内容
        """
        # 配对请求和响应
        request_response_pairs = self._pair_request_response(class_infos)
        
        if not request_response_pairs:
            return ""
        
        # 生成服务定义
        service_lines = ["service MessageService {"]
        
        for request_class, response_class in request_response_pairs:
            rpc_name = self._generate_rpc_name(request_class.name)
            service_lines.append(f"    rpc {rpc_name}({request_class.name}) returns ({response_class.name});")
        
        service_lines.append("}")
        
        return '\n'.join(service_lines)
    
    def _pair_request_response(self, class_infos: List[ProtoClassInfo]) -> List[tuple]:
        """
        配对请求和响应类
        
        Args:
            class_infos: 类信息列表
            
        Returns:
            List[tuple]: 请求响应配对列表
        """
        request_classes = {cls.name: cls for cls in class_infos if cls.is_request}
        response_classes = {cls.name: cls for cls in class_infos if cls.is_response}
        
        pairs = []
        
        # 尝试根据名称匹配
        for req_name, req_class in request_classes.items():
            # 寻找对应的响应类
            possible_response_names = [
                req_name.replace('Request', 'Response'),
                req_name + 'Response',
                req_name.replace('Req', 'Resp'),
                req_name.replace('Req', 'Response')
            ]
            
            for resp_name in possible_response_names:
                if resp_name in response_classes:
                    pairs.append((req_class, response_classes[resp_name]))
                    break
        
        return pairs
    
    def _generate_rpc_name(self, request_name: str) -> str:
        """
        生成RPC方法名
        
        Args:
            request_name: 请求类名
            
        Returns:
            str: RPC方法名
        """
        # 移除Request后缀
        if request_name.endswith('Request'):
            rpc_name = request_name[:-7]
        elif request_name.endswith('Req'):
            rpc_name = request_name[:-3]
        else:
            rpc_name = request_name
        
        # 确保首字母大写
        return rpc_name[0].upper() + rpc_name[1:] if rpc_name else "Handle"
    
    def generate_complete_proto(self, class_infos: List[ProtoClassInfo]) -> str:
        """
        生成完整的Proto文件（包含服务定义）
        
        Args:
            class_infos: 类信息列表
            
        Returns:
            str: 完整Proto文件路径
        """
        file_path = os.path.join(self.output_dir, "knight_messages.proto")
        
        # 分离请求和响应类
        request_classes = [cls for cls in class_infos if cls.is_request]
        response_classes = [cls for cls in class_infos if cls.is_response]
        
        # 生成Proto内容
        proto_content = self._generate_proto_content(
            "knight_messages",
            request_classes,
            response_classes,
            "Knight Server 消息定义"
        )
        
        # 添加服务定义
        service_definition = self.generate_service_definition(class_infos)
        if service_definition:
            proto_content += "\n\n" + service_definition
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(proto_content)
        
        self.logger.info(f"生成完整Proto文件: {file_path}")
        return file_path
    
    def validate_proto_file(self, file_path: str) -> bool:
        """
        验证生成的Proto文件
        
        Args:
            file_path: Proto文件路径
            
        Returns:
            bool: 是否有效
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 基本语法检查
            if not content.strip().startswith('/*') and not content.strip().startswith('//'):
                if 'syntax = "proto3";' not in content:
                    self.logger.error(f"Proto文件缺少语法声明: {file_path}")
                    return False
            
            # 检查包声明
            if 'package ' not in content:
                self.logger.error(f"Proto文件缺少包声明: {file_path}")
                return False
            
            # 检查是否有消息定义
            if 'message ' not in content:
                self.logger.warning(f"Proto文件没有消息定义: {file_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"验证Proto文件失败: {file_path}, 错误: {str(e)}")
            return False
    
    def backup_existing_file(self, file_path: str) -> Optional[str]:
        """
        备份现有文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[str]: 备份文件路径，如果没有现有文件则返回None
        """
        if not os.path.exists(file_path):
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{file_path}.backup_{timestamp}"
        
        try:
            os.rename(file_path, backup_path)
            self.logger.info(f"备份现有文件: {file_path} -> {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.error(f"备份文件失败: {file_path}, 错误: {str(e)}")
            return None