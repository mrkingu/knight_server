#!/usr/bin/env python3
"""
启动Logic服务
"""
import asyncio
from server_launcher.launcher import ServerLauncher

async def start_logic():
    launcher = ServerLauncher()
    await launcher.start(['logic'])

if __name__ == "__main__":
    asyncio.run(start_logic())