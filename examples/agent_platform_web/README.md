# Vue 3 + Vite

docker build -f docker/Dockerfile -t sage-web:latest .

docker run -d \
  --name agent-platform-web \
  -p 30051:80 \
  sage-web:latest