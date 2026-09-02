import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/runtime_host.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';

class _RegistryApi extends V2ApiClient {
  _RegistryApi({this.healthyPorts = const {54321}});

  final Set<int> healthyPorts;

  @override
  Future<bool> health() async => healthyPorts.contains(baseUri.port);
}

class _FakeProcess implements Process {
  _FakeProcess({
    required this.pid,
    required int readyPort,
    this.exitOnSigterm = true,
  }) : _stdout = Stream.value(
         utf8.encode('${jsonEncode({'port': readyPort})}\n'),
       );

  @override
  final int pid;
  final bool exitOnSigterm;
  final Completer<int> _exitCode = Completer<int>();
  final IOSink _stdin = IOSink(StreamController<List<int>>().sink);
  final Stream<List<int>> _stdout;
  final List<ProcessSignal> killSignals = [];

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
      if (!_exitCode.isCompleted) _exitCode.complete(0);
    }
    return true;
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
        '"port":54321,"pid":123,"revision":3,"build_id":"test-build"}',
      );
      final api = _RegistryApi();
      final host = RuntimeHost(
        api: api,
        sidecarRegistryFile: registry,
        buildId: 'test-build',
      );

      await host.ensureReady();

      expect(api.baseUri, Uri.parse('http://127.0.0.1:54321'));
      expect(registry.existsSync(), isTrue);
    },
  );

  test(
    'RuntimeHost retires an unresponsive registered sidecar before spawn',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'sage-runtime-host-restart-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final registry = File('${directory.path}/desktop-v2-sidecar.json');
      await registry.writeAsString(
        '{"protocol":"sage.runtime/v2","host":"127.0.0.1",'
        '"port":54321,"pid":123,"revision":3,"build_id":"test-build"}',
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

      expect(killed, [(123, ProcessSignal.sigterm)]);
      expect(api.baseUri, Uri.parse('http://127.0.0.1:54322'));
    },
  );

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
