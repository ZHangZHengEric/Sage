"""Run the local full-duplex audio pipeline and project UI events."""

import asyncio
import json
import sys
import time

from .voice_pipeline import VoiceSession
from .voice_pipeline.asr import QwenAudioASR, VolcengineASR
from .voice_pipeline.audio import LocalAudio
from .voice_pipeline.observability import (
    AgentTextEvent,
    ErrorEvent,
    InputLevelEvent,
    MetricsEvent,
    PlaybackEvent,
    SessionEvent,
    SpeechEvent,
    SynthesisEvent,
    TranscriptEvent,
    TurnEvent,
    UserInputEvent,
)
from .voice_pipeline.tts import QwenAudioTTS, VolcengineTTS
from .voice_pipeline.observability.events import ProgressSpeechEvent
from .tools import voice_tool_catalog
from .voice_pipeline.turn_detection import SmartTurnV3
from .voice_pipeline.vad import AdaptiveInputLevelGate, SileroVAD
from pydantic import ValidationError

from .agent import SageVoiceAgent
from .config import VoiceConfig, save_config


class VoiceObserver:
    def __init__(self, emit, config):
        self.emit = emit
        self.config = config
        self.last_level = 0.0

    def on_event(self, event):
        match event:
            case SessionEvent(state=state):
                self.emit("session", state=state)
            case SpeechEvent(state=state):
                self.emit("speech", state=state)
            case InputLevelEvent(level=level):
                now = time.monotonic()
                if now - self.last_level >= 1 / 20:
                    self.last_level = now
                    self.emit("level", value=level)
            case TranscriptEvent(text=text, is_final=is_final):
                self.emit("transcript", text=text, final=is_final)
            case UserInputEvent(text=text):
                self.emit("user", text=text)
            case AgentTextEvent(delta=delta):
                self.emit("assistant", delta=delta)
            case ProgressSpeechEvent(text=text):
                self.emit("progress_speech", text=text)
            case PlaybackEvent(state=state, spoken_text=text) if state != "progress":
                self.emit("playback", state=state, spoken_text=text)
            case SynthesisEvent(state="started"):
                self.emit("synthesis")
            case TurnEvent(state=state):
                self.emit("turn", state=state)
            case MetricsEvent(metrics=metrics):
                self.emit(
                    "metrics",
                    turn=metrics.turn_ms,
                    vad=metrics.vad_confirmation_ms,
                    turn_detection=metrics.turn_detection_ms,
                    asr=metrics.asr_finalization_ms,
                    agent=metrics.agent_first_token_ms,
                    tts=metrics.tts_first_audio_ms,
                    playback=metrics.estimated_user_stop_to_first_playback_ms,
                    progress_cue=metrics.progress_cue,
                )
            case ErrorEvent(component=component, message=message):
                for key in (self.config.model_api_key, self.config.speech_api_key):
                    message = message.replace(key.get_secret_value(), "••••")
                self.emit("error", message=f"{component}: {message}")


def build_session(config, agent, emit):
    speech_key = config.speech_api_key.get_secret_value()
    if config.speech_provider == "qwen_audio":
        workspace = config.workspace_id or None
        asr = QwenAudioASR(api_key=speech_key, workspace_id=workspace)
        tts = QwenAudioTTS(
            api_key=speech_key,
            workspace_id=workspace,
            voice=config.voice or "longanhuan_v3.6",
            sample_rate=48000,
        )
    else:
        asr = VolcengineASR(
            api_key=speech_key, resource_id="volc.seedasr.sauc.duration"
        )
        tts = VolcengineTTS(
            api_key=speech_key,
            voice=config.voice or "zh_female_vv_uranus_bigtts",
            resource_id="seed-tts-2.0",
            sample_rate=48000,
        )
    return VoiceSession(
        audio=LocalAudio(
            input_sample_rate=16000,
            output_sample_rate=tts.output_format.sample_rate,
            echo_cancellation="required",
        ),
        vad=SileroVAD(),
        turn_analyzer=SmartTurnV3(),
        input_level_gate=AdaptiveInputLevelGate(),
        asr=asr,
        agent=agent,
        tts=tts,
        observers=[VoiceObserver(emit, config)],
        opening_enabled=False,
        tool_speech={
            name: rule.model_dump() for name, rule in config.tool_speech.items()
        },
    )


class VoiceRuntime:
    def __init__(self, path, root, emit):
        self.path = path
        self.root = root
        self.emit = emit
        self.config = None
        self.agent = None
        self.session = None
        self.task = None

    async def run_session(self, session):
        try:
            await session.run()
        except Exception:
            # VoiceSession reports failures through its observer.
            pass
        finally:
            self.session = None
            self.task = None

    async def stop(self):
        if self.task is not None:
            task = self.task
            await self.session.stop()
            await task

    async def close(self):
        try:
            await self.stop()
        finally:
            if self.agent is not None:
                await self.agent.shutdown()

    async def command(self, request):
        match request.get("command"):
            case "configure":
                if self.task is not None:
                    raise ValueError("请先结束语音会话。")
                config = VoiceConfig.model_validate(request.get("settings"))
                preserves_agent = self.config is not None and self.config.model_dump(
                    exclude={"tool_speech"}
                ) == config.model_dump(exclude={"tool_speech"})
                if self.agent is not None and not preserves_agent:
                    await self.agent.shutdown()
                    self.agent = None
                save_config(self.path, config)
                self.config = config
                return {
                    "preserved_conversation": preserves_agent,
                    "settings": config.fields(),
                }
            case "start":
                if self.config is None:
                    raise ValueError("请先配置模型和语音服务。")
                if self.task is None:
                    if self.agent is None:
                        self.agent = SageVoiceAgent(self.config, self.root)
                    self.session = build_session(self.config, self.agent, self.emit)
                    self.task = asyncio.create_task(self.run_session(self.session))
                    # Let VoiceSession install its stop handler before another command.
                    await asyncio.sleep(0)
            case "stop":
                await self.stop()
            case "submit":
                if self.session is None:
                    raise ValueError("请先开始语音。")
                text = request.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("请输入消息。")
                try:
                    self.session.submit_text(text.strip())
                except asyncio.QueueFull as error:
                    raise ValueError("请等待当前消息进入对话。") from error
            case "interrupt":
                if self.session is not None:
                    self.session.interrupt()
            case "new":
                await self.stop()
                if self.agent is not None:
                    self.agent.session_id = None
            case _:
                raise ValueError("未知的语音命令。")


async def serve(path, root, emit):
    runtime = VoiceRuntime(path, root, emit)
    try:
        runtime.config = VoiceConfig.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        pass
    except (OSError, ValidationError):
        emit("error", message="无法读取语音配置，请重新保存设置。")
    emit(
        "ready",
        settings=runtime.config.fields() if runtime.config else None,
        tools=voice_tool_catalog(),
    )
    reader = asyncio.StreamReader(limit=128 * 1024)
    pipe, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
    )
    try:
        while line := await reader.readline():
            request = json.loads(line)
            try:
                result = await runtime.command(request)
            except ValidationError as error:
                issue = error.errors(include_input=False)[0]
                field = issue["loc"]
                reason = issue.get("ctx", {}).get("error")
                emit(
                    "reply",
                    id=request["id"],
                    error=(
                        str(reason)
                        if field[:1] == ("tool_speech",)
                        and isinstance(reason, ValueError)
                        else f"请检查设置项 {'.'.join(map(str, field))}。"
                    ),
                )
            except (ValueError, OSError, RuntimeError) as error:
                emit("reply", id=request["id"], error=str(error))
            else:
                emit("reply", id=request["id"], **(result or {}))
    finally:
        pipe.close()
        await runtime.close()
