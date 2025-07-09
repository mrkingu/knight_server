#!/usr/bin/env python3
"""
启动Chat服务
"""
import asyncio
from server_launcher.launcher import ServerLauncher

async def start_chat():
    launcher = ServerLauncher()
    await launcher.start(['chat'])

if __name__ == "__main__":
    asyncio.run(start_chat())