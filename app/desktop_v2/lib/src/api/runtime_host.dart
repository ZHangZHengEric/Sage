import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'v2_api.dart';

typedef RuntimeProcessStarter =
    Future<Process> Function(
      String executable,
      List<String> arguments, {
      String? workingDirectory,
      Map<String, String>? environment,
    });

typedef RuntimePidKiller = bool Function(int pid, ProcessSignal signal);

typedef RuntimePythonVersionReader =
    Future<(int, int)> Function(String executable);

class RuntimeHost {
  RuntimeHost({
    V2ApiClient? api,
    File? sidecarRegistryFile,
    String? buildId,
    RuntimeProcessStarter startProcess = Process.start,
    RuntimePidKiller killPid = Process.killPid,
    Duration terminationGracePeriod = const Duration(seconds: 2),
    int sidecarReadyAttempts = 20,
    Duration sidecarPollInterval = const Duration(milliseconds: 100),
    RuntimePythonVersionReader readPythonVersion = _inspectPythonVersion,
  }) : api = api ?? V2ApiClient(),
       _sidecarRegistryFileOverride = sidecarRegistryFile,
       _buildIdOverride = buildId,
       _processStarter = startProcess,
       _pidKiller = killPid,
       _shutdownGracePeriod = terminationGracePeriod,
       _registryReadyAttempts = sidecarReadyAttempts,
       _registryPollInterval = sidecarPollInterval,
       _readPythonVersion = readPythonVersion;

  final V2ApiClient api;
  final File? _sidecarRegistryFileOverride;
  final String? _buildIdOverride;
  final RuntimeProcessStarter _processStarter;
  final RuntimePidKiller _pidKiller;
  final RuntimePythonVersionReader _readPythonVersion;
  final Duration _shutdownGracePeriod;
  final int _registryReadyAttempts;
  final Duration _registryPollInterval;
  Process? _process;
  int? _sidecarPid;
  final StringBuffer _sidecarStderr = StringBuffer();

  Future<void> ensureReady() async {
    final root = _findRepositoryRoot();
    final buildId = _buildIdOverride ?? await _sourceBuildId(root);
    api.expectedBuildId = buildId;
    if (await api.health()) return;
    if (await _connectRegisteredSidecar(buildId)) return;
    final executable = _pythonExecutable(root);
    await _requirePython312(executable);
    final dataRoot = _dataRootPath();
    final process = await _processStarter(
      executable,
      [
        '-m',
        'app.desktop_v2.backend.main',
        '--port',
        '0',
        '--data-root',
        dataRoot,
        '--build-id',
        buildId,
      ],
      workingDirectory: root.path,
      environment: Platform.environment,
    );
    _process = process;
    _sidecarPid = process.pid;
    unawaited(
      process.exitCode.then((_) {
        if (identical(_process, process)) _process = null;
        if (_sidecarPid == process.pid) _sidecarPid = null;
      }),
    );
    unawaited(
      process.stderr.transform(utf8.decoder).listen((chunk) {
        if (_sidecarStderr.length >= 6000) return;
        final remaining = 6000 - _sidecarStderr.length;
        _sidecarStderr.write(
          chunk.length <= remaining ? chunk : chunk.substring(0, remaining),
        );
      }).asFuture<void>(),
    );
    final stdoutLines = process.stdout
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
    late final int port;
    try {
      port = await readyPort.future.timeout(const Duration(seconds: 10));
    } on Object {
      await process.exitCode.timeout(
        const Duration(seconds: 1),
        onTimeout: () => -1,
      );
      if (await _connectRegisteredSidecar(buildId)) return;
      throw _startupException(
        'Sage Desktop v2 sidecar exited before readiness.',
      );
    }
    api.baseUri = Uri.parse('http://127.0.0.1:$port');
    for (var attempt = 0; attempt < 120; attempt++) {
      if (await api.health()) return;
      if ((await process.exitCode.timeout(
            const Duration(milliseconds: 1),
            onTimeout: () => -1,
          )) !=
          -1) {
        throw _startupException(
          'Sage Desktop v2 sidecar exited during startup.',
        );
      }
      await Future<void>.delayed(const Duration(milliseconds: 250));
    }
    throw const SageApiException(
      'Sage Desktop v2 sidecar did not become ready.',
    );
  }

  File _sidecarRegistryFile() {
    final override = _sidecarRegistryFileOverride;
    if (override != null) return override;
    final dataRoot = _dataRootPath();
    return File(
      '$dataRoot${Platform.pathSeparator}runtime${Platform.pathSeparator}'
      'desktop-v2-sidecar.json',
    );
  }

  String _dataRootPath() {
    final home = Platform.environment['HOME'];
    if (home == null || home.trim().isEmpty) {
      throw const SageApiException('Cannot determine the user home directory.');
    }
    return '$home${Platform.pathSeparator}sage';
  }

  Future<bool> _connectRegisteredSidecar(String buildId) async {
    final registry = _sidecarRegistryFile();
    try {
      final value = jsonDecode(await registry.readAsString());
      if (value is! Map || value['protocol'] != sageSidecarProtocol) {
        return false;
      }
      final host = value['host']?.toString();
      final port = value['port'];
      if (host == null || port is! num || port.toInt() <= 0) return false;
      if (value['revision'] != sageSidecarRevision ||
          value['build_id'] != buildId) {
        await _retireIncompatibleSidecar(value, registry, host, port.toInt());
        return false;
      }
      final previous = api.baseUri;
      api.baseUri = Uri.parse('http://$host:${port.toInt()}');
      // Registry publication happens immediately before Uvicorn starts. A
      // concurrently launched desktop process must give that matching sidecar
      // a short readiness window instead of deleting valid discovery data.
      for (var attempt = 0; attempt < _registryReadyAttempts; attempt++) {
        if (await api.health()) {
          final pid = value['pid'];
          _sidecarPid = pid is num && pid.toInt() > 0 ? pid.toInt() : null;
          return true;
        }
        await Future<void>.delayed(_registryPollInterval);
      }
      api.baseUri = previous;
      await _retireRegisteredSidecar(value, registry);
    } on SageApiException {
      rethrow;
    } on Object {
      // Missing, stale, or partially written discovery data is not fatal. The
      // app can still provision a fresh sidecar below.
    }
    return false;
  }

  Future<void> _retireIncompatibleSidecar(
    Map<dynamic, dynamic> value,
    File registry,
    String host,
    int port,
  ) async {
    final previous = api.baseUri;
    api.baseUri = Uri.parse('http://$host:$port');
    try {
      await _retireRegisteredSidecar(value, registry);
    } finally {
      api.baseUri = previous;
    }
  }

  Future<void> _retireRegisteredSidecar(
    Map<dynamic, dynamic> value,
    File registry,
  ) async {
    final rawPid = value['pid'];
    final sidecarPid = rawPid is num ? rawPid.toInt() : 0;
    if (sidecarPid > 0) {
      final signaled = _pidKiller(sidecarPid, ProcessSignal.sigterm);
      if (signaled &&
          await _waitForRegistryRemoval(registry, _shutdownGracePeriod)) {
        return;
      }
      if (signaled) {
        _pidKiller(sidecarPid, ProcessSignal.sigkill);
        // File locks are released by the OS when SIGKILL takes effect. Give the
        // kernel a short scheduling window before provisioning a replacement.
        await Future<void>.delayed(const Duration(milliseconds: 100));
      }
    }
    await _deleteRegistryIfOwned(registry, sidecarPid);
  }

  Future<bool> _waitForRegistryRemoval(File registry, Duration timeout) async {
    if (!registry.existsSync()) return true;
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 50));
      if (!registry.existsSync()) return true;
    }
    return !registry.existsSync();
  }

  Future<void> _deleteRegistryIfOwned(File registry, int sidecarPid) async {
    if (!registry.existsSync()) return;
    try {
      final current = jsonDecode(await registry.readAsString());
      if (current is Map && current['pid'] == sidecarPid) {
        await registry.delete();
      }
    } on FileSystemException {
      // Another process may have removed or replaced the registry concurrently.
    } on FormatException {
      // A partial stale registry cannot identify an owner safely.
    }
  }

  SageApiException _startupException(String summary) {
    final details = _sidecarStderr.toString().trim();
    return SageApiException(details.isEmpty ? summary : '$summary\n$details');
  }

  Directory _findRepositoryRoot() {
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
      'Cannot locate the Sage repository for source-mode execution.',
    );
  }

  String _pythonExecutable(Directory root) {
    final candidate = File('${root.path}/.venv/bin/python');
    if (candidate.existsSync()) return candidate.path;
    return Platform.isWindows ? 'python' : 'python3';
  }

  Future<void> _requirePython312(String executable) async {
    final version = await _readPythonVersion(executable);
    if (version.$1 > 3 || (version.$1 == 3 && version.$2 >= 12)) {
      return;
    }
    throw SageApiException(
      'Sage Desktop v2 requires Python 3.12 or newer; '
      '$executable reports ${version.$1}.${version.$2}.',
    );
  }

  static Future<(int, int)> _inspectPythonVersion(String executable) async {
    final result = await Process.run(executable, const [
      '-c',
      'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")',
    ]);
    final text = '${result.stdout}'.trim();
    final parts = text.split('.');
    if (result.exitCode != 0 || parts.length < 2) {
      throw SageApiException(
        'Sage Desktop v2 requires Python 3.12+; failed to inspect $executable.',
      );
    }
    final major = int.tryParse(parts[0]);
    final minor = int.tryParse(parts[1]);
    if (major == null || minor == null) {
      throw SageApiException(
        'Sage Desktop v2 requires Python 3.12+; failed to inspect $executable.',
      );
    }
    return (major, minor);
  }

  Future<String> _sourceBuildId(Directory root) async {
    final sourceRoots = [
      Directory('${root.path}/app/desktop_v2/backend'),
      Directory('${root.path}/sagents/v2'),
    ];
    final files = <File>[];
    for (final sourceRoot in sourceRoots) {
      if (!sourceRoot.existsSync()) continue;
      await for (final entry in sourceRoot.list(recursive: true)) {
        if (entry is File && entry.path.endsWith('.py')) files.add(entry);
      }
    }
    files.sort((left, right) => left.path.compareTo(right.path));
    var hash = 5381;
    const mask = 0x1fffffffffffff;
    for (final file in files) {
      final relativePath = file.path.substring(root.path.length);
      for (final byte in utf8.encode(relativePath)) {
        hash = ((hash * 33) ^ byte) & mask;
      }
      for (final byte in await file.readAsBytes()) {
        hash = ((hash * 33) ^ byte) & mask;
      }
    }
    return 'source-${hash.toRadixString(16).padLeft(14, '0')}';
  }

  /// Close the transport and terminate the dedicated Desktop sidecar.
  void detach() {
    unawaited(stopOwnedSidecar());
  }

  Future<void> stopOwnedSidecar() async {
    api.close();
    final process = _process;
    final sidecarPid = _sidecarPid;
    _process = null;
    _sidecarPid = null;
    if (process != null) {
      process.kill(ProcessSignal.sigterm);
      await process.exitCode
          .timeout(
            _shutdownGracePeriod,
            onTimeout: () {
              process.kill(ProcessSignal.sigkill);
              return -1;
            },
          )
          .catchError((Object _) => -1);
      await _deleteRegistryIfOwned(_sidecarRegistryFile(), process.pid);
      return;
    }
    if (sidecarPid != null && sidecarPid > 0) {
      final registry = _sidecarRegistryFile();
      final signaled = _pidKiller(sidecarPid, ProcessSignal.sigterm);
      if (signaled &&
          !await _waitForRegistryRemoval(registry, _shutdownGracePeriod)) {
        _pidKiller(sidecarPid, ProcessSignal.sigkill);
        await Future<void>.delayed(const Duration(milliseconds: 100));
      }
      await _deleteRegistryIfOwned(registry, sidecarPid);
    }
  }
}
