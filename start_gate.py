#!/usr/bin/env python3
"""
启动Gate服务
"""
import asyncio
from server_launcher.launcher import ServerLauncher

async def start_gate():
    launcher = ServerLauncher()
    await launcher.start(['gate'])

if __name__ == "__main__":
    asyncio.run(start_gate())