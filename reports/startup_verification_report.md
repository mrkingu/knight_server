# 框架启动验证报告
生成时间: 2025-07-09 02:29:00

## 验证摘要
- 总检查项: 6
- 通过检查: 0
- 失败检查: 6
- 成功率: 0.0%

## 详细结果
- **config_loading**: ❌ 失败
  - 错误详情: `cannot import name 'Config' from 'setting.config' (/home/runner/work/knight_server/knight_server/setting/config.py)`

- **database_connection**: ❌ 失败
  - 错误详情: `'RedisManager' object has no attribute '_pools'`

- **service_startup**: ❌ 失败
  - 错误详情: `cannot import name 'GateServer' from 'services.gate' (/home/runner/work/knight_server/knight_server/services/gate/__init__.py)`

- **message_codec**: ❌ 失败
  - 错误详情: `No module named 'zstd'`

- **core_functionality**: ❌ 失败
  - 错误详情: `LockConfig.__init__() got an unexpected keyword argument 'ttl'`

- **advanced_features**: ❌ 失败
  - 错误详情: `'EventualConsistencyManager' object has no attribute 'put_data'`

## 建议
❌ 部分验证失败，需要修复以下问题：
- 修复 config_loading
- 修复 database_connection
- 修复 service_startup
- 修复 message_codec
- 修复 core_functionality
- 修复 advanced_features