"""
Kubernetes 远程沙箱实现

通过创建 K8s Pod 实现沙箱隔离
"""

import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from .base import RemoteSandboxProvider
from ...interface import CommandResult, ExecutionResult, FileInfo
from ...config import MountPath

logger = logging.getLogger(__name__)


class KubernetesSandboxProvider(RemoteSandboxProvider):
    """Kubernetes 远程沙箱实现"""

    def __init__(
        self,
        sandbox_id: str,
        namespace: str = "default",
        image: str = "python:3.11-slim",
        timeout: timedelta = timedelta(minutes=30),
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        virtual_workspace: str = "/sage-workspace",
        resources: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            sandbox_id=sandbox_id,
            workspace_mount=workspace_mount,
            mount_paths=mount_paths,
            virtual_workspace=virtual_workspace,
            timeout=timeout,
        )
        self.namespace = namespace
        self.image = image
        self.resources = resources or {}
        self._pod_name = None
        self._k8s_client = None

    async def initialize(self) -> None:
        """在 K8s 中创建 Pod"""
        try:
            from kubernetes import client, config
        except ImportError:
            raise ImportError(
                "kubernetes package is required. "
                "Install with: pip install kubernetes"
            )

        # 加载 K8s 配置
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        self._k8s_client = client.CoreV1Api()

        # 创建 Pod
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"sage-sandbox-{self._sandbox_id}",
                "labels": {
                    "app": "sage-sandbox",
                    "sandbox-id": self._sandbox_id,
                },
            },
            "spec": {
                "containers": [
                    {
                        "name": "sandbox",
                        "image": self.image,
                        "command": ["sleep", "infinity"],
                        "resources": self.resources,
                    }
                ],
            },
        }

        # 添加卷挂载
        volumes = []
        volume_mounts = []

        if self.workspace_mount:
            volumes.append({
                "name": "workspace",
                "hostPath": {"path": self.workspace_mount},
            })
            volume_mounts.append({
                "name": "workspace",
                "mountPath": self._workspace_path,
            })

        for i, mp in enumerate(self.mount_paths):
            vol_name = f"mount-{i}"
            volumes.append({
                "name": vol_name,
                "hostPath": {"path": mp.host_path},
            })
            volume_mounts.append({
                "name": vol_name,
                "mountPath": mp.sandbox_path,
                "readOnly": mp.read_only,
            })

        if volumes:
            pod_manifest["spec"]["volumes"] = volumes
            pod_manifest["spec"]["containers"][0]["volumeMounts"] = volume_mounts

        # 创建 Pod
        pod = self._k8s_client.create_namespaced_pod(
            namespace=self.namespace,
            body=pod_manifest,
        )

        self._pod_name = pod.metadata.name
        self._is_initialized = True

        logger.info(f"KubernetesSandboxProvider: 创建 Pod {self._pod_name}")

    async def execute_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
        background: bool = False,
    ) -> CommandResult:
        """在 K8s Pod 中执行命令"""
        if not self._is_initialized:
            await self.initialize()

        from kubernetes import stream

        exec_command = ["/bin/sh", "-c", command]

        resp = stream.stream(
            self._k8s_client.connect_get_namespaced_pod_exec,
            self._pod_name,
            self.namespace,
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )

        return CommandResult(
            success=True,  # 简化处理
            stdout=resp,
            stderr="",
            return_code=0,
            execution_time=0,
        )

    async def execute_python(
        self,
        code: str,
        requirements: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """执行 Python 代码"""
        # 通过命令执行
        command = f"python -c '{code}'"
        result = await self.execute_command(command, workdir, timeout)
        return ExecutionResult(
            success=result.success,
            output=result.stdout,
            error=result.stderr if not result.success else None,
            execution_time=result.execution_time,
            installed_packages=requirements or [],
        )

    async def execute_javascript(
        self,
        code: str,
        packages: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """执行 JavaScript 代码"""
        command = f"node -e '{code}'"
        result = await self.execute_command(command, workdir, timeout)
        return ExecutionResult(
            success=result.success,
            output=result.stdout,
            error=result.stderr if not result.success else None,
            execution_time=result.execution_time,
            installed_packages=packages or [],
        )

    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """读取文件"""
        result = await self.execute_command(f"cat {path}")
        return result.stdout

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        mode: str = "overwrite",
    ) -> None:
        """写入文件"""
        escaped = content.replace("'", "'\\''")
        await self.execute_command(f"echo '{escaped}' > {path}")

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        result = await self.execute_command(f"test -f {path} && echo 'exists'")
        return "exists" in result.stdout

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
    ) -> List[FileInfo]:
        """列出目录内容"""
        result = await self.execute_command(f"ls -la {path}")
        # 解析 ls 输出... (简化实现)
        return []

    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        await self.execute_command(f"mkdir -p {path}")

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        await self.execute_command(f"rm -rf {path}")

    async def cleanup(self) -> None:
        """清理沙箱资源"""
        if self._k8s_client and self._pod_name:
            # 删除 Pod
            self._k8s_client.delete_namespaced_pod(
                name=self._pod_name,
                namespace=self.namespace,
            )
            logger.info(f"KubernetesSandboxProvider: 删除 Pod {self._pod_name}")
            self._pod_name = None
            self._is_initialized = False

    async def kill(self) -> None:
        """强制删除沙箱"""
        await self.cleanup()
