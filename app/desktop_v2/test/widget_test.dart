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
import 'package:sage_desktop_v2/src/ui/file_preview.dart';
import 'package:sage_desktop_v2/src/ui/tool_activity_presentation.dart';

class _FakeApi extends V2ApiClient {
  Map<String, Object?>? lastAgentPatch;
  String? lastCreatedAgentName;
  Map<String, Object?>? lastModelPatch;
  Map<String, Object?>? lastModelCreate;
  DesktopSettings? lastSettings;
  String? lastDeletedModelId;
  String? lastDeletedAgentId;
  String? lastDeletedSessionId;
  Map<String, Object?>? lastRunBody;
  int workspaceFileCalls = 0;
  String? lastWorkspaceTreeId;
  String? importedSkillFolder;
  String? lastSelectedComponent;
  String? lastSelectedComponentPlugin;
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
  Future<List<SkillSummary>> listSkills(String agentId) async => const [
    SkillSummary(name: 'code-review'),
  ];

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
        availableSkills: const ['code-review'],
      );

  @override
  Future<AgentConfiguration> patchAgentConfiguration(
    String agentId,
    Map<String, Object?> patch,
  ) async {
    lastAgentPatch = patch;
    return AgentConfiguration(
      id: agentId,
      name: patch['name']?.toString() ?? 'Sage Agent',
      systemPrefix: '# Sage\n\n- Follow instructions.',
      systemContext: const {'language': 'zh'},
      deepThinking: patch['deep_thinking'] as bool? ?? true,
      thinkingLevel: patch['thinking_level']?.toString() ?? 'medium',
      availableTools: const ['read_file'],
      availableSkills: const ['code-review'],
    );
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
  Future<List<SkillSummary>> listSkillCatalog() async => const [
    SkillSummary(name: 'code-review', description: 'Review code safely'),
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
    return const ['code-review'];
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
    ),
    ModelProviderSummary(
      id: 'model_secondary',
      name: 'Secondary',
      model: 'test-model-secondary',
      baseUrl: 'https://example.test/v1',
      apiKeyConfigured: true,
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
      supportsMultimodal: true,
      supportsStructuredOutput: true,
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
    return ModelProviderSummary(
      id: providerId,
      name: patch['name']?.toString() ?? 'Primary',
      protocol: patch['protocol']?.toString() ?? 'openai-responses',
      model: patch['model']?.toString() ?? 'test-model',
      baseUrl: patch['base_url']?.toString() ?? 'https://example.test/v1',
      apiKeyConfigured: true,
      supportsMultimodal: true,
    );
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
  Future<List<McpConnectionSummary>> listMcpConnections() async => const [
    McpConnectionSummary(name: 'filesystem', protocol: 'stdio', toolCount: 2),
  ];

  @override
  Future<List<ComponentSummary>> listComponents() async => const [
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
  ];

  @override
  Future<void> selectComponent(String componentId, String pluginId) async {
    lastSelectedComponent = componentId;
    lastSelectedComponentPlugin = pluginId;
  }

  @override
  Future<DesktopSettings> saveSettings(DesktopSettings settings) async {
    lastSettings = settings;
    desktopSettings = settings;
    return settings;
  }

  @override
  Future<List<WorkspaceFileNode>> workspaceTree({
    required String agentId,
    String workspaceId = '',
  }) async {
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
    ToolSummary(name: 'file_read', source: '文件'),
    ToolSummary(name: 'grep', source: '代码检索'),
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
        'allowed_decisions': ['approve_once', 'deny', 'cancel'],
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
    'allowed_decisions': ['approve_once', 'deny', 'cancel'],
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

void main() {
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

  testWidgets('unsupported sagents display languages fall back to English', (
    tester,
  ) async {
    late String language;
    await tester.pumpWidget(
      Localizations(
        locale: const Locale('ja'),
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
      expect(
        toolArgumentPreview('grep', const {
          'pattern': 'quicksort',
          'path': '/workspace/projects',
          'case_insensitive': true,
          'session_id': 'hidden-session',
        }, 'zh'),
        '“quicksort” · /workspace/projects · 忽略大小写',
      );
    },
  );

  test('workspace selection queues an exact composer reference', () async {
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
    expect(
      controller.takeComposerInsertion(controller.selectedConversationId),
      '@docs/notes.md\n> 第一行\n> 第二行',
    );
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

        await tester.tap(
          find.byKey(const ValueKey('file-tree-reference:README.md')),
        );
        await tester.pumpAndSettle();
        expect(controller.attachments.single.name, 'README.md');
      },
    );
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

  for (final brightness in Brightness.values) {
    testWidgets(
      'sidebar creation icons and project disclosure work in ${brightness.name} mode',
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
      findsOneWidget,
    );
    expect(find.text('我先搜索一下相关资料。'), findsOneWidget);
    expect(find.byTooltip('复制'), findsNWidgets(2));
    final processTop = tester
        .getTopLeft(find.byKey(const ValueKey('process-panel')))
        .dy;
    expect(
      processTop,
      greaterThan(tester.getTopLeft(find.text('检查一下代码').last).dy),
    );
    expect(processTop, lessThan(tester.getTopLeft(find.text('完成')).dy));
    expect(find.textContaining('搜索网页'), findsOneWidget);
    expect(find.textContaining('“Sage”'), findsOneWidget);
    expect(find.textContaining('search_web'), findsNothing);
    expect(
      tester.getTopLeft(find.text('我先搜索一下相关资料。')).dy,
      lessThan(tester.getTopLeft(find.textContaining('搜索网页')).dy),
    );
  });

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
    expect(
      api.lastRunBody?['session_id'],
      matches(RegExp(r'^session_\d{13}_\d{6}$')),
    );
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
    final controller = await _controller();
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
    expect(find.text('每次工具调用及参数'), findsOneWidget);
    expect(find.text('常规工作区写入、已知只读命令'), findsOneWidget);
    expect(find.text('系统级破坏、下载后直接执行'), findsOneWidget);
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
        expect(
          find.byKey(
            const ValueKey('settings-component-picker-model.protocol'),
          ),
          findsNothing,
        );

        await tester.tap(
          find.byKey(
            const ValueKey('settings-component-picker-context.reducer'),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('窗口裁剪').last);
        await tester.pumpAndSettle();
        expect(api.lastSelectedComponent, 'context.reducer');
        expect(api.lastSelectedComponentPlugin, 'sage.context.reducer.window');
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
      'agent tools keep source groups in ${brightness.name} appearance',
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
      find.byKey(const ValueKey('agent-system-context-formatted')),
      findsOneWidget,
    );
    expect(find.text('preferences'), findsOneWidget);
    expect(find.textContaining('"concise": true'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('settings-agent-edit')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('agent-deep-thinking')),
        matching: find.text('关闭'),
      ),
    );
    await tester.pumpAndSettle();
    expect(api.lastAgentPatch, {'deep_thinking': false});
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

    expect(find.text('显示运行事件'), findsNothing);
  });

  testWidgets('model draft is applied only after explicit save', (
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
      findsNothing,
    );
    await tester.tap(find.byKey(const ValueKey('settings-model-save')));
    await tester.pumpAndSettle();

    expect(api.lastModelPatch?['model'], 'next-model');
    expect(api.lastModelPatch?['base_url'], 'https://next.example.test/v1');
    expect(api.lastModelPatch?['protocol'], 'openai-responses');
    expect(find.byKey(const ValueKey('settings-model-id-field')), findsNothing);
    expect(find.byKey(const ValueKey('settings-save-button')), findsNothing);
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
        await tester.enterText(
          find.byKey(const ValueKey('settings-model-id-field')),
          'created-model',
        );
        await tester.tap(find.byKey(const ValueKey('settings-model-save')));
        await tester.pumpAndSettle();

        expect(api.lastModelCreate?['model'], 'created-model');
        expect(api.lastModelCreate?['protocol'], 'openai-responses');
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
    await tester.tap(find.byKey(const ValueKey('settings-model-save')));
    await tester.pumpAndSettle();

    expect(api.lastModelPatch?['protocol'], 'anthropic-messages');
  });

  testWidgets(
    'model save enables after changes and cancel discards the draft',
    (tester) async {
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
      expect(savePointer.ignoring, isFalse);
      await tester.tap(find.byKey(const ValueKey('settings-model-cancel')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('settings-model-id-field')),
        findsNothing,
      );
      expect(api.lastModelPatch, isNull);
    },
  );

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
