# Knight Server YAML Configuration System

## Overview

This refactored system provides unified YAML configuration management for all Knight Server services. The CLI-based startup has been replaced with simple Python script execution.

## Key Features

✅ **Single Configuration File**: All service configurations are centralized in `setting/config.yml`  
✅ **Environment Variable Override**: Use `GAME_*` environment variables to override config values  
✅ **Service Instance Management**: Configure multiple instances per service  
✅ **Startup Order Control**: Define service startup and shutdown order  
✅ **Redis Bucket Configuration**: Built-in Redis data sharding support  
✅ **No CLI Dependencies**: Direct Python script execution  
✅ **Monitoring Integration**: Health checks and process monitoring retained  

## Usage

### Basic Service Startup

```bash
# Start all services in configured order
python start_server.py

# Start specific services
python start_gate.py
python start_logic.py
python start_chat.py
python start_fight.py
```

### Environment Variable Overrides

```bash
# Override log level
GAME_COMMON_LOG_LEVEL=debug python start_server.py

# Override Redis host
GAME_DATABASE_REDIS_HOST=production-redis python start_gate.py

# Override MongoDB settings
GAME_DATABASE_MONGODB_DB=production_db python start_server.py

# Multiple overrides
GAME_COMMON_LOG_LEVEL=info GAME_DATABASE_REDIS_PORT=6380 python start_server.py
```

### Configuration Structure

The main configuration file `setting/config.yml` contains:

- **Environment settings**: `development`, `testing`, `production`
- **Common settings**: Logging, directories, retention policies
- **Database settings**: Redis and MongoDB with connection pooling
- **Service registry**: etcd/consul configuration
- **Celery settings**: Task queue configuration
- **Launcher settings**: Startup order, health checks, auto-restart
- **Service configurations**: Individual service instances and settings
- **Monitoring settings**: Prometheus, alerting, performance monitoring

### Service Configuration Example

```yaml
services:
  gate:
    instances:
      - port: 8000
        name: gate-8000
      - port: 8001
        name: gate-8001
    settings:
      workers: 1
      access_log: true
      websocket_max_size: 1048576
    startup_interval: 1.0
```

### Redis Bucket Configuration

```yaml
database:
  redis:
    bucket_config:
      total_buckets: 16
      default_bucket: 0
      bucket_strategy: "hash"
      buckets:
        0: {db: 0, prefix: "bucket_0"}
        1: {db: 1, prefix: "bucket_1"}
        # ... additional buckets
```

## Code Usage

### Accessing Configuration

```python
from setting import config

# Get simple values
log_level = config.get('common.log_level')
redis_host = config.get('database.redis.host')

# Get complex configurations
gate_config = config.get_service_config('gate')
redis_config = config.get_database_config('redis')

# Get service instances
gate_instances = config.get_service_instances('gate')
```

### Service Configuration in Code

```python
# Example: Redis Manager
from setting import config

def load_redis_config():
    redis_config = config.get_database_config('redis')
    return {
        'host': redis_config.get('host', 'localhost'),
        'port': redis_config.get('port', 6379),
        'bucket_config': redis_config.get('bucket_config', {})
    }
```

## Migration from CLI

The old CLI-based launcher has been replaced with direct script execution:

### Before (CLI-based)
```bash
python -m server_launcher start --service gate
python -m server_launcher start --all
```

### After (Script-based)
```bash
python start_gate.py
python start_server.py
```

## Benefits

1. **Simplified Deployment**: No CLI argument parsing, just run scripts
2. **Centralized Configuration**: All settings in one YAML file
3. **Environment Flexibility**: Easy configuration override for different environments
4. **Better Maintainability**: Clear separation of concerns
5. **Docker-Friendly**: Environment variables work seamlessly in containers
6. **IDE-Friendly**: Direct script execution works better with IDEs and debuggers

## Files Changed

- `setting/config.yml` - Main configuration file
- `setting/config_loader.py` - Configuration loader
- `setting/__init__.py` - Updated to export config instance
- `server_launcher/launcher.py` - Simplified launcher (CLI removed)
- `start_*.py` - Individual service startup scripts
- `common/db/redis_manager.py` - Updated to use unified config
- `common/db/mongo_manager.py` - Updated to use unified config

## Environment Variables

All configuration values can be overridden using environment variables with the `GAME_` prefix:

| Environment Variable | Configuration Path | Example |
|---------------------|-------------------|---------|
| `GAME_COMMON_LOG_LEVEL` | `common.log_level` | `debug` |
| `GAME_DATABASE_REDIS_HOST` | `database.redis.host` | `redis.example.com` |
| `GAME_DATABASE_MONGODB_DB` | `database.mongodb.db` | `production_db` |
| `GAME_SERVICES_GATE_INSTANCES_0_PORT` | `services.gate.instances.0.port` | `8080` |

## Future Enhancements

- Configuration validation with schema
- Hot configuration reload
- Configuration templates for different environments
- Kubernetes ConfigMap integration
- Service discovery integration