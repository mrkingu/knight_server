# 框架启动验证报告
生成时间: 2025-07-09 02:37:41

## 验证摘要
- 总检查项: 6
- 通过检查: 1
- 失败检查: 5
- 成功率: 16.7%

## 详细结果
- **config_loading**: ❌ 失败
  - 错误详情: `cannot import name 'EnvManager' from 'setting.env_manager' (/home/runner/work/knight_server/knight_server/setting/env_manager.py)`

- **database_connection**: ❌ 失败
  - 错误详情: `type object 'MongoManager' has no attribute 'create_instance'`

- **service_startup**: ✅ 通过

- **message_codec**: ❌ 失败
  - 错误详情: `[1007] unique_id 格式无效: badly formed hexadecimal UUID string`

- **core_functionality**: ❌ 失败
  - 错误详情: `分布式锁释放失败`

- **advanced_features**: ❌ 失败
  - 错误详情: `cannot import name 'TransactionManager' from 'common.distributed.transaction' (/home/runner/work/knight_server/knight_server/common/distributed/transaction.py)`

## 建议
❌ 部分验证失败，需要修复以下问题：
- 修复 config_loading
- 修复 database_connection
- 修复 message_codec
- 修复 core_functionality
- 修复 advanced_features