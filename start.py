#!/usr/bin/env python
"""
快速启动脚本
直接运行此脚本启动所有服务
"""
from server_launcher.launcher import ServerLauncher

if __name__ == "__main__":
    launcher = ServerLauncher()
    launcher.start_all()