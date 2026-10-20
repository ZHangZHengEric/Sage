# Sage Kubernetes 部署

本目录仅部署 Sage Server v1 和 Web。环境仅支持 `dev`、`prod`；MySQL、S3 兼容存储及观测平台需单独部署。

## 组件与前置条件

- `sage-server`：后端 API，端口 `8080`
- `sage-web`：Web 静态资源和 nginx 代理，端口 `80`
- 已配置的 Kubernetes 集群和 `kubectl`
- 本地 Docker 以及目标节点的 containerd / `ctr`，用于构建和导入应用镜像
- 启用 Ingress 时需准备 Ingress Controller；默认使用 nginx 注解

Server 保留原有沙箱所需的 `SYS_ADMIN`、unconfined seccomp 和 AppArmor 配置。集群需允许这些配置，或使用远程沙箱。

## 配置与部署

复制目标环境的应用配置和 Kubernetes 配置：

```bash
cp app/v1/deploy/dev/.env.example app/v1/deploy/dev/.env
cp app/v1/deploy/k8s/env/dev.env.example app/v1/deploy/k8s/env/dev.env
# prod 使用 app/v1/deploy/prod/.env.example 和 app/v1/deploy/k8s/env/prod.env.example
```

应用配置中需填写外部 `SAGE_MYSQL_HOST`、`SAGE_MYSQL_PORT`、数据库账号、`SAGE_S3_ENDPOINT` 及其密钥，并修改管理员密码、JWT 和会话密钥。地址必须在集群 Pod 内可访问，模板中的示例域名需要替换。

Kubernetes 配置包括：

- `NAMESPACE`：默认由环境模板设置为 `sage-dev` 或 `sage-prod`
- `SAGE_HOST`、`SAGE_PUBLIC_URL`：对外访问域名/IP 和根地址
- `SAGE_WEB_SERVICE_TYPE`、`SAGE_WEB_NODE_PORT`：默认 NodePort，dev 为 `30151`、prod 为 `30080`
- `ENABLE_INGRESS`：默认 `false`；启用时可设置 `INGRESS_CLASS_NAME`、`TLS_SECRET_NAME`
- `IMAGE_REGISTRY`：可选镜像名前缀，不执行 push
- `IMAGE_PULL_POLICY`：无镜像前缀时默认 `Never`，有前缀时默认 `IfNotPresent`
- `K8S_IMAGE_TARGET`、`CTR_BIN`、`CTR_NAMESPACE`：默认 `ctr`、`ctr`、`k8s.io`

IP 地址配合 NodePort 时，`SAGE_PUBLIC_URL` 留空会使用 `http://<IP>:<NodePort>`；域名默认使用 HTTPS。IP 地址不生成 Ingress host 和 TLS host。

```bash
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh
DEPLOY_ENV=prod app/v1/deploy/k8s/scripts/deploy.sh
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh server
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh --service web
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh sage-server sage-web
```

脚本默认读取 `app/v1/deploy/<env>/.env` 和 `app/v1/deploy/k8s/env/<env>.env`，Kubernetes 配置不存在时使用对应 `.env.example`。可用 `ENV_FILE`、`K8S_ENV_FILE` 覆盖路径。默认环境为 `prod`。

镜像仅构建 `sage-server:latest`、`sage-web:latest`，通过 `docker save` 和 `ctr images import` 导入 containerd；指定服务时仅准备对应镜像。支持 `ctr` / `containerd` / `cri`，不执行 registry push，也不拉取基础服务镜像。设置 `IMAGE_REGISTRY` 时给应用镜像添加此前缀。已有镜像可使用 `--skip-images`。

部署流程依次创建 Namespace、Server 所需 ConfigMap/Secret、所选应用 Service 和 Deployment，以及可选的 Web Ingress，最后等待应用 rollout。

```bash
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh --recreate web
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh --redeploy
```

重建仅删除所选应用资源；Server PVC 默认保留，`DELETE_PVCS=true` 时允许删除 Server 的持久化声明。`pvcs/` 中仅保留 Server 模板，可按存储需求单独配置应用；`STORAGE_CLASS` 用于渲染这些模板。

## 访问与清理

Web 为 `${SAGE_PUBLIC_URL}/sage/`，API 健康检查为 `${SAGE_PUBLIC_URL}/prod-api/api/health`。

```bash
kubectl -n sage-dev logs -f deployment/sage-server
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/delete.sh
DELETE_PVCS=true DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/delete.sh
```

清理仅涉及 Sage Server、Web 及其配置，默认保留 Server PVC。独立部署的基础服务及其存储需由其所属部署管理。`DELETE_NAMESPACE=true` 会删除整个命名空间，仅应在命名空间专用于这两个应用时使用。

外部观测平台可通过应用配置中的 `SAGE_TRACE_JAEGER_URL`、`SAGE_TRACE_JAEGER_PUBLIC_URL` 接入；默认留空，Web Ingress 不再暴露 Jaeger 路径。
