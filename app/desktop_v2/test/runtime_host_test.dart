import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/runtime_host.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';

class _RegistryApi extends V2ApiClient {
  _RegistryApi({
    this.healthyPorts = const {54321},
    this.shutdownOnDetach = true,
    this.idleShutdownResult = const {
      'active_clients': 0,
      'shutdown_requested': true,
    },
  });

  final Set<int> healthyPorts;
  final bool shutdownOnDetach;
  final Map<String, Object?> idleShutdownResult;
  int attachCalls = 0;
  int detachCalls = 0;
  int idleShutdownCalls = 0;

  @override
  Future<bool> health() async => healthyPorts.contains(baseUri.port);

  @override
  Future<Map<String, Object?>> attachRuntimeClient(String clientId) async {
    attachCalls += 1;
    return {'active_clients': 1, 'lease_ttl_seconds': 30};
  }

  @override
  Future<Map<String, Object?>> detachRuntimeClient(String clientId) async {
    detachCalls += 1;
    return {
      'active_clients': shutdownOnDetach ? 0 : 1,
      'shutdown_requested': shutdownOnDetach,
    };
  }

  @override
  Future<Map<String, Object?>> shutdownRuntimeIfIdle() async {
    idleShutdownCalls += 1;
    return idleShutdownResult;
  }
}

class _FakeProcess implements Process {
  _FakeProcess({
    required this.pid,
    required int readyPort,
    this.exitOnSigterm = true,
  }) : _stdout = Stream.value(
         utf8.encode(
           '${jsonEncode({'port': readyPort, 'auth_token': 'spawn-token'})}\n',
         ),
       );

  @override
  final int pid;
  final bool exitOnSigterm;
  final Completer<int> _exitCode = Completer<int>();
  final IOSink _stdin = IOSink(StreamController<List<int>>().sink);
  final Stream<List<int>> _stdout;
  final List<ProcessSignal> killSignals = [];

  void complete([int exitCode = 0]) {
    if (!_exitCode.isCompleted) _exitCode.complete(exitCode);
  }

  @override
  Future<int> get exitCode => _exitCode.future;

  @override
  IOSink get stdin => _stdin;

  @override
  Stream<List<int>> get stderr => const Stream.empty();

  @override
  Stream<List<int>> get stdout => _stdout;

  @override
  bool kill([ProcessSignal signal = ProcessSignal.sigterm]) {
    killSignals.add(signal);
    if ((signal == ProcessSignal.sigterm && exitOnSigterm) ||
        signal == ProcessSignal.sigkill) {
      complete();
    }
    return true;
  }
}

class _FailingLeaseApi extends _RegistryApi {
  _FailingLeaseApi() : super(healthyPorts: const {54322});

  @override
  Future<Map<String, Object?>> attachRuntimeClient(String clientId) {
    throw const SageApiException('lease attach failed');
  }
}

class _BlockingRenewalApi extends _RegistryApi {
  _BlockingRenewalApi() : super(shutdownOnDetach: false);

  final renewalStarted = Completer<void>();
  final releaseRenewal = Completer<void>();

  @override
  Future<Map<String, Object?>> attachRuntimeClient(String clientId) async {
    attachCalls += 1;
    if (attachCalls > 1) {
      if (!renewalStarted.isCompleted) renewalStarted.complete();
      await releaseRenewal.future;
    }
    return {'active_clients': 1};
  }
}

void main() {
  test(
    'RuntimeHost reconnects to a registered sidecar before spawning',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final registry = File('${directory.path}/desktop-v2-sidecar.json');
      await registry.writeAsString(
        '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
        '"port":54321,"pid":123,"revision":5,"build_id":"test-build",'
        '"auth_token":"registry-token"}',
      );
      final api = _RegistryApi();
      final host = RuntimeHost(
        api: api,
        sidecarRegistryFile: registry,
        buildId: 'test-build',
      );

      await host.ensureReady();

      expect(api.baseUri, Uri.parse('http://127.0.0.1:54321'));
      expect(api.authToken, 'registry-token');
      expect(api.attachCalls, 1);
      expect(registry.existsSync(), isTrue);
    },
  );

  test(
    'RuntimeHost does not terminate a sidecar owned by another host',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-shared-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final registry = File('${directory.path}/desktop-v2-sidecar.json');
      await registry.writeAsString(
        '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
        '"port":54321,"pid":123,"revision":5,"build_id":"test-build",'
        '"auth_token":"registry-token"}',
      );
      final killed = <(int, ProcessSignal)>[];
      final host = RuntimeHost(
        api: _RegistryApi(shutdownOnDetach: false),
        sidecarRegistryFile: registry,
        buildId: 'test-build',
        killPid: (pid, signal) {
          killed.add((pid, signal));
          return true;
        },
      );

      await host.ensureReady();
      await host.stopOwnedSidecar();

      expect(killed, isEmpty);
      expect(registry.existsSync(), isTrue);
    },
  );

  test(
    'RuntimeHost owner keeps a sidecar used by another client alive',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-owner-shared-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final process = _FakeProcess(pid: 456, readyPort: 54322);
      final api = _RegistryApi(
        healthyPorts: const {54322},
        shutdownOnDetach: false,
      );
      final host = RuntimeHost(
        api: api,
        sidecarRegistryFile: File('${directory.path}/desktop-v2-sidecar.json'),
        buildId: 'test-build',
        startProcess:
            (executable, arguments, {workingDirectory, environment}) async =>
                process,
        readPythonVersion: (executable) async => (3, 12),
        sidecarReadyAttempts: 1,
        sidecarPollInterval: Duration.zero,
      );

      await host.ensureReady();
      await host.stopOwnedSidecar();

      expect(api.detachCalls, 1);
      expect(process.killSignals, isEmpty);
    },
  );

  test(
    'RuntimeHost replaces stale discovery without signaling an unowned pid',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-restart-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final registry = File('${directory.path}/desktop-v2-sidecar.json');
      await registry.writeAsString(
        '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
        '"port":54321,"pid":123,"revision":5,"build_id":"test-build",'
        '"auth_token":"registry-token"}',
      );
      final api = _RegistryApi(healthyPorts: const {54322});
      final process = _FakeProcess(pid: 456, readyPort: 54322);
      final killed = <(int, ProcessSignal)>[];
      final host = RuntimeHost(
        api: api,
        sidecarRegistryFile: registry,
        buildId: 'test-build',
        startProcess:
            (executable, arguments, {workingDirectory, environment}) async =>
                process,
        readPythonVersion: (executable) async => (3, 12),
        killPid: (pid, signal) {
          killed.add((pid, signal));
          if (signal == ProcessSignal.sigterm) registry.deleteSync();
          return true;
        },
        terminationGracePeriod: Duration.zero,
        sidecarReadyAttempts: 1,
        sidecarPollInterval: Duration.zero,
      );

      await host.ensureReady();

      expect(killed, isEmpty);
      expect(api.baseUri, Uri.parse('http://127.0.0.1:54322'));
      expect(api.authToken, 'spawn-token');
    },
  );

  test('RuntimeHost does not replace an incompatible active sidecar', () async {
    final directory = await Directory.systemTemp.createTemp(
      'sage-runtime-host-active-upgrade-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final registry = File('${directory.path}/desktop-v2-sidecar.json');
    await registry.writeAsString(
      '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
      '"port":54321,"pid":123,"revision":5,"build_id":"old-build",'
      '"auth_token":"registry-token"}',
    );
    var spawned = false;
    final api = _RegistryApi(
      idleShutdownResult: const {
        'active_clients': 2,
        'shutdown_requested': false,
      },
    );
    final host = RuntimeHost(
      api: api,
      sidecarRegistryFile: registry,
      buildId: 'new-build',
      startProcess:
          (executable, arguments, {workingDirectory, environment}) async {
            spawned = true;
            return _FakeProcess(pid: 456, readyPort: 54322);
          },
      readPythonVersion: (executable) async => (3, 12),
    );

    await expectLater(
      host.ensureReady(),
      throwsA(
        isA<SageApiException>().having(
          (error) => error.message,
          'message',
          contains('2 active client'),
        ),
      ),
    );

    expect(api.idleShutdownCalls, 1);
    expect(spawned, isFalse);
    expect(registry.existsSync(), isTrue);
  });

  test(
    'RuntimeHost escalates sidecar shutdown when SIGTERM does not exit',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-shutdown-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final process = _FakeProcess(
        pid: 456,
        readyPort: 54322,
        exitOnSigterm: false,
      );
      final host = RuntimeHost(
        api: _RegistryApi(healthyPorts: const {54322}),
        sidecarRegistryFile: File('${directory.path}/desktop-v2-sidecar.json'),
        buildId: 'test-build',
        startProcess:
            (executable, arguments, {workingDirectory, environment}) async =>
                process,
        readPythonVersion: (executable) async => (3, 12),
        terminationGracePeriod: Duration.zero,
        sidecarReadyAttempts: 1,
        sidecarPollInterval: Duration.zero,
      );

      await host.ensureReady();
      await host.stopOwnedSidecar();

      expect(process.killSignals, [
        ProcessSignal.sigterm,
        ProcessSignal.sigkill,
      ]);
    },
  );

  test('RuntimeHost waits for the sidecar graceful shutdown', () async {
    final directory = await Directory.systemTemp.createTemp(
      'sage-runtime-host-graceful-shutdown-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final process = _FakeProcess(pid: 456, readyPort: 54322);
    final host = RuntimeHost(
      api: _RegistryApi(healthyPorts: const {54322}),
      sidecarRegistryFile: File('${directory.path}/desktop-v2-sidecar.json'),
      buildId: 'test-build',
      startProcess:
          (executable, arguments, {workingDirectory, environment}) async =>
              process,
      readPythonVersion: (executable) async => (3, 12),
      terminationGracePeriod: const Duration(milliseconds: 100),
      sidecarReadyAttempts: 1,
      sidecarPollInterval: Duration.zero,
    );

    await host.ensureReady();
    scheduleMicrotask(process.complete);
    await host.stopOwnedSidecar();

    expect(process.killSignals, isEmpty);
  });

  test('RuntimeHost drains an in-flight lease renewal before detach', () async {
    final directory = await Directory.systemTemp.createTemp(
      'sage-runtime-host-renewal-race-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final registry = File('${directory.path}/desktop-v2-sidecar.json');
    await registry.writeAsString(
      '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
      '"port":54321,"pid":123,"revision":5,"build_id":"test-build",'
      '"auth_token":"registry-token"}',
    );
    final api = _BlockingRenewalApi();
    final host = RuntimeHost(
      api: api,
      sidecarRegistryFile: registry,
      buildId: 'test-build',
      leaseHeartbeatInterval: const Duration(milliseconds: 1),
    );

    await host.ensureReady();
    await api.renewalStarted.future;
    final stopping = host.stopOwnedSidecar();
    await Future<void>.delayed(Duration.zero);
    expect(api.detachCalls, 0);

    api.releaseRenewal.complete();
    await stopping;
    expect(api.detachCalls, 1);
  });

  test(
    'RuntimeHost cleans up an owned sidecar when lease attach fails',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-lease-failure-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final process = _FakeProcess(pid: 456, readyPort: 54322);
      final host = RuntimeHost(
        api: _FailingLeaseApi(),
        sidecarRegistryFile: File('${directory.path}/desktop-v2-sidecar.json'),
        buildId: 'test-build',
        startProcess:
            (executable, arguments, {workingDirectory, environment}) async =>
                process,
        readPythonVersion: (executable) async => (3, 12),
        sidecarReadyAttempts: 1,
        sidecarPollInterval: Duration.zero,
      );

      await expectLater(host.ensureReady(), throwsA(isA<SageApiException>()));

      expect(process.killSignals, [ProcessSignal.sigterm]);
    },
  );

  test('RuntimeHost cannot restart after it has detached', () async {
    final directory = await Directory.systemTemp.createTemp(
      'sage-runtime-host-closed-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final registry = File('${directory.path}/desktop-v2-sidecar.json');
    await registry.writeAsString(
      '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
      '"port":54321,"pid":123,"revision":5,"build_id":"test-build",'
      '"auth_token":"registry-token"}',
    );
    final host = RuntimeHost(
      api: _RegistryApi(),
      sidecarRegistryFile: registry,
      buildId: 'test-build',
    );

    await host.ensureReady();
    await host.stopOwnedSidecar();

    await expectLater(
      host.ensureReady(),
      throwsA(
        isA<SageApiException>().having(
          (error) => error.message,
          'message',
          contains('closed'),
        ),
      ),
    );
  });

  test('RuntimeHost rejects Python older than 3.12 before spawn', () async {
    final directory = await Directory.systemTemp.createTemp(
      'sage-runtime-host-python-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    var spawned = false;
    final host = RuntimeHost(
      api: _RegistryApi(healthyPorts: const {}),
      sidecarRegistryFile: File('${directory.path}/desktop-v2-sidecar.json'),
      buildId: 'test-build',
      startProcess:
          (executable, arguments, {workingDirectory, environment}) async {
            spawned = true;
            return _FakeProcess(pid: 456, readyPort: 54322);
          },
      readPythonVersion: (executable) async => (3, 11),
      sidecarReadyAttempts: 1,
      sidecarPollInterval: Duration.zero,
    );

    await expectLater(
      host.ensureReady(),
      throwsA(
        isA<SageApiException>().having(
          (error) => error.message,
          'message',
          contains('Python 3.12'),
        ),
      ),
    );
    expect(spawned, isFalse);
  });
}
