"""
数据仓库生成工具主程序

提供命令行接口，用于扫描文档模型并生成Repository类。
支持批量处理、自定义扩展等功能。
"""

import os
import sys
import argparse
from typing import List, Optional
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.logger import logger
from .document_scanner import DocumentScanner
from .repository_generator import RepositoryGenerator


class RepositoryGeneratorConfig:
    """Repository生成器配置"""
    
    def __init__(self):
        self.scan_dirs: List[str] = ["models/document"]
        self.output_dir: str = "models/repository"
        self.backup: bool = True
        self.validate: bool = True
        self.preserve_custom: bool = True
        self.verbose: bool = False


class RepositoryCodeGenerator:
    """
    Repository代码生成器
    
    负责协调文档扫描和Repository生成的完整流程
    """
    
    def __init__(self, config: RepositoryGeneratorConfig):
        """
        初始化生成器
        
        Args:
            config: 生成器配置
        """
        self.config = config
        self.logger = logger
        
        # 初始化各个组件
        self.scanner = DocumentScanner(scan_dirs=config.scan_dirs)
        self.generator = RepositoryGenerator(output_dir=config.output_dir)
    
    def generate_repository_files(self) -> bool:
        """
        生成Repository文件
        
        Returns:
            bool: 是否成功
        """
        try:
            self.logger.info("开始生成Repository文件...")
            
            # 扫描文档模型
            self.logger.info("扫描文档模型...")
            document_infos = self.scanner.scan_directories()
            
            if not document_infos:
                self.logger.warning("没有找到可处理的文档模型")
                return False
            
            # 验证扫描结果
            if not self.scanner.validate_scanned_documents():
                self.logger.error("文档模型验证失败")
                return False
            
            # 生成Repository文件
            self.logger.info("生成Repository文件...")
            repo_files = self.generator.generate_repository_files(document_infos)
            
            # 验证生成的文件
            if self.config.validate:
                self.logger.info("验证生成的文件...")
                self._validate_generated_files(repo_files)
            
            self.logger.info(f"Repository文件生成完成！")
            self.logger.info(f"扫描到文档模型: {len(document_infos)}个")
            self.logger.info(f"生成Repository文件: {len(repo_files)}个")
            
            # 显示统计信息
            self._show_generation_stats(document_infos, repo_files)
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成Repository文件失败: {str(e)}")
            return False
    
    def generate_from_specific_documents(self, document_files: List[str]) -> bool:
        """
        从指定的文档文件生成Repository文件
        
        Args:
            document_files: 文档文件路径列表
            
        Returns:
            bool: 是否成功
        """
        try:
            self.logger.info(f"从指定文件生成Repository文件: {len(document_files)}个文件")
            
            # 扫描指定的文件
            document_infos = []
            for doc_file in document_files:
                if os.path.exists(doc_file):
                    self.scanner._scan_python_file(doc_file)
                else:
                    self.logger.warning(f"文件不存在: {doc_file}")
            
            # 获取扫描结果
            document_infos = self.scanner.scanned_documents
            
            if not document_infos:
                self.logger.warning("没有找到可处理的文档模型")
                return False
            
            # 生成Repository文件
            repo_files = self.generator.generate_repository_files(document_infos)
            
            # 验证生成的文件
            if self.config.validate:
                self._validate_generated_files(repo_files)
            
            self.logger.info(f"Repository文件生成完成！")
            return True
            
        except Exception as e:
            self.logger.error(f"生成Repository文件失败: {str(e)}")
            return False
    
    def _validate_generated_files(self, repo_files: List[str]) -> None:
        """
        验证生成的文件
        
        Args:
            repo_files: Repository文件列表
        """
        valid_count = 0
        for repo_file in repo_files:
            if self.generator.validate_repository_file(repo_file):
                valid_count += 1
            else:
                self.logger.warning(f"Repository文件验证失败: {repo_file}")
        
        self.logger.info(f"文件验证完成: {valid_count}/{len(repo_files)} 个文件有效")
    
    def _show_generation_stats(self, document_infos: List, repo_files: List[str]) -> None:
        """
        显示生成统计信息
        
        Args:
            document_infos: 文档信息列表
            repo_files: Repository文件列表
        """
        # 统计文档信息
        total_fields = sum(len(doc.fields) for doc in document_infos)
        total_custom_methods = sum(len(doc.custom_methods) for doc in document_infos)
        
        # 统计集合信息
        collections = [doc.collection_name for doc in document_infos if doc.collection_name]
        
        self.logger.info("=== 生成统计信息 ===")
        self.logger.info(f"文档模型: {len(document_infos)}个")
        self.logger.info(f"总字段数: {total_fields}个")
        self.logger.info(f"自定义方法: {total_custom_methods}个")
        self.logger.info(f"集合: {len(set(collections))}个")
        self.logger.info(f"Repository文件: {len(repo_files)}个")
        
        # 显示生成的文件
        for repo_file in repo_files:
            file_size = os.path.getsize(repo_file)
            self.logger.info(f"  - {repo_file} ({file_size} bytes)")


def parse_arguments() -> argparse.Namespace:
    """
    解析命令行参数
    
    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(
        description="数据仓库生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  %(prog)s --scan ./models/document
  %(prog)s --scan ./models/document --output ./models/repository
  %(prog)s --files user_document.py order_document.py  # 处理指定文件
  %(prog)s --no-preserve-custom                        # 不保留自定义方法
        """
    )
    
    # 扫描选项
    scan_group = parser.add_mutually_exclusive_group()
    scan_group.add_argument(
        "--scan", "-s",
        nargs="+",
        default=["models/document"],
        help="扫描目录列表 (默认: models/document)"
    )
    scan_group.add_argument(
        "--files", "-f",
        nargs="+",
        help="指定要处理的文件列表"
    )
    
    # 输出选项
    parser.add_argument(
        "--output", "-o",
        default="models/repository",
        help="输出目录路径 (默认: models/repository)"
    )
    
    # 功能选项
    parser.add_argument(
        "--no-preserve-custom",
        action="store_true",
        help="不保留自定义方法"
    )
    
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="不备份现有文件"
    )
    
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="不验证生成的文件"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出"
    )
    
    return parser.parse_args()


def create_config_from_args(args: argparse.Namespace) -> RepositoryGeneratorConfig:
    """
    从命令行参数创建配置
    
    Args:
        args: 命令行参数
        
    Returns:
        RepositoryGeneratorConfig: 生成器配置
    """
    config = RepositoryGeneratorConfig()
    
    # 设置扫描目录
    if args.scan:
        config.scan_dirs = args.scan
    
    # 设置输出目录
    config.output_dir = args.output
    
    # 设置其他配置
    config.preserve_custom = not args.no_preserve_custom
    config.backup = not args.no_backup
    config.validate = not args.no_validate
    config.verbose = args.verbose
    
    return config


def main():
    """主程序入口"""
    try:
        # 解析命令行参数
        args = parse_arguments()
        
        # 创建配置
        config = create_config_from_args(args)
        
        # 创建生成器
        generator = RepositoryCodeGenerator(config)
        
        # 执行生成
        success = False
        
        if args.files:
            # 处理指定文件
            success = generator.generate_from_specific_documents(args.files)
        else:
            # 扫描目录
            success = generator.generate_repository_files()
        
        # 返回结果
        return 0 if success else 1
        
    except KeyboardInterrupt:
        logger.info("用户中断操作")
        return 1
    except Exception as e:
        logger.error(f"程序执行失败: {str(e)}")
        return 1


if __name__ == "__main__":
    exit(main())