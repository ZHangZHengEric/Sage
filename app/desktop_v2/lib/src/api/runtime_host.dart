import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

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
    Duration terminationGracePeriod = const Duration(seconds: 10),
    int sidecarReadyAttempts = 20,
    Duration sidecarPollInterval = const Duration(milliseconds: 100),
    this._leaseHeartbeatInterval = const Duration(seconds: 10),
    String? clientId,
    this.readPythonVersion = _inspectPythonVersion,
  }) : api = api ?? V2ApiClient(),
       _sidecarRegistryFileOverride = sidecarRegistryFile,
       _buildIdOverride = buildId,
       _processStarter = startProcess,
       _pidKiller = killPid,
       _shutdownGracePeriod = terminationGracePeriod,
       _registryReadyAttempts = sidecarReadyAttempts,
       _registryPollInterval = sidecarPollInterval,
       _clientId = clientId ?? _newClientId();

  final V2ApiClient api;
  final File? _sidecarRegistryFileOverride;
  final String? _buildIdOverride;
  final RuntimeProcessStarter _processStarter;
  final RuntimePidKiller _pidKiller;
  final RuntimePythonVersionReader readPythonVersion;
  final Duration _shutdownGracePeriod;
  final int _registryReadyAttempts;
  final Duration _registryPollInterval;
  final Duration _leaseHeartbeatInterval;
  final String _clientId;
  Process? _process;
  int? _sidecarPid;
  bool _ownsSidecar = false;
  bool _leaseAttached = false;
  Timer? _leaseHeartbeat;
  Future<void>? _leaseRenewal;
  Future<void>? _ensureReadyOperation;
  bool _closed = false;
  final StringBuffer _sidecarStderr = StringBuffer();

  Future<void> ensureReady() {
    if (_closed) {
      return Future<void>.error(
        const SageApiException('Sage Desktop v2 runtime host is closed.'),
      );
    }
    final active = _ensureReadyOperation;
    if (active != null) return active;
    late final Future<void> operation;
    operation = _ensureReadyWithCleanup().whenComplete(() {
      if (identical(_ensureReadyOperation, operation)) {
        _ensureReadyOperation = null;
      }
    });
    _ensureReadyOperation = operation;
    return operation;
  }

  Future<void> _ensureReadyWithCleanup() async {
    try {
      await _ensureReadyOnce();
    } on Object {
      await _cleanupFailedOwnedStartup();
      rethrow;
    }
  }

  Future<void> _ensureReadyOnce() async {
    final root = _findRepositoryRoot();
    final buildId = _buildIdOverride ?? await _sourceBuildId(root);
    api.expectedBuildId = buildId;
    if (await api.health()) {
      await _attachClientLease();
      return;
    }
    if (await _connectRegisteredSidecar(buildId)) {
      await _attachClientLease();
      return;
    }
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
    _ownsSidecar = true;
    unawaited(
      process.exitCode.then((_) {
        if (identical(_process, process)) _process = null;
        if (_sidecarPid == process.pid) _sidecarPid = null;
        _ownsSidecar = false;
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
    final readyEndpoint = Completer<(int, String)>();
    unawaited(
      stdoutLines
          .listen(
            (line) {
              try {
                final value = jsonDecode(line);
                final port = value is Map
                    ? (value['port'] as num?)?.toInt()
                    : null;
                final authToken = value is Map
                    ? value['auth_token']?.toString()
                    : null;
                if (port != null &&
                    port > 0 &&
                    authToken != null &&
                    authToken.isNotEmpty &&
                    !readyEndpoint.isCompleted) {
                  readyEndpoint.complete((port, authToken));
                }
              } on FormatException {
                // Existing Sage imports may log before the readiness envelope.
              }
            },
            onError: (Object error, StackTrace stackTrace) {
              if (!readyEndpoint.isCompleted) {
                readyEndpoint.completeError(error, stackTrace);
              }
            },
            onDone: () {
              if (!readyEndpoint.isCompleted) {
                readyEndpoint.completeError(
                  const SageApiException(
                    'Sage Desktop v2 sidecar exited before readiness.',
                  ),
                );
              }
            },
          )
          .asFuture<void>(),
    );
    late final (int, String) endpoint;
    try {
      endpoint = await readyEndpoint.future.timeout(
        const Duration(seconds: 10),
      );
    } on Object {
      await process.exitCode.timeout(
        const Duration(seconds: 1),
        onTimeout: () => -1,
      );
      if (await _connectRegisteredSidecar(buildId)) {
        await _attachClientLease();
        return;
      }
      throw _startupException(
        'Sage Desktop v2 sidecar exited before readiness.',
      );
    }
    final (port, authToken) = endpoint;
    api.baseUri = Uri.parse('http://127.0.0.1:$port');
    api.authToken = authToken;
    for (var attempt = 0; attempt < 120; attempt++) {
      if (await api.health()) {
        await _attachClientLease();
        return;
      }
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

  Future<void> _cleanupFailedOwnedStartup() async {
    if (!_ownsSidecar || _leaseAttached) return;
    final process = _process;
    final pid = _sidecarPid;
    _process = null;
    _sidecarPid = null;
    _ownsSidecar = false;
    api.authToken = null;
    if (process == null) return;
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
    await _deleteRegistryIfOwned(_sidecarRegistryFile(), pid ?? process.pid);
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
      final authToken = value['auth_token']?.toString() ?? '';
      if (host == null ||
          !_isLoopbackHost(host) ||
          port is! num ||
          port.toInt() <= 0) {
        return false;
      }
      if (value['revision'] != sageSidecarRevision ||
          value['build_id'] != buildId ||
          authToken.isEmpty) {
        await _retireIncompatibleSidecar(value, registry, host, port.toInt());
        return false;
      }
      final previous = api.baseUri;
      final previousAuthToken = api.authToken;
      api.baseUri = Uri.parse('http://$host:${port.toInt()}');
      api.authToken = authToken;
      // Registry publication happens immediately before Uvicorn starts. A
      // concurrently launched desktop process must give that matching sidecar
      // a short readiness window instead of deleting valid discovery data.
      for (var attempt = 0; attempt < _registryReadyAttempts; attempt++) {
        if (await api.health()) {
          final pid = value['pid'];
          _sidecarPid = pid is num && pid.toInt() > 0 ? pid.toInt() : null;
          _ownsSidecar = false;
          return true;
        }
        await Future<void>.delayed(_registryPollInterval);
      }
      api.baseUri = previous;
      api.authToken = previousAuthToken;
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
    if (value['revision'] == sageSidecarRevision &&
        _authTokenFrom(value).isNotEmpty &&
        _isLoopbackHost(host)) {
      final previous = api.baseUri;
      final previousAuthToken = api.authToken;
      api.baseUri = Uri.parse('http://$host:$port');
      api.authToken = _authTokenFrom(value);
      try {
        final result = await api.shutdownRuntimeIfIdle();
        if (result['shutdown_requested'] != true) {
          throw SageApiException(
            'A different Sage Desktop build is still serving '
            '${result['active_clients'] ?? 'unknown'} active client(s).',
          );
        }
        if (!await _waitForRegistryRemoval(registry, _shutdownGracePeriod)) {
          throw const SageApiException(
            'The previous Sage Desktop sidecar did not stop after an idle shutdown.',
          );
        }
        return;
      } on SageApiException {
        rethrow;
      } on Object {
        // An unreachable endpoint is stale discovery and can be removed below.
      } finally {
        api.baseUri = previous;
        api.authToken = previousAuthToken;
      }
    }
    await _retireRegisteredSidecar(value, registry);
  }

  static String _authTokenFrom(Map<dynamic, dynamic> value) =>
      value['auth_token']?.toString() ?? '';

  static bool _isLoopbackHost(String host) =>
      host == '127.0.0.1' || host == 'localhost';

  Future<void> _retireRegisteredSidecar(
    Map<dynamic, dynamic> value,
    File registry,
  ) async {
    final rawPid = value['pid'];
    final sidecarPid = rawPid is num ? rawPid.toInt() : 0;
    // A registry can outlive its process and its PID can later be reused. Never
    // signal a process that this RuntimeHost did not spawn and therefore cannot
    // identify by its Process handle. The SessionStore writer lock remains the
    // authoritative protection against accidentally provisioning two writers.
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

  Future<void> _attachClientLease() async {
    if (_leaseAttached) return;
    await api.attachRuntimeClient(_clientId);
    _leaseAttached = true;
    _leaseHeartbeat?.cancel();
    _leaseHeartbeat = Timer.periodic(_leaseHeartbeatInterval, (_) {
      _startLeaseRenewal();
    });
  }

  void _startLeaseRenewal() {
    if (_closed || !_leaseAttached || _leaseRenewal != null) return;
    late final Future<void> renewal;
    renewal = _renewClientLease().whenComplete(() {
      if (identical(_leaseRenewal, renewal)) _leaseRenewal = null;
    });
    _leaseRenewal = renewal;
  }

  Future<void> _renewClientLease() async {
    if (!_leaseAttached) return;
    try {
      await api.attachRuntimeClient(_clientId);
    } on Object {
      // A foreground API call will surface an unavailable sidecar. The lease
      // expires server-side, so a crashed or disconnected client cannot pin it.
    }
  }

  static String _newClientId() {
    final random = Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
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
    final version = await readPythonVersion(executable);
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
    if (_closed) return;
    _closed = true;
    final startup = _ensureReadyOperation;
    if (startup != null) {
      try {
        await startup;
      } on Object {
        // Startup already reports its own failure; shutdown still clears state.
      }
    }
    _leaseHeartbeat?.cancel();
    _leaseHeartbeat = null;
    final renewal = _leaseRenewal;
    if (renewal != null) await renewal;
    Map<String, Object?>? release;
    final hadLease = _leaseAttached;
    if (hadLease) {
      try {
        release = await api.detachRuntimeClient(_clientId);
      } on Object {
        // The server-side TTL will release this lease if the sidecar is alive.
      }
    }
    _leaseAttached = false;
    final process = _process;
    final sidecarPid = _sidecarPid;
    final ownsSidecar = _ownsSidecar;
    _process = null;
    _sidecarPid = null;
    _ownsSidecar = false;
    api.close();
    if (!ownsSidecar) return;
    if (hadLease && release == null) return;
    if (release != null && release['shutdown_requested'] != true) return;
    if (process != null) {
      // The detach response means the sidecar has already scheduled its own
      // Uvicorn shutdown. Let it drain requests and close durable stores before
      // escalating to process signals.
      final gracefulExit = await process.exitCode
          .timeout(_shutdownGracePeriod, onTimeout: () => -1)
          .catchError((Object _) => -1);
      if (gracefulExit != -1) {
        await _deleteRegistryIfOwned(_sidecarRegistryFile(), process.pid);
        return;
      }
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
