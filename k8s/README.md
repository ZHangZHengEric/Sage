# Sage Kubernetes 部署

此目录提供一套与根目录 `docker-compose.yml` 对齐的 Kubernetes 全栈部署清单。资源从独立 Namespace 开始创建，所有持久化目录均使用单独 PVC，外部访问通过 Ingress 暴露。

## 组件

- `sage-server`: 后端 API，端口 `8080`
- `sage-web`: Web 静态资源与 nginx 反向代理，端口 `80`
- `sage-wiki`: Wiki 静态资源，端口 `80`
- `sage-mysql`: MySQL 8.4，使用 StatefulSet，端口 `3306`
- `sage-es`: 带 IK 插件的 Elasticsearch，端口 `9200`
- `sage-rustfs`: S3 兼容对象存储，端口 `9000` / `9001`
- `sage-jaeger`: Jaeger all-in-one，OTLP `4317` / `4318`，查询 UI `16686`

## 前置条件

- 可用 Kubernetes 集群
- `kubectl` 已配置到目标集群
- 可用 Ingress Controller，默认按 nginx ingress 生成注解
- 可用默认 StorageClass，或在 `.env` 中设置 `STORAGE_CLASS`
- 本地或 CI 环境有 Docker，用于构建 Sage 自有镜像

`sage-server` 沿用 compose 中的沙箱能力要求，Deployment 默认添加 `SYS_ADMIN` capability、unconfined seccomp 和 AppArmor 注解。若集群启用了严格 Pod Security Admission，需要为 `sage` namespace 配置例外，或改用远程沙箱配置。

## 配置

复制环境变量模板：

```bash
cp k8s/.env.example k8s/.env
```

至少修改：

- `SAGE_HOST`: 对外访问域名，例如 `sage.example.com`
- `SAGE_PUBLIC_URL`: 对外访问根地址，例如 `https://sage.example.com`
- `IMAGE_REGISTRY`: 私有镜像仓库地址；本地集群可留空
- `IMAGE_TAG`: 镜像标签
- `INGRESS_CLASS_NAME`: IngressClass 名称
- `TLS_SECRET_NAME`: 已存在的 TLS Secret 名称；留空则不启用 TLS
- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_MYSQL_PASSWORD`
- `SAGE_ELASTICSEARCH_PASSWORD`
- `SAGE_S3_SECRET_KEY`
- `SAGE_JWT_KEY`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`
- `SAGE_BOOTSTRAP_ADMIN_PASSWORD`

如果 `STORAGE_CLASS` 留空，PVC 使用集群默认 StorageClass。

## 构建并发布镜像

构建镜像，并自动发布到当前 `kubectl` 指向的集群可见的位置：

```bash
k8s/scripts/build-images.sh
```

默认行为：

- 如果设置了 `IMAGE_REGISTRY`，脚本会在构建后 `docker push` 到该仓库。
- 如果未设置 `IMAGE_REGISTRY`，脚本会按当前 `kubectl` context 自动识别 `kind`、`minikube`、`k3d` 或 Docker Desktop Kubernetes，并把镜像导入本地集群。

推送到私有镜像仓库：

```bash
IMAGE_REGISTRY=registry.example.com/sage k8s/scripts/build-images.sh
```

脚本会构建：

- `sage-server:${IMAGE_TAG}`
- `sage-web:${IMAGE_TAG}`
- `sage-wiki:${IMAGE_TAG}`
- `sage-es:${IMAGE_TAG}`

当 `IMAGE_REGISTRY` 非空时，镜像名会变为 `${IMAGE_REGISTRY}/sage-server:${IMAGE_TAG}` 等。

可用 `K8S_IMAGE_TARGET` 显式指定发布方式：

```bash
K8S_IMAGE_TARGET=registry IMAGE_REGISTRY=registry.example.com/sage k8s/scripts/build-images.sh
K8S_IMAGE_TARGET=kind k8s/scripts/build-images.sh
K8S_IMAGE_TARGET=minikube k8s/scripts/build-images.sh
K8S_IMAGE_TARGET=k3d K3D_CLUSTER_NAME=sage k8s/scripts/build-images.sh
K8S_IMAGE_TARGET=none k8s/scripts/build-images.sh
```

如果只想构建本地镜像、不发布或导入集群：

```bash
PUSH_IMAGES=false k8s/scripts/build-images.sh
```

## 部署

```bash
k8s/scripts/deploy.sh
```

脚本会按顺序创建：

1. Namespace
2. ConfigMap 和 Secret
3. PVC
4. Service
5. StatefulSet 和 Deployment
6. Ingress

部署完成后脚本会等待 MySQL StatefulSet 和所有 Deployment rollout，并输出 `pods,pvc,svc,ingress` 状态。

## 访问

默认入口：

- Web: `${SAGE_PUBLIC_URL}/sage/`
- API 健康检查: `${SAGE_PUBLIC_URL}/prod-api/api/health`
- Jaeger: `${SAGE_PUBLIC_URL}/jaeger/`
- Wiki: `${SAGE_PUBLIC_URL}/wiki/`

健康检查示例：

```bash
curl -sS "${SAGE_PUBLIC_URL}/prod-api/api/health"
kubectl -n "${NAMESPACE:-sage}" logs -f deployment/sage-server
```

## 清理

删除工作负载、服务、Ingress、ConfigMap 和 Secret，保留 PVC：

```bash
k8s/scripts/delete.sh
```

同时删除 PVC：

```bash
DELETE_PVCS=true k8s/scripts/delete.sh
```

同时删除 Namespace：

```bash
DELETE_PVCS=true DELETE_NAMESPACE=true k8s/scripts/delete.sh
```

默认保留 PVC，避免误删 MySQL、Elasticsearch、RustFS 和 Sage 工作数据。

## 静态校验

默认命名空间文件可直接校验：

```bash
kubectl apply --dry-run=client -f k8s/namespace.yaml
```

完整模板需要通过脚本渲染环境变量后应用。可先在测试集群运行：

```bash
k8s/scripts/deploy.sh
kubectl -n sage get pods,pvc,svc,ingress
```

## 注意事项

- MySQL 数据库 `SAGE_MYSQL_DATABASE` 由应用启动逻辑自动创建。
- MySQL、Elasticsearch、RustFS 和 Jaeger 的内部 Service 名称保持为 compose 中的服务名，应用配置无需改成 Kubernetes FQDN。
- `sage-web` 镜像构建时会写入 `VITE_SAGE_WEB_BASE_PATH=/sage/`，并通过镜像内 nginx 将 `/prod-api/api` 和 `/jaeger` 代理到后端与 Jaeger。
- Elasticsearch 的 `vm.max_map_count` 由 initContainer 尝试设置；若集群禁止 privileged initContainer，需要在节点层面预先设置。
