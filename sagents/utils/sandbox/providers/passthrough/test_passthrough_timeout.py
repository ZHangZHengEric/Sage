"""
测试 PassthroughSandboxProvider 的超时返回 stdio 功能

验证当命令执行超时时，能够返回超时前已收集的输出内容。
"""
import asyncio
import pytest
import os

from sagents.utils.sandbox.providers.passthrough.passthrough import PassthroughSandboxProvider


class TestExecuteCommandTimeout:
    """测试 execute_command 超时行为"""

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_output(self, tmp_path):
        """测试超时时返回已收集的部分输出"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        # 执行一个会产生输出然后 sleep 超时的命令
        command = 'echo "LINE1" && echo "LINE2" && sleep 10'

        result = await provider.execute_command(
            command=command,
            timeout=2,  # 2秒超时
        )

        # 验证超时返回
        assert result.success is False
        assert result.return_code == -1
        assert "timed out" in result.stderr.lower()

        # 关键验证：应该包含超时前输出的内容
        assert "LINE1" in result.stdout
        assert "LINE2" in result.stdout

    @pytest.mark.asyncio
    async def test_timeout_with_continuous_output(self, tmp_path):
        """测试持续输出时的超时行为"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        # 使用 shell 循环产生持续输出
        command = 'for i in 1 2 3 4 5; do echo "OUTPUT_$i"; sleep 1; done'

        result = await provider.execute_command(
            command=command,
            timeout=2,  # 2秒超时，应该只能捕获部分输出
        )

        # 验证超时返回
        assert result.success is False
        assert result.return_code == -1

        # 验证至少捕获了部分输出
        # 应该至少看到 OUTPUT_1 和 OUTPUT_2
        assert "OUTPUT_1" in result.stdout
        assert "OUTPUT_2" in result.stdout

    @pytest.mark.asyncio
    async def test_normal_execution_no_timeout(self, tmp_path):
        """测试正常执行（无超时）的情况"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        command = 'echo "HELLO" && echo "WORLD"'

        result = await provider.execute_command(
            command=command,
            timeout=10,  # 足够长的超时时间
        )

        # 验证正常执行
        assert result.success is True
        assert result.return_code == 0
        assert "HELLO" in result.stdout
        assert "WORLD" in result.stdout
        assert "timed out" not in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_timeout_with_stderr_output(self, tmp_path):
        """测试包含 stderr 输出时的超时行为"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        # 输出到 stderr 然后 sleep
        command = 'echo "STDOUT_MSG" && echo "STDERR_MSG" >&2 && sleep 10'

        result = await provider.execute_command(
            command=command,
            timeout=2,
        )

        # 验证超时返回
        assert result.success is False

        # 验证 stdout 和 stderr 都被捕获
        assert "STDOUT_MSG" in result.stdout
        # stderr 内容可能在 stdout 或 stderr 中，取决于实现
        combined = result.stdout + result.stderr
        assert "STDERR_MSG" in combined

    @pytest.mark.asyncio
    async def test_immediate_timeout_still_returns_output(self, tmp_path):
        """测试即使立即超时也能返回已产生的输出"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        # 产生大量输出然后 sleep
        command = 'seq 1 100 && sleep 10'

        result = await provider.execute_command(
            command=command,
            timeout=2,
        )

        # 验证超时返回
        assert result.success is False

        # 应该捕获了部分数字输出
        assert "1" in result.stdout
        assert "2" in result.stdout


class TestExecuteCommandEdgeCases:
    """测试边界情况"""

    @pytest.mark.asyncio
    async def test_empty_command_timeout(self, tmp_path):
        """测试空命令的超时行为"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        # 空命令应该立即返回，不会超时
        result = await provider.execute_command(
            command='',
            timeout=5,
        )

        # 空命令在 shell 中返回 0
        assert result.success is True

    @pytest.mark.asyncio
    async def test_very_short_timeout(self, tmp_path):
        """测试非常短的超时时间"""
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        provider = PassthroughSandboxProvider(
            sandbox_id="test_sandbox",
            sandbox_agent_workspace=workspace,
        )

        # 使用 1 秒超时
        command = 'echo "TEST" && sleep 5'

        result = await provider.execute_command(
            command=command,
            timeout=1,  # 1秒应该足够捕获 echo 的输出
        )

        # 可能成功也可能超时，取决于系统速度
        # 但如果超时，应该仍然返回已收集的输出
        if not result.success:
            assert "timed out" in result.stderr.lower()
            assert "TEST" in result.stdout
