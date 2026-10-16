import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';

void main() {
  final root = Directory.current.parent.parent.parent;
  final python = File(
    '${root.path}/.venv/${Platform.isWindows ? 'Scripts/python.exe' : 'bin/python'}',
  );
  final live = Platform.environment.containsKey('SAGE_DESKTOP_LIVE_CATALOG');
  test(
    live ? 'live model completes two streamed turns with persisted history' : 'real sidecar completes two streamed turns with persisted history',
    () async {
      expect(
        python.existsSync(),
        isTrue,
        reason: 'Install the repository Python test dependencies first.',
      );
      final data = await Directory.systemTemp.createTemp(
        'sage-flutter-unified-',
      );
      final process = await Process.start(
        python.path,
        ['app/v2/desktop/test/fixtures/unified_sidecar.py', data.path],
        workingDirectory: root.path,
        environment: {'PYTHONPATH': root.path},
      );
      final errors = StringBuffer();
      final stderr = process.stderr
          .transform(utf8.decoder)
          .listen(errors.write);
      addTearDown(() async {
        process.kill(ProcessSignal.sigterm);
        try {
          await process.exitCode.timeout(const Duration(seconds: 15));
        } on TimeoutException {
          process.kill(ProcessSignal.sigkill);
          await process.exitCode;
        }
        await stderr.cancel();
        await data.delete(recursive: true);
      });
      final ready = await process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .map((line) {
            try {
              return jsonDecode(line);
            } catch (_) {
              return null;
            }
          })
          .firstWhere((value) => value is Map && value.containsKey('token'))
          .timeout(
            const Duration(seconds: 30),
            onTimeout: () => throw StateError(errors.toString()),
          );
      final api = V2ApiClient(
        baseUri: Uri.parse('http://127.0.0.1:${ready['port']}'),
        authToken: ready['token'] as String,
      );
      addTearDown(api.close);
      expect(await api.health(), isTrue);
      final agents = await api.listAgents();
      expect(agents, isNotEmpty);
      String? sessionId;
      for (var turn = 1; turn <= 2; turn++) {
        final frames = await api
            .startRun({
              'agent_id': agents.first.id,
              'messages': [
                {'role': 'user', 'text': live ? (turn == 1 ? '记住验收代号 SAGE_ENTRY_716。不要调用工具，只回复代号。' : '上一轮的验收代号是什么？不要调用工具，只回复代号。') : 'Conversation test turn $turn'},
              ],
              'idempotency_key': 'flutter-unified-$turn',
              'session_id': sessionId,
            })
            .toList()
            .timeout(Duration(seconds: live ? 180 : 30));
        expect(
          frames.any((frame) => frame['type'] == 'run.failed'),
          isFalse,
          reason: jsonEncode(frames),
        );
        expect(
          frames.any((frame) => frame['type'] == 'run.completed'),
          isTrue,
          reason: jsonEncode(frames),
        );
        expect(jsonEncode(frames), contains(live ? 'SAGE_ENTRY_716' : 'Unified reply $turn'));
        final opened = frames.firstWhere(
          (frame) => frame['kind'] == 'stream.opened',
        );
        final data = opened['handle'] as Map;
        sessionId = data['session_id'] as String;
        final run = await api.getRun(data['run_id'] as String);
        expect((run['run'] as Map)['state'], 'completed');
      }
    },
    timeout: Timeout(Duration(minutes: live ? 7 : 2)),
    skip: python.existsSync()
        ? false
        : 'Requires repository .venv with Python backend dependencies',
  );
}
