import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/cupertino.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/localization/app_localizations.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/usage_models.dart';
import 'package:sage_desktop_v2/src/ui/file_preview.dart';
import 'package:sage_desktop_v2/src/ui/tool_activity_presentation.dart';
import 'package:sage_desktop_v2/src/ui/usage_overview.dart';

class _FakeApi extends V2ApiClient {
  final _sessionTreeEvents = StreamController<Map<String, Object?>>.broadcast();
  Map<String, Object?>? lastAgentPatch;
  String? lastCreatedAgentName;
  Map<String, Object?>? lastModelPatch;
  Map<String, Object?>? lastModelCreate;
  Map<String, Object?>? lastModelCapabilityDraft;
  Map<String, Object?>? modelCapabilityResult;
  String? lastModelCapabilityProviderId;
  DesktopSettings? lastSettings;
  String? lastDeletedModelId;
  String? lastDeletedAgentId;
  String? lastDeletedSkillName;
  String? lastDeletedSessionId;
  String? lastRemovedProjectId;
  Map<String, Object?>? lastRunBody;
  int workspaceTreeCalls = 0;
  int workspaceFileCalls = 0;
  String? lastWorkspaceFileAgentId;
  String? lastWorkspaceFileId;
  String? lastWorkspaceFilePath;
  Object? workspaceFileError;
  int? lastUsageDays;
  UsageDataQuality usageDataQuality = const UsageDataQuality();
  String? lastWorkspaceTreeId;
  String? importedSkillFolder;
  String? lastSelectedComponent;
  String? lastSelectedComponentPlugin;
  Map<String, Object?>? lastSelectedComponentConfig;
  int sessionTreeSnapshotCalls = 0;
  int sessionTreeSubscriptionCalls = 0;
  bool skillDeleted = false;
  WorkspaceFileContent workspaceFileContent = WorkspaceFileContent(
    bytes: Uint8List.fromList('Sage v2 workspace'.codeUnits),
    mediaType: 'text/plain',
  );
  DesktopSettings desktopSettings = const DesktopSettings(
    language: 'zh',
    agentWorkspacePath: '/tmp/sage/agent_workspace',
    projects: [
      DesktopProject(
        id: 'project_demo',
        name: 'Demo Project',
        path: '/tmp/demo-project',
      ),
    ],
  );

  @override
  Future<List<AgentSummary>> listAgents() async => const [
    AgentSummary(id: 'agent_main', name: 'Sage Agent', isDefault: true),
    AgentSummary(id: 'agent_review', name: 'Review Agent'),
  ];

  @override
  Future<DesktopSettings> getSettings() async => desktopSettings;

  @override
  Future<UsageOverview> getUsageOverview({int days = 30}) async {
    lastUsageDays = days;
    return UsageOverview(
      rangeDays: days,
      dataQuality: usageDataQuality,
      totals: const UsageTotals(
        inputTokens: 12000,
        outputTokens: 3000,
        cachedInputTokens: 4000,
        totalTokens: 15000,
        modelRequests: 8,
        failedModelRequests: 1,
        turns: 5,
        toolCalls: 4,
        sessions: 2,
        averageFirstTokenLatencyMs: 725.5,
        firstTokenLatencyP50Ms: 680.0,
        firstTokenLatencyP95Ms: 1350.0,
        firstTokenLatencySamples: 8,
        outputTokensPerSecond: 32.0,
        outputTokensPerSecondP50: 30.0,
        outputTokensPerSecondP95: 48.0,
        outputTokensPerSecondSamples: 7,
      ),
      daily: [
        UsageDay(
          date: DateTime(2026, 8, 29),
          inputTokens: 12000,
          outputTokens: 3000,
          cachedInputTokens: 4000,
          totalTokens: 15000,
          turns: 5,
          toolCalls: 4,
        ),
      ],
      models: const [
        UsageBreakdown(
          name: 'test-model',
          inputTokens: 12000,
          outputTokens: 3000,
          cachedInputTokens: 4000,
          totalTokens: 15000,
          requests: 8,
        ),
      ],
      agents: const [
        UsageBreakdown(
          id: 'agent_main',
          name: 'Sage Agent',
          inputTokens: 12000,
          outputTokens: 3000,
          cachedInputTokens: 4000,
          totalTokens: 15000,
          requests: 8,
          turns: 5,
          toolCalls: 4,
        ),
      ],
      tools: const [ToolUsage(name: 'read_file', count: 4)],
    );
  }

  @override
  Future<List<SkillSummary>> listSkills(String agentId) async => skillDeleted
      ? const []
      : const [SkillSummary(name: 'code-review', canDelete: true)];

  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) async =>
      AgentConfiguration(
        id: agentId,
        name: agentId == 'agent_review' ? 'Review Agent' : 'Sage Agent',
        systemPrefix: '# Sage\n\n- Follow instructions.',
        systemContext: const {
          'language': 'zh',
          'preferences': {'concise': true},
        },
        deepThinking: true,
        thinkingLevel: 'medium',
        availableTools: const ['read_file'],
        availableSkills: skillDeleted ? const [] : const ['code-review'],
        shellPolicy: const ShellPolicySummary(
          autoExecuteKeywords: ['git push (non-force)', 'relative rm -rf'],
          approvalKeywords: ['git reset --hard', 'git clean'],
          blockedKeywords: ['sudo / su', 'curl|sh / wget|bash'],
          userApprovedCommands: ['git clean -fd'],
        ),
      );

  @override
  Future<AgentConfiguration> patchAgentConfiguration(
    String agentId,
    Map<String, Object?> patch,
  ) async {
    lastAgentPatch = patch;
    return (await getAgentConfiguration(agentId)).applyPatch(patch);
  }

  @override
  Future<AgentConfiguration> createAgent(String name) async {
    lastCreatedAgentName = name;
    return AgentConfiguration(
      id: 'agent_created',
      name: name,
      systemPrefix: 'You are a helpful Sage agent.',
      systemContext: const {},
      agentMode: 'simple',
      maxLoopCount: 48,
      deepThinking: false,
      thinkingLevel: 'medium',
      llmProviderId: 'model_main',
      availableTools: const ['read_file'],
      availableSkills: const [],
    );
  }

  @override
  Future<List<AgentSummary>> deleteAgent(String agentId) async {
    lastDeletedAgentId = agentId;
    return const [
      AgentSummary(id: 'agent_main', name: 'Sage Agent', isDefault: true),
    ];
  }

  @override
  Future<List<ToolSummary>> listTools() async => const [
    ToolSummary(
      name: 'read_file',
      description: '读取文件',
      source: '基础工具',
      inputSchema: {
        'type': 'object',
        'properties': {
          'path': {'type': 'string'},
        },
        'required': ['path'],
      },
      parameters: {
        'path': {'type': 'string'},
      },
      required: ['path'],
    ),
  ];

  @override
  Future<List<SkillSummary>> listSkillCatalog() async => skillDeleted
      ? const []
      : const [
          SkillSummary(
            name: 'code-review',
            description: 'Review code safely',
            canDelete: true,
          ),
        ];

  @override
  Future<String> getSkillContent(String skillName) async => '''---
name: code-review
description: Review code safely
---
# Code Review

Inspect the complete diff before reporting findings.
''';

  @override
  Future<List<String>> importSkillFolder(String path) async {
    importedSkillFolder = path;
    skillDeleted = false;
    return const ['code-review'];
  }

  @override
  Future<void> deleteSkill(String skillName) async {
    lastDeletedSkillName = skillName;
    skillDeleted = true;
  }

  @override
  Future<List<ModelProviderSummary>> listModelProviders() async => const [
    ModelProviderSummary(
      id: 'model_main',
      name: 'Primary',
      model: 'test-model',
      baseUrl: 'https://example.test/v1',
      apiKeyConfigured: true,
      isDefault: true,
      compatibilityProfile: {
        'schema_version': 2,
        'reasoning_behavior': 'controllable',
        'supported_reasoning_efforts': ['low', 'high'],
      },
    ),
    ModelProviderSummary(
      id: 'model_secondary',
      name: 'Secondary',
      model: 'test-model-secondary',
      baseUrl: 'https://example.test/v1',
      apiKeyConfigured: true,
      compatibilityProfile: {
        'schema_version': 2,
        'reasoning_behavior': 'always',
        'supported_reasoning_efforts': <String>[],
      },
    ),
    ModelProviderSummary(
      id: 'model_luna',
      name: 'Luna',
      model: 'gpt-5.6-luna',
      baseUrl: 'https://example.test/v1',
      apiKeyConfigured: true,
      compatibilityProfile: {
        'schema_version': 2,
        'reasoning_behavior': 'none',
        'supported_reasoning_efforts': <String>[],
        'text_only_reasoning_efforts': ['low', 'medium', 'high', 'xhigh'],
      },
    ),
  ];

  @override
  Future<String> revealModelProviderApiKey(String providerId) async =>
      'sk-visible-test';

  @override
  Future<ModelProviderSummary> createModelProvider(
    Map<String, Object?> value,
  ) async {
    lastModelCreate = value;
    return ModelProviderSummary(
      id: 'model_created',
      name: value['name']?.toString() ?? 'New Model',
      protocol: value['protocol']?.toString() ?? 'openai-responses',
      model: value['model']?.toString() ?? 'gpt-5.4',
      baseUrl: value['base_url']?.toString() ?? 'https://api.openai.com/v1',
      apiKeyConfigured: (value['api_keys'] as List?)?.isNotEmpty == true,
      supportsMultimodal: value['supports_multimodal'] as bool? ?? true,
      supportsStructuredOutput: true,
      supportsToolCalling: true,
      maxTokens: value['max_tokens'] as int?,
      maxModelLength: value['max_model_len'] as int?,
    );
  }

  @override
  Future<ModelProviderSummary> patchModelProvider(
    String providerId,
    Map<String, Object?> patch,
  ) async {
    lastModelPatch = patch;
    final compatibility = patch['compatibility_profile'];
    return ModelProviderSummary(
      id: providerId,
      name:
          patch['name']?.toString() ??
          (providerId == 'model_secondary' ? 'Secondary' : 'Primary'),
      protocol: patch['protocol']?.toString() ?? 'openai-responses',
      model:
          patch['model']?.toString() ??
          (providerId == 'model_secondary'
              ? 'test-model-secondary'
              : 'test-model'),
      baseUrl: patch['base_url']?.toString() ?? 'https://example.test/v1',
      apiKeyConfigured: true,
      supportsMultimodal: patch['supports_multimodal'] as bool? ?? true,
      isDefault: patch['is_default'] == true || providerId == 'model_main',
      compatibilityProfile: compatibility is Map
          ? compatibility.cast<String, Object?>()
          : null,
    );
  }

  @override
  Future<Map<String, Object?>> verifyModelProviderCapabilities(
    Map<String, Object?> draft, {
    String? providerId,
  }) async {
    lastModelCapabilityDraft = Map<String, Object?>.of(draft);
    lastModelCapabilityProviderId = providerId;
    return modelCapabilityResult ??
        const {
          'connection': {'supported': true},
          'supports_multimodal': true,
          'supports_structured_output': true,
          'supports_tool_calling': true,
          'compatibility_profile': {
            'schema_version': 2,
            'route_fingerprint': 'sha256:verified-route',
            'verified_at': '2026-09-01T00:00:00Z',
            'max_output_tokens_field': 'max_completion_tokens',
            'effective_max_output_tokens': 4096,
            'reasoning_disable_strategy': 'omit',
            'reasoning_behavior': 'controllable',
            'reasoning_effort_strategy': 'reasoning_effort',
            'supported_reasoning_efforts': ['low', 'high'],
            'text_only_reasoning_efforts': ['xhigh'],
            'unsupported_reasoning_efforts': ['minimal', 'medium', 'max'],
            'supports_json_object': true,
            'auxiliary_json_compatible': true,
            'successful_probes': [
              'connection',
              'structured_output',
              'json_object',
              'tool_calling',
            ],
            'failed_probes': <String>[],
          },
        };
  }

  @override
  Future<List<ModelProviderSummary>> deleteModelProvider(
    String providerId,
  ) async {
    lastDeletedModelId = providerId;
    return const [
      ModelProviderSummary(
        id: 'model_main',
        name: 'Primary',
        model: 'test-model',
        baseUrl: 'https://example.test/v1',
        apiKeyConfigured: true,
        isDefault: true,
      ),
    ];
  }

  @override
  Future<void> deleteSession(String sessionId) async {
    lastDeletedSessionId = sessionId;
  }

  @override
  Future<List<Map<String, Object?>>> getSessionTree(String sessionId) async {
    sessionTreeSnapshotCalls += 1;
    return const [];
  }

  @override
  Stream<Map<String, Object?>> subscribeSessionTree(String sessionId) {
    sessionTreeSubscriptionCalls += 1;
    return _sessionTreeEvents.stream;
  }

  @override
  Future<List<McpConnectionSummary>> listMcpConnections() async => const [
    McpConnectionSummary(name: 'filesystem', protocol: 'stdio', toolCount: 2),
  ];

  @override
  Future<List<ComponentSummary>> listComponents() async => const [
    ComponentSummary(
      id: 'agent.continuation-policy',
      name: 'Run completion policy',
      value: 'Decides when a run completes.',
      selectionMode: 'user',
      applyMode: 'next_run',
      scope: 'run',
      activePluginId: 'sage.agent.continuation.deterministic',
      activeConfig: {
        'repeat_threshold': 3,
        'mode': 'deterministic',
        'completion_reason': 'text.final',
        'status_source': 'turn_status',
        'explicit_statuses': [
          'task_done',
          'need_user_input',
          'blocked',
          'continue_work',
          'failed',
        ],
        'flow_boundaries': ['complete_node', 'continue_node'],
        'uses_llm_judge': false,
        'uses_finish_reason': false,
      },
      plugins: [
        ComponentPluginSummary(
          id: 'sage.agent.continuation.deterministic',
          name: 'Deterministic completion rules',
          value: 'Uses tools and final text.',
        ),
        ComponentPluginSummary(
          id: 'sage.agent.continuation.llm-judge',
          name: 'LLM Judge completion policy',
          value: 'Uses a separate Judge request.',
        ),
        ComponentPluginSummary(
          id: 'sage.agent.continuation.explicit-status',
          name: 'Explicit status only',
          value: 'Requires turn_status.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'tool.selection-policy',
      name: 'Tool selection policy',
      value: 'Bounds large Tool catalogs.',
      selectionMode: 'user',
      applyMode: 'next_run',
      scope: 'agent',
      activePluginId: 'sage.tool-selection.llm',
      selectedPluginId: 'sage.tool-selection.llm',
      activeConfig: {'max_visible_tools': 24},
      plugins: [
        ComponentPluginSummary(
          id: 'sage.tool-selection.direct',
          name: 'Direct Tool selection',
          value: 'Shows every Tool.',
        ),
        ComponentPluginSummary(
          id: 'sage.tool-selection.llm',
          name: 'LLM Tool selection',
          value: 'Uses a fast model.',
          configSchema: {
            'properties': {
              'max_visible_tools': {
                'type': 'integer',
                'minimum': 1,
                'maximum': 10000,
                'default': 24,
              },
            },
          },
        ),
        ComponentPluginSummary(
          id: 'sage.tool-selection.lexical',
          name: 'BM25 Tool selection',
          value: 'Selects relevant Tools.',
          configSchema: {
            'properties': {
              'max_visible_tools': {
                'type': 'integer',
                'minimum': 1,
                'maximum': 10000,
                'default': 24,
              },
            },
          },
        ),
        ComponentPluginSummary(
          id: 'sage.tool-selection.recent',
          name: 'Recent Tool selection',
          value: 'Keeps recent Tools first.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'context.reducer',
      name: 'Context reducer',
      value: 'Keeps requests inside model limits.',
      selectionMode: 'user',
      applyMode: 'next_run',
      scope: 'tenant',
      activePluginId: 'sage.context.reducer.persistent-summary',
      plugins: [
        ComponentPluginSummary(
          id: 'sage.context.reducer.persistent-summary',
          name: 'Persistent summary',
          value: 'Summarizes old complete message units.',
        ),
        ComponentPluginSummary(
          id: 'sage.context.reducer.window',
          name: 'Window reducer',
          value: 'Drops old complete message units.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'model.protocol',
      name: 'Model protocol',
      value: 'Selected by each model route.',
      selectionMode: 'model_route',
      applyMode: 'locked',
      scope: 'agent-model-route',
      plugins: [
        ComponentPluginSummary(
          id: 'openai-responses',
          name: 'OpenAI Responses',
          value: 'Uses typed Responses items.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'memory.provider',
      name: 'Long-term memory',
      value: 'Recalls and writes long-term memory.',
      selectionMode: 'user',
      applyMode: 'restart',
      scope: 'process',
      activePluginId: 'sage.memory.filesystem-bm25',
      activeConfig: {
        'path': '/Users/test/sage/runtime/memory',
        'recall': true,
        'auto_write': true,
        'scope_mode': 'agent',
      },
      plugins: [
        ComponentPluginSummary(
          id: 'sage.memory.filesystem-bm25',
          name: 'Local BM25 memory',
          value: 'Persists and retrieves memory locally.',
        ),
        ComponentPluginSummary(
          id: 'sage.memory.noop',
          name: 'Memory off',
          value: 'Disables recall and writing.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'memory.recall-query',
      name: 'Memory query generation',
      value: 'Chooses how search_memory builds its query.',
      selectionMode: 'user',
      applyMode: 'next_run',
      scope: 'agent',
      activePluginId: 'sage.memory.recall-query.direct',
      plugins: [
        ComponentPluginSummary(
          id: 'sage.memory.recall-query.direct',
          name: 'Direct user input',
          value: 'Uses the current user input directly.',
        ),
        ComponentPluginSummary(
          id: 'sage.memory.recall-query.llm',
          name: 'LLM-generated keywords',
          value: 'Uses the fast model to generate retrieval keywords.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'session-memory.provider',
      name: 'session-memory.provider',
      value: 'session-memory.provider',
      selectionMode: 'user',
      applyMode: 'restart',
      scope: 'process',
      activePluginId: 'sage.session-memory.sqlite-bm25',
      activeConfig: {
        'path': '/Users/test/sage/runtime/session-memory',
        'derived_from': 'session.events',
      },
      plugins: [
        ComponentPluginSummary(
          id: 'sage.session-memory.noop',
          name: 'No-op Session Memory provider',
          value: 'Disables Session Memory.',
        ),
        ComponentPluginSummary(
          id: 'sage.session-memory.sqlite-bm25',
          name: 'SQLite BM25 Session Memory provider',
          value: 'Indexes Session history.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'observability.diagnostic-sink',
      name: 'Model diagnostics',
      value: 'Stores model diagnostics.',
      selectionMode: 'host',
      applyMode: 'restart',
      scope: 'process',
      activePluginId: 'sage.observability.filesystem',
      activeConfig: {'path': '/Users/test/sage/runtime/diagnostics'},
      plugins: [
        ComponentPluginSummary(
          id: 'sage.observability.filesystem',
          name: 'Filesystem diagnostics',
          value: 'Writes model diagnostics.',
        ),
        ComponentPluginSummary(
          id: 'sage.observability.noop',
          name: 'No-op diagnostics',
          value: 'Disables model diagnostics.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'observability.log-sink',
      name: 'Structured logging',
      value: 'Records operational failures.',
      selectionMode: 'user',
      applyMode: 'restart',
      scope: 'process',
      activePluginId: 'sage.logging.filesystem',
      activeConfig: {
        'format_version': 'sage.log/v1',
        'path': '/Users/test/sage/runtime/logs/sage.jsonl',
        'min_level': 'info',
        'max_bytes': 10485760,
        'backup_count': 5,
      },
      plugins: [
        ComponentPluginSummary(
          id: 'sage.logging.filesystem',
          name: 'Rotating filesystem structured log sink',
          value: 'Writes redacted rotating JSONL files.',
        ),
        ComponentPluginSummary(
          id: 'sage.logging.noop',
          name: 'No-op structured log sink',
          value: 'Disables operational log persistence.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'execution.sandbox',
      name: 'Execution sandbox',
      value: 'Applies sandbox workspace and execution policy.',
      selectionMode: 'host',
      applyMode: 'next_run',
      scope: 'run',
      activePluginId: 'sage.sandbox.local-workspace',
      activeConfig: {
        'workspace_root': '/workspace',
        'workspace_path_mode': 'virtual',
        'workspace_mapping': 'active_workspace',
        'filesystem_mode': 'workspace',
      },
      plugins: [
        ComponentPluginSummary(
          id: 'sage.sandbox.local-workspace',
          name: 'Local workspace sandbox',
          value: 'Maps the active workspace.',
        ),
        ComponentPluginSummary(
          id: 'sage.sandbox.ephemeral',
          name: 'Ephemeral sandbox',
          value: 'Uses an isolated filesystem.',
        ),
      ],
    ),
    ComponentSummary(
      id: 'workspace.initializer',
      name: 'Workspace initialization',
      value: 'Seeds Agent Workspace files and folders on first use.',
      selectionMode: 'user',
      applyMode: 'immediate',
      scope: 'agent',
      activePluginId: 'sage.workspace.initializer.claw',
      plugins: [
        ComponentPluginSummary(
          id: 'sage.workspace.initializer.claw',
          name: 'Claw Mode workspace',
          value: 'Seeds identity, memory, and working folders.',
        ),
        ComponentPluginSummary(
          id: 'sage.workspace.initializer.bare',
          name: 'Bare workspace',
          value: 'Seeds nothing.',
        ),
      ],
    ),
  ];

  @override
  Future<void> selectComponent(
    String componentId,
    String pluginId, {
    Map<String, Object?> config = const {},
  }) async {
    lastSelectedComponent = componentId;
    lastSelectedComponentPlugin = pluginId;
    lastSelectedComponentConfig = config;
  }

  @override
  Future<DesktopSettings> saveSettings(DesktopSettings settings) async {
    lastSettings = settings;
    desktopSettings = settings;
    return settings;
  }

  @override
  Future<void> removeProject(String projectId) async {
    lastRemovedProjectId = projectId;
  }

  @override
  Future<List<WorkspaceFileNode>> workspaceTree({
    required String agentId,
    String workspaceId = '',
  }) async {
    workspaceTreeCalls += 1;
    lastWorkspaceTreeId = workspaceId;
    return const [
      WorkspaceFileNode(
        name: 'projects',
        path: 'projects',
        isDirectory: true,
        size: 0,
        children: [
          WorkspaceFileNode(
            name: 'example.py',
            path: 'projects/example.py',
            isDirectory: false,
            size: 8,
          ),
        ],
      ),
      WorkspaceFileNode(
        name: 'README.md',
        path: 'README.md',
        isDirectory: false,
        size: 12,
      ),
    ];
  }

  @override
  Future<WorkspaceFileContent> workspaceFile({
    required String agentId,
    required String path,
    String workspaceId = '',
  }) async {
    workspaceFileCalls += 1;
    lastWorkspaceFileAgentId = agentId;
    lastWorkspaceFileId = workspaceId;
    lastWorkspaceFilePath = path;
    final failure = workspaceFileError;
    if (failure != null) throw failure;
    return workspaceFileContent;
  }

  @override
  Stream<Map<String, Object?>> startRun(Map<String, Object?> body) {
    lastRunBody = Map<String, Object?>.of(body);
    return Stream.fromIterable([
      {
        'kind': 'stream.opened',
        'handle': {
          'run_id': 'run_1',
          'session_id': 'session_1',
          'event_cursor': {'run_sequence': 0},
        },
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'turn.started',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'run_sequence': 1,
        'data': {'kind': 'turn', 'state': 'running'},
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.delta',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'item_id': 'item_process',
        'run_sequence': 2,
        'data': {'kind': 'item', 'operation': 'delta', 'delta': '我先搜索一下相关资料。'},
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'tool.call.proposed',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'run_sequence': 3,
        'data': {
          'kind': 'tool',
          'tool_call_id': 'call_1',
          'tool_name': 'search_web',
          'state': 'proposed',
          'arguments': {'query': 'Sage'},
        },
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'tool.call.started',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'run_sequence': 4,
        'data': {
          'kind': 'tool',
          'tool_call_id': 'call_1',
          'tool_name': 'search_web',
          'state': 'started',
        },
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'tool.call.succeeded',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'run_sequence': 5,
        'data': {
          'kind': 'tool',
          'tool_call_id': 'call_1',
          'tool_name': 'search_web',
          'state': 'succeeded',
          'result_item_id': 'item_tool_result',
        },
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'item.completed',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'run_sequence': 6,
        'data': {
          'kind': 'item',
          'operation': 'completed',
          'item': {
            'item_id': 'item_tool_result',
            'data': {
              'kind': 'tool_result',
              'tool_call_id': 'call_1',
              'content': [
                {'kind': 'text', 'text': '找到 Sage V2 运行时资料'},
              ],
            },
          },
        },
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.delta',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'item_id': 'item_1',
        'run_sequence': 7,
        'data': {'kind': 'item', 'operation': 'delta', 'delta': '**完成**'},
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'run.completed',
        'run_id': 'run_1',
        'session_id': 'session_1',
        'turn_id': 'turn_1',
        'run_sequence': 8,
        'data': {'kind': 'run', 'state': 'completed'},
      },
    ]);
  }
}

class _ControlledProcessApi extends _FakeApi {
  final _events = StreamController<Map<String, Object?>>();
  String _runState = 'running';
  int _runSequence = 0;

  @override
  Stream<Map<String, Object?>> startRun(Map<String, Object?> body) {
    lastRunBody = Map<String, Object?>.of(body);
    return _events.stream;
  }

  void emitRunningProcess() {
    _events
      ..add({
        'kind': 'stream.opened',
        'handle': {
          'run_id': 'run_controlled',
          'session_id': 'session_controlled',
          'event_cursor': {'run_sequence': 0},
        },
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'turn.started',
        'run_id': 'run_controlled',
        'session_id': 'session_controlled',
        'turn_id': 'turn_controlled',
        'run_sequence': 1,
        'data': {'kind': 'turn', 'state': 'running'},
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.delta',
        'run_id': 'run_controlled',
        'session_id': 'session_controlled',
        'turn_id': 'turn_controlled',
        'item_id': 'item_process_controlled',
        'run_sequence': 2,
        'data': {'kind': 'item', 'operation': 'delta', 'delta': '正在检查实现。'},
      });
  }

  void emitLargeProcessDelta(String delta) {
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'message.delta',
      'run_id': 'run_controlled',
      'session_id': 'session_controlled',
      'turn_id': 'turn_controlled',
      'item_id': 'item_process_controlled',
      'run_sequence': 3,
      'data': {'kind': 'item', 'operation': 'delta', 'delta': delta},
    });
  }

  void emitSuspended() {
    _runState = 'suspended';
    _runSequence = 3;
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'run.suspended',
      'run_id': 'run_controlled',
      'session_id': 'session_controlled',
      'turn_id': 'turn_controlled',
      'run_sequence': 3,
      'data': {'kind': 'run', 'state': 'suspended', 'reason': 'manual_pause'},
    });
  }

  void emitResumed() {
    _runState = 'running';
    _runSequence = 4;
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'run.resumed',
      'run_id': 'run_controlled',
      'session_id': 'session_controlled',
      'turn_id': 'turn_controlled',
      'run_sequence': 4,
      'data': {'kind': 'run', 'state': 'running'},
    });
  }

  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_controlled',
      'active_turn_id': 'turn_controlled',
      'state': _runState,
      'last_run_sequence': _runSequence,
      'updated_at': DateTime.now().toIso8601String(),
    },
  };

  void emitDelegationActivity() {
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'tool.call.proposed',
      'run_id': 'run_controlled',
      'session_id': 'session_controlled',
      'turn_id': 'turn_controlled',
      'run_sequence': 3,
      'occurred_at': '2026-08-30T15:00:02Z',
      'data': {
        'kind': 'tool',
        'tool_call_id': 'call_delegate',
        'tool_name': 'sys_delegate_task',
        'state': 'proposed',
        'arguments': {
          'tasks': [
            {'agent_id': 'agent_review', 'content': '检查快速排序'},
          ],
        },
      },
    });
  }

  void emitParentFollowupMessage() {
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'message.delta',
      'run_id': 'run_controlled',
      'session_id': 'session_controlled',
      'turn_id': 'turn_controlled',
      'item_id': 'item_after_delegate',
      'run_sequence': 4,
      'occurred_at': '2026-08-30T15:00:44Z',
      'data': {'kind': 'item', 'operation': 'delta', 'delta': '子任务返回后继续汇总。'},
    });
  }

  void emitRunningTool() {
    _events
      ..add({
        'kind': 'stream.opened',
        'handle': {
          'run_id': 'run_tool_shimmer',
          'session_id': 'session_tool_shimmer',
          'event_cursor': {'run_sequence': 0},
        },
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'turn.started',
        'run_id': 'run_tool_shimmer',
        'session_id': 'session_tool_shimmer',
        'turn_id': 'turn_tool_shimmer',
        'run_sequence': 1,
        'data': {'kind': 'turn', 'state': 'running'},
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'tool.call.proposed',
        'run_id': 'run_tool_shimmer',
        'session_id': 'session_tool_shimmer',
        'turn_id': 'turn_tool_shimmer',
        'run_sequence': 2,
        'data': {
          'kind': 'tool',
          'tool_call_id': 'call_delegate',
          'tool_name': 'sys_team_delegate_task',
          'state': 'proposed',
          'arguments': {'agent_id': 'agent_review', 'task': '检查实现'},
        },
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'tool.call.started',
        'run_id': 'run_tool_shimmer',
        'session_id': 'session_tool_shimmer',
        'turn_id': 'turn_tool_shimmer',
        'run_sequence': 3,
        'data': {
          'kind': 'tool',
          'tool_call_id': 'call_delegate',
          'tool_name': 'sys_team_delegate_task',
          'state': 'started',
        },
      });
  }

  void emitToolSucceeded() {
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'tool.call.succeeded',
      'run_id': 'run_tool_shimmer',
      'session_id': 'session_tool_shimmer',
      'turn_id': 'turn_tool_shimmer',
      'run_sequence': 4,
      'data': {
        'kind': 'tool',
        'tool_call_id': 'call_delegate',
        'tool_name': 'sys_team_delegate_task',
        'state': 'succeeded',
      },
    });
  }

  Future<void> finishToolRun() async {
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'run.completed',
      'run_id': 'run_tool_shimmer',
      'session_id': 'session_tool_shimmer',
      'turn_id': 'turn_tool_shimmer',
      'run_sequence': 5,
      'data': {'kind': 'run', 'state': 'completed'},
    });
    await _events.close();
  }

  void emitThinking() {
    _events
      ..add({
        'kind': 'stream.opened',
        'handle': {
          'run_id': 'run_thinking',
          'session_id': 'session_thinking',
          'event_cursor': {'run_sequence': 0},
        },
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'turn.started',
        'run_id': 'run_thinking',
        'session_id': 'session_thinking',
        'turn_id': 'turn_thinking',
        'run_sequence': 1,
        'data': {'kind': 'turn', 'state': 'running'},
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'reasoning.started',
        'run_id': 'run_thinking',
        'session_id': 'session_thinking',
        'turn_id': 'turn_thinking',
        'item_id': 'reasoning_private',
        'run_sequence': 2,
        'data': {'kind': 'item', 'operation': 'started'},
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'reasoning.delta',
        'run_id': 'run_thinking',
        'session_id': 'session_thinking',
        'turn_id': 'turn_thinking',
        'item_id': 'reasoning_private',
        'run_sequence': 3,
        'data': {
          'kind': 'item',
          'operation': 'delta',
          'delta': 'private reasoning must stay hidden',
        },
      });
  }

  void emitAnswerAfterThinking() {
    _events
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.delta',
        'run_id': 'run_thinking',
        'session_id': 'session_thinking',
        'turn_id': 'turn_thinking',
        'item_id': 'answer_visible',
        'run_sequence': 4,
        'data': {'kind': 'item', 'operation': 'delta', 'delta': '这是可见回答。'},
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'run.completed',
        'run_id': 'run_thinking',
        'session_id': 'session_thinking',
        'turn_id': 'turn_thinking',
        'run_sequence': 5,
        'data': {'kind': 'run', 'state': 'completed'},
      });
  }

  Future<void> emitFinalMessage() async {
    _events
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.delta',
        'run_id': 'run_controlled',
        'session_id': 'session_controlled',
        'turn_id': 'turn_controlled',
        'item_id': 'item_final_controlled',
        'run_sequence': 3,
        'data': {'kind': 'item', 'operation': 'delta', 'delta': '## 已完成'},
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.completed',
        'run_id': 'run_controlled',
        'session_id': 'session_controlled',
        'turn_id': 'turn_controlled',
        'item_id': 'item_final_controlled',
        'run_sequence': 4,
        'data': {
          'kind': 'item',
          'operation': 'completed',
          'item': {
            'item_id': 'item_final_controlled',
            'data': {
              'kind': 'message',
              'role': 'assistant',
              'content': [
                {'kind': 'text', 'text': '## 已完成'},
              ],
            },
          },
        },
      })
      ..add({
        'protocol_version': 'sage.runtime/v2',
        'type': 'run.completed',
        'run_id': 'run_controlled',
        'session_id': 'session_controlled',
        'turn_id': 'turn_controlled',
        'run_sequence': 5,
        'data': {'kind': 'run', 'state': 'completed'},
      });
    await _events.close();
  }
}

class _BranchingApi extends _FakeApi {
  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_branch_source',
      'state': 'completed',
      'revision': runId == 'run_branch_1' ? 2 : 3,
      'accepted_session_revision': runId == 'run_branch_1' ? 4 : 8,
      'last_run_sequence': 8,
      'updated_at': '2026-09-01T10:00:00Z',
    },
  };

  @override
  Stream<Map<String, Object?>> startRun(Map<String, Object?> body) {
    lastRunBody = Map<String, Object?>.of(body);
    return Stream.fromIterable([
      {
        'kind': 'stream.opened',
        'handle': {
          'run_id': 'run_branch_child',
          'session_id': 'session_branch_child',
          'event_cursor': {'run_sequence': 0},
        },
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'run.completed',
        'run_id': 'run_branch_child',
        'session_id': 'session_branch_child',
        'turn_id': 'turn_branch_child',
        'run_sequence': 1,
        'data': {'kind': 'run', 'state': 'completed'},
      },
    ]);
  }
}

class _SessionTreeApi extends _ControlledProcessApi {
  final _treeEvents = StreamController<Map<String, Object?>>();
  String? repliedRunId;
  String? repliedInteractionId;
  String? cancelledRunId;
  bool rootFailed = false;
  bool childCancelled = false;

  @override
  Stream<Map<String, Object?>> subscribeSessionTree(String sessionId) =>
      _treeEvents.stream;

  void emitChildSession() {
    _treeEvents
      ..add({
        'kind': 'session.discovered',
        'session': {
          'session_id': 'session_child',
          'parent_session_id': 'session_controlled',
          'created_at': '2026-08-30T15:00:00Z',
        },
        'run': {
          'run_id': 'run_child',
          'state': 'running',
          'last_run_sequence': 0,
          'created_at': '2026-08-30T15:00:02Z',
          'updated_at': '2026-08-30T15:00:02Z',
        },
        'agent_id': 'agent_review',
        'parent_run_id': 'run_controlled',
        'parent_tool_call_id': 'call_delegate',
        'task_name': '检查快速排序',
        'original_task': '实现并验证快速排序',
      })
      ..add({
        'kind': 'session.event',
        'session_id': 'session_child',
        'parent_session_id': 'session_controlled',
        'run_id': 'run_child',
        'event': {
          'protocol_version': 'sage.runtime/v2',
          'type': 'message.delta',
          'run_id': 'run_child',
          'session_id': 'session_child',
          'turn_id': 'turn_child',
          'item_id': 'item_child',
          'run_sequence': 1,
          'data': {'kind': 'item', 'operation': 'delta', 'delta': '正在检查分区逻辑。'},
        },
      })
      ..add({
        'kind': 'session.event',
        'session_id': 'session_child',
        'parent_session_id': 'session_controlled',
        'run_id': 'run_child',
        'event': {
          'protocol_version': 'sage.runtime/v2',
          'type': 'interaction.requested',
          'run_id': 'run_child',
          'session_id': 'session_child',
          'turn_id': 'turn_child',
          'run_sequence': 2,
          'data': {
            'interaction_id': 'interaction_child',
            'interaction_type': 'approval',
            'allowed_decisions': ['approve_once', 'deny'],
            'payload': {
              'tool_name': 'execute_shell_command',
              'arguments': {'command': 'flutter test'},
            },
          },
        },
      });
  }

  void emitCompletedChildSession() {
    _treeEvents
      ..add({
        'kind': 'session.discovered',
        'session': {
          'session_id': 'session_child_completed',
          'parent_session_id': 'session_controlled',
          'created_at': '2026-08-30T15:00:02Z',
        },
        'run': {
          'run_id': 'run_child_completed',
          'state': 'completed',
          'last_run_sequence': 8,
          'created_at': '2026-08-30T15:00:02Z',
          'updated_at': '2026-08-30T15:00:44Z',
        },
        'agent_id': 'agent_review',
        'parent_run_id': 'run_controlled',
        'parent_tool_call_id': 'call_delegate',
        'task_name': '已完成快速排序',
        'original_task': '实现并验证快速排序',
      })
      ..add({
        'kind': 'session.event',
        'session_id': 'session_child_completed',
        'parent_session_id': 'session_controlled',
        'run_id': 'run_child_completed',
        'event': {
          'protocol_version': 'sage.runtime/v2',
          'type': 'tool.call.succeeded',
          'run_id': 'run_child_completed',
          'session_id': 'session_child_completed',
          'turn_id': 'turn_child_completed',
          'run_sequence': 1,
          'occurred_at': '2026-08-30T15:00:20Z',
          'data': {
            'kind': 'tool',
            'tool_call_id': 'call_child_read',
            'tool_name': 'read_file',
            'state': 'succeeded',
          },
        },
      });
  }

  void emitRootFailed() {
    rootFailed = true;
    _events.add({
      'protocol_version': 'sage.runtime/v2',
      'type': 'run.failed',
      'run_id': 'run_controlled',
      'session_id': 'session_controlled',
      'turn_id': 'turn_controlled',
      'run_sequence': 3,
      'data': {
        'kind': 'run',
        'state': 'failed',
        'error': {
          'code': 'agent.driver_crashed',
          'category': 'internal',
          'message': 'parent failed',
        },
      },
    });
  }

  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': runId == 'run_child'
          ? 'session_child'
          : 'session_controlled',
      'active_turn_id': runId == 'run_child' ? 'turn_child' : 'turn_controlled',
      'state': runId == 'run_child'
          ? (childCancelled ? 'cancelled' : 'running')
          : (rootFailed ? 'failed' : 'running'),
      'last_run_sequence': runId == 'run_child' ? (childCancelled ? 3 : 2) : 3,
    },
  };

  @override
  Future<List<Map<String, Object?>>> getSessionTree(String sessionId) async => [
    {
      'session': {
        'session_id': 'session_child',
        'parent_session_id': 'session_controlled',
        'created_at': '2026-08-30T15:00:00Z',
      },
      'run': {
        'run_id': 'run_child',
        'state': childCancelled ? 'cancelled' : 'running',
        'last_run_sequence': childCancelled ? 3 : 2,
      },
      'agent_id': 'agent_review',
      'parent_run_id': 'run_controlled',
      'task_name': '检查快速排序',
      'original_task': '实现并验证快速排序',
    },
  ];

  @override
  Future<void> cancel(String runId) async {
    cancelledRunId = runId;
    if (runId == 'run_child') childCancelled = true;
  }

  @override
  Future<void> replyInteraction(
    String runId, {
    required String interactionId,
    required String decision,
    Map<String, Object?> payload = const {},
  }) async {
    repliedRunId = runId;
    repliedInteractionId = interactionId;
  }

  @override
  Stream<Map<String, Object?>> subscribeRun(
    String runId, {
    int afterSequence = 0,
  }) => Stream.value({
    'protocol_version': 'sage.runtime/v2',
    'type': 'run.completed',
    'run_id': runId,
    'session_id': 'session_child',
    'turn_id': 'turn_child',
    'run_sequence': 3,
    'data': {'kind': 'run', 'state': 'completed'},
  });
}

class _LegacySubSessionHydrationApi extends _FakeApi {
  @override
  Future<List<Map<String, Object?>>> getSessionTree(String sessionId) async =>
      const [
        {
          'session': {
            'session_id': 'session_child',
            'parent_session_id': 'session_root',
            'created_at': '2026-08-30T15:00:00Z',
          },
          'run': {
            'run_id': 'run_child',
            'state': 'completed',
            'last_run_sequence': 8,
            'created_at': '2026-08-30T15:00:02Z',
            'updated_at': '2026-08-30T15:00:44Z',
          },
          'agent_id': 'agent_review',
          'parent_run_id': 'run_root',
          'task_name': '检查快速排序',
          'task': '实现并验证快速排序',
          'original_task': '委派快速排序',
        },
      ];
}

class _ReconnectingSessionTreeApi extends _SessionTreeApi {
  int treeSubscriptionCount = 0;

  @override
  Stream<Map<String, Object?>> subscribeSessionTree(String sessionId) {
    treeSubscriptionCount += 1;
    if (treeSubscriptionCount == 1) {
      return const Stream<Map<String, Object?>>.empty();
    }
    return super.subscribeSessionTree(sessionId);
  }
}

class _ManyToolsApi extends _FakeApi {
  @override
  Future<List<ToolSummary>> listTools() async => [
    for (var index = 0; index < 30; index++)
      ToolSummary(
        name: 'tool_$index',
        description: '工具 $index',
        source: '基础工具',
        inputSchema: {
          'type': 'object',
          'properties': {
            'value': {
              'type': 'string',
              'description': '输入值',
              'enum': ['alpha', 'beta'],
              'default': 'alpha',
            },
            'options': {
              'type': 'object',
              'properties': {
                'enabled': {'type': 'boolean'},
              },
              'required': ['enabled'],
            },
            'session_id': {
              'type': 'string',
              'description': 'The current session ID',
              'default': '',
            },
          },
          'required': const ['value'],
        },
      ),
  ];
}

class _DenseAgentApi extends _ManyToolsApi {
  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) async {
    final tools = await listTools();
    return AgentConfiguration(
      id: agentId,
      name: 'Sage Agent',
      systemPrefix: 'You are Sage.',
      systemContext: const {'language': 'zh'},
      availableTools: [for (final tool in tools) tool.name],
      availableSkills: [
        for (var index = 0; index < 24; index++) 'skill_$index',
      ],
    );
  }

  @override
  Future<List<SkillSummary>> listSkillCatalog() async => [
    for (var index = 0; index < 24; index++) SkillSummary(name: 'skill_$index'),
  ];
}

class _GroupedToolsApi extends _FakeApi {
  @override
  Future<List<ToolSummary>> listTools() async => const [
    ToolSummary(name: 'file_read', source: '基础工具', category: 'files'),
    ToolSummary(name: 'grep', source: '基础工具', category: 'code_search'),
    ToolSummary(name: 'search_web_page', source: '内置MCP: search'),
  ];

  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) async =>
      AgentConfiguration(
        id: agentId,
        name: 'Grouped Agent',
        availableTools: const ['file_read', 'search_web_page'],
      );
}

class _RecordingGroupedToolsApi extends _GroupedToolsApi {
  final List<Map<String, Object?>> agentPatches = [];

  @override
  Future<AgentConfiguration> patchAgentConfiguration(
    String agentId,
    Map<String, Object?> patch,
  ) async {
    agentPatches.add(Map<String, Object?>.from(patch));
    return (await getAgentConfiguration(agentId)).applyPatch(patch);
  }
}

class _TeamAgentApi extends _FakeApi {
  _TeamAgentApi({String mode = 'team'})
    : configuration = AgentConfiguration(
        id: 'agent_main',
        name: 'Sage Agent',
        agentMode: mode,
      );

  AgentConfiguration configuration;
  final List<Map<String, Object?>> agentPatches = [];

  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) async =>
      agentId == configuration.id
      ? configuration
      : AgentConfiguration(id: agentId, name: 'Review Agent');

  @override
  Future<AgentConfiguration> patchAgentConfiguration(
    String agentId,
    Map<String, Object?> patch,
  ) async {
    agentPatches.add(Map<String, Object?>.from(patch));
    configuration = configuration.applyPatch(patch);
    return configuration;
  }
}

class _ReconnectApi extends _FakeApi {
  int? subscribedAfterSequence;

  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_reconnect',
      'active_turn_id': 'turn_reconnect',
      'state': 'completed',
      'last_run_sequence': 3,
    },
  };

  @override
  Stream<Map<String, Object?>> subscribeRun(
    String runId, {
    int afterSequence = 0,
  }) {
    subscribedAfterSequence = afterSequence;
    return Stream.fromIterable([
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'message.delta',
        'run_id': runId,
        'session_id': 'session_reconnect',
        'turn_id': 'turn_reconnect',
        'item_id': 'item_final',
        'run_sequence': 2,
        'data': {'kind': 'item', 'operation': 'delta', 'delta': '恢复后的正文'},
      },
      {
        'protocol_version': 'sage.runtime/v2',
        'type': 'run.completed',
        'run_id': runId,
        'session_id': 'session_reconnect',
        'turn_id': 'turn_reconnect',
        'run_sequence': 3,
        'data': {'kind': 'run', 'state': 'completed'},
      },
    ]);
  }
}

class _SuspendedRunApi extends _FakeApi {
  _SuspendedRunApi({this.cancelled = false});

  bool cancelled;
  String? repliedDecision;
  Map<String, Object?>? repliedPayload;

  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_suspended',
      'active_turn_id': 'turn_suspended',
      'state': cancelled ? 'cancelled' : 'suspended',
      'last_run_sequence': cancelled ? 5 : 4,
    },
    if (!cancelled)
      'interaction': {
        'interaction_id': 'interaction_approval',
        'interaction_type': 'approval',
        'status': 'pending',
        'allowed_decisions': [
          'approve_once',
          'approve_and_remember',
          'deny',
          'cancel',
        ],
        'payload': {
          'tool_name': 'execute_shell_command',
          'arguments': {'command': 'rm -rf build'},
          'risk_category': 'filesystem_delete',
          'risk_reason': 'command deletes workspace files',
          'side_effect_level': 'irreversible',
        },
      },
  };

  @override
  Future<void> cancel(String runId) async {
    cancelled = true;
  }

  @override
  Future<void> replyInteraction(
    String runId, {
    required String interactionId,
    required String decision,
    Map<String, Object?> payload = const {},
  }) async {
    repliedDecision = decision;
    repliedPayload = payload;
  }

  @override
  Stream<Map<String, Object?>> subscribeRun(
    String runId, {
    int afterSequence = 0,
  }) => Stream.value({
    'protocol_version': 'sage.runtime/v2',
    'type': cancelled ? 'run.cancelled' : 'run.completed',
    'run_id': runId,
    'session_id': 'session_suspended',
    'turn_id': 'turn_suspended',
    'run_sequence': 5,
    'data': {'kind': 'run', 'state': cancelled ? 'cancelled' : 'completed'},
  });
}

class _FileWriteSuspendedRunApi extends _SuspendedRunApi {
  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_suspended',
      'active_turn_id': 'turn_suspended',
      'state': 'suspended',
      'last_run_sequence': 4,
    },
    'interaction': {
      'interaction_id': 'interaction_file_write',
      'interaction_type': 'approval',
      'status': 'pending',
      'allowed_decisions': ['approve_once', 'deny', 'cancel'],
      'payload': {
        'tool_name': 'file_write',
        'arguments': {
          'file_path': '/workspace/quicksort.py',
          'content': 'def quicksort(values):\n    return sorted(values)\n',
          'mode': 'overwrite',
          'session_id': 'internal-marker',
        },
        'side_effect_level': 'write',
      },
    },
  };
}

class _FileUpdateSuspendedRunApi extends _SuspendedRunApi {
  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_suspended',
      'active_turn_id': 'turn_suspended',
      'state': 'suspended',
      'last_run_sequence': 4,
    },
    'interaction': {
      'interaction_id': 'interaction_file_update',
      'interaction_type': 'approval',
      'status': 'pending',
      'allowed_decisions': ['approve_once', 'deny', 'cancel'],
      'payload': {
        'tool_name': 'file_update',
        'arguments': {
          'file_path': '/workspace/quicksort.html',
          'operations': [
            {
              'update_mode': 'search_replace',
              'search_pattern': 'const pivot = arr[0]',
              'replacement': 'const pivot = arr[Math.floor(arr.length / 2)]',
            },
          ],
        },
        'side_effect_level': 'write',
      },
    },
  };
}

class _PlanSuspendedRunApi extends _SuspendedRunApi {
  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_suspended',
      'active_turn_id': 'turn_suspended',
      'state': 'suspended',
      'last_run_sequence': 4,
    },
    'interaction': {
      'interaction_id': 'interaction_goal_submit',
      'interaction_type': 'approval',
      'status': 'pending',
      'allowed_decisions': ['approve_once', 'deny', 'cancel'],
      'payload': {
        'tool_name': 'goal_submit',
        'arguments': {'content': '# 实施计划\n\n1. 检查现状\n2. 修改实现\n3. 运行验证'},
        'risk_category': 'plan_approval',
        'side_effect_level': 'none',
      },
    },
  };
}

class _QuestionnaireSuspendedRunApi extends _SuspendedRunApi {
  _QuestionnaireSuspendedRunApi({this.source = 'questionnaire_async'});

  final String? source;

  @override
  Future<Map<String, Object?>> getRun(String runId) async => {
    'run': {
      'run_id': runId,
      'session_id': 'session_suspended',
      'active_turn_id': 'turn_suspended',
      'state': 'suspended',
      'last_run_sequence': 4,
    },
    'interaction': {
      'interaction_id': 'interaction_questionnaire',
      'interaction_type': 'user_input',
      'status': 'pending',
      'allowed_decisions': ['submit', 'cancel'],
      'payload': {
        if (source != null) 'source': source,
        'title': '需要你的引导',
        'prompt': '请选择部署目标并补充说明。',
        'guidance': '回答后 Agent 会从原位置继续。',
        'questions': [
          {
            'id': 'target',
            'type': 'single',
            'title': '部署目标',
            'default': 'production',
            'allow_other': true,
            'options': [
              {'label': '预发布', 'value': 'staging'},
              {'label': '生产', 'value': 'production'},
            ],
          },
          {
            'id': 'preserve',
            'type': 'multiple',
            'title': '保留内容',
            'options': [
              {'label': '页面结构', 'value': 'structure'},
              {'label': '交互逻辑', 'value': 'interaction'},
            ],
          },
          {'id': 'notes', 'type': 'text', 'title': '补充说明', 'placeholder': '可选'},
        ],
      },
    },
  };
}

class _DelayedAgentApi extends _FakeApi {
  final reviewConfiguration = Completer<AgentConfiguration>();

  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) {
    if (agentId == 'agent_review') return reviewConfiguration.future;
    return super.getAgentConfiguration(agentId);
  }
}

class _MissingProviderAgentApi extends _FakeApi {
  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) async =>
      AgentConfiguration(
        id: agentId,
        name: 'Sage Agent',
        llmProviderId: 'provider-not-in-catalog',
        availableTools: const ['read_file'],
        availableSkills: const ['code-review'],
      );
}

Future<WorkspaceController> _controller({_FakeApi? api}) async {
  SharedPreferences.setMockInitialValues({});
  final value = WorkspaceController(
    api: api ?? _FakeApi(),
    preferencesLoader: SharedPreferences.getInstance,
  );
  return value;
}

Future<TestGesture> _hoverFileTreeRow(WidgetTester tester, String path) async {
  final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
  await mouse.addPointer(location: Offset.zero);
  await mouse.moveTo(
    tester.getCenter(find.byKey(ValueKey('file-tree-row:$path'))),
  );
  await tester.pump(const Duration(milliseconds: 160));
  return mouse;
}

Map<String, Object?> _persistedSuspendedConversation() => {
  'id': 'conversation-suspended',
  'title': '暂停任务',
  'agent_id': 'agent_main',
  'run_id': 'run_suspended',
  'session_id': 'session_suspended',
  'turn_id': 'turn_suspended',
  'run_sequence': 4,
  'status': 'suspended',
  'messages': [
    {'id': 'user-suspended', 'role': 'user', 'text': '执行清理'},
  ],
  'pending_interaction': {
    'interaction_id': 'interaction_approval',
    'interaction_type': 'approval',
    'allowed_decisions': [
      'approve_once',
      'approve_and_remember',
      'deny',
      'cancel',
    ],
    'payload': {
      'tool_name': 'execute_shell_command',
      'arguments': {'command': 'rm -rf build'},
      'risk_category': 'filesystem_delete',
      'risk_reason': 'command deletes workspace files',
    },
  },
  'process_panels': [
    {
      'id': 'process-suspended',
      'anchor_message_id': 'user-suspended',
      'started_at': DateTime.now().toIso8601String(),
      'running': true,
      'activities': const [],
    },
  ],
};

Map<String, Object?> _persistedGroupedActivitiesConversation() => {
  'id': 'conversation-grouped-activities',
  'title': '工具分组',
  'agent_id': 'agent_main',
  'run_id': 'run_grouped_activities',
  'session_id': 'session_grouped_activities',
  'turn_id': 'turn_grouped_activities',
  'run_sequence': 70,
  'status': 'completed',
  'messages': const [
    {'id': 'user-grouped', 'role': 'user', 'text': '检查工具分组'},
    {
      'id': 'empty-model-boundary-1',
      'role': 'assistant',
      'text': '',
      'process_only': true,
      'sequence': 20,
    },
    {
      'id': 'empty-model-boundary-2',
      'role': 'assistant',
      'text': '',
      'process_only': true,
      'sequence': 40,
    },
  ],
  'process_panels': [
    {
      'id': 'process-grouped-activities',
      'anchor_message_id': 'user-grouped',
      'run_id': 'run_grouped_activities',
      'started_at': '2026-09-01T09:00:00Z',
      'completed_at': '2026-09-01T09:00:05Z',
      'running': false,
      'activities': const [
        {
          'id': 'call-memory',
          'label': 'search_memory',
          'active': false,
          'sequence': 10,
        },
        {
          'id': 'call-shell-1',
          'label': 'execute_shell_command',
          'active': false,
          'sequence': 30,
          'arguments': {'command': 'ruby -v'},
        },
        {
          'id': 'call-shell-2',
          'label': 'execute_shell_command',
          'active': false,
          'sequence': 50,
          'arguments': {'command': 'bundle -v'},
        },
        {
          'id': 'call-read',
          'label': 'file_read',
          'active': false,
          'sequence': 60,
          'arguments': {'path': 'Gemfile'},
        },
        {
          'id': 'call-shell-3',
          'label': 'execute_shell_command',
          'active': false,
          'sequence': 70,
          'arguments': {'command': 'bundle install'},
        },
      ],
    },
  ],
};

Map<String, Object?> _persistedBranchableConversation() => {
  'id': 'conversation-branch-source',
  'title': '分支源对话',
  'agent_id': 'agent_main',
  'run_id': 'run_branch_2',
  'session_id': 'session_branch_source',
  'turn_id': 'turn_branch_2',
  'run_sequence': 8,
  'status': 'completed',
  'messages': const [
    {'id': 'user-branch-1', 'role': 'user', 'text': '第一轮问题'},
    {'id': 'assistant-branch-1', 'role': 'assistant', 'text': '第一轮结果'},
    {'id': 'user-branch-2', 'role': 'user', 'text': '第二轮问题'},
    {'id': 'assistant-branch-2', 'role': 'assistant', 'text': '第二轮结果'},
  ],
  'process_panels': const [
    {
      'id': 'process-branch-1',
      'anchor_message_id': 'user-branch-1',
      'run_id': 'run_branch_1',
      'started_at': '2026-09-01T09:00:00Z',
      'completed_at': '2026-09-01T09:00:05Z',
      'running': false,
      'activities': [],
    },
    {
      'id': 'process-branch-2',
      'anchor_message_id': 'user-branch-2',
      'run_id': 'run_branch_2',
      'started_at': '2026-09-01T09:01:00Z',
      'completed_at': '2026-09-01T09:01:05Z',
      'running': false,
      'activities': [],
    },
  ],
};

void main() {
  test('legacy child prompt cache is migrated without duplication', () async {
    const prompt = '实现并验证快速排序';
    final root = Conversation(
      id: 'root',
      title: 'root',
      agentId: 'agent_main',
      sessionId: 'session_root',
      runId: 'run_root',
      status: RunStatus.completed,
      subSessions: [
        Conversation(
          id: 'sub-session:session_child',
          title: '检查快速排序',
          agentId: 'agent_review',
          sessionId: 'session_child',
          parentSessionId: 'session_root',
          parentRunId: 'run_root',
          runId: 'run_child',
          status: RunStatus.completed,
          messages: [
            ChatMessage(
              id: 'sub-task:session_child',
              role: 'user',
              text: prompt,
              createdAt: DateTime.parse('2026-08-30T15:00:44Z'),
            ),
            ChatMessage(
              id: 'assistant-final',
              role: 'assistant',
              text: '已完成',
              createdAt: DateTime.parse('2026-08-30T15:00:43Z'),
            ),
            ChatMessage(
              id: 'sub-task:session_child:run_child',
              role: 'user',
              text: prompt,
              createdAt: DateTime.parse('2026-08-30T15:00:02Z'),
            ),
          ],
          processPanels: [
            RuntimeProcessPanel(
              id: 'legacy-panel',
              anchorMessageId: 'sub-task:session_child',
              runId: 'run_child',
              startedAt: DateTime.parse('2026-08-30T15:00:02Z'),
              completedAt: DateTime.parse('2026-08-30T15:00:44Z'),
              running: false,
            ),
          ],
        ),
      ],
    );
    SharedPreferences.setMockInitialValues({
      'sage.desktop_v2.conversations.v1': jsonEncode({
        WorkspaceController.agentWorkspaceId: [root.toJson()],
      }),
    });
    final controller = WorkspaceController(
      api: _LegacySubSessionHydrationApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await controller.initialize();

    final child =
        controller.agentWorkspaceConversations.single.subSessions.single;
    final userMessages = child.messages
        .where((message) => message.role == 'user')
        .toList();
    expect(userMessages, hasLength(1));
    expect(userMessages.single.id, 'sub-task:session_child:run_child');
    expect(userMessages.single.text, prompt);
    expect(child.messages.first.id, 'sub-task:session_child:run_child');
    expect(
      userMessages.single.createdAt,
      DateTime.parse('2026-08-30T15:00:02Z'),
    );
    expect(
      child.processPanels.single.anchorMessageId,
      'sub-task:session_child:run_child',
    );
  });

  test(
    'all supported frontend locales contain the complete translation set',
    () {
      expect(SageLocalizations.supportedLocales, hasLength(9));
      expect(SageLocalizations.translationsAreComplete, isTrue);
      for (final locale in SageLocalizations.supportedLocales) {
        final l10n = SageLocalizations(locale);
        expect(l10n.text('settings.general'), isNot('settings.general'));
        expect(l10n.text('workspace.newConversation'), isNotEmpty);
        expect(l10n.text('settings.tools'), isNotEmpty);
      }
    },
  );

  test('desktop settings serialize all supported language values', () {
    for (final language in const [
      'zh',
      'en',
      'pt',
      'es',
      'fr',
      'de',
      'ja',
      'ko',
      'ru',
    ]) {
      final settings = DesktopSettings.fromJson({'language': language});
      expect(settings.language, language);
      expect(settings.toJson()['language'], language);
    }
    expect(
      DesktopSettings.fromJson(const {'language': 'unsupported'}).language,
      'system',
    );
  });

  test(
    'conversation persists invocation mode and migrates legacy plan mode',
    () {
      final goal = Conversation(
        id: 'goal',
        invocationMode: InvocationMode.goal,
      );
      final restored = Conversation.fromJson(goal.toJson());
      final legacy = Conversation.fromJson(const {
        'id': 'legacy-plan',
        'plan_mode': true,
      });

      expect(restored.invocationMode, InvocationMode.goal);
      expect(restored.toJson()['invocation_mode'], 'goal');
      expect(legacy.invocationMode, InvocationMode.plan);
    },
  );

  test(
    'failed parent keeps active child manageable and blocks tree deletion',
    () async {
      final api = _SessionTreeApi();
      final controller = await _controller(api: api);
      addTearDown(controller.dispose);
      await controller.initialize();

      await controller.send('委派快速排序检查');
      api.emitRunningProcess();
      api.emitChildSession();
      api.emitRootFailed();
      await pumpEventQueue();

      final root = controller.selectedConversation!;
      expect(root.status, RunStatus.failed);
      expect(root.subSessions.single.status, RunStatus.running);
      expect(controller.canManageConversation(root), isFalse);

      await controller.deleteConversation(
        WorkspaceController.agentWorkspaceId,
        root.id,
      );
      expect(api.lastDeletedSessionId, isNull);
      expect(controller.error, '运行中的会话不能删除');

      controller.selectSubSession(root.id, 'session_child');
      await controller.cancel();

      expect(api.cancelledRunId, 'run_child');
      expect(root.subSessions.single.status, RunStatus.cancelled);
      expect(controller.canManageConversation(root), isTrue);

      await controller.deleteConversation(
        WorkspaceController.agentWorkspaceId,
        root.id,
      );
      expect(api.lastDeletedSessionId, 'session_controlled');
      expect(controller.selectedSubSessionId, isEmpty);
      expect(
        controller.agentWorkspaceConversations.any(
          (value) => value.id == root.id,
        ),
        isFalse,
      );
    },
  );

  test('desktop settings preserve generic component configuration', () {
    final settings = DesktopSettings.fromJson(const {
      'component_selections': {
        'execution.sandbox': 'sage.sandbox.local-workspace',
      },
      'component_configs': {
        'execution.sandbox': {
          'workspace_root': '/project',
          'workspace_mapping': 'active_workspace',
        },
      },
    });

    expect(
      settings.componentSelections['execution.sandbox'],
      'sage.sandbox.local-workspace',
    );
    expect(
      settings.componentConfigs['execution.sandbox']?['workspace_root'],
      '/project',
    );
    expect(
      (settings.toJson()['component_configs'] as Map)['execution.sandbox'],
      containsPair('workspace_mapping', 'active_workspace'),
    );
  });

  testWidgets('unsupported sagents display languages fall back to English', (
    tester,
  ) async {
    late String language;
    await tester.pumpWidget(
      Localizations(
        locale: const Locale('it'),
        delegates: const [
          SageLocalizations.delegate,
          DefaultWidgetsLocalizations.delegate,
        ],
        child: Builder(
          builder: (context) {
            language = toolPresentationLanguage(context);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    expect(language, 'en');
  });

  test('legacy flat activities migrate into a process panel', () {
    final conversation = Conversation.fromJson({
      'id': 'legacy-conversation',
      'messages': [
        {'id': 'user-1', 'role': 'user', 'text': '旧任务'},
        {'id': 'assistant-1', 'role': 'assistant', 'text': '旧回复'},
      ],
      'activities': [
        {'id': 'call-1', 'label': 'read_file', 'active': false},
      ],
    });

    expect(conversation.processPanels, hasLength(1));
    expect(conversation.processPanels.single.anchorMessageId, 'user-1');
    expect(
      conversation.processPanels.single.activities.single.label,
      'read_file',
    );
    expect(conversation.processPanels.single.running, isFalse);
  });

  test('ToolSummary keeps the schema returned by sagents', () {
    final tool = ToolSummary.fromJson({
      'name': 'read_file',
      'input_schema': {
        'type': 'object',
        'properties': {
          'path': {'type': 'string'},
        },
        'required': ['path'],
      },
      'parameters': {
        'path': {'type': 'string'},
      },
      'required': ['path'],
    });

    expect(tool.inputSchema['type'], 'object');
    expect(tool.parameters, contains('path'));
    expect(tool.required, ['path']);
  });

  testWidgets(
    'HTML file preview is read-only and exposes rendered and source',
    (tester) async {
      var referencedText = '';
      Widget preview(WorkspaceFilePreviewMode mode) => MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 720,
            height: 520,
            child: WorkspaceFilePreview(
              node: const WorkspaceFileNode(
                name: 'index.html',
                path: 'index.html',
                isDirectory: false,
                size: 28,
              ),
              content: WorkspaceFileContent(
                bytes: Uint8List.fromList(
                  '<h1>Preview title</h1><script>alert(1)</script>'.codeUnits,
                ),
                mediaType: 'text/html; charset=utf-8',
              ),
              mode: mode,
              onReferenceSelection: (value) => referencedText = value,
            ),
          ),
        ),
      );

      await tester.pumpWidget(preview(WorkspaceFilePreviewMode.rendered));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('file-preview-rendered')),
        findsOneWidget,
      );
      expect(find.text('Preview title'), findsOneWidget);
      expect(find.text('alert(1)'), findsNothing);
      expect(
        find.byWidgetPredicate(
          (widget) => widget is EditableText && !widget.readOnly,
        ),
        findsNothing,
      );

      final htmlSelectionArea = find.descendant(
        of: find.byKey(const ValueKey('file-preview-html-selection')),
        matching: find.byType(SelectionArea),
      );
      tester
          .state<SelectionAreaState>(htmlSelectionArea)
          .selectableRegion
          .selectAll();
      await tester.pump();
      await tester.tapAt(
        tester.getCenter(find.text('Preview title')),
        buttons: kSecondaryMouseButton,
      );
      await tester.pumpAndSettle();
      expect(find.text('局部引用'), findsOneWidget);
      await tester.tap(find.text('局部引用'));
      await tester.pumpAndSettle();
      expect(referencedText, contains('Preview title'));

      await tester.pumpWidget(preview(WorkspaceFilePreviewMode.source));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('file-preview-source')), findsOneWidget);
      expect(find.textContaining('<h1>Preview title</h1>'), findsOneWidget);
      expect(
        find.byWidgetPredicate(
          (widget) => widget is EditableText && !widget.readOnly,
        ),
        findsNothing,
      );
    },
  );

  test(
    'interactive HTML preview preserves scripts inside an offline sandbox',
    () {
      final document = workspaceInteractiveHtmlDocument(
        '<html><head><title>Demo</title></head><body>'
        '<button onclick="runDemo()">Run</button>'
        '<script>const marker = "</body>"; '
        'function runDemo() { window.didRun = true; }</script>'
        '</body></html>',
      );

      expect(document, contains('<button onclick="runDemo()">Run</button>'));
      expect(document, contains('function runDemo()'));
      expect(
        document.indexOf('const marker'),
        lessThan(document.indexOf('SagePreviewSelection')),
      );
      expect(document, contains("connect-src 'none'"));
      expect(document, contains("frame-src 'none'"));
      expect(document, contains('SagePreviewSelection.postMessage'));
    },
  );

  testWidgets(
    'Markdown preview selects across blocks and references selection',
    (tester) async {
      var referencedText = '';
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 720,
              height: 520,
              child: WorkspaceFilePreview(
                node: const WorkspaceFileNode(
                  name: 'notes.md',
                  path: 'notes.md',
                  isDirectory: false,
                  size: 32,
                ),
                content: WorkspaceFileContent(
                  bytes: Uint8List.fromList(
                    utf8.encode('# 标题\n\n第一段内容\n\n- 第二段内容'),
                  ),
                  mediaType: 'text/markdown; charset=utf-8',
                ),
                onReferenceSelection: (value) => referencedText = value,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final markdown = tester.widget<MarkdownBody>(find.byType(MarkdownBody));
      expect(markdown.selectable, isFalse);
      final markdownSelectionArea = find.descendant(
        of: find.byKey(const ValueKey('file-preview-markdown-selection')),
        matching: find.byType(SelectionArea),
      );
      final selectionArea = tester.state<SelectionAreaState>(
        markdownSelectionArea,
      );
      selectionArea.selectableRegion.selectAll();
      await tester.pump();
      await tester.tapAt(
        tester.getCenter(
          find.textContaining('第一段内容', findRichText: true).first,
        ),
        buttons: kSecondaryMouseButton,
      );
      await tester.pumpAndSettle();

      expect(find.text('局部引用'), findsOneWidget);
      await tester.tap(find.text('局部引用'));
      await tester.pumpAndSettle();
      expect(referencedText, contains('第一段内容'));
      expect(referencedText, contains('第二段内容'));
    },
  );

  testWidgets('source preview selection supports partial reference', (
    tester,
  ) async {
    var referencedText = '';
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 720,
            height: 520,
            child: WorkspaceFilePreview(
              node: const WorkspaceFileNode(
                name: 'sitemap.xml',
                path: 'sitemap.xml',
                isDirectory: false,
                size: 48,
              ),
              content: WorkspaceFileContent(
                bytes: Uint8List.fromList(
                  utf8.encode(
                    '<url><loc>https://example.test/feed.xml</loc></url>',
                  ),
                ),
                mediaType: 'application/xml; charset=utf-8',
              ),
              onReferenceSelection: (value) => referencedText = value,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final sourceSelectionArea = find.descendant(
      of: find.byKey(const ValueKey('file-preview-source-selection')),
      matching: find.byType(SelectionArea),
    );
    final selectionArea = tester.state<SelectionAreaState>(sourceSelectionArea);
    selectionArea.selectableRegion.selectAll();
    await tester.pump();
    expect(
      selectionArea.selectableRegion.contextMenuButtonItems.any(
        (item) => item.type == ContextMenuButtonType.copy,
      ),
      isTrue,
    );
    await tester.tapAt(
      tester.getCenter(find.textContaining('example.test', findRichText: true)),
      buttons: kSecondaryMouseButton,
    );
    await tester.pumpAndSettle();

    expect(find.text('局部引用'), findsOneWidget);
    await tester.tap(find.text('局部引用'));
    await tester.pumpAndSettle();
    expect(referencedText, contains('https://example.test/feed.xml'));
  });

  test(
    'tool activity presentation localizes names and keeps useful arguments',
    () {
      expect(localizedToolName('list_dir', 'zh'), '查看目录');
      expect(localizedToolName('list_dir', 'en'), 'List directory');
      expect(localizedToolName('list_dir', 'pt'), 'Listar diretório');
      for (final language in const ['es', 'fr', 'de', 'ja', 'ko', 'ru']) {
        expect(
          localizedToolName('list_dir', language),
          isNot('List directory'),
        );
        final approval = approvalToolPresentation('file_write', const {
          'file_path': '/workspace/a.txt',
          'content': 'hello',
        }, language);
        expect(approval.previewLabel, isNot('Content preview'));
        expect(localizedToolFailure(language), isNot('Failed'));
      }
      expect(
        toolArgumentPreview('grep', const {
          'pattern': 'quicksort',
          'path': '/workspace/projects',
          'case_insensitive': true,
          'session_id': 'hidden-session',
        }, 'zh'),
        '“quicksort” · /workspace/projects · 忽略大小写',
      );
      final plan = approvalToolPresentation('goal_submit', const {
        'content': '# 实施计划\n\n1. 检查代码\n2. 完成验证',
      }, 'zh');
      expect(localizedToolName('goal_submit', 'zh'), '提交目标');
      expect(plan.previewLabel, '计划全文');
      expect(plan.preview, contains('2. 完成验证'));
    },
  );

  test('workspace selection queues a structured composer reference', () async {
    final controller = await _controller();
    addTearDown(controller.dispose);
    const node = WorkspaceFileNode(
      name: 'notes.md',
      path: 'docs/notes.md',
      isDirectory: false,
      size: 48,
    );

    controller.referenceWorkspaceSelection(node, '第一行\n第二行');

    expect(
      controller.attachments.single.virtualPath,
      '/workspace/docs/notes.md',
    );
    expect(controller.composerReferences.single.fileName, 'notes.md');
    expect(controller.composerReferences.single.path, 'docs/notes.md');
    final content = controller.composerReferences.single.toMessageContent();
    expect(content.type, 'reference');
    expect(content.path, 'docs/notes.md');
    expect(content.quote, '第一行\n第二行');
  });

  test('chat messages persist interleaved text and reference content', () {
    final original = ChatMessage(
      id: 'message-structured-content',
      role: 'user',
      text: '请看然后继续',
      content: const [
        ChatMessageContent.text('请看'),
        ChatMessageContent.reference(
          fileName: 'image copy.png',
          path: 'uploads/image copy.png',
        ),
        ChatMessageContent.text('然后继续'),
      ],
    );

    final restored = ChatMessage.fromJson(original.toJson());

    expect(restored.text, '请看然后继续');
    expect(restored.content.map((part) => part.type), [
      'text',
      'reference',
      'text',
    ]);
    expect(restored.content[0].text, '请看');
    expect(restored.content[1].path, 'uploads/image copy.png');
    expect(restored.content[2].text, '然后继续');
  });

  testWidgets(
    'composer shows a compact inline reference and reveals its full text',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = _FakeApi();
      final controller = await _controller(api: api);
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('agent-composer')),
        '请解释',
      );
      const fullReference = '这是完整引用的第一行，内容足够长以便在输入消息里只展示简短摘要。\n这是完整引用的第二行。';
      controller.referenceWorkspaceSelection(
        const WorkspaceFileNode(
          name: 'notes.md',
          path: 'docs/notes.md',
          isDirectory: false,
          size: 96,
        ),
        fullReference,
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('composer-asset-shelf')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('composer-inline-reference')),
        findsOneWidget,
      );
      final composer = tester.widget<TextField>(
        find.byKey(const ValueKey('agent-composer')),
      );
      expect(composer.controller?.text, '请解释\uFFFC');

      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      addTearDown(mouse.removePointer);
      await mouse.addPointer(location: Offset.zero);
      await mouse.moveTo(
        tester.getCenter(
          find.byKey(const ValueKey('composer-inline-reference')),
        ),
      );
      await tester.pump(const Duration(milliseconds: 400));
      expect(
        find.byKey(const ValueKey('composer-inline-reference-hover')),
        findsOneWidget,
      );
      expect(find.text('docs/notes.md'), findsOneWidget);
      expect(find.text(fullReference), findsOneWidget);

      final editingController = composer.controller!;
      final nextText = '${editingController.text}这一段';
      editingController.value = editingController.value.copyWith(
        text: nextText,
        selection: TextSelection.collapsed(offset: nextText.length),
        composing: TextRange.empty,
      );
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('send-button')));
      await tester.pumpAndSettle();

      final sentText =
          ((api.lastRunBody?['messages'] as List).single as Map)['text'];
      expect(sentText, '请解释这一段');
      final sentContent =
          ((api.lastRunBody?['messages'] as List).single as Map)['content']
              as List;
      expect(sentContent.map((part) => (part as Map)['type']), [
        'text',
        'reference',
        'text',
      ]);
      expect((sentContent[0] as Map)['text'], '请解释');
      expect((sentContent[1] as Map)['path'], 'docs/notes.md');
      expect((sentContent[1] as Map)['quote'], fullReference);
      expect((sentContent[2] as Map)['text'], '这一段');
      final storedContent = controller.selectedConversation!.messages
          .lastWhere((message) => message.role == 'user')
          .content;
      expect(storedContent.map((part) => part.type), [
        'text',
        'reference',
        'text',
      ]);
      expect(
        find.byKey(const ValueKey('message-reference-chip:docs/notes.md')),
        findsOneWidget,
      );
      expect(controller.composerReferences, isEmpty);
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'composer loads image attachment bytes from the workspace API in ${brightness.name} mode',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = _FakeApi();
        api
          ..desktopSettings = api.desktopSettings.copyWith(
            themeMode: brightness.name,
          )
          ..workspaceFileContent = WorkspaceFileContent(
            bytes: base64Decode(
              'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
            ),
            mediaType: 'image/png',
          );
        final controller = await _controller(api: api);
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        controller.referenceWorkspaceNode(
          const WorkspaceFileNode(
            name: 'image.png',
            path: 'uploads/image.png',
            isDirectory: false,
            size: 68,
          ),
        );
        await tester.pumpAndSettle();

        expect(api.workspaceFileCalls, 1);
        expect(api.lastWorkspaceFileAgentId, 'agent_main');
        expect(api.lastWorkspaceFileId, isEmpty);
        expect(api.lastWorkspaceFilePath, 'uploads/image.png');
        final preview = tester.widget<Image>(
          find.byKey(
            const ValueKey(
              'composer-attachment-preview-image:uploads/image.png',
            ),
          ),
        );
        expect(preview.image, isA<MemoryImage>());
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'composer uses a themed fallback when image preview loading fails',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = _FakeApi()
        ..workspaceFileError = StateError('preview unavailable');
      final controller = await _controller(api: api);
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      controller.referenceWorkspaceNode(
        const WorkspaceFileNode(
          name: 'image.png',
          path: 'uploads/image.png',
          isDirectory: false,
          size: 68,
        ),
      );
      await tester.pumpAndSettle();

      expect(api.workspaceFileCalls, 1);
      expect(
        find.byKey(
          const ValueKey(
            'composer-attachment-preview-fallback:uploads/image.png',
          ),
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('deleting an inline reference also removes its shelf item', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    controller.referenceWorkspaceSelection(
      const WorkspaceFileNode(
        name: 'notes.md',
        path: 'docs/notes.md',
        isDirectory: false,
        size: 32,
      ),
      '待删除的引用',
    );
    await tester.pumpAndSettle();

    final composer = tester.widget<TextField>(
      find.byKey(const ValueKey('agent-composer')),
    );
    expect(composer.controller?.text, '\uFFFC');
    composer.controller!.value = const TextEditingValue(
      text: '',
      selection: TextSelection.collapsed(offset: 0),
    );
    await tester.pumpAndSettle();

    expect(controller.composerReferences, isEmpty);
    expect(
      find.byKey(const ValueKey('composer-inline-reference')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('composer-asset-shelf')), findsNothing);
    expect(controller.attachments, isEmpty);
  });

  testWidgets('a whole folder reference is also embedded in composer text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    controller.referenceWorkspaceNode(
      const WorkspaceFileNode(
        name: 'mini_site',
        path: 'mini_site',
        isDirectory: true,
        size: 0,
      ),
    );
    await tester.pumpAndSettle();

    expect(controller.attachments, hasLength(1));
    expect(controller.composerReferences, hasLength(1));
    expect(
      controller.composerReferences.single.toMessageContent().path,
      'mini_site',
    );
    expect(find.byKey(const ValueKey('composer-asset-shelf')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('composer-inline-reference')),
      findsOneWidget,
    );
    expect(find.text('mini_site'), findsNWidgets(2));
    final composer = tester.widget<TextField>(
      find.byKey(const ValueKey('agent-composer')),
    );
    final editingController = composer.controller!;
    final nextText = '${editingController.text}删除';
    editingController.value = editingController.value.copyWith(
      text: nextText,
      selection: TextSelection.collapsed(offset: nextText.length),
      composing: TextRange.empty,
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pumpAndSettle();

    final sentText =
        ((api.lastRunBody?['messages'] as List).single as Map)['text'];
    expect(sentText, '删除');
    final sentContent =
        ((api.lastRunBody?['messages'] as List).single as Map)['content']
            as List;
    expect(sentContent.map((part) => (part as Map)['type']), [
      'reference',
      'text',
    ]);
    final folderChip = find.byKey(
      const ValueKey('message-reference-chip:mini_site'),
    );
    expect(folderChip, findsOneWidget);
    expect(
      find.descendant(
        of: folderChip,
        matching: find.byIcon(CupertinoIcons.folder),
      ),
      findsOneWidget,
    );
  });

  testWidgets('a file reference is rendered as an inline chip in its message', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final persisted = _persistedBranchableConversation();
    persisted['messages'] = const [
      {
        'id': 'user-file-reference',
        'role': 'user',
        'text': '@quicksort.html\n\n我发现这个网页里的排序不正确。',
      },
    ];
    SharedPreferences.setMockInitialValues({
      'sage.desktop_v2.conversations.v1': jsonEncode({
        WorkspaceController.agentWorkspaceId: [persisted],
      }),
    });
    final controller = WorkspaceController(
      api: _FakeApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    final fileChip = find.byKey(
      const ValueKey('message-reference-chip:quicksort.html'),
    );
    expect(fileChip, findsOneWidget);
    expect(find.text('@quicksort.html'), findsNothing);
    expect(find.text('quicksort.html'), findsOneWidget);
    expect(
      find.descendant(of: fileChip, matching: find.byIcon(CupertinoIcons.doc)),
      findsOneWidget,
    );
    expect(find.textContaining('排序不正确'), findsOneWidget);
  });

  testWidgets('a file reference with spaces is rendered as an inline chip', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    const source =
        '/Users/zhangzheng/sage/agent_workspace/uploads/小凤筝 copy.jpeg';
    final persisted = _persistedBranchableConversation();
    persisted['messages'] = const [
      {
        'id': 'user-file-reference-with-spaces',
        'role': 'user',
        'text': '这个图片里有什么呢？\n\n@$source',
      },
    ];
    SharedPreferences.setMockInitialValues({
      'sage.desktop_v2.conversations.v1': jsonEncode({
        WorkspaceController.agentWorkspaceId: [persisted],
      }),
    });
    final controller = WorkspaceController(
      api: _FakeApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    final fileChip = find.byKey(
      const ValueKey('message-reference-chip:$source'),
    );
    expect(fileChip, findsOneWidget);
    expect(find.text('@$source'), findsNothing);
    expect(find.text('小凤筝 copy.jpeg'), findsOneWidget);
    expect(find.text('这个图片里有什么呢？'), findsOneWidget);
    expect(
      find.descendant(of: fileChip, matching: find.byIcon(CupertinoIcons.doc)),
      findsOneWidget,
    );
  });

  for (final brightness in Brightness.values) {
    testWidgets(
      'hovering an image reference shows workspace content in ${brightness.name} mode',
      (tester) async {
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final persisted = _persistedBranchableConversation();
        persisted['messages'] = const [
          {
            'id': 'user-image-reference',
            'role': 'user',
            'text': '@/workspace/uploads/image.png\n\n这个图片里面有什么？',
          },
        ];
        SharedPreferences.setMockInitialValues({
          'sage.desktop_v2.conversations.v1': jsonEncode({
            WorkspaceController.agentWorkspaceId: [persisted],
          }),
        });
        final api = _FakeApi()
          ..workspaceFileContent = WorkspaceFileContent(
            bytes: base64Decode(
              'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
            ),
            mediaType: 'image/png',
          );
        final controller = WorkspaceController(
          api: api,
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        final chip = find.byKey(
          const ValueKey('message-reference-chip:/workspace/uploads/image.png'),
        );
        expect(chip, findsOneWidget);
        expect(api.workspaceFileCalls, 0);

        final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
        addTearDown(mouse.removePointer);
        await mouse.addPointer(location: Offset.zero);
        await mouse.moveTo(tester.getCenter(chip));
        await tester.pumpAndSettle();

        expect(api.workspaceFileCalls, 1);
        expect(api.lastWorkspaceFilePath, 'uploads/image.png');
        final previewCard = find.byKey(
          const ValueKey(
            'message-reference-preview:/workspace/uploads/image.png',
          ),
        );
        expect(previewCard, findsOneWidget);
        final previewRect = tester.getRect(previewCard);
        expect(previewRect.left, greaterThanOrEqualTo(0));
        expect(previewRect.top, greaterThanOrEqualTo(0));
        expect(previewRect.right, lessThanOrEqualTo(1200));
        expect(previewRect.bottom, lessThanOrEqualTo(800));
        expect(
          find.byKey(
            const ValueKey(
              'message-reference-preview-image:/workspace/uploads/image.png',
            ),
          ),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);

        await mouse.moveTo(Offset.zero);
        await tester.pumpAndSettle();
        expect(previewCard, findsNothing);
      },
    );
  }

  testWidgets('hovering a quote reference shows the quoted content', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final persisted = _persistedBranchableConversation();
    persisted['messages'] = const [
      {
        'id': 'user-quote-reference',
        'role': 'user',
        'text': '@引用\n> 第一行引用\n> 第二行引用\n\n继续处理',
      },
    ];
    SharedPreferences.setMockInitialValues({
      'sage.desktop_v2.conversations.v1': jsonEncode({
        WorkspaceController.agentWorkspaceId: [persisted],
      }),
    });
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    final chip = find.byKey(const ValueKey('message-reference-chip:引用'));
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    addTearDown(mouse.removePointer);
    await mouse.addPointer(location: Offset.zero);
    await mouse.moveTo(tester.getCenter(chip));
    await tester.pumpAndSettle();

    expect(api.workspaceFileCalls, 0);
    expect(
      find.byKey(const ValueKey('message-reference-preview-text:引用')),
      findsOneWidget,
    );
    expect(
      tester
          .widget<Text>(
            find.byKey(const ValueKey('message-reference-preview-text:引用')),
          )
          .data,
      '第一行引用\n第二行引用',
    );
    expect(tester.takeException(), isNull);
  });

  test('workspace references use the real path in host path mode', () async {
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);
    await controller.initialize();
    controller.components = [
      const ComponentSummary(
        id: 'execution.sandbox',
        name: 'Execution sandbox',
        value: 'Maps the active workspace.',
        activeConfig: {
          'workspace_root': '/workspace',
          'workspace_path_mode': 'host',
          'workspace_mapping': 'active_workspace',
        },
      ),
    ];
    const node = WorkspaceFileNode(
      name: 'notes.md',
      path: 'docs/notes.md',
      isDirectory: false,
      size: 48,
    );

    controller.referenceWorkspaceNode(node);

    expect(
      controller.attachments.single.virtualPath,
      '/tmp/sage/agent_workspace/docs/notes.md',
    );
    await controller.loadMessageReference(
      '/tmp/sage/agent_workspace/docs/notes.md',
    );
    expect(api.lastWorkspaceFilePath, 'docs/notes.md');

    controller.selectedGroupId = 'project_demo';
    controller.referenceWorkspaceNode(
      const WorkspaceFileNode(
        name: 'project.md',
        path: 'docs/project.md',
        isDirectory: false,
        size: 64,
      ),
    );

    expect(
      controller.attachments.last.virtualPath,
      '/tmp/demo-project/docs/project.md',
    );
    await controller.loadMessageReference('/tmp/demo-project/docs/project.md');
    expect(api.lastWorkspaceFileId, 'project_demo');
    expect(api.lastWorkspaceFilePath, 'docs/project.md');
  });

  test(
    'reconnect replays unseen terminal events before promoting final text',
    () async {
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            {
              'id': 'conversation-reconnect',
              'title': '恢复会话',
              'agent_id': 'agent_main',
              'run_id': 'run_reconnect',
              'session_id': 'session_reconnect',
              'turn_id': 'turn_reconnect',
              'run_sequence': 1,
              'status': 'running',
              'messages': [
                {'id': 'user-reconnect', 'role': 'user', 'text': '继续任务'},
              ],
              'process_panels': [
                {
                  'id': 'process-reconnect',
                  'anchor_message_id': 'user-reconnect',
                  'started_at': DateTime.now().toIso8601String(),
                  'running': true,
                  'activities': const [],
                },
              ],
            },
          ],
        }),
      });
      final api = _ReconnectApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await controller.initialize();
      await pumpEventQueue();

      final conversation = controller.selectedConversation!;
      expect(api.subscribedAfterSequence, 1);
      expect(conversation.runSequence, 3);
      expect(conversation.status, RunStatus.completed);
      expect(conversation.processPanels.single.running, isFalse);
      expect(conversation.messages.last.text, '恢复后的正文');
      expect(conversation.messages.last.processOnly, isFalse);
    },
  );

  test(
    'startup reconciles a stale suspended run to its terminal state',
    () async {
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            _persistedSuspendedConversation(),
          ],
        }),
      });
      final controller = WorkspaceController(
        api: _SuspendedRunApi(cancelled: true),
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await controller.initialize();
      await pumpEventQueue();

      final conversation = controller.selectedConversation!;
      expect(conversation.status, RunStatus.cancelled);
      expect(conversation.pendingInteraction, isNull);
      expect(conversation.processPanels.single.running, isFalse);
      expect(controller.canManageConversation(conversation), isTrue);
    },
  );

  test(
    'cancelling a suspended run clears approval state and permits deletion',
    () async {
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            _persistedSuspendedConversation(),
          ],
        }),
      });
      final api = _SuspendedRunApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await controller.initialize();
      final conversation = controller.selectedConversation!;
      expect(conversation.status, RunStatus.suspended);
      expect(conversation.pendingInteraction, isNotNull);

      await controller.cancel();

      expect(conversation.status, RunStatus.cancelled);
      expect(conversation.pendingInteraction, isNull);
      expect(conversation.processPanels.single.running, isFalse);
      await controller.deleteConversation(
        WorkspaceController.agentWorkspaceId,
        conversation.id,
      );
      expect(api.lastDeletedSessionId, 'session_suspended');
      expect(
        controller.agentWorkspaceConversations.any(
          (value) => value.id == conversation.id,
        ),
        isFalse,
      );
    },
  );

  test(
    'archived conversations are not selected or reconnected on startup',
    () async {
      SharedPreferences.setMockInitialValues({
        WorkspaceController.archivedConversationsKey: jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            {
              'id': 'conversation-archived',
              'title': '已归档会话',
              'agent_id': 'agent_main',
              'run_id': 'run_reconnect',
              'session_id': 'session_reconnect',
              'run_sequence': 1,
              'status': 'running',
              'archived': true,
              'archived_at': DateTime.now().toIso8601String(),
            },
          ],
        }),
      });
      final api = _ReconnectApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await controller.initialize();
      await pumpEventQueue();

      expect(
        controller.selectedConversation?.id,
        isNot('conversation-archived'),
      );
      expect(controller.archivedConversationsLoaded, isFalse);
      expect(controller.archivedConversations, isEmpty);
      controller.loadArchivedConversations();
      expect(
        controller.archivedConversations.single.conversation.id,
        'conversation-archived',
      );
      expect(controller.archivedConversationsLoaded, isTrue);
      expect(api.subscribedAfterSequence, isNull);
    },
  );

  test(
    'completed history snapshots do not open live session tree streams',
    () async {
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            {
              'id': 'conversation-completed',
              'title': '已完成会话',
              'agent_id': 'agent_main',
              'run_id': 'run_completed',
              'session_id': 'session_completed',
              'turn_id': 'turn_completed',
              'run_sequence': 4,
              'status': 'completed',
            },
          ],
        }),
      });
      final api = _FakeApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await controller.initialize();
      await pumpEventQueue();

      expect(api.sessionTreeSnapshotCalls, 1);
      expect(api.sessionTreeSubscriptionCalls, 0);
      expect(controller.selectedConversation?.status, RunStatus.completed);
    },
  );

  testWidgets('desktop layout exposes agent, skill, workspace, and files', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    expect(find.text('Agent Workspace'), findsOneWidget);
    expect(find.text('未绑定工作区'), findsNothing);
    expect(find.text('Demo Project'), findsOneWidget);
    expect(find.text('最近'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('new-agent-workspace-conversation')),
      findsOneWidget,
    );
    expect(find.text('就绪'), findsNothing);
    expect(find.byKey(const ValueKey('agent-picker')), findsOneWidget);
    expect(find.byKey(const ValueKey('skill-picker')), findsOneWidget);
    expect(find.text('README.md'), findsWidgets);
    expect(find.byKey(const ValueKey('file-tree-overlay')), findsOneWidget);
    expect(find.byKey(const ValueKey('file-tree-filter')), findsOneWidget);
    expect(controller.selectedFile, isNull);
    expect(api.workspaceFileCalls, 0);
    expect(find.byKey(const ValueKey('file-preview-empty')), findsOneWidget);
    expect(find.text('Sage v2 workspace'), findsNothing);

    final projectsReferenceVisibility = find.byKey(
      const ValueKey('file-tree-reference-visibility:projects'),
    );
    expect(
      tester.widget<AnimatedOpacity>(projectsReferenceVisibility).opacity,
      0,
    );
    final projectsMouse = await _hoverFileTreeRow(tester, 'projects');
    addTearDown(projectsMouse.removePointer);
    expect(
      tester.widget<AnimatedOpacity>(projectsReferenceVisibility).opacity,
      1,
    );
    await tester.tap(
      find.byKey(const ValueKey('file-tree-reference:projects')),
    );
    await tester.pumpAndSettle();
    expect(controller.attachments, hasLength(1));
    expect(controller.attachments.single.virtualPath, '/workspace/projects');
    expect(controller.attachments.single.isDirectory, isTrue);
    controller.removeAttachment(controller.attachments.single);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('file-tree-row:README.md')));
    await tester.pumpAndSettle();

    expect(controller.selectedFile?.path, 'README.md');
    expect(api.workspaceFileCalls, 1);
    expect(find.text('Sage v2 workspace'), findsOneWidget);
    expect(find.byKey(const ValueKey('file-preview-rendered')), findsOneWidget);
    expect(find.byKey(const ValueKey('file-preview-mode')), findsOneWidget);
    expect(find.byKey(const ValueKey('file-preview-toolbar')), findsNothing);
    expect(
      tester.getCenter(find.byKey(const ValueKey('file-preview-mode'))).dy,
      closeTo(
        tester
            .getCenter(find.byKey(const ValueKey('file-header-reference')))
            .dy,
        1,
      ),
    );

    await tester.tap(find.text('源码'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('file-preview-source')), findsOneWidget);

    expect(find.byKey(const ValueKey('file-header-reference')), findsOneWidget);
    expect(find.byKey(const ValueKey('file-preview-reference')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('file-header-reference')));
    await tester.pumpAndSettle();
    expect(controller.attachments, hasLength(1));
    expect(controller.attachments.single.virtualPath, '/workspace/README.md');
    expect(
      find.byKey(const ValueKey('file-header-referenced')),
      findsOneWidget,
    );
    expect(
      tester.getTopLeft(find.text('Agent Workspace')).dx,
      lessThan(
        tester.getTopLeft(find.byKey(const ValueKey('file-tree-toggle'))).dx,
      ),
    );
    expect(
      tester.getSize(find.byKey(const ValueKey('file-tree-filter'))).height,
      34,
    );
  });

  for (final brightness in Brightness.values) {
    testWidgets(
      'project opens files beside its own tree in ${brightness.name} mode',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 900);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final api = _FakeApi();
        final controller = await _controller(api: api);
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Demo Project').first);
        await tester.pumpAndSettle();

        expect(controller.selectedGroup.project, isNotNull);
        expect(api.lastWorkspaceTreeId, 'project_demo');
        expect(find.byKey(const ValueKey('file-tree-overlay')), findsOneWidget);
        expect(find.byKey(const ValueKey('file-tree-toggle')), findsOneWidget);
        expect(
          find.byKey(const ValueKey('workspace-remove-project')),
          findsNothing,
        );
        expect(
          find.byKey(const ValueKey('file-preview-empty')),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('file-preview-mode')), findsNothing);
        expect(api.workspaceFileCalls, 0);

        await tester.tap(find.byKey(const ValueKey('file-tree-row:README.md')));
        await tester.pumpAndSettle();
        expect(controller.selectedFile?.path, 'README.md');
        expect(api.workspaceFileCalls, 1);
        expect(find.text('Sage v2 workspace'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('file-preview-rendered')),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('file-preview-mode')), findsOneWidget);

        final referenceVisibility = find.byKey(
          const ValueKey('file-tree-reference-visibility:README.md'),
        );
        expect(tester.widget<AnimatedOpacity>(referenceVisibility).opacity, 0);
        final mouse = await _hoverFileTreeRow(tester, 'README.md');
        addTearDown(mouse.removePointer);
        expect(tester.widget<AnimatedOpacity>(referenceVisibility).opacity, 1);
        await tester.tap(
          find.byKey(const ValueKey('file-tree-reference:README.md')),
        );
        await tester.pumpAndSettle();
        expect(controller.attachments.single.name, 'README.md');
      },
    );
  }

  testWidgets('file update approval identifies the file and renders a diff', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({
      'sage.desktop_v2.conversations.v1': jsonEncode({
        WorkspaceController.agentWorkspaceId: [
          _persistedSuspendedConversation(),
        ],
      }),
    });
    final controller = WorkspaceController(
      api: _FileUpdateSuspendedRunApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.text('更新 quicksort.html'), findsOneWidget);
    expect(find.text('文件写入'), findsOneWidget);
    expect(find.text('/workspace/quicksort.html'), findsOneWidget);
    expect(find.text('1 处变更'), findsOneWidget);
    expect(find.textContaining('- const pivot = arr[0]'), findsOneWidget);
    expect(
      find.textContaining('+ const pivot = arr[Math.floor(arr.length / 2)]'),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('interaction-preview-toggle')),
      findsOneWidget,
    );
    expect(find.text('查看完整变更'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('agent tool assignments save and update immediately', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _RecordingGroupedToolsApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('grep'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('grep'));
    await tester.pumpAndSettle();

    expect(api.agentPatches.last, {
      'available_tools': ['file_read', 'grep', 'search_web_page'],
    });
    expect(controller.agentConfiguration?.availableTools, contains('grep'));

    await tester.ensureVisible(find.text('search_web_page'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('search_web_page'));
    await tester.pumpAndSettle();

    expect(api.agentPatches.last, {
      'available_tools': ['file_read', 'grep'],
    });
    expect(
      controller.agentConfiguration?.availableTools,
      unorderedEquals(['file_read', 'grep']),
    );
  });

  for (final mode in ['fibre', 'team']) {
    testWidgets('$mode agent settings can select a custom member roster', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1400, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = _TeamAgentApi(mode: mode);
      final controller = await _controller(api: api);
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('settings-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('智能体').first);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
      await tester.pumpAndSettle();

      expect(find.text('所选成员作为叶节点执行，不会继续 Fibre / Team 编排。'), findsOneWidget);
      final scope = find.byKey(const ValueKey('agent-team-scope'));
      await tester.ensureVisible(scope);
      await tester.tap(
        find.descendant(of: scope, matching: find.text('自定义成员')),
      );
      await tester.pumpAndSettle();
      expect(api.agentPatches.last, {'sub_agent_selection_mode': 'manual'});

      final reviewMember = find.byKey(
        const ValueKey('assignment-协作成员-agent_review'),
      );
      await tester.ensureVisible(reviewMember);
      await tester.tap(reviewMember);
      await tester.pumpAndSettle();
      expect(api.agentPatches.last, {
        'available_sub_agent_ids': ['agent_review'],
      });
      expect(controller.agentConfiguration?.availableSubAgentIds, [
        'agent_review',
      ]);
    });
  }

  for (final brightness in Brightness.values) {
    testWidgets(
      'desktop rail owns its collapse button in ${brightness.name} mode',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 900);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final controller = await _controller();
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();

        final rail = find.byKey(
          const ValueKey('project-rail-repaint-boundary'),
        );
        final collapseButton = find.byKey(
          const ValueKey('rail-collapse-button'),
        );
        expect(collapseButton, findsOneWidget);
        expect(
          tester.getCenter(collapseButton).dx,
          lessThan(tester.getRect(rail).right),
        );
        expect(
          tester.getCenter(collapseButton).dx,
          greaterThan(tester.getRect(rail).center.dx),
        );

        await tester.tap(collapseButton);
        await tester.pumpAndSettle();

        expect(rail, findsNothing);
        expect(
          find.byKey(const ValueKey('rail-expand-button')),
          findsOneWidget,
        );

        await tester.tap(find.byKey(const ValueKey('rail-expand-button')));
        await tester.pumpAndSettle();

        expect(rail, findsOneWidget);
        expect(collapseButton, findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('generic user input is not rendered as an inline questionnaire', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final conversation = _persistedSuspendedConversation();
    conversation['pending_interaction'] = {
      'interaction_id': 'interaction_generic_input',
      'interaction_type': 'user_input',
      'allowed_decisions': ['submit', 'cancel'],
      'payload': {
        'reason_code': 'judge.plain_text_no_progress',
        'questions': [
          {'id': 'direction', 'type': 'text', 'title': '接下来应该怎么做？'},
        ],
      },
    };
    SharedPreferences.setMockInitialValues({
      'sage.desktop_v2.conversations.v1': jsonEncode({
        WorkspaceController.agentWorkspaceId: [conversation],
      }),
    });
    final controller = WorkspaceController(
      api: _QuestionnaireSuspendedRunApi(source: null),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.byKey(const ValueKey('questionnaire-block')), findsNothing);
    expect(
      find.byKey(const ValueKey('interaction-submit-submit')),
      findsOneWidget,
    );
  });

  for (final brightness in Brightness.values) {
    testWidgets(
      'project conversations only collapse explicitly in ${brightness.name} mode',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 900);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final controller = await _controller();
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();

        final recentNewConversation = find.byKey(
          const ValueKey('recent-new-conversation'),
        );
        expect(
          find.descendant(
            of: recentNewConversation,
            matching: find.byIcon(CupertinoIcons.square_pencil),
          ),
          findsOneWidget,
        );
        final recentCount = controller.agentWorkspaceConversations.length;
        await tester.tap(recentNewConversation);
        await tester.pumpAndSettle();
        expect(controller.agentWorkspaceConversations.length, recentCount + 1);
        expect(
          controller.selectedGroupId,
          WorkspaceController.agentWorkspaceId,
        );
        final recentConversationTile = find.byKey(
          ValueKey('conversation-tile:${controller.selectedConversationId}'),
        );
        final recentConversationIcon = find.descendant(
          of: recentConversationTile,
          matching: find.byIcon(CupertinoIcons.bubble_left),
        );
        final newConversationIcon = find.descendant(
          of: find.byKey(const ValueKey('new-agent-workspace-conversation')),
          matching: find.byIcon(CupertinoIcons.square_pencil),
        );
        expect(
          tester.getCenter(recentConversationIcon).dx -
              tester.getCenter(newConversationIcon).dx,
          inInclusiveRange(10, 14),
        );

        await tester.tap(
          find.byKey(const ValueKey('workspace-header:project_demo')),
        );
        await tester.pumpAndSettle();

        final disclosure = find.byKey(
          const ValueKey('project-disclosure:project_demo'),
        );
        final projectNewConversation = find.byKey(
          const ValueKey('project-new-conversation:project_demo'),
        );
        final conversationTile = find.byKey(
          ValueKey('conversation-tile:${controller.selectedConversationId}'),
        );

        expect(conversationTile, findsOneWidget);
        final projectIcon = find.descendant(
          of: find.byKey(const ValueKey('workspace-header:project_demo')),
          matching: find.byIcon(CupertinoIcons.square_stack_3d_up),
        );
        final projectConversationIcon = find.descendant(
          of: conversationTile,
          matching: find.byIcon(CupertinoIcons.bubble_left),
        );
        expect(
          tester.getCenter(projectConversationIcon).dx -
              tester.getCenter(projectIcon).dx,
          inInclusiveRange(12, 14),
        );
        expect(
          tester.getCenter(projectConversationIcon).dx,
          tester.getCenter(recentConversationIcon).dx,
        );
        expect(
          find.descendant(
            of: disclosure,
            matching: find.byIcon(CupertinoIcons.chevron_down),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: projectNewConversation,
            matching: find.byIcon(CupertinoIcons.square_pencil),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('new-agent-workspace-conversation')),
            matching: find.byIcon(CupertinoIcons.square_pencil),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('add-project-button')),
            matching: find.byIcon(CupertinoIcons.add),
          ),
          findsOneWidget,
        );

        // Moving to Agent Workspace changes selection, but does not collapse
        // the project's conversation list.
        await tester.tap(recentNewConversation);
        await tester.pumpAndSettle();
        expect(
          controller.selectedGroupId,
          WorkspaceController.agentWorkspaceId,
        );
        expect(conversationTile, findsOneWidget);

        // A visible conversation under an inactive project must select both
        // the project and the conversation. Updating only the conversation id
        // leaves the center pane with no matching conversation to render.
        await tester.tap(conversationTile);
        await tester.pumpAndSettle();
        expect(controller.selectedGroupId, 'project_demo');
        expect(controller.selectedDisplayConversation, isNotNull);
        expect(
          controller.selectedDisplayConversation?.id,
          controller.selectedConversationId,
        );

        await tester.tap(recentNewConversation);
        await tester.pumpAndSettle();
        expect(
          controller.selectedGroupId,
          WorkspaceController.agentWorkspaceId,
        );

        await tester.tap(
          find.byKey(const ValueKey('workspace-header:project_demo')),
        );
        await tester.pumpAndSettle();

        await tester.tap(disclosure);
        await tester.pumpAndSettle();

        expect(conversationTile, findsNothing);
        expect(controller.selectedGroupId, 'project_demo');
        expect(
          find.descendant(
            of: disclosure,
            matching: find.byIcon(CupertinoIcons.chevron_right),
          ),
          findsOneWidget,
        );

        await tester.tap(disclosure);
        await tester.pumpAndSettle();

        expect(conversationTile, findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final brightness in Brightness.values) {
    testWidgets(
      'project right-click menu removes an inactive project in ${brightness.name} mode',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 900);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final api = _FakeApi();
        final controller = await _controller(api: api);
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();

        final projectHeader = find.byKey(
          const ValueKey('workspace-header:project_demo'),
        );
        expect(projectHeader, findsOneWidget);
        expect(
          controller.selectedGroupId,
          WorkspaceController.agentWorkspaceId,
        );

        await tester.tap(projectHeader, buttons: kSecondaryMouseButton);
        await tester.pumpAndSettle();

        final removeProject = find.byKey(
          const ValueKey('project-remove:project_demo'),
        );
        expect(removeProject, findsOneWidget);
        expect(find.text('移除项目'), findsOneWidget);

        await tester.tap(removeProject);
        await tester.pumpAndSettle();

        expect(api.lastRemovedProjectId, 'project_demo');
        expect(projectHeader, findsNothing);
        expect(
          controller.selectedGroupId,
          WorkspaceController.agentWorkspaceId,
        );
        expect(controller.selectedDisplayConversation, isNotNull);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('new chat creates an Agent Workspace conversation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    final before = controller.agentWorkspaceConversations.length;
    await tester.tap(
      find.byKey(const ValueKey('new-agent-workspace-conversation')),
    );
    await tester.pumpAndSettle();

    expect(controller.agentWorkspaceConversations.length, before + 1);
    expect(controller.selectedGroupId, WorkspaceController.agentWorkspaceId);
    expect(controller.selectedGroup.project, isNull);
    expect(find.text('Demo Project'), findsOneWidget);
  });

  testWidgets('standalone chat refreshes Agent Workspace after a run', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    final callsBeforeRun = api.workspaceTreeCalls;

    await controller.send('创建 index.html');
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pumpAndSettle();

    expect(controller.selectedGroupId, WorkspaceController.agentWorkspaceId);
    expect(controller.selectedGroup.project, isNull);
    expect(api.lastRunBody, isNot(contains('workspace_id')));
    expect(api.lastWorkspaceTreeId, '');
    expect(api.workspaceTreeCalls, greaterThan(callsBeforeRun));
    expect(find.text('Agent Workspace'), findsOneWidget);
    expect(find.text('README.md'), findsWidgets);
  });

  testWidgets('native stream updates the selected conversation', (
    tester,
  ) async {
    tester.platformDispatcher.localeTestValue = const Locale('zh');
    tester.platformDispatcher.localesTestValue = const [Locale('zh')];
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.platformDispatcher.clearLocaleTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '检查一下代码',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pumpAndSettle();

    expect(find.text('检查一下代码'), findsWidgets);
    expect(find.text('完成'), findsOneWidget);
    expect(find.byType(MarkdownBody), findsWidgets);
    expect(find.text('已完成'), findsOneWidget);
    expect(find.byKey(const ValueKey('process-panel')), findsOneWidget);
    expect(find.textContaining('已处理'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('process-message:item_process')),
      findsNothing,
    );
    expect(find.text('我先搜索一下相关资料。'), findsNothing);
    expect(find.byIcon(CupertinoIcons.chevron_right), findsWidgets);
    expect(find.byTooltip('复制'), findsNWidgets(2));
    final processTop = tester
        .getTopLeft(find.byKey(const ValueKey('process-panel')))
        .dy;
    expect(
      processTop,
      greaterThan(tester.getTopLeft(find.text('检查一下代码').last).dy),
    );
    expect(processTop, lessThan(tester.getTopLeft(find.text('完成')).dy));
    final processBottom = tester
        .getBottomLeft(find.byKey(const ValueKey('process-panel')))
        .dy;
    final finalMessageTop = tester
        .getTopLeft(find.byKey(const ValueKey('item_1')))
        .dy;
    expect(finalMessageTop - processBottom, 16);

    await tester.tap(find.byKey(const ValueKey('process-panel-toggle')));
    await tester.pump();

    expect(
      find.byKey(const ValueKey('process-message:item_process')),
      findsOneWidget,
    );
    expect(find.text('我先搜索一下相关资料。'), findsOneWidget);
    expect(find.textContaining('搜索网页'), findsOneWidget);
    expect(find.textContaining('“Sage”'), findsOneWidget);
    expect(find.textContaining('search_web'), findsNothing);
    expect(
      tester.getTopLeft(find.text('我先搜索一下相关资料。')).dy,
      lessThan(tester.getTopLeft(find.textContaining('搜索网页')).dy),
    );
  });

  for (final brightness in Brightness.values) {
    testWidgets(
      'process panel groups consecutive tools by category across empty model boundaries in ${brightness.name} mode',
      (tester) async {
        tester.platformDispatcher.localeTestValue = const Locale('zh');
        tester.platformDispatcher.localesTestValue = const [Locale('zh')];
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.platformDispatcher.clearLocaleTestValue);
        addTearDown(tester.platformDispatcher.clearLocalesTestValue);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        SharedPreferences.setMockInitialValues({
          'sage.desktop_v2.conversations.v1': jsonEncode({
            WorkspaceController.agentWorkspaceId: [
              _persistedGroupedActivitiesConversation(),
            ],
          }),
        });
        final controller = WorkspaceController(
          api: _FakeApi(),
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('process-panel-toggle')));
        await tester.pump();

        expect(
          find.byKey(const ValueKey('process-operation-group:call-shell-1')),
          findsOneWidget,
        );
        expect(find.text('执行了 2 个命令，共 2 个操作'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('process-activity:call-memory')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('process-activity:call-read')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('process-activity:call-shell-3')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('process-message:empty-model-boundary-1')),
          findsNothing,
        );
        expect(
          find.byKey(const ValueKey('process-message:empty-model-boundary-2')),
          findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('process panel collapses when the final body is promoted', (
    tester,
  ) async {
    tester.platformDispatcher.localeTestValue = const Locale('zh');
    tester.platformDispatcher.localesTestValue = const [Locale('zh')];
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.platformDispatcher.clearLocaleTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _ControlledProcessApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '检查流式折叠',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pump();

    api.emitRunningProcess();
    await tester.pump(const Duration(milliseconds: 10));

    expect(find.text('正在检查实现。'), findsOneWidget);
    expect(find.byKey(const ValueKey('running-message-shimmer')), findsNothing);
    expect(find.byIcon(CupertinoIcons.chevron_up), findsWidgets);

    await api.emitFinalMessage();
    await tester.pumpAndSettle();

    expect(find.text('已完成'), findsWidgets);
    expect(find.text('正在检查实现。'), findsNothing);
    expect(find.byKey(const ValueKey('running-message-shimmer')), findsNothing);
    expect(find.byIcon(CupertinoIcons.chevron_right), findsWidgets);

    await tester.tap(find.byKey(const ValueKey('process-panel-toggle')));
    await tester.pump();
    expect(find.text('正在检查实现。'), findsOneWidget);
  });

  testWidgets('large stream deltas are revealed progressively', (tester) async {
    tester.platformDispatcher.localeTestValue = const Locale('zh');
    tester.platformDispatcher.localesTestValue = const [Locale('zh')];
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.platformDispatcher.clearLocaleTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _ControlledProcessApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '检查大块流式输出',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pump();
    api.emitRunningProcess();
    await tester.pump(const Duration(milliseconds: 10));

    const largeDelta = '这里是一段一次返回的较长内容，用来确认桌面端不会把整段文字突然全部显示出来，而是平滑地逐步展示。';
    api.emitLargeProcessDelta(largeDelta);
    await tester.pump();

    final message = controller.selectedConversation!.messages.last;
    expect(message.text, '正在检查实现。$largeDelta');
    expect(message.renderedText, '正在检查实现。');

    await tester.pump(const Duration(milliseconds: 48));
    expect(message.renderedText.length, greaterThan('正在检查实现。'.length));
    expect(message.renderedText, isNot(message.text));

    await tester.pump(const Duration(seconds: 3));
    expect(message.renderedText, message.text);
    expect(find.text('正在检查实现。$largeDelta'), findsOneWidget);
  });

  testWidgets('paused process time freezes and resumes from the frozen value', (
    tester,
  ) async {
    tester.platformDispatcher.localeTestValue = const Locale('zh');
    tester.platformDispatcher.localesTestValue = const [Locale('zh')];
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.platformDispatcher.clearLocaleTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _ControlledProcessApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '暂停后继续',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pump();
    api.emitRunningProcess();
    await tester.pump(const Duration(milliseconds: 10));

    final panel = controller.selectedConversation!.processPanels.single;
    panel.startedAt = DateTime.now().subtract(const Duration(seconds: 7));
    api.emitSuspended();
    await tester.pump();

    expect(controller.selectedConversation!.status, RunStatus.suspended);
    expect(panel.running, isFalse);
    expect(find.text('已处理 7s'), findsOneWidget);

    await tester.pump(const Duration(seconds: 3));
    expect(find.text('已处理 7s'), findsOneWidget);

    api.emitResumed();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 10));

    expect(controller.selectedConversation!.status, RunStatus.running);
    expect(panel.running, isTrue);
    expect(find.text('正在处理'), findsOneWidget);
    expect(find.text('7s'), findsOneWidget);

    panel.startedAt = panel.startedAt.subtract(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('9s'), findsOneWidget);
  });

  testWidgets('active tool text shimmers until the tool completes', (
    tester,
  ) async {
    tester.platformDispatcher.localeTestValue = const Locale('zh');
    tester.platformDispatcher.localesTestValue = const [Locale('zh')];
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.platformDispatcher.clearLocaleTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _ControlledProcessApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '委派检查任务',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pump();

    api.emitRunningTool();
    await tester.pump(const Duration(milliseconds: 20));

    expect(find.textContaining('团队委派'), findsOneWidget);
    expect(find.textContaining('检查实现', findRichText: true), findsOneWidget);
    expect(
      find.textContaining('agent_review', findRichText: true),
      findsNothing,
    );
    final toolLine = tester
        .widgetList<RichText>(find.byType(RichText))
        .firstWhere((widget) => widget.text.toPlainText().contains('团队委派'));
    expect(toolLine.maxLines, 1);
    expect(toolLine.softWrap, isFalse);
    expect(toolLine.overflow, TextOverflow.ellipsis);
    expect(
      find.byKey(const ValueKey('tool-activity-shimmer:call_delegate')),
      findsOneWidget,
    );

    api.emitToolSucceeded();
    await tester.pump(const Duration(milliseconds: 20));

    expect(find.textContaining('团队委派'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('tool-activity-shimmer:call_delegate')),
      findsNothing,
    );

    await api.finishToolRun();
    await tester.pumpAndSettle();
  });

  testWidgets(
    'session tree reconnects and shows child messages in the parent flow',
    (tester) async {
      tester.platformDispatcher.localeTestValue = const Locale('zh');
      tester.platformDispatcher.localesTestValue = const [Locale('zh')];
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.platformDispatcher.clearLocaleTestValue);
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = _ReconnectingSessionTreeApi();
      final controller = await _controller(api: api);
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('agent-composer')),
        '委派快速排序检查',
      );
      await tester.tap(find.byKey(const ValueKey('send-button')));
      await tester.pump();
      api.emitRunningProcess();
      await tester.pump(const Duration(milliseconds: 20));
      expect(api.treeSubscriptionCount, 1);

      await tester.pump(const Duration(seconds: 1));
      await tester.pump(const Duration(milliseconds: 20));
      expect(api.treeSubscriptionCount, greaterThanOrEqualTo(2));

      api.emitDelegationActivity();
      api.emitParentFollowupMessage();
      await tester.pump(const Duration(milliseconds: 20));
      api.emitChildSession();
      await tester.pump(const Duration(milliseconds: 40));

      expect(
        find.byKey(const ValueKey('sub-session-tile:session_child')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('sub-session-process:session_child')),
        findsOneWidget,
      );
      expect(find.text('正在检查分区逻辑。'), findsOneWidget);
      expect(find.text('等待审批'), findsOneWidget);
      final delegateY = tester
          .getTopLeft(
            find.byKey(const ValueKey('process-activity:call_delegate')),
          )
          .dy;
      final childY = tester
          .getTopLeft(
            find.byKey(const ValueKey('sub-session-process:session_child')),
          )
          .dy;
      final followupY = tester
          .getTopLeft(
            find.byKey(const ValueKey('process-message:item_after_delegate')),
          )
          .dy;
      expect(childY, greaterThan(delegateY));
      expect(childY, lessThan(followupY));

      await tester.tap(
        find.byKey(const ValueKey('sub-session-tile:session_child')),
      );
      await tester.pump();
      expect(
        controller.selectedDisplayConversation?.sessionId,
        'session_child',
      );
      expect(find.byKey(const ValueKey('agent-composer')), findsNothing);
      expect(find.byIcon(CupertinoIcons.stop_fill), findsOneWidget);

      await controller.replyDisplayInteraction('approve_once');
      expect(api.repliedRunId, 'run_child');
      expect(api.repliedInteractionId, 'interaction_child');

      await tester.tap(
        find.byKey(
          ValueKey('conversation-tile:${controller.selectedConversationId}'),
        ),
      );
      await tester.pump();
      expect(controller.selectedSubSessionId, isEmpty);
      expect(
        controller.selectedDisplayConversation?.id,
        controller.selectedConversationId,
      );
      expect(find.byKey(const ValueKey('agent-composer')), findsOneWidget);
    },
  );

  testWidgets('completed child uses authoritative run duration', (
    tester,
  ) async {
    tester.platformDispatcher.localeTestValue = const Locale('zh');
    tester.platformDispatcher.localesTestValue = const [Locale('zh')];
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.platformDispatcher.clearLocaleTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _SessionTreeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '委派快速排序检查',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pump();
    api.emitRunningProcess();
    api.emitDelegationActivity();
    await tester.pump(const Duration(milliseconds: 20));
    api.emitCompletedChildSession();
    await tester.pump(const Duration(milliseconds: 40));

    await tester.tap(
      find.byKey(const ValueKey('sub-session-tile:session_child_completed')),
    );
    await tester.pump();

    expect(find.text('已处理 42s'), findsOneWidget);
  });

  testWidgets(
    'reasoning events show a bottom thinking status without exposing content',
    (tester) async {
      tester.platformDispatcher.localeTestValue = const Locale('zh');
      tester.platformDispatcher.localesTestValue = const [Locale('zh')];
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.platformDispatcher.clearLocaleTestValue);
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      SharedPreferences.setMockInitialValues({});
      final api = _ControlledProcessApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('agent-composer')),
        '先思考再回答',
      );
      await tester.tap(find.byKey(const ValueKey('send-button')));
      await tester.pump();

      api.emitThinking();
      await tester.pump(const Duration(milliseconds: 20));

      expect(
        find.byKey(const ValueKey('thread-thinking-status')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('running-message-shimmer')),
        findsNothing,
      );
      expect(find.textContaining('正在思考'), findsOneWidget);
      expect(find.textContaining('private reasoning'), findsNothing);

      api.emitAnswerAfterThinking();
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('thread-thinking-status')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('running-message-shimmer')),
        findsNothing,
      );
      expect(find.text('这是可见回答。'), findsOneWidget);
    },
  );

  testWidgets('composer sends the selected approval mode', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    expect(find.text('我能帮你做什么？'), findsOneWidget);
    expect(find.byKey(const ValueKey('approval-mode-picker')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('approval-mode-picker')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('approval-mode-auto_approve')));
    await tester.pumpAndSettle();
    expect(
      controller.selectedConversation?.approvalMode,
      ApprovalMode.autoApprove,
    );

    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '执行任务',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pumpAndSettle();

    expect(api.lastRunBody?['approval_mode'], 'auto_approve');
    expect(api.lastRunBody?['response_language'], 'zh');
    expect(
      api.lastRunBody?['session_id'],
      matches(RegExp(r'^session_\d{13}_\d{6}$')),
    );
  });

  testWidgets('plus menu enables plan mode for the conversation and run', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('composer-upload-button')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('composer-plan-mode-option')),
      findsOneWidget,
    );
    expect(find.text('计划模式'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('composer-plan-mode-option')));
    await tester.pumpAndSettle();
    expect(controller.selectedConversation?.planMode, isTrue);
    expect(
      controller.selectedConversation?.invocationMode,
      InvocationMode.plan,
    );
    expect(find.text('描述你想规划的任务…'), findsOneWidget);

    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '先规划这个功能',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pumpAndSettle();

    expect(api.lastRunBody?['invocation_mode'], 'plan');
  });

  testWidgets('plus menu selects goal mode as the same invocation contract', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('composer-upload-button')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('composer-goal-mode-option')),
      findsOneWidget,
    );
    expect(find.text('目标模式'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('composer-goal-mode-option')));
    await tester.pumpAndSettle();
    expect(
      controller.selectedConversation?.invocationMode,
      InvocationMode.goal,
    );
    expect(find.text('描述你要持续完成的目标…'), findsOneWidget);

    await tester.enterText(
      find.byKey(const ValueKey('agent-composer')),
      '完成并验证这个目标',
    );
    await tester.tap(find.byKey(const ValueKey('send-button')));
    await tester.pumpAndSettle();

    expect(api.lastRunBody?['invocation_mode'], 'goal');
  });

  test(
    'composer reuses the session id already bound to the conversation',
    () async {
      SharedPreferences.setMockInitialValues({});
      final api = _FakeApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      const sessionId = 'session_1787875200000_042731';
      controller.selectedConversation!.sessionId = sessionId;

      await controller.send('继续任务');
      await pumpEventQueue();

      expect(api.lastRunBody?['session_id'], sessionId);
    },
  );

  test(
    'branch copies through the selected Run and forks on first send',
    () async {
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            _persistedBranchableConversation(),
          ],
        }),
      });
      final api = _BranchingApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);
      await controller.initialize();

      expect(await controller.branchFromRun('run_branch_1'), isTrue);
      final branch = controller.selectedConversation!;
      expect(branch.sessionId, isNull);
      expect(branch.parentSessionId, 'session_branch_source');
      expect(branch.parentRunId, 'run_branch_1');
      expect(branch.forkBaseSessionRevision, 6);
      expect(branch.messages.map((value) => value.id), [
        'user-branch-1',
        'assistant-branch-1',
      ]);
      expect(branch.processPanels.single.runId, 'run_branch_1');

      await controller.send('从这里继续');
      await pumpEventQueue();

      expect(api.lastRunBody?['session_id'], 'session_branch_source');
      expect(api.lastRunBody?['session_concurrency_mode'], 'fork');
      expect(api.lastRunBody?['base_session_revision'], 6);
      expect(api.lastRunBody?['fork_source_run_id'], 'run_branch_1');
      expect(
        ((api.lastRunBody?['messages'] as List).single as Map)['text'],
        '从这里继续',
      );
      expect(branch.sessionId, 'session_branch_child');
    },
  );

  test(
    'rewriting the last user message replaces the current conversation',
    () async {
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            _persistedBranchableConversation(),
          ],
        }),
      });
      final api = _BranchingApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final source = controller.selectedConversation!;
      final conversationCount = controller.agentWorkspaceConversations.length;

      await controller.rewriteLastUserMessage('user-branch-2', '改写后的第二轮问题');
      await pumpEventQueue();

      expect(controller.selectedConversation, same(source));
      expect(controller.agentWorkspaceConversations.length, conversationCount);
      expect(source.messages.map((value) => value.text), [
        '第一轮问题',
        '第一轮结果',
        '改写后的第二轮问题',
      ]);
      expect(source.sessionId, 'session_branch_child');
      expect(api.lastRunBody?['fork_source_run_id'], 'run_branch_1');
      expect(api.lastRunBody?['session_concurrency_mode'], 'fork');
      expect(
        ((api.lastRunBody?['messages'] as List).single as Map)['text'],
        '改写后的第二轮问题',
      );
    },
  );

  test(
    'rewriting the first user message restarts the current conversation',
    () async {
      final persisted = _persistedBranchableConversation();
      persisted['run_id'] = 'run_branch_1';
      persisted['turn_id'] = 'turn_branch_1';
      persisted['messages'] = (persisted['messages'] as List).take(2).toList();
      persisted['process_panels'] = (persisted['process_panels'] as List)
          .take(1)
          .toList();
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [persisted],
        }),
      });
      final api = _BranchingApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final source = controller.selectedConversation!;

      await controller.rewriteLastUserMessage('user-branch-1', '改写后的第一轮问题');
      await pumpEventQueue();

      expect(controller.selectedConversation, same(source));
      expect(source.messages.map((value) => value.text), ['改写后的第一轮问题']);
      expect(api.lastRunBody, isNot(contains('session_concurrency_mode')));
      expect(api.lastRunBody, isNot(contains('fork_source_run_id')));
      expect(
        api.lastRunBody?['session_id'],
        matches(RegExp(r'^session_\d{13}_\d{6}$')),
      );
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'message actions expose last-user edit and per-Run branch in ${brightness.name} mode',
      (tester) async {
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        SharedPreferences.setMockInitialValues({
          'sage.desktop_v2.conversations.v1': jsonEncode({
            WorkspaceController.agentWorkspaceId: [
              _persistedBranchableConversation(),
            ],
          }),
        });
        final controller = WorkspaceController(
          api: _BranchingApi(),
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();

        final editAction = find.byKey(
          const ValueKey('message-edit:user-branch-2'),
        );
        final branchAction = find.byKey(
          const ValueKey('message-branch:assistant-branch-1'),
        );
        expect(editAction, findsOneWidget);
        expect(
          find.byKey(const ValueKey('message-edit:user-branch-1')),
          findsNothing,
        );
        expect(branchAction, findsOneWidget);
        expect(
          find.byKey(const ValueKey('message-branch:assistant-branch-2')),
          findsOneWidget,
        );
        for (final action in [editAction, branchAction]) {
          final inkWell = tester.widget<InkWell>(action);
          expect(inkWell.hoverColor, isNotNull);
          expect(inkWell.focusColor, isNotNull);
          expect(
            find.ancestor(of: action, matching: find.byType(GlassButton)),
            findsNothing,
          );
        }
        await tester.tap(editAction);
        await tester.pump();
        expect(
          find.byKey(const ValueKey('message-edit-card:user-branch-2')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'thread user jump rail matches yiii navigation and jumps between prompts',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);

      final persisted = _persistedBranchableConversation();
      persisted['messages'] = [
        for (var index = 0; index < 3; index++) ...[
          {
            'id': 'jump-user-$index',
            'role': 'user',
            'text': 'User prompt number $index with enough text',
          },
          {
            'id': 'jump-assistant-$index',
            'role': 'assistant',
            'text': [
              'Assistant reply $index',
              ...List.filled(24, 'Long reply block $index'),
            ].join('\n\n'),
          },
        ],
      ];
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [persisted],
        }),
      });
      final controller = WorkspaceController(
        api: _BranchingApi(),
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('thread-user-jump-rail')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('thread-user-jump-marker-0')),
        findsOneWidget,
      );
      expect(
        tester
            .getSize(find.byKey(const ValueKey('thread-user-jump-line-0')))
            .width,
        8,
      );

      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      addTearDown(mouse.removePointer);
      await mouse.addPointer(location: Offset.zero);
      await mouse.moveTo(
        tester.getCenter(
          find.byKey(const ValueKey('thread-user-jump-marker-0')),
        ),
      );
      await tester.pumpAndSettle(const Duration(milliseconds: 180));
      expect(
        tester
            .getSize(find.byKey(const ValueKey('thread-user-jump-line-0')))
            .width,
        24,
      );
      expect(find.textContaining('User prompt number 0'), findsOneWidget);
      expect(find.textContaining('Assistant reply 0'), findsOneWidget);

      await tester.tap(find.byKey(const ValueKey('thread-user-jump-marker-0')));
      await tester.pumpAndSettle(const Duration(milliseconds: 300));
      final firstPrompt = find.byKey(const ValueKey('jump-user-0'));
      expect(firstPrompt, findsOneWidget);
      final viewport = tester.getRect(
        find.byKey(const ValueKey('thread-message-list')),
      );
      final promptRect = tester.getRect(firstPrompt);
      expect(promptRect.bottom, greaterThan(viewport.top));
      expect(promptRect.top, lessThan(viewport.bottom));
    },
  );

  testWidgets(
    'chat messages select across Markdown blocks and expose copy and reference',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final persisted = _persistedBranchableConversation();
      persisted['messages'] = const [
        {'id': 'user-branch-1', 'role': 'user', 'text': '请给一个例子'},
        {
          'id': 'assistant-branch-1',
          'role': 'assistant',
          'text':
              '第一段内容\n\n- 第二段内容\n\n```dart\nvoid main() {\n  print("hi");\n}\n```',
        },
      ];
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [persisted],
        }),
      });
      final controller = WorkspaceController(
        api: _BranchingApi(),
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();

      final message = find.byKey(
        const ValueKey('message-selection:assistant-branch-1'),
      );
      final markdown = tester.widget<MarkdownBody>(
        find.descendant(of: message, matching: find.byType(MarkdownBody)),
      );
      expect(markdown.selectable, isFalse);
      expect(markdown.fitContent, isFalse);
      expect(find.byKey(const ValueKey('message-code-block')), findsOneWidget);
      expect(find.text('dart'), findsOneWidget);
      expect(
        tester.getSize(find.byKey(const ValueKey('message-code-block'))).width,
        greaterThan(360),
      );
      expect(
        find.byKey(const ValueKey('message-copy:assistant-branch-1')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('message-reference:assistant-branch-1')),
        findsOneWidget,
      );

      final selectionAreaFinder = find.descendant(
        of: message,
        matching: find.byType(SelectionArea),
      );
      final selectionArea = tester.state<SelectionAreaState>(
        selectionAreaFinder,
      );
      selectionArea.selectableRegion.selectAll();
      await tester.pump();
      await tester.tapAt(
        tester.getCenter(
          find.textContaining('第一段内容', findRichText: true).first,
        ),
        buttons: kSecondaryMouseButton,
      );
      await tester.pumpAndSettle();

      expect(find.text('局部引用'), findsOneWidget);
      await tester.tap(find.text('局部引用'));
      await tester.pumpAndSettle();
      expect(controller.composerReferences, hasLength(1));
      expect(controller.composerReferences.single.text, contains('第一段内容'));
      expect(controller.composerReferences.single.text, contains('第二段内容'));
      expect(controller.composerReferences.single.text, contains('void main'));
      final reference = controller.composerReferences.single.toMessageContent();
      expect(reference.citationLabel, '引用');
      expect(reference.quote, startsWith('第一段内容'));

      await tester.tap(
        find.byKey(const ValueKey('message-reference:assistant-branch-1')),
      );
      await tester.pumpAndSettle();
      expect(controller.composerReferences, hasLength(2));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'approval card shows the concrete risk and has distinct actions',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [
            _persistedSuspendedConversation(),
          ],
        }),
      });
      final api = _SuspendedRunApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      expect(find.text('执行命令'), findsOneWidget);
      expect(find.text('rm -rf build'), findsOneWidget);
      expect(find.text('将递归删除文件或目录'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('interaction-submit-approve_once')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('interaction-submit-approve_and_remember')),
        findsOneWidget,
      );
      expect(find.text('后续自动允许该命令'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('interaction-submit-deny')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('interaction-submit-cancel')),
        findsNothing,
      );

      await tester.tap(
        find.byKey(const ValueKey('interaction-submit-approve_once')),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));
      expect(api.repliedDecision, 'approve_once');
      expect(controller.selectedConversation?.pendingInteraction, isNull);
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'questionnaire renders inline with Yiii controls and submits answers '
      'in ${brightness.name} appearance',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final conversation = _persistedSuspendedConversation();
        conversation['pending_interaction'] = {
          'interaction_id': 'interaction_questionnaire',
          'interaction_type': 'questionnaire',
          'allowed_decisions': ['submit', 'cancel'],
          'payload': const {},
        };
        SharedPreferences.setMockInitialValues({
          'sage.desktop_v2.conversations.v1': jsonEncode({
            WorkspaceController.agentWorkspaceId: [conversation],
          }),
        });
        final api = _QuestionnaireSuspendedRunApi();
        final controller = WorkspaceController(
          api: api,
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 500));

        expect(find.text('需要你的引导'), findsOneWidget);
        expect(find.text('请选择部署目标并补充说明。'), findsNothing);
        expect(find.text('回答后 Agent 会从原位置继续。'), findsNothing);
        expect(find.text('可选'), findsNothing);
        expect(find.text('其他'), findsOneWidget);
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('thread-message-list')),
            matching: find.byKey(const ValueKey('questionnaire-block')),
          ),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('interaction-question-notes')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('interaction-submit-cancel')),
          findsNothing,
        );
        expect(find.byType(DropdownButtonFormField<String>), findsNothing);

        await tester.tap(
          find.byKey(
            const ValueKey('interaction-question-target-option-staging'),
          ),
        );
        await tester.pump(const Duration(milliseconds: 140));
        await tester.tap(
          find.byKey(
            const ValueKey('interaction-question-preserve-option-structure'),
          ),
        );
        await tester.pump(const Duration(milliseconds: 140));
        await tester.tap(
          find.byKey(
            const ValueKey('interaction-question-preserve-option-interaction'),
          ),
        );
        await tester.pump(const Duration(milliseconds: 140));
        await tester.enterText(
          find.byKey(const ValueKey('interaction-question-notes')),
          '先进行冒烟验证',
        );
        await tester.tap(
          find.byKey(const ValueKey('interaction-submit-submit')),
        );
        await tester.pump(const Duration(milliseconds: 300));

        expect(api.repliedDecision, 'submit');
        expect(api.repliedPayload?['answers'], {
          'target': 'staging',
          'preserve': ['structure', 'interaction'],
          'notes': '先进行冒烟验证',
        });
      },
    );
  }

  for (final brightness in Brightness.values) {
    testWidgets(
      'file approval shows a compact user-facing preview in ${brightness.name} appearance',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 900);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        SharedPreferences.setMockInitialValues({
          'sage.desktop_v2.conversations.v1': jsonEncode({
            WorkspaceController.agentWorkspaceId: [
              _persistedSuspendedConversation(),
            ],
          }),
        });
        final controller = WorkspaceController(
          api: _FileWriteSuspendedRunApi(),
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 500));

        expect(find.text('写入 quicksort.py'), findsOneWidget);
        expect(find.text('文件写入'), findsOneWidget);
        expect(find.text('/workspace/quicksort.py'), findsOneWidget);
        expect(find.text('内容预览'), findsOneWidget);
        expect(find.text('49 个字符'), findsOneWidget);
        expect(find.text('3 行'), findsOneWidget);
        expect(find.textContaining('def quicksort(values):'), findsOneWidget);
        expect(find.textContaining('internal-marker'), findsNothing);
        expect(
          find.byKey(const ValueKey('interaction-technical-toggle')),
          findsNothing,
        );
        expect(
          find.byKey(const ValueKey('interaction-technical-details')),
          findsNothing,
        );
        expect(find.textContaining('internal-marker'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'plan submission shows full text and approval selects goal mode',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final persisted = _persistedSuspendedConversation();
      persisted['invocation_mode'] = 'plan';
      SharedPreferences.setMockInitialValues({
        'sage.desktop_v2.conversations.v1': jsonEncode({
          WorkspaceController.agentWorkspaceId: [persisted],
        }),
      });
      final api = _PlanSuspendedRunApi();
      final controller = WorkspaceController(
        api: api,
        preferencesLoader: SharedPreferences.getInstance,
      );
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      expect(find.text('审批计划'), findsOneWidget);
      expect(find.text('计划全文'), findsOneWidget);
      expect(find.textContaining('3. 运行验证'), findsOneWidget);
      expect(find.text('批准计划'), findsOneWidget);

      await tester.tap(
        find.byKey(const ValueKey('interaction-submit-approve_once')),
      );
      await tester.pump(const Duration(milliseconds: 300));

      expect(api.repliedDecision, 'approve_once');
      expect(
        controller.selectedConversation?.invocationMode,
        InvocationMode.goal,
      );
    },
  );

  testWidgets('workspace errors use a compact top-right notice', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);
    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    controller.error = '任务状态已变化，此审批请求已失效';
    controller.notifyListeners();
    await tester.pump();

    final notice = find.byKey(const ValueKey('workspace-error-notice'));
    expect(notice, findsOneWidget);
    expect(tester.getTopLeft(notice).dy, lessThan(120));
    expect(tester.getSize(notice).width, lessThanOrEqualTo(380));
    expect(find.text('任务状态已变化，此审批请求已失效'), findsOneWidget);
  });

  testWidgets('settings exposes the effective security scope', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);
    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('安全与权限'));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('settings-security-scope')),
      findsOneWidget,
    );
    expect(find.text('非 Shell 工具'), findsOneWidget);
    expect(find.text('Shell · 自动执行'), findsOneWidget);
    expect(find.text('Shell · 请求审批'), findsOneWidget);
    expect(find.text('Shell · 自动阻止'), findsOneWidget);
    expect(find.textContaining('非 Shell 工具不会仅因写入而触发审批'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('security-command:git reset --hard')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('security-command:curl|sh / wget|bash')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('security-command:git clean -fd')),
      findsOneWidget,
    );

    final rememberedChip = find.byKey(
      const ValueKey('security-command:git clean -fd'),
    );
    await tester.tapAt(
      tester.getTopRight(rememberedChip) - const Offset(12, -12),
    );
    await tester.pumpAndSettle();

    expect(api.lastAgentPatch, {'approved_shell_commands': <String>[]});
    expect(
      find.byKey(const ValueKey('security-command:git clean -fd')),
      findsNothing,
    );
  });

  testWidgets('sandbox settings control mapping and workspace path mode', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);
    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('沙箱').first);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('settings-sandbox-configuration')),
      findsOneWidget,
    );
    expect(find.text('工作区访问'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('settings-sandbox-path-mode-control')),
      findsOneWidget,
    );
    await tester.tap(find.text('与真实目录一致'));
    await tester.pumpAndSettle();
    expect(
      api
          .lastSettings
          ?.componentConfigs['execution.sandbox']?['workspace_path_mode'],
      'host',
    );
    expect(
      api.lastSettings?.componentSelections['execution.sandbox'],
      'sage.sandbox.local-workspace',
    );
    expect(
      find.byKey(const ValueKey('settings-sandbox-host-path')),
      findsOneWidget,
    );

    await tester.tap(find.text('固定虚拟路径').first);
    await tester.pumpAndSettle();
    expect(
      api
          .lastSettings
          ?.componentConfigs['execution.sandbox']?['workspace_path_mode'],
      'virtual',
    );
    expect(
      find.byKey(const ValueKey('settings-sandbox-workspace-root')),
      findsOneWidget,
    );

    expect(find.textContaining('空白沙箱看不到项目文件'), findsOneWidget);
    await tester.tap(find.text('使用临时空白沙箱'));
    await tester.pumpAndSettle();
    expect(
      api.lastSettings?.componentSelections['execution.sandbox'],
      'sage.sandbox.ephemeral',
    );
    expect(
      api
          .lastSettings
          ?.componentConfigs['execution.sandbox']?['workspace_mapping'],
      'isolated',
    );
    expect(
      api
          .lastSettings
          ?.componentConfigs['execution.sandbox']?['workspace_path_mode'],
      'virtual',
    );

    await tester.enterText(
      find.byKey(const ValueKey('settings-sandbox-workspace-root')),
      '/project',
    );
    await tester.pump(const Duration(milliseconds: 700));
    await tester.pumpAndSettle();
    expect(
      api
          .lastSettings
          ?.componentConfigs['execution.sandbox']?['workspace_root'],
      '/project',
    );
  });

  for (final brightness in [Brightness.light, Brightness.dark]) {
    testWidgets(
      'component settings explain active plugins and enforce route ownership in ${brightness.name}',
      (tester) async {
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = _FakeApi();
        final controller = await _controller(api: api);
        addTearDown(controller.dispose);
        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const ValueKey('settings-button')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('运行组件'));
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey('settings-component-context.reducer')),
          findsOneWidget,
        );
        expect(find.text('上下文压缩'), findsOneWidget);
        expect(find.text('在请求超过模型窗口前精简历史消息'), findsOneWidget);
        expect(find.text('持久摘要'), findsWidgets);
        expect(find.text('Run 完成判定'), findsOneWidget);
        expect(find.text('无工具调用即完成'), findsWidgets);
        expect(find.text('无工具调用 + LLM Judge'), findsOneWidget);
        expect(find.text('结束工具（turn_status）'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('settings-continuation-policy-details')),
          findsOneWidget,
        );
        expect(find.text('工具选择策略'), findsOneWidget);
        expect(find.text('大模型工具选择'), findsWidgets);
        expect(find.text('BM25 相关性选择'), findsOneWidget);
        expect(find.text('最近使用优先'), findsOneWidget);
        expect(find.text('直接展示全部工具'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('settings-tool-selection-config')),
          findsOneWidget,
        );
        expect(find.text('插件参数'), findsOneWidget);
        expect(find.text('长期记忆'), findsOneWidget);
        expect(find.text('本地 BM25 记忆'), findsWidgets);
        expect(find.text('/Users/test/sage/runtime/memory'), findsOneWidget);
        expect(find.text('记忆检索词生成'), findsOneWidget);
        expect(find.text('直接使用用户输入'), findsWidgets);
        expect(find.text('LLM 生成检索词'), findsOneWidget);
        expect(
          find.byKey(
            const ValueKey('settings-component-picker-memory.recall-query'),
          ),
          findsOneWidget,
        );
        expect(
          tester
              .getTopLeft(
                find.byKey(
                  const ValueKey('settings-component-memory.recall-query'),
                ),
              )
              .dy,
          lessThan(
            tester
                .getTopLeft(
                  find.byKey(
                    const ValueKey('settings-component-context.reducer'),
                  ),
                )
                .dy,
          ),
        );
        expect(find.text('会话记忆'), findsOneWidget);
        expect(find.text('SQLite BM25 会话记忆'), findsWidgets);
        expect(find.text('关闭会话记忆'), findsOneWidget);
        expect(
          find.text('/Users/test/sage/runtime/session-memory'),
          findsOneWidget,
        );
        expect(find.text('模型请求记录'), findsOneWidget);
        expect(find.text('文件模型请求记录'), findsWidgets);
        expect(find.textContaining('Session → LLM 请求'), findsWidgets);
        expect(
          find.text('/Users/test/sage/runtime/diagnostics'),
          findsOneWidget,
        );
        expect(find.text('结构化日志'), findsOneWidget);
        expect(find.text('轮转文件日志'), findsWidgets);
        expect(find.text('执行沙箱'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('settings-sandbox-workspace-config')),
          findsOneWidget,
        );
        expect(find.textContaining('固定虚拟路径：/workspace'), findsOneWidget);
        expect(find.textContaining('使用当前工作区'), findsOneWidget);
        expect(find.text('工作区初始化'), findsOneWidget);
        expect(find.text('Claw Mode'), findsWidgets);
        expect(find.text('空白工作区'), findsOneWidget);
        expect(
          find.text('/Users/test/sage/runtime/logs/sage.jsonl'),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('settings-log-file-path')),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const ValueKey('settings-component-picker-model.protocol'),
          ),
          findsNothing,
        );

        final maxVisibleTools = find.byKey(
          const ValueKey('settings-tool-selection-max_visible_tools'),
        );
        await tester.ensureVisible(maxVisibleTools);
        await tester.enterText(maxVisibleTools, '20');
        await tester.pumpAndSettle();
        final saveToolSelection = find.byKey(
          const ValueKey('settings-tool-selection-save'),
        );
        await tester.ensureVisible(saveToolSelection);
        await tester.tap(saveToolSelection);
        await tester.pumpAndSettle();
        expect(api.lastSelectedComponent, 'tool.selection-policy');
        expect(api.lastSelectedComponentPlugin, 'sage.tool-selection.llm');
        expect(api.lastSelectedComponentConfig, {'max_visible_tools': 20});

        final toolSelectionPicker = find.byKey(
          const ValueKey('settings-component-picker-tool.selection-policy'),
        );
        await tester.ensureVisible(toolSelectionPicker);
        await tester.tap(toolSelectionPicker);
        await tester.pumpAndSettle();
        await tester.tap(find.text('BM25 相关性选择').last);
        await tester.pumpAndSettle();
        expect(api.lastSelectedComponent, 'tool.selection-policy');
        expect(api.lastSelectedComponentPlugin, 'sage.tool-selection.lexical');

        final contextReducerPicker = find.byKey(
          const ValueKey('settings-component-picker-context.reducer'),
        );
        await tester.ensureVisible(contextReducerPicker);
        await tester.pumpAndSettle();
        await tester.tap(contextReducerPicker);
        await tester.pumpAndSettle();
        await tester.tap(find.text('窗口裁剪').last);
        await tester.pumpAndSettle();
        expect(api.lastSelectedComponent, 'context.reducer');
        expect(api.lastSelectedComponentPlugin, 'sage.context.reducer.window');

        final memoryRecallPicker = find.byKey(
          const ValueKey('settings-component-picker-memory.recall-query'),
        );
        await tester.ensureVisible(memoryRecallPicker);
        await tester.pumpAndSettle();
        await tester.tap(memoryRecallPicker);
        await tester.pumpAndSettle();
        await tester.tap(find.text('LLM 生成检索词').last);
        await tester.pumpAndSettle();
        expect(api.lastSelectedComponent, 'memory.recall-query');
        expect(api.lastSelectedComponentPlugin, 'sage.memory.recall-query.llm');
      },
    );
  }

  testWidgets('settings uses the Yiii two-pane shell', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    final normalRailWidth = tester
        .getSize(find.byKey(const ValueKey('project-rail-repaint-boundary')))
        .width;
    final normalContentX = tester
        .getTopLeft(find.byKey(const ValueKey('thread-repaint-boundary')))
        .dx;
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();

    expect(
      tester.getSize(find.byKey(const ValueKey('settings-rail'))).width,
      moreOrLessEquals(normalRailWidth),
    );
    expect(
      tester.getTopLeft(find.byKey(const ValueKey('settings-content'))).dx,
      moreOrLessEquals(normalContentX),
    );
    expect(find.byKey(const ValueKey('settings-back-button')), findsOneWidget);
    expect(find.text('通用'), findsWidgets);
    expect(find.text('运行时'), findsNothing);
    expect(find.text('工作区'), findsNothing);
    await tester.tap(find.text('通用').first);
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('settings-agent-workspace-path')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('settings-add-project')), findsNothing);
    expect(find.text('Demo Project'), findsNothing);
    expect(
      find.byKey(const ValueKey('settings-preview-bytes')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('settings-tree-entries')), findsOneWidget);
    expect(find.text('组件'), findsNothing);
    expect(find.text('模型'), findsOneWidget);
    expect(find.text('智能体'), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('MCP')).dy,
      lessThan(tester.getTopLeft(find.text('归档记录')).dy),
    );
    expect(find.byKey(const ValueKey('settings-save-button')), findsNothing);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byKey(const ValueKey('settings-back-button')));
    await tester.pumpAndSettle();
    expect(
      tester
          .getSize(find.byKey(const ValueKey('project-rail-repaint-boundary')))
          .width,
      moreOrLessEquals(normalRailWidth),
    );
    expect(
      tester
          .getTopLeft(find.byKey(const ValueKey('thread-repaint-boundary')))
          .dx,
      moreOrLessEquals(normalContentX),
    );
  });

  testWidgets('settings opens with the usage overview and changes range', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();

    expect(find.text('概览'), findsWidgets);
    expect(find.text('总 Token'), findsOneWidget);
    expect(find.text('15K'), findsWidgets);
    expect(find.text('Prompt Cache 利用率'), findsOneWidget);
    expect(find.text('33.3%'), findsWidgets);
    expect(find.text('TTFT P50'), findsOneWidget);
    expect(find.text('680 ms'), findsOneWidget);
    expect(find.text('Token/s P50'), findsOneWidget);
    expect(find.text('30 token/s'), findsOneWidget);
    expect(find.byKey(const ValueKey('usage-metric-strip')), findsOneWidget);
    expect(find.byKey(const ValueKey('usage-token-chart')), findsOneWidget);
    expect(find.text('模型消耗'), findsOneWidget);
    expect(find.text('Agent 消耗'), findsOneWidget);
    expect(find.text('read_file'), findsOneWidget);
    expect(api.lastUsageDays, 30);

    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    addTearDown(mouse.removePointer);
    await mouse.addPointer(location: Offset.zero);
    await mouse.moveTo(
      tester.getCenter(find.byKey(const ValueKey('usage-token-chart'))),
    );
    await tester.pump();

    expect(find.byKey(const ValueKey('usage-token-tooltip')), findsOneWidget);
    expect(find.text('非缓存输入'), findsWidgets);
    expect(find.text('8,000'), findsOneWidget);
    expect(find.text('4,000'), findsOneWidget);
    expect(find.text('3,000'), findsOneWidget);
    expect(find.text('合计'), findsOneWidget);
    expect(find.text('15,000'), findsOneWidget);

    await tester.tap(find.text('7 天'));
    await tester.pumpAndSettle();
    expect(api.lastUsageDays, 7);
  });

  for (final brightness in [Brightness.light, Brightness.dark]) {
    testWidgets(
      'usage latency metrics stay responsive in ${brightness.name} mode',
      (tester) async {
        tester.view.physicalSize = const Size(375, 720);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final api = _FakeApi()
          ..usageDataQuality = const UsageDataQuality(
            partial: true,
            skippedSessions: 1,
            skippedEventSessions: 1,
          );
        final controller = await _controller(api: api);
        addTearDown(controller.dispose);
        await controller.loadUsageOverview();

        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            locale: const Locale('en'),
            localizationsDelegates: const [SageLocalizations.delegate],
            supportedLocales: SageLocalizations.supportedLocales,
            home: Scaffold(
              body: Padding(
                padding: const EdgeInsets.all(16),
                child: UsageOverviewSettings(controller: controller),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('TTFT P50'), findsOneWidget);
        expect(find.text('P95 1.35 s · n=8'), findsOneWidget);
        expect(find.text('Token/s P50'), findsOneWidget);
        expect(find.text('P95 48 token/s · n=7'), findsOneWidget);
        expect(
          find.text('8 model requests · 1 failed · 2 sessions'),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('usage-metric-strip')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('usage-partial-data-notice')),
          findsOneWidget,
        );
        expect(
          find.text('Partial data · affected sessions: 1'),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'archived conversations stay out of recents and can be restored',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
      final controller = await _controller();
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      final conversation = controller.selectedConversation!;
      conversation.title = '需要归档的会话';
      conversation.messages.addAll([
        ChatMessage(
          id: 'user-visible',
          role: 'user',
          text: '帮我检查一下',
          createdAt: DateTime(2026, 8, 27, 9),
        ),
        ChatMessage(
          id: 'assistant-process',
          role: 'assistant',
          text: '这是折叠区里的过程内容',
          processOnly: true,
          createdAt: DateTime(2026, 8, 27, 20, 30),
        ),
        ChatMessage(
          id: 'assistant-visible',
          role: 'assistant',
          text: '**最终结果**\n\n这是正常聊天区可见的内容。',
          createdAt: DateTime(2026, 8, 27, 9, 5),
        ),
      ]);
      controller.archiveConversation(
        WorkspaceController.agentWorkspaceId,
        conversation.id,
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(ValueKey('conversation-actions-button-${conversation.id}')),
        findsNothing,
      );
      expect(
        controller.agentWorkspaceConversations,
        isNot(contains(conversation)),
      );
      expect(
        controller.archivedConversations.single.conversation,
        conversation,
      );

      await tester.tap(find.byKey(const ValueKey('settings-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('归档记录'));
      await tester.pumpAndSettle();

      expect(
        find.byKey(ValueKey('settings-archived-${conversation.id}')),
        findsWidgets,
      );
      expect(find.text('最终结果 这是正常聊天区可见的内容。'), findsOneWidget);
      expect(find.text('2026/08/27 09:05'), findsOneWidget);
      expect(find.textContaining('这是折叠区里的过程内容'), findsNothing);
      final preview = tester.widget<Text>(
        find.byKey(ValueKey('settings-archived-preview-${conversation.id}')),
      );
      expect(preview.maxLines, 2);
      expect(preview.overflow, TextOverflow.ellipsis);
      final time = tester.widget<Text>(
        find.byKey(ValueKey('settings-archived-time-${conversation.id}')),
      );
      expect(time.maxLines, 1);
      expect(time.overflow, TextOverflow.ellipsis);
      await tester.tap(
        find.byKey(ValueKey('settings-archived-restore-${conversation.id}')),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('settings-archived-empty')),
        findsOneWidget,
      );
      expect(controller.agentWorkspaceConversations, contains(conversation));
    },
  );

  testWidgets('selected conversation exposes the liquid glass archive menu', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    final conversation = controller.selectedConversation!;
    final action = find.byKey(
      ValueKey('conversation-actions-button-${conversation.id}'),
    );
    expect(action, findsOneWidget);

    await tester.tap(action);
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(ValueKey('conversation-archive-${conversation.id}')),
    );
    await tester.pumpAndSettle();

    expect(controller.archivedConversations.single.conversation, conversation);
    expect(
      controller.agentWorkspaceConversations,
      isNot(contains(conversation)),
    );
  });

  testWidgets('archived conversations can be permanently deleted', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    final conversation = controller.selectedConversation!
      ..title = '彻底删除的会话'
      ..sessionId = 'session_to_delete'
      ..messages.add(
        ChatMessage(
          id: 'assistant-light-preview',
          role: 'assistant',
          text: '浅色模式下的可见摘要',
          createdAt: DateTime(2026, 8, 26, 17, 12),
        ),
      );
    controller.archiveConversation(
      WorkspaceController.agentWorkspaceId,
      conversation.id,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('归档记录'));
    await tester.pumpAndSettle();

    expect(find.text('浅色模式下的可见摘要'), findsOneWidget);
    expect(find.text('2026/08/26 17:12'), findsOneWidget);

    await tester.tap(
      find.byKey(ValueKey('settings-archived-delete-${conversation.id}')),
    );
    await tester.pumpAndSettle();
    expect(find.text('彻底删除“彻底删除的会话”？'), findsOneWidget);
    await tester.tap(
      find.byKey(const ValueKey('archived-conversation-delete-confirm')),
    );
    await tester.pumpAndSettle();

    expect(api.lastDeletedSessionId, 'session_to_delete');
    expect(controller.archivedConversations, isEmpty);
    expect(
      find.byKey(const ValueKey('settings-archived-empty')),
      findsOneWidget,
    );
  });

  testWidgets('agent settings are view first and auto-save while editing', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-name-field')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();
    expect(find.text('保存'), findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('agent-name-field')),
      'Refactor Agent',
    );
    await tester.pump(const Duration(milliseconds: 700));
    await tester.pumpAndSettle();

    expect(api.lastAgentPatch, {'name': 'Refactor Agent'});
    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('agent-name-field')), findsNothing);
    expect(find.byKey(const ValueKey('settings-save-button')), findsNothing);
  });

  for (final brightness in Brightness.values) {
    testWidgets(
      'adding an agent creates defaults and enters editing in ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final api = _FakeApi();
        final controller = await _controller(api: api);
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-button')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('智能体').first);
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-agent-add')));
        await tester.pumpAndSettle();

        expect(api.lastCreatedAgentName, '新建智能体');
        expect(controller.agentConfiguration?.id, 'agent_created');
        expect(controller.agentConfiguration?.agentMode, 'simple');
        expect(find.byKey(const ValueKey('agent-name-field')), findsOneWidget);
        expect(find.text('新建智能体'), findsWidgets);
      },
    );
  }

  for (final brightness in Brightness.values) {
    testWidgets(
      'tool catalog and agent tools keep source groups in ${brightness.name} appearance',
      (tester) async {
        tester.view.physicalSize = const Size(1400, 800);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        tester.platformDispatcher.localeTestValue = const Locale('zh', 'CN');
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        SharedPreferences.setMockInitialValues({});
        final controller = WorkspaceController(
          api: _GroupedToolsApi(),
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-button')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('工具').first);
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey('settings-choice-group-文件')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('settings-choice-group-代码检索')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('settings-choice-group-内置MCP: search')),
          findsOneWidget,
        );

        await tester.tap(find.text('智能体').first);
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey('assignment-group-工具-文件')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('assignment-group-工具-内置MCP: search')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('assignment-group-工具-代码检索')),
          findsNothing,
        );

        await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey('assignment-group-工具-代码检索')),
          findsOneWidget,
        );
        expect(find.text('grep'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'skill settings show the complete SKILL.md in reading and source modes',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = await _controller();
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('settings-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('技能').first);
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('settings-skill-upload-folder')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('settings-skill-document')),
        findsOneWidget,
      );
      expect(find.text('Code Review'), findsOneWidget);
      expect(
        find.text('Inspect the complete diff before reporting findings.'),
        findsOneWidget,
      );
      expect(find.textContaining('name: code-review'), findsNothing);
      expect(
        find.textContaining('description: Review code safely'),
        findsNothing,
      );

      await tester.tap(find.text('源码'));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('settings-skill-source')),
        findsOneWidget,
      );
      expect(find.textContaining('name: code-review'), findsOneWidget);
    },
  );

  testWidgets('imported skill can be deleted after confirmation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('技能').first);
    await tester.pumpAndSettle();

    final deleteButton = find.byKey(
      const ValueKey('settings-skill-delete-code-review'),
    );
    expect(deleteButton, findsOneWidget);
    await tester.tap(deleteButton);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('settings-skill-delete-confirm')),
      findsOneWidget,
    );
    expect(find.text('删除“code-review”？'), findsOneWidget);
    await tester.tap(
      find.byKey(const ValueKey('settings-skill-delete-confirm')),
    );
    await tester.pumpAndSettle();

    expect(api.lastDeletedSkillName, 'code-review');
    expect(deleteButton, findsNothing);
    expect(find.text('已删除 code-review'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('agent settings use a flat compact agent selector', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();

    final selector = find.byKey(const ValueKey('settings-agent-picker'));
    expect(selector, findsOneWidget);
    expect(
      find.descendant(of: selector, matching: find.byType(GlassCard)),
      findsNothing,
    );
    expect(find.text('Review Agent'), findsOneWidget);
    await tester.tap(find.text('Review Agent'));
    await tester.pumpAndSettle();
    expect(controller.agentConfiguration?.id, 'agent_review');
  });

  testWidgets('selecting an agent keeps the selector mounted', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _DelayedAgentApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();

    final list = find.byKey(const ValueKey('settings-choice-list'));
    final listElement = tester.element(list);
    await tester.tap(find.text('Review Agent'));
    await tester.pump();

    expect(list, findsOneWidget);
    expect(identical(tester.element(list), listElement), isTrue);
    expect(
      find.byKey(const ValueKey('settings-agent-detail-loading')),
      findsOneWidget,
    );

    api.reviewConfiguration.complete(
      const AgentConfiguration(id: 'agent_review', name: 'Review Agent'),
    );
    await tester.pumpAndSettle();

    expect(controller.agentConfiguration?.id, 'agent_review');
    expect(
      find.byKey(const ValueKey('settings-agent-detail-loading')),
      findsNothing,
    );
    expect(identical(tester.element(list), listElement), isTrue);
  });

  testWidgets('agent edit accepts a provider missing from the catalog', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final controller = WorkspaceController(
      api: _MissingProviderAgentApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();

    expect(
      find.descendant(
        of: find.byKey(const ValueKey('agent-main-model')),
        matching: find.text('provider-not-in-catalog'),
      ),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('agent view formats prompt and context and edits thinking', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('agent-system-prompt-markdown')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('agent-runtime-variables-formatted')),
      findsOneWidget,
    );
    expect(find.text('运行变量'), findsOneWidget);
    expect(find.text('快速模型'), findsOneWidget);
    expect(find.text('系统上下文'), findsNothing);
    expect(find.text('preferences'), findsOneWidget);
    expect(find.text('concise'), findsOneWidget);
    expect(find.text('true'), findsOneWidget);
    expect(find.textContaining('"concise"'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('agent-fast-model')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('agent-fast-model')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Secondary · test-model-secondary').last);
    await tester.pumpAndSettle();
    expect(api.lastAgentPatch, {'fast_llm_provider_id': 'model_secondary'});
    expect(
      find.byKey(const ValueKey('agent-runtime-variables-editor')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('runtime-variable-key:language')),
      findsOneWidget,
    );
    expect(find.textContaining('{"language"'), findsNothing);
    await tester.enterText(
      find.descendant(
        of: find.byKey(const ValueKey('runtime-variable-value:language')),
        matching: find.byType(GlassTextField),
      ),
      'en',
    );
    await tester.pump(const Duration(milliseconds: 700));
    expect(api.lastAgentPatch, {
      'runtime_variables': {
        'language': 'en',
        'preferences': {'concise': true},
      },
    });
    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('agent-deep-thinking')),
        matching: find.text('关闭'),
      ),
    );
    await tester.pumpAndSettle();
    expect(api.lastAgentPatch, {'deep_thinking': false});
  });

  testWidgets('agent reasoning controls follow verified model capabilities', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('agent-thinking-level')));
    await tester.pumpAndSettle();
    expect(find.text('低'), findsWidgets);
    expect(find.text('高'), findsOneWidget);
    expect(find.text('中'), findsNothing);
    await tester.tap(find.text('高'));
    await tester.pumpAndSettle();
    expect(api.lastAgentPatch, {'thinking_level': 'high'});

    await tester.tap(find.byKey(const ValueKey('agent-main-model')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Secondary · test-model-secondary').last);
    await tester.pumpAndSettle();
    expect(api.lastAgentPatch, {
      'llm_provider_id': 'model_secondary',
      'deep_thinking': true,
    });
    expect(find.byKey(const ValueKey('agent-thinking-level')), findsNothing);
    expect(find.text('默认'), findsWidgets);

    await tester.tap(find.byKey(const ValueKey('agent-main-model')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Luna · gpt-5.6-luna').last);
    await tester.pumpAndSettle();
    expect(api.lastAgentPatch, {
      'llm_provider_id': 'model_luna',
      'deep_thinking': false,
    });
    expect(find.byKey(const ValueKey('agent-thinking-level')), findsNothing);
    expect(find.text('默认'), findsWidgets);
  });

  testWidgets('agent can be deleted from the compact list', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();

    await tester.tap(
      find.byKey(const ValueKey('settings-agent-delete-agent_review')),
    );
    await tester.pumpAndSettle();
    expect(find.text('删除“Review Agent”？'), findsOneWidget);
    await tester.tap(
      find.byKey(const ValueKey('settings-agent-delete-confirm')),
    );
    await tester.pumpAndSettle();

    expect(api.lastDeletedAgentId, 'agent_review');
    expect(controller.agents.map((value) => value.id), ['agent_main']);
  });

  testWidgets('general settings omit the unused runtime event preference', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('通用').first);
    await tester.pumpAndSettle();

    expect(find.text('显示运行事件'), findsNothing);
    expect(
      find.byKey(const ValueKey('settings-default-agent-picker')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('settings-default-model-picker')),
      findsNothing,
    );
  });

  testWidgets('agent and model pages expose right-click default actions', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _FakeApi();
    final controller = await _controller(api: api);
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('settings-agent-set-default')),
      findsOneWidget,
    );

    await tester.tap(find.text('Review Agent'), buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('settings-set-default-agent_review')),
        matching: find.text('设为默认'),
      ),
      findsOneWidget,
    );
    await tester.tap(
      find.byKey(const ValueKey('settings-set-default-agent_review')),
    );
    await tester.pumpAndSettle();
    expect(api.lastSettings?.defaultAgentId, 'agent_review');

    await tester.tap(find.text('模型').first);
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('settings-model-set-default')),
      findsOneWidget,
    );
    await tester.tap(find.text('Secondary'), buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('settings-set-default-model_secondary')),
        matching: find.text('设为默认'),
      ),
      findsOneWidget,
    );
    await tester.tap(
      find.byKey(const ValueKey('settings-set-default-model_secondary')),
    );
    await tester.pumpAndSettle();

    expect(api.lastModelPatch, {'is_default': true});
    expect(
      controller.modelProviders
          .firstWhere((value) => value.id == 'model_secondary')
          .isDefault,
      isTrue,
    );
    expect(
      controller.modelProviders
          .firstWhere((value) => value.id == 'model_main')
          .isDefault,
      isFalse,
    );

    await tester.tap(find.text('Secondary'), buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('settings-set-default-model_secondary')),
        matching: find.text('当前默认'),
      ),
      findsOneWidget,
    );
    expect(
      tester
          .widget<PopupMenuItem<bool>>(
            find.byKey(const ValueKey('settings-set-default-model_secondary')),
          )
          .enabled,
      isFalse,
    );
  });

  testWidgets('model draft is validated before explicit save', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-model-edit')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('settings-model-base-url-field')),
      'https://next.example.test/v1',
    );
    await tester.enterText(
      find.byKey(const ValueKey('settings-model-id-field')),
      'next-model',
    );
    await tester.pumpAndSettle();

    expect(api.lastModelPatch, isNull);
    expect(find.byKey(const ValueKey('settings-model-save')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('settings-model-capability-check')),
      findsOneWidget,
    );
    final capabilityCheck = find.byKey(
      const ValueKey('settings-model-capability-check'),
    );
    await tester.ensureVisible(capabilityCheck);
    await tester.pumpAndSettle();
    await tester.tap(capabilityCheck);
    await tester.pumpAndSettle();

    expect(api.lastModelPatch, isNull);
    expect(api.lastModelCapabilityProviderId, 'model_main');
    expect(api.lastModelCapabilityDraft?['model'], 'next-model');
    expect(
      find.byKey(const ValueKey('settings-model-capability-result')),
      findsOneWidget,
    );
    expect(find.text('输出 Token 参数'), findsOneWidget);
    expect(find.text('max_completion_tokens'), findsOneWidget);
    expect(find.text('实测输出上限'), findsOneWidget);
    expect(find.text('4096'), findsOneWidget);
    expect(find.text('可控制'), findsOneWidget);
    expect(find.text('reasoning_effort'), findsOneWidget);
    expect(find.text('低 · 高'), findsOneWidget);
    expect(find.text('极高'), findsOneWidget);
    expect(find.text('辅助 JSON'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('settings-model-save')));
    await tester.pumpAndSettle();

    expect(api.lastModelPatch?['model'], 'next-model');
    expect(api.lastModelPatch?['base_url'], 'https://next.example.test/v1');
    expect(api.lastModelPatch?['protocol'], 'openai-responses');
    expect(api.lastModelPatch?['supports_tool_calling'], isTrue);
    expect(
      (api.lastModelPatch?['compatibility_profile']
          as Map?)?['route_fingerprint'],
      'sha256:verified-route',
    );
    expect(find.text('工具调用'), findsOneWidget);
    expect(find.byKey(const ValueKey('settings-model-id-field')), findsNothing);
    expect(find.byKey(const ValueKey('settings-save-button')), findsNothing);
  });

  testWidgets('model capability check shows the multimodal probe cause', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi()
      ..modelCapabilityResult = {
        'supports_multimodal': false,
        'supports_structured_output': true,
        'supports_tool_calling': true,
        'multimodal': {
          'supported': false,
          'status': 'error',
          'provider_code': '400',
          'error_code': 'model.provider_permanent',
          'error': 'large raw provider error',
          'metadata': {
            'diagnostic_error':
                'ResponseInputImageParam.detail: Field required',
          },
        },
        'probes': {
          'multimodal': {
            'supported': false,
            'status': 'error',
            'provider_code': '400',
            'error_code': 'model.provider_permanent',
            'error': 'large raw provider error',
            'metadata': {
              'diagnostic_error':
                  'ResponseInputImageParam.detail: Field required',
            },
          },
        },
        'compatibility_profile': {
          'schema_version': 2,
          'route_fingerprint': 'sha256:verified-route',
          'verified_at': '2026-09-03T00:00:00Z',
          'successful_probes': ['connection'],
          'failed_probes': ['multimodal'],
          'probe_diagnostics': {
            'multimodal': {
              'status': 'error',
              'provider_code': '400',
              'error_code': 'model.provider_permanent',
              'diagnostic_error':
                  'ResponseInputImageParam.detail: Field required',
            },
          },
        },
      };
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-model-edit')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('settings-model-id-field')),
      'changed-model',
    );
    final capabilityCheck = find.byKey(
      const ValueKey('settings-model-capability-check'),
    );
    await tester.ensureVisible(capabilityCheck);
    await tester.pumpAndSettle();
    await tester.tap(capabilityCheck);
    await tester.pumpAndSettle();

    expect(find.textContaining('HTTP 400'), findsOneWidget);
    expect(
      find.textContaining('ResponseInputImageParam.detail: Field required'),
      findsOneWidget,
    );

    final save = find.byKey(const ValueKey('settings-model-save'));
    await tester.ensureVisible(save);
    await tester.pumpAndSettle();
    await tester.tap(save);
    await tester.pumpAndSettle();

    expect(find.textContaining('HTTP 400'), findsOneWidget);
    expect(
      find.textContaining('ResponseInputImageParam.detail: Field required'),
      findsOneWidget,
    );
  });

  testWidgets(
    'model settings can create a new route in light and dark themes',
    (tester) async {
      for (final brightness in [Brightness.light, Brightness.dark]) {
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        SharedPreferences.setMockInitialValues({});
        final api = _FakeApi();
        final controller = WorkspaceController(
          api: api,
          preferencesLoader: SharedPreferences.getInstance,
        );

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-button')));
        await tester.pumpAndSettle();
        await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-model-add')));
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey('settings-model-id-field')),
          findsOneWidget,
        );
        await tester.tap(
          find.byKey(const ValueKey('settings-model-protocol-picker')),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Anthropic Messages').last);
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('settings-model-id-field')),
          findsOneWidget,
        );
        expect(find.text('Anthropic Messages'), findsOneWidget);
        await tester.enterText(
          find.byKey(const ValueKey('settings-model-id-field')),
          'created-model',
        );
        await tester.tap(
          find.byKey(const ValueKey('settings-model-capability-check')),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-model-save')));
        await tester.pumpAndSettle();

        expect(api.lastModelCreate?['model'], 'created-model');
        expect(api.lastModelCreate?['protocol'], 'anthropic-messages');
        expect(controller.modelProviders.last.id, 'model_created');
        controller.dispose();
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pumpAndSettle();
      }
      tester.platformDispatcher.clearPlatformBrightnessTestValue();
      tester.platformDispatcher.clearLocaleTestValue();
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    },
  );

  for (final width in const [375.0, 700.0]) {
    testWidgets(
      'model capability result does not overflow at ${width.toInt()}px',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        SharedPreferences.setMockInitialValues({});
        final controller = WorkspaceController(
          api: _FakeApi(),
          preferencesLoader: SharedPreferences.getInstance,
        );
        addTearDown(controller.dispose);

        await tester.pumpWidget(SageDesktopV2App(controller: controller));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings-button')));
        await tester.pumpAndSettle();
        await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
        await tester.pumpAndSettle();
        tester.view.physicalSize = Size(width, 800);
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey('settings-model-capability-result')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('model protocol is edited on the model route, not components', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
    await tester.pumpAndSettle();
    expect(find.text('OpenAI Responses'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('settings-model-edit')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('settings-model-protocol-picker')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Anthropic Messages').last);
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('settings-model-capability-check')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-model-save')));
    await tester.pumpAndSettle();

    expect(api.lastModelPatch?['protocol'], 'anthropic-messages');
  });

  testWidgets('model save waits for validation and cancel discards the draft', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-model-edit')));
    await tester.pumpAndSettle();
    var savePointer = tester.widget<IgnorePointer>(
      find
          .descendant(
            of: find.byKey(const ValueKey('settings-model-save')),
            matching: find.byType(IgnorePointer),
          )
          .first,
    );
    expect(savePointer.ignoring, isTrue);
    await tester.enterText(
      find.byKey(const ValueKey('settings-model-id-field')),
      'unchecked-model',
    );
    await tester.pumpAndSettle();

    expect(api.lastModelPatch, isNull);
    savePointer = tester.widget<IgnorePointer>(
      find
          .descendant(
            of: find.byKey(const ValueKey('settings-model-save')),
            matching: find.byType(IgnorePointer),
          )
          .first,
    );
    expect(savePointer.ignoring, isTrue);
    await tester.tap(find.byKey(const ValueKey('settings-model-cancel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('settings-model-id-field')), findsNothing);
    expect(api.lastModelPatch, isNull);
  });

  testWidgets('model API key is revealed only on demand and can be hidden', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = await _controller();
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
    await tester.pumpAndSettle();

    expect(find.text('sk-visible-test'), findsNothing);
    await tester.tap(
      find.byKey(const ValueKey('settings-model-api-key-toggle')),
    );
    await tester.pumpAndSettle();
    expect(find.text('sk-visible-test'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('settings-model-api-key-toggle')),
    );
    await tester.pumpAndSettle();
    expect(find.text('sk-visible-test'), findsNothing);
  });

  testWidgets('non-default model can be deleted from the compact list', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(CupertinoIcons.slider_horizontal_3).first);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('settings-model-delete-model_main')),
      findsOneWidget,
    );
    await tester.tap(
      find.byKey(const ValueKey('settings-model-delete-model_secondary')),
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('settings-model-delete-confirm')),
      findsOneWidget,
    );
    await tester.tap(
      find.byKey(const ValueKey('settings-model-delete-confirm')),
    );
    await tester.pumpAndSettle();

    expect(api.lastDeletedModelId, 'model_secondary');
    expect(controller.modelProviders.map((value) => value.id), ['model_main']);
    expect(find.text('Secondary'), findsNothing);
  });

  testWidgets('tool catalog has its own scroll view and renders schema', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final controller = WorkspaceController(
      api: _ManyToolsApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('工具').first);
    await tester.pumpAndSettle();

    final list = find.byKey(const ValueKey('settings-choice-list'));
    expect(list, findsOneWidget);
    expect(tester.widget<ListView>(list).controller, isNotNull);
    expect(
      find.byKey(const ValueKey('settings-tool-overview')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('settings-tool-schema')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('settings-tool-overview')),
        matching: find.byType(GlassCard),
      ),
      findsNothing,
    );
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('settings-tool-schema')),
        matching: find.byType(GlassCard),
      ),
      findsNothing,
    );
    expect(find.text('value'), findsOneWidget);
    expect(find.text('string'), findsNWidgets(2));
    expect(find.text('必填'), findsNWidgets(2));
    expect(find.text('输入值'), findsOneWidget);
    expect(find.text('可选值 · alpha / beta'), findsOneWidget);
    expect(find.text('默认值 · alpha'), findsOneWidget);
    expect(find.text('enabled'), findsOneWidget);
    expect(find.text('session_id'), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('session_id')).dx,
      moreOrLessEquals(tester.getTopLeft(find.text('value')).dx),
    );
    expect(find.textContaining('"properties"'), findsNothing);

    await tester.drag(list, const Offset(0, -900));
    await tester.pumpAndSettle();
    expect(find.text('tool_29'), findsOneWidget);
  });

  for (final brightness in Brightness.values) {
    testWidgets('tool details support ${brightness.name} appearance', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.platformBrightnessTestValue = brightness;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
      final controller = await _controller();
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('settings-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('工具').first);
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('settings-tool-overview')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('settings-tool-schema')),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }

  for (final brightness in Brightness.values) {
    testWidgets('skill document supports ${brightness.name} appearance', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.platformBrightnessTestValue = brightness;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
      final controller = await _controller();
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('settings-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('技能').first);
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('settings-skill-document')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('settings-skill-markdown')),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }

  for (final width in const [375.0, 700.0]) {
    testWidgets('skill document does not overflow at ${width.toInt()}px', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1200, 760);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = await _controller();
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('settings-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('技能').first);
      await tester.pumpAndSettle();
      tester.view.physicalSize = Size(width, 760);
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('settings-skill-document')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('settings-skill-delete-code-review')),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('settings title and selector stay fixed while detail scrolls', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final controller = WorkspaceController(
      api: _DenseAgentApi(),
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('智能体').first);
    await tester.pumpAndSettle();

    final title = find.byKey(const ValueKey('settings-content-title'));
    final selector = find.byKey(const ValueKey('settings-agent-picker'));
    final detail = find.byKey(const ValueKey('settings-detail-scroll'));
    final titleTop = tester.getTopLeft(title).dy;
    final selectorTop = tester.getTopLeft(selector).dy;

    await tester.drag(detail, const Offset(0, -900));
    await tester.pumpAndSettle();

    expect(tester.getTopLeft(title).dy, titleTop);
    expect(tester.getTopLeft(selector).dy, selectorTop);
    expect(find.text('skill_23'), findsOneWidget);
  });

  testWidgets('appearance restores and auto-saves from general settings', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi()
      ..desktopSettings = const DesktopSettings(
        themeMode: 'dark',
        language: 'zh',
        agentWorkspacePath: '/tmp/sage/agent_workspace',
      );
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();

    expect(
      tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode,
      ThemeMode.dark,
    );
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('通用').first);
    await tester.pumpAndSettle();
    final selector = tester.widget<GlassSegmentedControl>(
      find.byType(GlassSegmentedControl).first,
    );
    expect(selector.selectedIndex, ThemeMode.values.indexOf(ThemeMode.dark));

    await tester.tap(find.text('浅色'));
    await tester.pumpAndSettle();

    expect(api.lastSettings?.themeMode, 'light');
    expect(
      tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode,
      ThemeMode.light,
    );
  });

  testWidgets('language restores and auto-saves from general settings', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi()
      ..desktopSettings = const DesktopSettings(
        language: 'ja',
        agentWorkspacePath: '/tmp/sage/agent_workspace',
      );
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    expect(
      tester.widget<MaterialApp>(find.byType(MaterialApp)).locale,
      const Locale('ja'),
    );

    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    expect(find.text('一般'), findsWidgets);
    expect(find.text('ツール'), findsOneWidget);
    await tester.tap(find.text('一般').first);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('settings-language-picker')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('한국어').last);
    await tester.pumpAndSettle();

    expect(api.lastSettings?.language, 'ko');
    expect(
      tester.widget<MaterialApp>(find.byType(MaterialApp)).locale,
      const Locale('ko'),
    );
    expect(find.text('일반'), findsWidgets);
    expect(find.text('도구'), findsOneWidget);
  });

  testWidgets('agent workspace path auto-saves from general settings', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    final controller = WorkspaceController(
      api: api,
      preferencesLoader: SharedPreferences.getInstance,
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(SageDesktopV2App(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('通用').first);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('settings-agent-workspace-path')),
      '/tmp/custom_agent_workspace',
    );
    await tester.pump(const Duration(milliseconds: 750));
    await tester.pumpAndSettle();

    expect(api.lastSettings?.agentWorkspacePath, '/tmp/custom_agent_workspace');
    expect(find.byKey(const ValueKey('settings-save-button')), findsNothing);
  });

  for (final size in const [
    Size(375, 720),
    Size(700, 760),
    Size(768, 760),
    Size(1024, 760),
    Size(1440, 900),
  ]) {
    testWidgets('layout does not overflow at ${size.width.toInt()}px', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = await _controller();
      addTearDown(controller.dispose);

      await tester.pumpWidget(SageDesktopV2App(controller: controller));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('project-rail-repaint-boundary')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('thread-repaint-boundary')),
        findsOneWidget,
      );
      if (size.width < 760 || size.width >= 1024) {
        expect(
          find.byKey(const ValueKey('workspace-repaint-boundary')),
          findsOneWidget,
        );
      }
      expect(tester.takeException(), isNull);
    });
  }
}
