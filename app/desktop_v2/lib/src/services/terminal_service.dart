import 'dart:convert';
import 'dart:typed_data';

import '../api/v2_api.dart';

class TerminalSessionInfo {
  const TerminalSessionInfo({
    required this.sessionId,
    required this.pid,
    required this.cwd,
    required this.shell,
    required this.columns,
    required this.rows,
    required this.sequence,
    required this.running,
  });

  final String sessionId;
  final int pid;
  final String cwd;
  final String shell;
  final int columns;
  final int rows;
  final int sequence;
  final bool running;

  factory TerminalSessionInfo.fromJson(Map<String, Object?> json) =>
      TerminalSessionInfo(
        sessionId: json['session_id']?.toString() ?? '',
        pid: (json['pid'] as num?)?.toInt() ?? 0,
        cwd: json['cwd']?.toString() ?? '',
        shell: json['shell']?.toString() ?? '',
        columns: (json['columns'] as num?)?.toInt() ?? 0,
        rows: (json['rows'] as num?)?.toInt() ?? 0,
        sequence: (json['sequence'] as num?)?.toInt() ?? 0,
        running: json['running'] == true,
      );
}

sealed class TerminalEvent {
  const TerminalEvent({required this.sessionId, required this.sequence});

  final String sessionId;
  final int sequence;

  static TerminalEvent fromJson(Map<String, Object?> json) {
    final sessionId = json['session_id']?.toString() ?? '';
    final sequence = (json['sequence'] as num?)?.toInt() ?? 0;
    return switch (json['type']?.toString()) {
      'terminal.output' => TerminalOutputEvent(
        sessionId: sessionId,
        sequence: sequence,
        bytes: _decodeBytes(json['data']),
      ),
      'terminal.exited' => TerminalExitedEvent(
        sessionId: sessionId,
        sequence: sequence,
        exitCode: (json['exit_code'] as num?)?.toInt() ?? -1,
      ),
      'terminal.failed' => TerminalFailedEvent(
        sessionId: sessionId,
        sequence: sequence,
        message: json['message']?.toString() ?? 'Terminal failed',
      ),
      final type => TerminalFailedEvent(
        sessionId: sessionId,
        sequence: sequence,
        message: 'Unsupported terminal event: $type',
      ),
    };
  }

  static Uint8List _decodeBytes(Object? value) {
    try {
      return base64Decode(value?.toString() ?? '');
    } on FormatException {
      return Uint8List(0);
    }
  }
}

class TerminalOutputEvent extends TerminalEvent {
  const TerminalOutputEvent({
    required super.sessionId,
    required super.sequence,
    required this.bytes,
  });

  final Uint8List bytes;
}

class TerminalExitedEvent extends TerminalEvent {
  const TerminalExitedEvent({
    required super.sessionId,
    required super.sequence,
    required this.exitCode,
  });

  final int exitCode;
}

class TerminalFailedEvent extends TerminalEvent {
  const TerminalFailedEvent({
    required super.sessionId,
    required super.sequence,
    required this.message,
  });

  final String message;
}

class TerminalService {
  const TerminalService(this._api);

  final V2ApiClient _api;

  Future<TerminalSessionInfo> create({
    required String agentId,
    String workspaceId = '',
    int columns = 100,
    int rows = 30,
  }) async => TerminalSessionInfo.fromJson(
    await _api.createTerminal(
      agentId: agentId,
      workspaceId: workspaceId,
      columns: columns,
      rows: rows,
    ),
  );

  Stream<TerminalEvent> events(String sessionId, {int afterSequence = 0}) =>
      _api
          .terminalEvents(sessionId, afterSequence: afterSequence)
          .map(TerminalEvent.fromJson);

  Future<void> write(String sessionId, String data) =>
      _api.writeTerminal(sessionId, data);

  Future<void> resize(
    String sessionId, {
    required int columns,
    required int rows,
  }) => _api.resizeTerminal(sessionId, columns: columns, rows: rows);

  Future<void> close(String sessionId) => _api.closeTerminal(sessionId);
}
