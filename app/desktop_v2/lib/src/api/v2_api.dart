import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:file_selector/file_selector.dart';

import '../models.dart';

class SageApiException implements Exception {
  const SageApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class V2ApiClient {
  V2ApiClient({Uri? baseUri, HttpClient? httpClient})
    : baseUri =
          baseUri ??
          Uri.parse(
            Platform.environment['SAGE_DESKTOP_V2_API'] ?? 'http://127.0.0.1:0',
          ),
      _http = httpClient ?? HttpClient();

  Uri baseUri;
  final HttpClient _http;

  Future<bool> health() async {
    try {
      final request = await _http
          .getUrl(baseUri.resolve('/health'))
          .timeout(const Duration(seconds: 1));
      final response = await request.close().timeout(
        const Duration(seconds: 1),
      );
      await response.drain<void>();
      return response.statusCode == HttpStatus.ok;
    } on Object {
      return false;
    }
  }

  Future<List<AgentSummary>> listAgents() async {
    final value = await _json('GET', '/api/v2/agents');
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                AgentSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<AgentConfiguration> createAgent(String name) async =>
      AgentConfiguration.fromJson(
        (await _json('POST', '/api/v2/agents', body: {'name': name}) as Map)
            .cast<String, Object?>(),
      );

  Future<List<SkillSummary>> listSkills(String agentId) async {
    final value = await _json(
      'GET',
      '/api/v2/agents/${Uri.encodeComponent(agentId)}/skills',
    );
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                SkillSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<AgentConfiguration> getAgentConfiguration(String agentId) async =>
      AgentConfiguration.fromJson(
        (await _json(
                  'GET',
                  '/api/v2/agents/${Uri.encodeComponent(agentId)}/settings',
                )
                as Map)
            .cast<String, Object?>(),
      );

  Future<AgentConfiguration> patchAgentConfiguration(
    String agentId,
    Map<String, Object?> patch,
  ) async => AgentConfiguration.fromJson(
    (await _json(
              'PATCH',
              '/api/v2/agents/${Uri.encodeComponent(agentId)}/settings',
              body: patch,
            )
            as Map)
        .cast<String, Object?>(),
  );

  Future<List<AgentSummary>> deleteAgent(String agentId) async {
    final value = await _json(
      'DELETE',
      '/api/v2/agents/${Uri.encodeComponent(agentId)}',
    );
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                AgentSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<List<ToolSummary>> listTools() async {
    final value = await _json('GET', '/api/v2/tools');
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                ToolSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<List<SkillSummary>> listSkillCatalog() async {
    final value = await _json('GET', '/api/v2/skills');
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                SkillSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<String> getSkillContent(String skillName) async {
    final value = await _json(
      'GET',
      '/api/v2/skills/${Uri.encodeComponent(skillName)}/content',
    );
    return value?.toString() ?? '';
  }

  Future<List<String>> importSkillFolder(String path) async {
    final value = await _json(
      'POST',
      '/api/v2/skills/import-folder',
      body: {'path': path},
    );
    final raw = value is Map ? value['imported_names'] : null;
    return raw is List ? [for (final item in raw) item.toString()] : const [];
  }

  Future<List<ModelProviderSummary>> listModelProviders() async {
    final value = await _json('GET', '/api/v2/model-providers');
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                ModelProviderSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<String> revealModelProviderApiKey(String providerId) async {
    final value =
        (await _json(
                  'GET',
                  '/api/v2/model-providers/${Uri.encodeComponent(providerId)}/api-key',
                )
                as Map)
            .cast<String, Object?>();
    return value['api_key']?.toString() ?? '';
  }

  Future<ModelProviderSummary> createModelProvider(
    Map<String, Object?> value,
  ) async => ModelProviderSummary.fromJson(
    (await _json('POST', '/api/v2/model-providers', body: value) as Map)
        .cast<String, Object?>(),
  );

  Future<ModelProviderSummary> patchModelProvider(
    String providerId,
    Map<String, Object?> patch,
  ) async => ModelProviderSummary.fromJson(
    (await _json(
              'PATCH',
              '/api/v2/model-providers/${Uri.encodeComponent(providerId)}',
              body: patch,
            )
            as Map)
        .cast<String, Object?>(),
  );

  Future<List<ModelProviderSummary>> deleteModelProvider(
    String providerId,
  ) async {
    final value = await _json(
      'DELETE',
      '/api/v2/model-providers/${Uri.encodeComponent(providerId)}',
    );
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                ModelProviderSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<List<McpConnectionSummary>> listMcpConnections() async {
    final value = await _json('GET', '/api/v2/mcp-connections');
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                McpConnectionSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<McpConnectionSummary> addMcpConnection(
    Map<String, Object?> value,
  ) async => McpConnectionSummary.fromJson(
    (await _json('POST', '/api/v2/mcp-connections', body: value) as Map)
        .cast<String, Object?>(),
  );

  Future<McpConnectionSummary> setMcpConnectionEnabled(
    String name,
    bool enabled,
  ) async => McpConnectionSummary.fromJson(
    (await _json(
              'PUT',
              '/api/v2/mcp-connections/${Uri.encodeComponent(name)}/enabled?enabled=$enabled',
            )
            as Map)
        .cast<String, Object?>(),
  );

  Future<List<ComponentSummary>> listComponents() async {
    final value = await _json('GET', '/api/v2/components');
    return value is List
        ? [
            for (final item in value)
              if (item is Map)
                ComponentSummary.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<void> selectComponent(String componentId, String pluginId) async {
    await _json(
      'PUT',
      '/api/v2/components/${Uri.encodeComponent(componentId)}/selection',
      body: {'plugin_id': pluginId, 'config': <String, Object?>{}},
    );
  }

  Future<DesktopSettings> getSettings() async => DesktopSettings.fromJson(
    (await _json('GET', '/api/v2/settings') as Map).cast<String, Object?>(),
  );

  Future<DesktopSettings> saveSettings(DesktopSettings settings) async =>
      DesktopSettings.fromJson(
        (await _json('PUT', '/api/v2/settings', body: settings.toJson()) as Map)
            .cast<String, Object?>(),
      );

  Future<DesktopProject> addProject(String path, {String name = ''}) async =>
      DesktopProject.fromJson(
        (await _json(
                  'POST',
                  '/api/v2/projects',
                  body: {'name': name, 'path': path},
                )
                as Map)
            .cast<String, Object?>(),
      );

  Future<void> removeProject(String projectId) async {
    await _json('DELETE', '/api/v2/projects/${Uri.encodeComponent(projectId)}');
  }

  Future<List<WorkspaceFileNode>> workspaceTree({
    required String agentId,
    String workspaceId = '',
  }) async {
    final uri = _uri('/api/v2/workspaces/tree', {
      'agent_id': agentId,
      if (workspaceId.isNotEmpty) 'workspace_id': workspaceId,
    });
    final value = await _jsonUri('GET', uri);
    final raw = value is Map ? value['files'] : null;
    return raw is List
        ? [
            for (final item in raw)
              if (item is Map)
                WorkspaceFileNode.fromJson(item.cast<String, Object?>()),
          ]
        : const [];
  }

  Future<WorkspaceFileContent> workspaceFile({
    required String agentId,
    required String path,
    String workspaceId = '',
  }) async {
    final request = await _http.getUrl(
      _uri('/api/v2/workspaces/file', {
        'agent_id': agentId,
        'path': path,
        if (workspaceId.isNotEmpty) 'workspace_id': workspaceId,
      }),
    );
    final response = await request.close();
    final bytes = await _responseBytes(response);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw _httpError(response.statusCode, utf8.decode(bytes));
    }
    return WorkspaceFileContent(
      bytes: bytes,
      mediaType:
          response.headers.contentType?.mimeType ?? 'application/octet-stream',
    );
  }

  Future<UploadedAttachment> upload({
    required String agentId,
    required XFile file,
    String workspaceId = '',
  }) async {
    final boundary =
        '----sage-v2-${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(1 << 32)}';
    final bytes = await file.readAsBytes();
    final request = await _http.postUrl(
      baseUri.resolve('/api/v2/workspaces/upload'),
    );
    request.headers.set(
      HttpHeaders.contentTypeHeader,
      'multipart/form-data; boundary=$boundary',
    );
    void field(String name, String value) {
      request.write('--$boundary\r\n');
      request.write('Content-Disposition: form-data; name="$name"\r\n\r\n');
      request.write('$value\r\n');
    }

    field('agent_id', agentId);
    if (workspaceId.isNotEmpty) field('workspace_id', workspaceId);
    request.write('--$boundary\r\n');
    request.write(
      'Content-Disposition: form-data; name="file"; filename="${_safeHeader(file.name)}"\r\n',
    );
    request.write('Content-Type: application/octet-stream\r\n\r\n');
    request.add(bytes);
    request.write('\r\n--$boundary--\r\n');
    final response = await request.close();
    final decoded = await _decodeResponse(response);
    final data = _unwrap(decoded, response.statusCode);
    return UploadedAttachment.fromJson((data as Map).cast<String, Object?>());
  }

  Stream<Map<String, Object?>> startRun(Map<String, Object?> body) =>
      _ndjson('POST', '/api/v2/runs/stream', body: body);

  Stream<Map<String, Object?>> subscribeRun(
    String runId, {
    required int afterSequence,
  }) => _ndjson(
    'GET',
    '/api/v2/runs/${Uri.encodeComponent(runId)}/events?after_sequence=$afterSequence',
  );

  Future<Map<String, Object?>> getRun(String runId) async =>
      (await _json('GET', '/api/v2/runs/${Uri.encodeComponent(runId)}') as Map)
          .cast<String, Object?>();

  Future<void> pause(String runId) =>
      _command('/api/v2/runs/${Uri.encodeComponent(runId)}/pause');

  Future<void> resume(String runId) =>
      _command('/api/v2/runs/${Uri.encodeComponent(runId)}/resume');

  Future<void> cancel(String runId) =>
      _command('/api/v2/runs/${Uri.encodeComponent(runId)}/cancel');

  Future<void> deleteSession(String sessionId) async {
    await _json('DELETE', '/api/v2/sessions/${Uri.encodeComponent(sessionId)}');
  }

  Future<void> steer(String runId, String turnId, String text) => _command(
    '/api/v2/runs/${Uri.encodeComponent(runId)}/steer',
    body: {'turn_id': turnId, 'text': text},
  );

  Future<void> replyInteraction(
    String runId, {
    required String interactionId,
    required String decision,
    Map<String, Object?> payload = const {},
  }) => _command(
    '/api/v2/runs/${Uri.encodeComponent(runId)}/interactions/reply',
    body: {
      'interaction_id': interactionId,
      'decision': decision,
      'payload': payload,
    },
  );

  Future<void> _command(
    String path, {
    Map<String, Object?> body = const {},
  }) async {
    await _json('POST', path, body: body);
  }

  Stream<Map<String, Object?>> _ndjson(
    String method,
    String path, {
    Map<String, Object?>? body,
  }) async* {
    final request = await _request(method, baseUri.resolve(path), body: body);
    final response = await request.close();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final text = await response.transform(utf8.decoder).join();
      throw _httpError(response.statusCode, text);
    }
    await for (final line
        in response.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.trim().isEmpty) continue;
      final decoded = jsonDecode(line);
      if (decoded is Map) yield decoded.cast<String, Object?>();
    }
  }

  Future<Object?> _json(
    String method,
    String path, {
    Map<String, Object?>? body,
  }) => _jsonUri(method, baseUri.resolve(path), body: body);

  Future<Object?> _jsonUri(
    String method,
    Uri uri, {
    Map<String, Object?>? body,
  }) async {
    final request = await _request(method, uri, body: body);
    final response = await request.close();
    final decoded = await _decodeResponse(response);
    return _unwrap(decoded, response.statusCode);
  }

  Future<HttpClientRequest> _request(
    String method,
    Uri uri, {
    Map<String, Object?>? body,
  }) async {
    final request = await _http.openUrl(method, uri);
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    if (body != null) {
      final bytes = utf8.encode(jsonEncode(body));
      request.headers.contentType = ContentType.json;
      request.contentLength = bytes.length;
      request.add(bytes);
    }
    return request;
  }

  Future<Object?> _decodeResponse(HttpClientResponse response) async {
    final text = await response.transform(utf8.decoder).join();
    if (text.isEmpty) return null;
    try {
      return jsonDecode(text);
    } on FormatException {
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw _httpError(response.statusCode, text);
      }
      rethrow;
    }
  }

  Object? _unwrap(Object? decoded, int statusCode) {
    if (statusCode < 200 || statusCode >= 300) {
      throw _httpError(statusCode, jsonEncode(decoded));
    }
    if (decoded is Map) {
      if (decoded['code'] == 0) return decoded['data'];
      if (decoded.containsKey('detail')) {
        throw SageApiException(
          decoded['detail'].toString(),
          statusCode: statusCode,
        );
      }
    }
    return decoded;
  }

  SageApiException _httpError(int statusCode, String body) {
    var message = body;
    try {
      final value = jsonDecode(body);
      if (value is Map) {
        message = (value['detail'] ?? value['message'] ?? body).toString();
      }
    } on FormatException {
      // Keep the original response body.
    }
    return SageApiException(message, statusCode: statusCode);
  }

  Uri _uri(String path, Map<String, String> query) =>
      baseUri.resolve(path).replace(queryParameters: query);

  Future<Uint8List> _responseBytes(HttpClientResponse response) async {
    final builder = BytesBuilder(copy: false);
    await for (final value in response) {
      builder.add(value);
    }
    return builder.takeBytes();
  }

  String _safeHeader(String value) => value.replaceAll(RegExp(r'[\r\n"]'), '_');

  void close() => _http.close(force: true);
}
