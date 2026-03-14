#!/bin/bash
set -e

# 如果挂载的 skills 目录为空或不存在，则复制默认 skills
if [ -z "$(ls -A /app/skills 2>/dev/null)" ]; then
    echo "Initializing /app/skills with default skills..."
    cp -r /app/app/skills/* /app/skills/ 2>/dev/null || true
    echo "Skills initialized."
fi

# 执行主命令
exec python -m app.server.main "$@"
