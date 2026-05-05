# Sage Kubernetes 部署

此目录提供一套与根目录 `docker-compose.yml` 对齐的 Kubernetes 全栈部署清单。资源从独立 Namespace 开始创建，所有持久化目录均使用单独 PVC，外部访问通过 Ingress 暴露。

## 组件

- `sage-server`: 后端 API，端口 `8080`
- `sage-web`: Web 静态资源与 nginx 反向代理，端口 `80`
- `sage-wiki`: Wiki 静态资源，端口 `80`
- `sage-mysql`: MySQL 8.4，使用 StatefulSet，端口 `3306`
- `sage-rustfs`: S3 兼容对象存储，端口 `9000` / `9001`
- `sage-jaeger`: Jaeger all-in-one，OTLP `4317` / `4318`，查询 UI `16686`

Elasticsearch 不再由这套 Kubernetes 清单内置部署。需要知识库检索能力时，请在 `.env` 中通过 `SAGE_ELASTICSEARCH_URL` 等变量接入外部 Elasticsearch。

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

- `SAGE_HOST`: 对外访问域名，例如 `sage.example.com`；如果临时用 IP，Ingress 会省略 host 规则
- `SAGE_PUBLIC_URL`: 对外访问根地址，例如 `https://sage.example.com`
- `IMAGE_REGISTRY`: 可选镜像名前缀；不会触发 registry push，只用于生成要导入 containerd 的镜像名
- `INGRESS_CLASS_NAME`: IngressClass 名称
- `TLS_SECRET_NAME`: 已存在的 TLS Secret 名称；留空则不启用 TLS。`SAGE_HOST` 为 IP 时会自动跳过 Ingress TLS host
- `ENABLE_INGRESS`: 是否创建 Ingress，默认 `false`
- `SAGE_WEB_NODE_PORT`: Web NodePort，默认 `30080`
- `SAGE_WIKI_NODE_PORT`: Wiki NodePort，默认 `30081`
- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_MYSQL_PASSWORD`
- `SAGE_ELASTICSEARCH_URL`: 可选，外部 Elasticsearch 地址；留空则跳过 ES 初始化
- `SAGE_S3_SECRET_KEY`
- `SAGE_JWT_KEY`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`
- `SAGE_BOOTSTRAP_ADMIN_PASSWORD`

如果 `SAGE_HOST` 是 IP 地址且 Web Service 使用 NodePort，`SAGE_PUBLIC_URL` 留空时会默认使用 `http://<IP>:${SAGE_WEB_NODE_PORT}`；如果是域名，则默认使用 `https://<域名>`。

## 镜像准备与部署

`deploy.sh` 会先准备所选服务需要的镜像，再部署 Kubernetes 资源：

```bash
k8s/scripts/deploy.sh
```

镜像准备规则：

- `server` / `web` / `wiki`: 先本地 `docker build`，再用 `docker save` 和 `ctr -n k8s.io images import` 导入 containerd。
- `mysql` / `rustfs` / `jaeger`: 先用 `ctr -n k8s.io images pull` 拉取外部镜像，再部署。
- 默认 `K8S_IMAGE_TARGET=ctr`、`CTR_NAMESPACE=k8s.io`，可通过 `.env` 或环境变量覆盖。
- Sage 自有镜像固定显式打 `latest` tag，不通过 `.env` 或环境变量配置。
- 脚本只支持 `ctr` / `containerd` / `cri` 导入，不会 `docker push`，也不会导入到 Docker Desktop、kind、minikube 或 k3d。
- 未设置 `IMAGE_REGISTRY` 时，containerd 可能以规范名显示镜像，例如 `docker.io/library/sage-web:latest`；Kubernetes 中仍可使用 `sage-web:latest`。

部署一个或多个指定服务：

```bash
k8s/scripts/deploy.sh server
k8s/scripts/deploy.sh web wiki
k8s/scripts/deploy.sh --service mysql --service rustfs
k8s/scripts/deploy.sh sage-server sage-web
```

销毁所选服务后重新构建/拉取镜像并部署：

```bash
k8s/scripts/deploy.sh --recreate web
k8s/scripts/deploy.sh --redeploy
```

默认保留 PVC；如需同时清理持久化数据：

```bash
DELETE_PVCS=true k8s/scripts/deploy.sh --recreate mysql rustfs server
```

如果需要镜像名前缀，可设置 `IMAGE_REGISTRY`；它只改变镜像名，不会 push：

```bash
IMAGE_REGISTRY=registry.example.com/sage k8s/scripts/deploy.sh
IMAGE_REGISTRY=registry.example.com/sage k8s/scripts/deploy.sh web
```

全量模式会构建：

- `sage-server:latest`
- `sage-web:latest`
- `sage-wiki:latest`

当 `IMAGE_REGISTRY` 非空时，镜像名会变为 `${IMAGE_REGISTRY}/sage-server:latest` 等，并同样通过 `ctr` 导入。`crictl images` 通常对应 `k8s.io`；如果只想让 `ctr -n sage images list` 能看到镜像，可设置 `CTR_NAMESPACE=sage`，但 kubelet 是否能直接使用取决于节点实际 CRI namespace。

可用服务名：

- `server` / `sage-server`
- `web` / `sage-web`
- `wiki` / `sage-wiki`
- `mysql` / `sage-mysql`
- `rustfs` / `sage-rustfs`
- `jaeger` / `sage-jaeger`
- `all`，默认值，部署全部服务

指定服务部署时，脚本不会自动部署其它业务服务依赖；例如 `k8s/scripts/deploy.sh server` 只会部署 `sage-server` 及其必需的 ConfigMap、Secret、Service 和 Deployment，不会自动部署 MySQL、RustFS、Jaeger、Web 或 Wiki。

全量部署时，脚本会按顺序创建：

1. 准备镜像：自有镜像构建并导入 containerd，外部镜像拉取到 containerd
2. Namespace
3. ConfigMap 和 Secret
4. Service
5. StatefulSet 和 Deployment
6. Ingress（仅 `ENABLE_INGRESS=true` 时）

部署完成后脚本会等待 MySQL StatefulSet 和所有 Deployment rollout，并输出 `pods,svc` 状态。

## 访问

默认入口：

- Web: `${SAGE_PUBLIC_URL}/sage/`，默认 `http://${SAGE_HOST}:30080/sage/`
- API 健康检查: `${SAGE_PUBLIC_URL}/prod-api/api/health`
- Jaeger: `${SAGE_PUBLIC_URL}/jaeger/`
- Wiki: `http://${SAGE_HOST}:30081/`

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

默认保留 PVC，避免误删 MySQL、RustFS 和 Sage 工作数据。

## 静态校验

默认命名空间文件可直接校验：

```bash
kubectl apply --dry-run=client -f k8s/namespace.yaml
```

完整模板需要通过脚本渲染环境变量后应用。可先在测试集群运行：

```bash
k8s/scripts/deploy.sh
kubectl -n sage get pods,svc
```

## 注意事项

- MySQL 数据库 `SAGE_MYSQL_DATABASE` 由应用启动逻辑自动创建。
- MySQL、RustFS 和 Jaeger 的内部 Service 名称保持为 compose 中的服务名，应用配置无需改成 Kubernetes FQDN。
- `sage-web` 镜像构建时会写入 `VITE_SAGE_WEB_BASE_PATH=/sage/`，并通过镜像内 nginx 将 `/prod-api/api` 和 `/jaeger` 代理到后端与 Jaeger。
