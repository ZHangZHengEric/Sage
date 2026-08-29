import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'v2_api.dart';

class RuntimeHost {
  RuntimeHost({V2ApiClient? api}) : api = api ?? V2ApiClient();

  final V2ApiClient api;
  Process? _process;

  Future<void> ensureReady() async {
    if (await api.health()) return;
    if (Platform.environment['SAGE_DESKTOP_V2_NO_SIDECAR'] == '1') {
      throw const SageApiException('Sage Desktop v2 sidecar is unavailable.');
    }
    final root = _findRepositoryRoot();
    final executable = _pythonExecutable(root);
    _process = await Process.start(
      executable,
      const ['-m', 'app.desktop_v2.backend.main', '--port', '0'],
      workingDirectory: root.path,
      environment: {
        ...Platform.environment,
        'SAGE_ROOT': root.path,
        'SAGE_HOST_PID': '$pid',
      },
    );
    final stdoutLines = _process!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .asBroadcastStream();
    final readyPort = Completer<int>();
    unawaited(
      stdoutLines
          .listen(
            (line) {
              try {
                final value = jsonDecode(line);
                final port = value is Map
                    ? (value['port'] as num?)?.toInt()
                    : null;
                if (port != null && port > 0 && !readyPort.isCompleted) {
                  readyPort.complete(port);
                }
              } on FormatException {
                // Existing Sage imports may log before the readiness envelope.
              }
            },
            onError: (Object error, StackTrace stackTrace) {
              if (!readyPort.isCompleted) {
                readyPort.completeError(error, stackTrace);
              }
            },
            onDone: () {
              if (!readyPort.isCompleted) {
                readyPort.completeError(
                  const SageApiException(
                    'Sage Desktop v2 sidecar exited before readiness.',
                  ),
                );
              }
            },
          )
          .asFuture<void>(),
    );
    final port = await readyPort.future.timeout(const Duration(seconds: 10));
    api.baseUri = Uri.parse('http://127.0.0.1:$port');
    unawaited(_process!.stderr.drain<void>());
    for (var attempt = 0; attempt < 120; attempt++) {
      if (await api.health()) return;
      if ((await _process!.exitCode.timeout(
            const Duration(milliseconds: 1),
            onTimeout: () => -1,
          )) !=
          -1) {
        throw const SageApiException(
          'Sage Desktop v2 sidecar exited during startup.',
        );
      }
      await Future<void>.delayed(const Duration(milliseconds: 250));
    }
    throw const SageApiException(
      'Sage Desktop v2 sidecar did not become ready.',
    );
  }

  Directory _findRepositoryRoot() {
    final explicit = Platform.environment['SAGE_ROOT'];
    if (explicit != null && explicit.trim().isNotEmpty) {
      return Directory(explicit).absolute;
    }
    final candidates = <Directory>[
      Directory.current.absolute,
      File(Platform.resolvedExecutable).parent.absolute,
    ];
    for (final candidate in candidates) {
      var current = candidate;
      for (var depth = 0; depth < 16; depth++) {
        if (Directory('${current.path}/sagents').existsSync() &&
            Directory('${current.path}/app/desktop_v2').existsSync()) {
          return current;
        }
        final parent = current.parent;
        if (parent.path == current.path) break;
        current = parent;
      }
    }
    throw const SageApiException(
      'Cannot locate Sage repository. Set SAGE_ROOT for source-mode runs.',
    );
  }

  String _pythonExecutable(Directory root) {
    final explicit = Platform.environment['SAGE_PYTHON'];
    if (explicit != null && explicit.trim().isNotEmpty) return explicit;
    final candidate = File('${root.path}/.venv/bin/python');
    if (candidate.existsSync()) return candidate.path;
    return Platform.isWindows ? 'python' : 'python3';
  }

  /// Disconnect the Flutter observer without converting app close into cancel.
  /// The sidecar may keep active runs alive and can be reused on the next launch.
  void detach() {
    api.close();
  }

  Future<void> stopOwnedSidecar() async {
    api.close();
    final process = _process;
    if (process != null) {
      process.kill(ProcessSignal.sigterm);
    }
  }
}
