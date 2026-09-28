"""Sage CLI 对 SAgents v2 运行时的进程内接入层。

本包只依赖 ``sagents.v2`` 的公开组合根（``SAgentBuilder``）与契约，不触碰 v1 运行时，
也不引入 HTTP：CLI 直接在进程内起 Run、消费 native 事件流、处理审批交互。
"""
