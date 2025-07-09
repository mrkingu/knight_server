"""
Repository类生成工具主入口
使用方法：
1. 修改下面的配置变量设置输入输出路径
2. 直接运行: python generator_main.py
"""

# ========== 配置区域 - 根据需要修改 ==========
# Document类文件扫描目录
DOCUMENT_SOURCE_DIR = "../document/"

# Repository类输出目录
REPOSITORY_OUTPUT_DIR = "../repository/"

# Document类的导入路径前缀
DOCUMENT_IMPORT_PREFIX = "models.document"

# Repository基类的导入路径
REPOSITORY_BASE_IMPORT = "common.db.base_repository"

# 是否生成Repository的__init__.py文件
GENERATE_INIT_FILE = True

# 是否为每个Repository生成单独的文件
SEPARATE_FILES = True

# 是否覆盖已存在的文件
OVERWRITE_EXISTING = True

# ========== 配置结束 ==========

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from models.gen_utils.document_scanner import DocumentScanner
from models.gen_utils.repository_generator import RepositoryGenerator
from common.logger import logger


def main():
    """主函数 - 执行Document到Repository类的生成"""
    logger.info("=" * 60)
    logger.info("开始执行Repository类生成")
    logger.info(f"Document源目录: {DOCUMENT_SOURCE_DIR}")
    logger.info(f"Repository输出目录: {REPOSITORY_OUTPUT_DIR}")
    logger.info("=" * 60)
    
    # 确保输出目录存在
    os.makedirs(REPOSITORY_OUTPUT_DIR, exist_ok=True)
    
    # 初始化组件
    scanner = DocumentScanner(scan_dirs=[DOCUMENT_SOURCE_DIR])
    generator = RepositoryGenerator(output_dir=REPOSITORY_OUTPUT_DIR)
    
    # 扫描Document文件
    document_files = list(Path(DOCUMENT_SOURCE_DIR).glob("*.py"))
    # 排除__init__.py
    document_files = [f for f in document_files if f.name != "__init__.py"]
    
    if not document_files:
        logger.warning(f"未在 {DOCUMENT_SOURCE_DIR} 目录下找到Document文件")
        return
    
    logger.info(f"找到 {len(document_files)} 个Document文件")
    
    # 收集所有Document类信息
    document_classes = []
    
    for doc_file in document_files:
        try:
            logger.info(f"\n扫描文件: {doc_file.name}")
            
            # 扫描文件中的Document类
            classes = scanner._scan_python_file(str(doc_file))
            
            for class_info in classes:
                if hasattr(class_info, 'is_document') and class_info.is_document:
                    document_classes.append({
                        'name': class_info.name,
                        'module_name': doc_file.stem,
                        'fields': getattr(class_info, 'fields', []),
                        'custom_methods': getattr(class_info, 'custom_methods', [])
                    })
                    logger.info(f"  ✓ 发现Document类: {class_info.name}")
                    
        except Exception as e:
            logger.error(f"扫描文件 {doc_file.name} 时出错: {e}")
            continue
    
    if not document_classes:
        logger.warning("未找到任何Document类")
        return
    
    # 生成Repository类
    generated_files = []
    
    if SEPARATE_FILES:
        # 为每个Document生成单独的Repository文件
        for doc_class in document_classes:
            try:
                repo_file = os.path.join(REPOSITORY_OUTPUT_DIR, f"{doc_class['name'].lower()}_repository.py")
                generator.generate_repository_file(doc_class, repo_file)
                generated_files.append(repo_file)
                logger.info(f"✓ 生成Repository: {repo_file}")
                
            except Exception as e:
                logger.error(f"生成 {doc_class['name']}Repository 时出错: {e}")
                
    else:
        # 生成单个包含所有Repository的文件
        all_repo_file = os.path.join(REPOSITORY_OUTPUT_DIR, "repositories.py")
        generator.generate_all_repositories(document_classes, all_repo_file)
        generated_files.append(all_repo_file)
        logger.info(f"✓ 生成所有Repository: {all_repo_file}")
    
    # 生成__init__.py文件
    if GENERATE_INIT_FILE:
        init_file = os.path.join(REPOSITORY_OUTPUT_DIR, "__init__.py")
        generator.generate_init_file(document_classes, init_file)
        logger.info(f"✓ 生成__init__.py: {init_file}")
    
    # 生成使用示例
    example_file = os.path.join(REPOSITORY_OUTPUT_DIR, "example_usage.py")
    generator.generate_usage_example(document_classes, example_file)
    logger.info(f"✓ 生成使用示例: {example_file}")
    
    logger.info("=" * 60)
    logger.info(f"Repository生成完成!")
    logger.info(f"  - 生成了 {len(document_classes)} 个Repository类")
    logger.info(f"  - 输出了 {len(generated_files)} 个文件")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()