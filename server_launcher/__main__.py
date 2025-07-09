#!/usr/bin/env python3
"""
服务启动器主入口模块

支持通过 python -m server_launcher 方式启动
"""

import sys
import asyncio
from .launcher import main

if __name__ == "__main__":
    asyncio.run(main())