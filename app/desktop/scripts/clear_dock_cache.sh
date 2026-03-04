#!/bin/bash
# 清理 macOS Dock 图标缓存

echo "清理 Dock 图标缓存..."

# 清理系统图标缓存
sudo rm -rf /Library/Caches/com.apple.iconservices.store
sudo rm -rf /Users/$(whoami)/Library/Caches/com.apple.iconservices.store

# 清理 Dock 缓存
rm -rf ~/Library/Caches/Dock

# 重启 Dock
killall Dock

echo "Dock 缓存已清理，请重新启动应用查看效果"
