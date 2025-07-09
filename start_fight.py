#!/usr/bin/env python
"""
启动Fight服务
"""
import asyncio
from server_launcher.launcher_new import ServerLauncher

async def start_fight():
    launcher = ServerLauncher()
    await launcher.start(['fight'])

if __name__ == "__main__":
    asyncio.run(start_fight())