import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';

void main() {
  test('health rejects a sidecar from an older runtime revision', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));

    server.listen((request) async {
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'code': 0,
          'data': {'status': 'ok', 'protocol': 'sage.runtime/v2'},
        }),
      );
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    );
    addTearDown(api.close);

    expect(await api.health(), isFalse);
  });

  test('health rejects a sidecar from a different source build', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));

    server.listen((request) async {
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'code': 0,
          'data': {
            'status': 'ok',
            'protocol': sageSidecarProtocol,
            'revision': sageSidecarRevision,
            'build_id': 'old-build',
          },
        }),
      );
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    )..expectedBuildId = 'new-build';
    addTearDown(api.close);

    expect(await api.health(), isFalse);
  });

  test('delete session treats an already missing session as success', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));

    server.listen((request) async {
      expect(request.method, 'DELETE');
      expect(request.uri.path, '/api/v2/sessions/session_stale');
      request.response.statusCode = HttpStatus.notFound;
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'detail': {
            'code': 'session.not_found',
            'category': 'validation',
            'message': "resource 'session_stale' was not found",
          },
        }),
      );
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    );
    addTearDown(api.close);

    await api.deleteSession('session_stale');
  });

  test('structured runtime conflicts retain their typed details', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));

    server.listen((request) async {
      request.response.statusCode = HttpStatus.conflict;
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'detail': {
            'code': 'session.active_run',
            'category': 'conflict',
            'message': 'session tree still has an active run',
            'metadata': {
              'active_run_ids': ['run_child'],
              'active_session_ids': ['session_child'],
            },
          },
        }),
      );
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    );
    addTearDown(api.close);

    await expectLater(
      api.deleteSession('session_root'),
      throwsA(
        isA<SageApiException>()
            .having((error) => error.statusCode, 'statusCode', 409)
            .having((error) => error.code, 'code', 'session.active_run')
            .having((error) => error.category, 'category', 'conflict')
            .having(
              (error) => error.metadata['active_run_ids'],
              'active run ids',
              ['run_child'],
            )
            .having(
              (error) => error.toString(),
              'message',
              'session tree still has an active run',
            ),
      ),
    );
  });

  test('tool catalog sends the active interface language', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final received = Completer<Uri>();

    server.listen((request) async {
      received.complete(request.uri);
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({'code': 0, 'data': []}));
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    )..toolCatalogLanguage = 'zh-CN';
    addTearDown(api.close);

    await api.listTools();

    expect((await received.future).path, '/api/v2/tools');
    expect((await received.future).queryParameters['lang'], 'zh-CN');
  });

  test('skill catalog exposes ownership and deletion uses DELETE', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final requests = <String>[];

    server.listen((request) async {
      requests.add('${request.method} ${request.uri.path}');
      request.response.headers.contentType = ContentType.json;
      if (request.method == 'GET') {
        request.response.write(
          jsonEncode({
            'code': 0,
            'data': [
              {
                'name': 'review',
                'description': 'Review code',
                'can_delete': true,
              },
            ],
          }),
        );
      } else {
        request.response.write(
          jsonEncode({
            'code': 0,
            'data': {'deleted_name': 'review'},
          }),
        );
      }
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    );
    addTearDown(api.close);

    final catalog = await api.listSkillCatalog();
    await api.deleteSkill('review');

    expect(catalog.single.canDelete, isTrue);
    expect(requests, ['GET /api/v2/skills', 'DELETE /api/v2/skills/review']);
  });

  test('usage overview sends the range and decodes aggregate data', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final received = Completer<Uri>();

    server.listen((request) async {
      received.complete(request.uri);
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'code': 0,
          'data': {
            'range_days': 7,
            'data_quality': {
              'partial': true,
              'skipped_sessions': 2,
              'skipped_event_sessions': 1,
              'skipped_diagnostic_sessions': 1,
            },
            'totals': {
              'input_tokens': 100,
              'output_tokens': 42,
              'cached_input_tokens': 40,
              'total_tokens': 142,
              'turns': 2,
              'average_first_token_latency_ms': 725.5,
              'first_token_latency_p50_ms': 650.0,
              'first_token_latency_p95_ms': 1200.0,
              'first_token_latency_samples': 7,
              'output_tokens_per_second': 32.0,
              'output_tokens_per_second_p50': 30.0,
              'output_tokens_per_second_p95': 48.0,
              'output_tokens_per_second_samples': 6,
            },
            'daily': [],
            'models': [],
            'agents': [],
            'tools': [],
          },
        }),
      );
      await request.response.close();
    });

    final api = V2ApiClient(
      baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
    );
    addTearDown(api.close);

    final overview = await api.getUsageOverview(days: 7);

    expect((await received.future).path, '/api/v2/usage/overview');
    expect((await received.future).queryParameters['days'], '7');
    expect(
      (await received.future).queryParameters['timezone_offset_minutes'],
      isNotNull,
    );
    expect(overview.rangeDays, 7);
    expect(overview.dataQuality.partial, isTrue);
    expect(overview.dataQuality.skippedSessions, 2);
    expect(overview.dataQuality.skippedEventSessions, 1);
    expect(overview.dataQuality.skippedDiagnosticSessions, 1);
    expect(overview.totals.totalTokens, 142);
    expect(overview.totals.turns, 2);
    expect(overview.totals.cachedInputTokens, 40);
    expect(overview.totals.nonCachedInputTokens, 60);
    expect(overview.totals.promptCacheUtilization, .4);
    expect(overview.totals.averageFirstTokenLatencyMs, 725.5);
    expect(overview.totals.firstTokenLatencyP50Ms, 650.0);
    expect(overview.totals.firstTokenLatencyP95Ms, 1200.0);
    expect(overview.totals.firstTokenLatencySamples, 7);
    expect(overview.totals.outputTokensPerSecond, 32.0);
    expect(overview.totals.outputTokensPerSecondP50, 30.0);
    expect(overview.totals.outputTokensPerSecondP95, 48.0);
    expect(overview.totals.outputTokensPerSecondSamples, 6);
  });

  test(
    'agent runtime variables remain compatible with a reused sidecar',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      final received = Completer<Map<String, Object?>>();

      server.listen((request) async {
        final body =
            (jsonDecode(await utf8.decoder.bind(request).join()) as Map)
                .cast<String, Object?>();
        received.complete(body);
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'code': 0,
            'data': {
              'id': 'sage',
              'name': 'Sage',
              'system_context': body['system_context'],
            },
          }),
        );
        await request.response.close();
      });

      final api = V2ApiClient(
        baseUri: Uri.parse('http://127.0.0.1:${server.port}'),
      );
      addTearDown(api.close);

      final configuration = await api.patchAgentConfiguration('sage', {
        'runtime_variables': {'language': 'zh'},
      });

      expect(await received.future, {
        'system_context': {'language': 'zh'},
      });
      expect(configuration.runtimeVariables, {'language': 'zh'});
    },
  );
}
