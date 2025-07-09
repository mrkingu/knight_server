#!/usr/bin/env python
"""
查看服务状态
"""
from server_launcher.launcher import ServerLauncher

if __name__ == "__main__":
    launcher = ServerLauncher()
    launcher.status()