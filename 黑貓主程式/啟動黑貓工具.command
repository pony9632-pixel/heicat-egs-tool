#!/bin/bash
cd "$(dirname "$0")"
python3 app.py
osascript -e 'tell application "Terminal" to close (every window whose name contains "啟動黑貓工具")' & exit 0
