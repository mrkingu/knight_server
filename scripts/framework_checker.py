#!/usr/bin/env python3
"""
框架完整性检查脚本
用于验证整个框架的实现质量

该脚本会检查：
1. 文件结构完整性
2. 模块导入能力
3. 重复逻辑实现
4. 模块依赖关系
5. 代码质量问题
"""

import os
import sys
import ast
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict
import time
import re


class FrameworkChecker:
    """框架完整性检查器"""
    
    def __init__(self, base_path: Optional[str] = None):
        """
        初始化检查器
        
        Args:
            base_path: 项目根目录，默认为当前目录
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.issues: List[Dict[str, Any]] = []  # 发现的问题
        self.warnings: List[Dict[str, Any]] = []  # 警告信息
        self.duplicates: List[Dict[str, Any]] = []  # 重复实现
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)  # 模块依赖关系
        self.import_errors: List[Dict[str, Any]] = []  # 导入错误
        
        # 预期的文件结构
        self.expected_structure = {
            'common': [
                '__init__.py', 'logger', 'db', 'proto', 'utils', 'grpc',
                'distributed', 'monitor', 'security', 'decorator', 'notify',
                'celery', 'registry', 'table'
            ],
            'services': [
                '__init__.py', 'base', 'gate', 'logic', 'chat', 'fight'
            ],
            'server_launcher': [
                '__init__.py', 'launcher.py', 'service_manager.py', 
                'process_monitor.py', 'health_checker.py', 'service_config.py',
                'process_pool.py', 'banner.py', 'cli.py', 'utils.py', '__main__.py'
            ],
            'setting': [
                '__init__.py', 'config.py', 'development.py', 'production.py',
                'env_manager.py', 'server_config'
            ],
            'proto': [
                '__init__.py', 'class_data', 'gen_utils', 'proto'
            ],
            'scripts': [
                '__init__.py'
            ],
            'tests': [
                '__init__.py'
            ]
        }
        
    def check_file_structure(self) -> bool:
        """检查文件结构完整性"""
        print("🔍 检查文件结构完整性...")
        
        structure_ok = True
        
        # 检查主要目录
        for directory, expected_files in self.expected_structure.items():
            dir_path = self.base_path / directory
            
            if not dir_path.exists():
                self.issues.append({
                    'type': 'missing_directory',
                    'severity': 'error',
                    'message': f'缺少目录: {directory}',
                    'path': str(dir_path)
                })
                structure_ok = False
                continue
            
            # 检查目录中的文件
            for expected_file in expected_files:
                file_path = dir_path / expected_file
                
                if not file_path.exists() and not (dir_path / expected_file).is_dir():
                    self.issues.append({
                        'type': 'missing_file',
                        'severity': 'error',
                        'message': f'缺少文件: {directory}/{expected_file}',
                        'path': str(file_path)
                    })
                    structure_ok = False
                else:
                    print(f"  ✓ {directory}/{expected_file}")
        
        # 检查关键配置文件
        config_files = ['requirements.txt', 'README.md', 'server_launcher_config.yaml']
        for config_file in config_files:
            file_path = self.base_path / config_file
            if not file_path.exists():
                self.warnings.append({
                    'type': 'missing_config',
                    'severity': 'warning',
                    'message': f'缺少配置文件: {config_file}',
                    'path': str(file_path)
                })
            else:
                print(f"  ✓ {config_file}")
        
        return structure_ok
    
    def check_imports(self) -> bool:
        """检查所有模块能否正常导入"""
        print("\n📦 检查模块导入...")
        
        # 将项目根目录添加到 sys.path
        if str(self.base_path) not in sys.path:
            sys.path.insert(0, str(self.base_path))
        
        import_ok = True
        
        # 要检查的核心模块
        core_modules = [
            'common.logger',
            'common.db',
            'common.proto',
            'common.utils',
            'common.grpc',
            'common.distributed',
            'services.base',
            'server_launcher.launcher',
            'server_launcher.service_manager',
            'setting.config'
        ]
        
        for module_name in core_modules:
            try:
                module = importlib.import_module(module_name)
                print(f"  ✓ {module_name}")
                
                # 检查模块是否有预期的导出
                if hasattr(module, '__all__'):
                    exports = getattr(module, '__all__')
                    if not exports:
                        self.warnings.append({
                            'type': 'empty_exports',
                            'severity': 'warning',
                            'message': f'模块 {module_name} 的 __all__ 为空',
                            'path': module_name
                        })
                else:
                    self.warnings.append({
                        'type': 'no_exports',
                        'severity': 'warning',
                        'message': f'模块 {module_name} 没有定义 __all__',
                        'path': module_name
                    })
                
            except Exception as e:
                self.import_errors.append({
                    'type': 'import_error',
                    'severity': 'error',
                    'message': f'导入模块 {module_name} 失败: {str(e)}',
                    'path': module_name,
                    'error': str(e)
                })
                print(f"  ✗ {module_name}: {str(e)}")
                import_ok = False
        
        return import_ok
    
    def check_duplicate_logic(self) -> bool:
        """检查重复的逻辑实现"""
        print("\n🔄 检查重复逻辑...")
        
        # 扫描所有Python文件
        py_files = list(self.base_path.rglob("*.py"))
        
        # 记录类名、函数名和它们的位置
        class_names = defaultdict(list)
        function_names = defaultdict(list)
        
        for py_file in py_files:
            if 'test' in str(py_file) or '__pycache__' in str(py_file):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # 解析AST
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        class_names[node.name].append(str(py_file))
                    elif isinstance(node, ast.FunctionDef):
                        function_names[node.name].append(str(py_file))
                        
            except Exception as e:
                self.warnings.append({
                    'type': 'parse_error',
                    'severity': 'warning',
                    'message': f'解析文件 {py_file} 时出错: {str(e)}',
                    'path': str(py_file)
                })
        
        # 检查重复的类名
        duplicate_found = False
        for class_name, locations in class_names.items():
            if len(locations) > 1:
                # 过滤掉一些合理的重复（如测试文件）
                filtered_locations = [loc for loc in locations if 'test' not in loc.lower()]
                if len(filtered_locations) > 1:
                    self.duplicates.append({
                        'type': 'duplicate_class',
                        'severity': 'warning',
                        'message': f'发现重复类名: {class_name}',
                        'locations': filtered_locations
                    })
                    print(f"  ⚠️  重复类名: {class_name} 在 {len(filtered_locations)} 个文件中")
                    duplicate_found = True
        
        # 检查重复的函数名（只检查可能重复的关键函数）
        key_functions = ['initialize', 'setup', 'configure', 'start', 'stop', 'close']
        for func_name in key_functions:
            if func_name in function_names:
                locations = function_names[func_name]
                if len(locations) > 3:  # 如果超过3个文件都有相同的关键函数名
                    self.duplicates.append({
                        'type': 'duplicate_function',
                        'severity': 'info',
                        'message': f'关键函数 {func_name} 在多个文件中定义',
                        'locations': locations[:5]  # 只显示前5个
                    })
        
        if not duplicate_found:
            print("  ✓ 未发现明显的重复逻辑")
        
        return not duplicate_found
    
    def check_dependencies(self) -> bool:
        """检查模块依赖关系"""
        print("\n🔗 检查模块依赖关系...")
        
        # 扫描所有Python文件分析import语句
        py_files = list(self.base_path.rglob("*.py"))
        
        for py_file in py_files:
            if '__pycache__' in str(py_file):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                tree = ast.parse(content)
                
                # 获取相对于项目根目录的模块路径
                relative_path = py_file.relative_to(self.base_path)
                module_path = str(relative_path.with_suffix(''))
                if module_path.endswith('/__init__'):
                    module_path = module_path[:-9]
                module_path = module_path.replace('/', '.')
                
                # 分析import语句
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith('common.') or alias.name.startswith('services.'):
                                self.dependencies[module_path].add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and (node.module.startswith('common.') or node.module.startswith('services.')):
                            self.dependencies[module_path].add(node.module)
                            
            except Exception as e:
                self.warnings.append({
                    'type': 'dependency_parse_error',
                    'severity': 'warning',
                    'message': f'分析依赖关系时出错: {py_file} - {str(e)}',
                    'path': str(py_file)
                })
        
        # 检查循环依赖
        circular_deps = self._detect_circular_dependencies()
        
        if circular_deps:
            for cycle in circular_deps:
                self.issues.append({
                    'type': 'circular_dependency',
                    'severity': 'error',
                    'message': f'发现循环依赖: {" -> ".join(cycle)}',
                    'cycle': cycle
                })
                print(f"  ✗ 循环依赖: {' -> '.join(cycle)}")
        else:
            print("  ✓ 未发现循环依赖")
        
        return len(circular_deps) == 0
    
    def _detect_circular_dependencies(self) -> List[List[str]]:
        """检测循环依赖"""
        visited = set()
        rec_stack = set()
        cycles = []
        
        def dfs(node, path):
            if node in rec_stack:
                # 找到循环
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return
            
            if node in visited:
                return
            
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in self.dependencies.get(node, []):
                dfs(neighbor, path + [node])
            
            rec_stack.remove(node)
        
        for node in self.dependencies.keys():
            if node not in visited:
                dfs(node, [])
        
        return cycles
    
    def check_code_quality(self) -> bool:
        """检查代码质量"""
        print("\n🔍 检查代码质量...")
        
        py_files = list(self.base_path.rglob("*.py"))
        quality_issues = []
        
        for py_file in py_files:
            if '__pycache__' in str(py_file) or 'test' in str(py_file):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.splitlines()
                    
                # 检查未实现的方法
                for i, line in enumerate(lines):
                    line_stripped = line.strip()
                    if line_stripped == 'pass' or line_stripped == 'raise NotImplementedError':
                        # 检查是否在函数或方法中
                        if i > 0:
                            prev_lines = lines[max(0, i-5):i]
                            if any('def ' in prev_line for prev_line in prev_lines):
                                quality_issues.append({
                                    'type': 'unimplemented_method',
                                    'severity': 'warning',
                                    'message': f'未实现的方法: {py_file}:{i+1}',
                                    'file': str(py_file),
                                    'line': i+1
                                })
                    
                    # 检查TODO注释
                    if 'TODO' in line_stripped or 'FIXME' in line_stripped:
                        quality_issues.append({
                            'type': 'todo_comment',
                            'severity': 'info',
                            'message': f'TODO注释: {py_file}:{i+1}',
                            'file': str(py_file),
                            'line': i+1
                        })
                    
                    # 检查中文注释（确保有适当的中文文档）
                    if line_stripped.startswith('"""') and not any(ord(c) > 127 for c in line_stripped):
                        quality_issues.append({
                            'type': 'missing_chinese_doc',
                            'severity': 'info',
                            'message': f'缺少中文文档: {py_file}:{i+1}',
                            'file': str(py_file),
                            'line': i+1
                        })
                        
            except Exception as e:
                self.warnings.append({
                    'type': 'quality_check_error',
                    'severity': 'warning',
                    'message': f'检查代码质量时出错: {py_file} - {str(e)}',
                    'path': str(py_file)
                })
        
        # 统计质量问题
        unimplemented_count = len([q for q in quality_issues if q['type'] == 'unimplemented_method'])
        todo_count = len([q for q in quality_issues if q['type'] == 'todo_comment'])
        
        print(f"  📊 质量检查结果:")
        print(f"     - 未实现方法: {unimplemented_count}")
        print(f"     - TODO注释: {todo_count}")
        
        if unimplemented_count > 0:
            self.warnings.extend([q for q in quality_issues if q['type'] == 'unimplemented_method'])
        
        return unimplemented_count < 10  # 如果未实现方法少于10个，认为质量可接受
    
    def generate_report(self) -> str:
        """生成检查报告"""
        report = []
        report.append("# 框架完整性检查报告")
        report.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"项目路径: {self.base_path}")
        report.append("")
        
        # 统计信息
        total_issues = len(self.issues)
        total_warnings = len(self.warnings)
        total_duplicates = len(self.duplicates)
        total_import_errors = len(self.import_errors)
        
        report.append("## 检查摘要")
        report.append(f"- 🔴 错误: {total_issues}")
        report.append(f"- 🟡 警告: {total_warnings}")
        report.append(f"- 🔄 重复: {total_duplicates}")
        report.append(f"- 📦 导入错误: {total_import_errors}")
        report.append("")
        
        # 详细问题
        if self.issues:
            report.append("## 🔴 发现的问题")
            for issue in self.issues:
                report.append(f"- **{issue['type']}**: {issue['message']}")
                if 'path' in issue:
                    report.append(f"  - 路径: `{issue['path']}`")
                report.append("")
        
        if self.warnings:
            report.append("## 🟡 警告信息")
            for warning in self.warnings:
                report.append(f"- **{warning['type']}**: {warning['message']}")
                if 'path' in warning:
                    report.append(f"  - 路径: `{warning['path']}`")
                report.append("")
        
        if self.duplicates:
            report.append("## 🔄 重复实现")
            for duplicate in self.duplicates:
                report.append(f"- **{duplicate['type']}**: {duplicate['message']}")
                if 'locations' in duplicate:
                    for loc in duplicate['locations']:
                        report.append(f"  - `{loc}`")
                report.append("")
        
        if self.import_errors:
            report.append("## 📦 导入错误")
            for error in self.import_errors:
                report.append(f"- **{error['path']}**: {error['message']}")
                report.append("")
        
        # 依赖关系分析
        if self.dependencies:
            report.append("## 🔗 模块依赖关系")
            for module, deps in self.dependencies.items():
                if deps:
                    report.append(f"- `{module}` 依赖:")
                    for dep in sorted(deps):
                        report.append(f"  - `{dep}`")
                    report.append("")
        
        # 建议
        report.append("## 💡 改进建议")
        if total_issues > 0:
            report.append("1. 优先修复所有错误级别的问题")
        if total_import_errors > 0:
            report.append("2. 解决导入错误，确保所有模块能正常导入")
        if total_duplicates > 0:
            report.append("3. 检查并合并重复的实现")
        if total_warnings > 5:
            report.append("4. 处理警告信息，提高代码质量")
        
        report.append("")
        report.append("## 总结")
        if total_issues == 0 and total_import_errors == 0:
            report.append("✅ 框架整体结构良好，可以正常运行")
        else:
            report.append("❌ 发现问题需要修复，建议优先处理错误级别的问题")
        
        return "\n".join(report)
    
    def run_full_check(self) -> bool:
        """运行完整检查"""
        print("🚀 开始框架完整性检查")
        print("=" * 50)
        
        # 执行所有检查
        structure_ok = self.check_file_structure()
        imports_ok = self.check_imports()
        duplicates_ok = self.check_duplicate_logic()
        dependencies_ok = self.check_dependencies()
        quality_ok = self.check_code_quality()
        
        # 生成报告
        report = self.generate_report()
        
        # 保存报告
        reports_dir = self.base_path / "reports"
        reports_dir.mkdir(exist_ok=True)
        
        report_file = reports_dir / "framework_check_report.md"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"\n📄 检查报告已保存到: {report_file}")
        
        # 总结
        all_checks_passed = all([structure_ok, imports_ok, duplicates_ok, dependencies_ok, quality_ok])
        
        print("\n" + "=" * 50)
        if all_checks_passed:
            print("🎉 框架完整性检查通过!")
        else:
            print("⚠️  框架存在问题，请查看报告详情")
        
        return all_checks_passed


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="框架完整性检查工具")
    parser.add_argument("--path", "-p", default=".", help="项目根目录路径")
    parser.add_argument("--report", "-r", action="store_true", help="只生成报告")
    
    args = parser.parse_args()
    
    checker = FrameworkChecker(args.path)
    
    if args.report:
        # 只生成报告
        report = checker.generate_report()
        print(report)
    else:
        # 运行完整检查
        success = checker.run_full_check()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()