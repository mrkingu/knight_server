#!/usr/bin/env python
"""
停止所有服务
"""
from server_launcher.launcher import ServerLauncher

if __name__ == "__main__":
    launcher = ServerLauncher()
    launcher.stop_all()