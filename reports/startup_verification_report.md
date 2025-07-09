# 框架启动验证报告
生成时间: 2025-07-09 02:41:44

## 验证摘要
- 总检查项: 6
- 通过检查: 4
- 失败检查: 2
- 成功率: 66.7%

## 详细结果
- **config_loading**: ❌ 失败
  - 错误详情: `cannot import name 'EnvManager' from 'setting.env_manager' (/home/runner/work/knight_server/knight_server/setting/env_manager.py)`

- **database_connection**: ✅ 通过

- **service_startup**: ✅ 通过

- **message_codec**: ✅ 通过

- **core_functionality**: ❌ 失败
  - 错误详情: `分布式锁释放失败`

- **advanced_features**: ✅ 通过

## 建议
❌ 部分验证失败，需要修复以下问题：
- 修复 config_loading
- 修复 core_functionality