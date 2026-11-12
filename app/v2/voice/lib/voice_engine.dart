import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

enum VoiceState {
  loading,
  idle,
  starting,
  listening,
  transcribing,
  thinking,
  speaking,
  stopping,
}

typedef RuntimeLog = ({DateTime time, String message});

typedef Utterance = ({bool user, String text});

class VoiceEngine extends ChangeNotifier {
  static const _platform = MethodChannel('sage.voice/microphone');
  static const _workerTimeout = Duration(seconds: 30);
  final List<Utterance> conversation = [];
  final Map<int, Completer<Map<String, Object?>>> _pending = {};
  final List<RuntimeLog> events = [];
  Map<String, Object?> metrics = {};

  Process? _process;
  int _sequence = 0;
  bool _disposed = false;
  bool _connecting = false;
  bool _newReply = true;
  bool interrupted = false;
  Timer? _interruptionNotice;
  Timer? _startupTimer;
  VoiceState? _incomingSpeech;
  String? _progressSpeech;
  VoiceState state = VoiceState.loading;
  Map<String, Object?>? settings;
  Map<String, Object?> toolSpeechDefaults = {};
  String transcript = '';
  String? error;
  double level = 0;

  bool get connected => _process != null && !_connecting;
  bool get idle => state == VoiceState.idle;
  bool get busy => {
    VoiceState.loading,
    VoiceState.starting,
    VoiceState.stopping,
  }.contains(state);
  bool get active => !idle && state != VoiceState.loading;
  bool get canSubmit => active && !busy;
  bool get canInterrupt =>
      state == VoiceState.thinking || state == VoiceState.speaking;
  bool get editingSettings => connected && idle;

  String get status {
    if (interrupted && state == VoiceState.listening) return '已打断回应';
    if (_progressSpeech case final String cue) {
      if (state == VoiceState.thinking || state == VoiceState.speaking) {
        return cue;
      }
    }
    return switch (state) {
      VoiceState.loading => '正在连接语音引擎',
      VoiceState.idle when !connected => '语音引擎未连接',
      VoiceState.idle when settings == null => '设置模型和语音服务以开始',
      VoiceState.idle => '点击开始聆听',
      VoiceState.starting => '正在启动',
      VoiceState.listening => '正在聆听',
      VoiceState.transcribing => '正在识别',
      VoiceState.thinking => '正在思考',
      VoiceState.speaking => '正在回应',
      VoiceState.stopping => '正在停止',
    };
  }

  void _log(String message) {
    if (events.length == 100) events.removeAt(0);
    events.add((time: DateTime.now(), message: message));
  }

  Future<void> connect() async {
    if (_connecting || _process != null) return;
    _connecting = true;
    state = VoiceState.loading;
    error = null;
    notifyListeners();
    try {
      final root = _sourceRoot();
      final python =
          Platform.environment['SAGE_VOICE_PYTHON'] ??
          '${root.path}/.venv-voice/bin/python';
      final process = await Process.start(python, [
        '-u',
        '-m',
        'app.v2.voice.backend',
      ], workingDirectory: root.path);
      if (_disposed) {
        process.kill();
        return;
      }
      _process = process;
      _startupTimer = Timer(_workerTimeout, () {
        _stopUnresponsiveWorker(process, '语音引擎连接超时，请重新连接。');
      });
      process.stderr.drain<void>();
      process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            if (_process == process) _receive(line);
          }, onDone: () => _disconnected(process));
    } on Object catch (_) {
      if (_disposed) return;
      _connecting = false;
      state = VoiceState.idle;
      error = '无法启动语音引擎。请检查 Python 安装，并从 Sage 源码运行。';
      notifyListeners();
    }
  }

  Directory _sourceRoot() {
    for (var directory in [
      Directory.current.absolute,
      File(Platform.resolvedExecutable).parent,
    ]) {
      while (true) {
        if (File(
          '${directory.path}/app/v2/voice/backend/__main__.py',
        ).existsSync()) {
          return directory;
        }
        final parent = directory.parent;
        if (parent.path == directory.path) break;
        directory = parent;
      }
    }
    throw StateError('Sage source tree not found');
  }

  void _disconnected(Process process) {
    if (_disposed || _process != process) return;
    _startupTimer?.cancel();
    _process = null;
    _connecting = false;
    state = VoiceState.idle;
    level = 0;
    _clearConversation();
    error ??= '语音引擎已退出。';
    for (final request in _pending.values) {
      request.completeError(VoiceException(error!));
    }
    _pending.clear();
    notifyListeners();
  }

  void _stopUnresponsiveWorker(Process process, String message) {
    if (_disposed || _process != process) return;
    error = message;
    process.kill(ProcessSignal.sigkill);
    _disconnected(process);
  }

  void _receive(String line) {
    if (_disposed) return;
    final data = jsonDecode(line) as Map<String, dynamic>;
    switch (data['event']) {
      case 'reply':
        final request = _pending.remove(data['id']);
        if (data['error'] case final String message) {
          request?.completeError(VoiceException(message));
        } else {
          request?.complete(data);
        }
        return;
      case 'ready':
        _startupTimer?.cancel();
        _connecting = false;
        settings = (data['settings'] as Map?)?.cast<String, Object?>();
        toolSpeechDefaults =
            (data['tool_speech_defaults'] as Map?)?.cast<String, Object?>() ??
            {};
        state = VoiceState.idle;
      case 'error':
        error = data['message'] as String;
        _log(error!);
      case 'session':
        switch (data['state']) {
          case 'starting':
            state = VoiceState.starting;
          case 'ready':
            state = VoiceState.listening;
            _log('语音会话已开始');
          case 'stopping':
            state = VoiceState.stopping;
          case 'stopped':
            _progressSpeech = null;
            state = VoiceState.idle;
            _incomingSpeech = null;
            transcript = '';
            level = 0;
            interrupted = false;
            _log('语音会话已结束');
        }
      case 'speech':
        if (busy) return;
        if (data['state'] == 'stopped') {
          _incomingSpeech = VoiceState.transcribing;
          state = VoiceState.transcribing;
        } else {
          _incomingSpeech = VoiceState.listening;
          transcript = '';
          if (state != VoiceState.speaking) state = VoiceState.listening;
        }
      case 'level':
        level = (data['value'] as num).toDouble();
      case 'transcript':
        transcript = data['text'] as String;
        if (data['final'] == true && transcript.isEmpty) {
          _incomingSpeech = null;
          if (state == VoiceState.transcribing) state = VoiceState.listening;
        }
      case 'user':
        _progressSpeech = null;
        _incomingSpeech = null;
        transcript = data['text'] as String;
        conversation.add((user: true, text: transcript));
        _newReply = true;
        interrupted = false;
        error = null;
        if (!busy) state = VoiceState.thinking;
      case 'assistant':
        _progressSpeech = null;
        final delta = data['delta'] as String;
        if (_newReply) {
          conversation.add((user: false, text: delta));
          _newReply = false;
        } else {
          conversation.last = (
            user: false,
            text: conversation.last.text + delta,
          );
        }
      case 'synthesis':
        if (!busy && _incomingSpeech == null) state = VoiceState.speaking;
      case 'progress_speech':
        _progressSpeech = data['text'] as String;
      case 'playback':
        if (data['state'] == 'interrupted') {
          _progressSpeech = null;
          interrupted = true;
          _log('已打断回应');
          _interruptionNotice?.cancel();
          _interruptionNotice = Timer(const Duration(seconds: 2), () {
            interrupted = false;
            notifyListeners();
          });
          if (!_newReply) {
            final spoken = data['spoken_text'] as String;
            if (spoken.isEmpty) {
              conversation.removeLast();
            } else {
              conversation.last = (user: false, text: spoken);
            }
            _newReply = true;
          }
        }
      case 'metrics':
        metrics = data;
      case 'turn':
        final result = data['state'];
        if (result != 'started') _progressSpeech = null;
        if (result == 'completed') _log('语音回合已完成');
        if (result == 'failed') _log('语音回合失败');
        if (!busy && data['state'] != 'started') {
          state = _incomingSpeech ?? VoiceState.listening;
          if (_incomingSpeech == null) transcript = '';
        }
    }
    notifyListeners();
  }

  Future<Map<String, Object?>> _command(
    String command, [
    Map<String, Object?>? values,
  ]) async {
    final process = _process;
    if (process == null || _connecting) throw const VoiceException('语音引擎未连接。');
    final id = ++_sequence;
    final request = jsonEncode({'id': id, 'command': command, ...?values});
    // Match the Python worker's newline-delimited request limit.
    if (utf8.encode(request).length >= 128 * 1024) {
      throw const VoiceException('输入过长，请缩短后重试。');
    }
    final response = _pending[id] = Completer<Map<String, Object?>>();
    try {
      process.stdin.writeln(request);
      return await response.future.timeout(_workerTimeout);
    } on TimeoutException {
      _pending.remove(id);
      const message = '语音引擎响应超时，请重新连接。';
      _stopUnresponsiveWorker(process, message);
      throw const VoiceException(message);
    } finally {
      _pending.remove(id);
    }
  }

  Future<void> configure(Map<String, Object?> values) async {
    final reply = await _command('configure', {'settings': values});
    if (_disposed) return;
    settings = values;
    error = null;
    if (reply['preserved_conversation'] != true) _clearConversation();
    notifyListeners();
  }

  Future<void> toggle() async {
    if (busy) return;
    final starting = idle;
    error = null;
    interrupted = false;
    state = starting ? VoiceState.starting : VoiceState.stopping;
    notifyListeners();
    try {
      if (starting && await _platform.invokeMethod<bool>('request') != true) {
        throw const VoiceException(
          '请在系统设置的「隐私与安全性 → 麦克风」中允许 Sage Voice 使用麦克风。',
        );
      }
      if (!_disposed) await _command(starting ? 'start' : 'stop');
    } on Object catch (exception) {
      if (_disposed) return;
      error = exception.toString();
      state = VoiceState.idle;
      notifyListeners();
    }
  }

  Future<bool> submitText(String text) async {
    if (!canSubmit || text.trim().isEmpty) return false;
    return _sendWorkCommand('submit', {'text': text.trim()});
  }

  Future<bool> interrupt() => _sendWorkCommand('interrupt');

  Future<bool> _sendWorkCommand(
    String command, [
    Map<String, Object?>? data,
  ]) async {
    try {
      await _command(command, data);
      return true;
    } on Object catch (exception) {
      if (!_disposed) {
        error = exception.toString();
        notifyListeners();
      }
      return false;
    }
  }

  Future<void> newConversation() async {
    if (busy) return;
    state = VoiceState.stopping;
    notifyListeners();
    try {
      await _command('new');
      if (_disposed) return;
      _clearConversation();
      error = null;
    } on Object catch (exception) {
      if (_disposed) return;
      error = exception.toString();
    }
    if (_disposed) return;
    state = VoiceState.idle;
    notifyListeners();
  }

  void _clearConversation() {
    conversation.clear();
    metrics = {};
    transcript = '';
    _progressSpeech = null;
    _incomingSpeech = null;
    interrupted = false;
    _newReply = true;
  }

  @override
  void dispose() {
    _disposed = true;
    _startupTimer?.cancel();
    _interruptionNotice?.cancel();
    final process = _process;
    if (process != null) {
      // EOF requests graceful shutdown of the session and any active Run.
      unawaited(process.stdin.close());
    }
    super.dispose();
  }
}

class VoiceException implements Exception {
  const VoiceException(this.message);

  final String message;

  @override
  String toString() => message;
}
