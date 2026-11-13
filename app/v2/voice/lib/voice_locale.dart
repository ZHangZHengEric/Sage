import 'package:flutter/widgets.dart';

extension VoiceLocale on BuildContext {
  bool get voiceChinese =>
      Localizations.maybeLocaleOf(this)?.languageCode == 'zh';

  String tr(String chinese, String english) => voiceChinese ? chinese : english;
}

// Translate application-owned worker messages when presenting them. Provider
// diagnostics, transcripts and speech announcements keep their original text.
String voiceMessage(BuildContext context, String message) {
  if (context.voiceChinese) return message;
  const english = {
    '已打断回应': 'Response interrupted',
    '正在连接语音引擎': 'Connecting to the voice engine',
    '语音引擎未连接': 'Voice engine disconnected',
    '语音引擎未连接。': 'Voice engine disconnected.',
    '设置模型和语音服务以开始': 'Set up a model and speech service',
    '点击开始聆听': 'Ready to listen',
    '正在启动': 'Starting',
    '正在聆听': 'Listening',
    '正在识别': 'Transcribing',
    '正在思考': 'Thinking',
    '正在回应': 'Responding',
    '正在停止': 'Stopping',
    '语音引擎连接超时，请重新连接。': 'Connection timed out. Reconnect to try again.',
    '语音引擎启动失败': 'Voice engine failed to start',
    '语音引擎已退出。': 'The voice engine exited.',
    '语音会话已开始': 'Voice session started',
    '语音会话已结束': 'Voice session ended',
    '语音回合已完成': 'Voice turn completed',
    '语音回合失败': 'Voice turn failed',
    '输入过长，请缩短后重试。': 'Shorten your input and try again.',
    '语音引擎响应超时，请重新连接。': 'The voice engine timed out. Reconnect to try again.',
    '请在系统设置的「隐私与安全性 → 麦克风」中允许 Sage Voice 使用麦克风。':
        'Allow Sage Voice in System Settings under Privacy & Security → Microphone.',
    '请先结束语音会话。': 'End the voice session first.',
    '请先配置模型和语音服务。': 'Set up a model and speech service first.',
    '请先开始语音。': 'Start a voice session first.',
    '请输入消息。': 'Enter a message.',
    '请等待当前消息进入对话。': 'Wait for the current message to be accepted.',
    '未知的语音命令。': 'Unknown voice command.',
    '无法读取语音配置，请重新保存设置。':
        'Voice settings could not be read. Save your settings again.',
  };
  if (english[message] case final String translated) return translated;
  final field = RegExp(r'^请检查设置项 (.+)。$').firstMatch(message);
  if (field != null) return 'Check the ${field[1]} setting.';
  final placeholder = RegExp(
    r'^(.+) 的播报只支持 \{target\} 占位符。$',
  ).firstMatch(message);
  if (placeholder != null) {
    return 'Only {target} is supported for ${placeholder[1]}.';
  }
  final target = RegExp(
    r'^(.+) 的参数不可用于播报，请移除 \{target\}。$',
  ).firstMatch(message);
  if (target != null) {
    return 'Remove {target} from the announcement for ${target[1]}.';
  }
  return message;
}
