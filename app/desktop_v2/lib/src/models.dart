import 'dart:typed_data';

enum RunStatus {
  idle,
  starting,
  running,
  suspending,
  suspended,
  completed,
  failed,
  cancelled,
}

RunStatus runStatusFromWire(String? value) => switch (value) {
  'queued' || 'starting' => RunStatus.starting,
  'running' || 'resuming' => RunStatus.running,
  'suspend_requested' || 'suspending' => RunStatus.suspending,
  'suspended' => RunStatus.suspended,
  'completed' => RunStatus.completed,
  'failed' => RunStatus.failed,
  'cancelled' => RunStatus.cancelled,
  _ => RunStatus.idle,
};

enum ApprovalMode { alwaysAsk, highRisk, autoApprove }

ApprovalMode approvalModeFromWire(String? value) => switch (value) {
  'always_ask' => ApprovalMode.alwaysAsk,
  'auto_approve' => ApprovalMode.autoApprove,
  _ => ApprovalMode.highRisk,
};

extension ApprovalModeWire on ApprovalMode {
  String get wireValue => switch (this) {
    ApprovalMode.alwaysAsk => 'always_ask',
    ApprovalMode.highRisk => 'high_risk',
    ApprovalMode.autoApprove => 'auto_approve',
  };
}

class AgentSummary {
  const AgentSummary({
    required this.id,
    required this.name,
    this.isDefault = false,
  });

  final String id;
  final String name;
  final bool isDefault;

  factory AgentSummary.fromJson(Map<String, Object?> json) => AgentSummary(
    id: json['id']?.toString() ?? '',
    name: json['name']?.toString() ?? '',
    isDefault: json['is_default'] == true,
  );
}

class SkillSummary {
  const SkillSummary({required this.name, this.description = ''});

  final String name;
  final String description;

  factory SkillSummary.fromJson(Map<String, Object?> json) => SkillSummary(
    name: json['name']?.toString() ?? '',
    description: json['description']?.toString() ?? '',
  );
}

class ToolSummary {
  const ToolSummary({
    required this.name,
    this.description = '',
    this.type = 'basic',
    this.source = '',
    this.inputSchema = const {},
    this.parameters = const {},
    this.required = const [],
  });

  final String name;
  final String description;
  final String type;
  final String source;
  final Map<String, Object?> inputSchema;
  final Map<String, Object?> parameters;
  final List<String> required;

  factory ToolSummary.fromJson(Map<String, Object?> json) {
    final rawSchema = json['input_schema'];
    final rawParameters = json['parameters'];
    return ToolSummary(
      name: json['name']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
      type: json['type']?.toString() ?? 'basic',
      source: json['source']?.toString() ?? '',
      inputSchema: rawSchema is Map
          ? rawSchema.cast<String, Object?>()
          : const {},
      parameters: rawParameters is Map
          ? rawParameters.cast<String, Object?>()
          : const {},
      required: _stringList(json['required']),
    );
  }
}

class ModelProviderSummary {
  const ModelProviderSummary({
    required this.id,
    required this.name,
    required this.model,
    required this.baseUrl,
    this.protocol = 'openai-responses',
    this.apiKeyConfigured = false,
    this.supportsMultimodal = false,
    this.supportsStructuredOutput = false,
    this.isDefault = false,
    this.maxTokens,
    this.temperature,
    this.topP,
    this.maxModelLength,
  });

  final String id;
  final String name;
  final String model;
  final String baseUrl;
  final String protocol;
  final bool apiKeyConfigured;
  final bool supportsMultimodal;
  final bool supportsStructuredOutput;
  final bool isDefault;
  final int? maxTokens;
  final double? temperature;
  final double? topP;
  final int? maxModelLength;

  factory ModelProviderSummary.fromJson(Map<String, Object?> json) =>
      ModelProviderSummary(
        id: json['id']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        model: json['model']?.toString() ?? '',
        baseUrl: json['base_url']?.toString() ?? '',
        protocol: json['protocol']?.toString() ?? 'openai-responses',
        apiKeyConfigured: json['api_key_configured'] == true,
        supportsMultimodal: json['supports_multimodal'] == true,
        supportsStructuredOutput: json['supports_structured_output'] == true,
        isDefault: json['is_default'] == true,
        maxTokens: (json['max_tokens'] as num?)?.toInt(),
        temperature: (json['temperature'] as num?)?.toDouble(),
        topP: (json['top_p'] as num?)?.toDouble(),
        maxModelLength: (json['max_model_len'] as num?)?.toInt(),
      );
}

class AgentConfiguration {
  const AgentConfiguration({
    required this.id,
    required this.name,
    this.description = '',
    this.systemPrefix = '',
    this.systemContext = const {},
    this.llmProviderId,
    this.fastLlmProviderId,
    this.agentMode = 'simple',
    this.maxLoopCount = 100,
    this.deepThinking = false,
    this.thinkingLevel = 'medium',
    this.availableTools = const [],
    this.availableSkills = const [],
    this.isDefault = false,
  });

  final String id;
  final String name;
  final String description;
  final String systemPrefix;
  final Map<String, Object?> systemContext;
  final String? llmProviderId;
  final String? fastLlmProviderId;
  final String agentMode;
  final int maxLoopCount;
  final bool deepThinking;
  final String thinkingLevel;
  final List<String> availableTools;
  final List<String> availableSkills;
  final bool isDefault;

  factory AgentConfiguration.fromJson(Map<String, Object?> json) {
    final context = json['system_context'];
    return AgentConfiguration(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
      systemPrefix: json['system_prefix']?.toString() ?? '',
      systemContext: context is Map
          ? context.cast<String, Object?>()
          : const {},
      llmProviderId: json['llm_provider_id']?.toString(),
      fastLlmProviderId: json['fast_llm_provider_id']?.toString(),
      agentMode: json['agent_mode']?.toString() ?? 'simple',
      maxLoopCount: (json['max_loop_count'] as num?)?.toInt() ?? 100,
      deepThinking: json['deep_thinking'] == true,
      thinkingLevel: json['thinking_level']?.toString() ?? 'medium',
      availableTools: _stringList(json['available_tools']),
      availableSkills: _stringList(json['available_skills']),
      isDefault: json['is_default'] == true,
    );
  }
}

class McpConnectionSummary {
  const McpConnectionSummary({
    required this.name,
    required this.protocol,
    this.disabled = false,
    this.toolCount = 0,
    this.apiKeyConfigured = false,
    this.url = '',
    this.command = '',
    this.connectionError = '',
  });

  final String name;
  final String protocol;
  final bool disabled;
  final int toolCount;
  final bool apiKeyConfigured;
  final String url;
  final String command;
  final String connectionError;

  factory McpConnectionSummary.fromJson(Map<String, Object?> json) =>
      McpConnectionSummary(
        name: json['name']?.toString() ?? '',
        protocol: json['protocol']?.toString() ?? '',
        disabled: json['disabled'] == true,
        toolCount: (json['tool_count'] as num?)?.toInt() ?? 0,
        apiKeyConfigured: json['api_key_configured'] == true,
        url:
            json['streamable_http_url']?.toString() ??
            json['sse_url']?.toString() ??
            '',
        command: json['command']?.toString() ?? '',
        connectionError: json['connection_error']?.toString() ?? '',
      );
}

class ComponentPluginSummary {
  const ComponentPluginSummary({
    required this.id,
    required this.name,
    required this.value,
    this.available = true,
    this.builtIn = true,
    this.dependencies = const [],
  });

  final String id;
  final String name;
  final String value;
  final bool available;
  final bool builtIn;
  final List<String> dependencies;

  factory ComponentPluginSummary.fromJson(Map<String, Object?> json) =>
      ComponentPluginSummary(
        id: json['plugin_id']?.toString() ?? json['id']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        value: json['value']?.toString() ?? '',
        available: json['available'] != false,
        builtIn: json['built_in'] != false,
        dependencies: _stringList(json['dependencies']),
      );
}

class ComponentSummary {
  const ComponentSummary({
    required this.id,
    required this.name,
    this.value = '',
    this.selectionMode = 'host',
    this.applyMode = 'locked',
    this.scope = '',
    this.plugins = const [],
    this.activePluginId,
    this.activeSource = '',
    this.activeConfig = const {},
    this.pendingRestart = false,
  });

  final String id;
  final String name;
  final String value;
  final String selectionMode;
  final String applyMode;
  final String scope;
  final List<ComponentPluginSummary> plugins;
  final String? activePluginId;
  final String activeSource;
  final Map<String, Object?> activeConfig;
  final bool pendingRestart;

  String get implementation {
    for (final plugin in plugins) {
      if (plugin.id == activePluginId) return plugin.name;
    }
    return activePluginId ?? '';
  }

  int get configured => plugins.length;
  Map<String, Object?> get config => activeConfig;

  factory ComponentSummary.fromJson(Map<String, Object?> json) {
    final component = json['component'] is Map
        ? (json['component'] as Map).cast<String, Object?>()
        : json;
    final active = json['active'] is Map
        ? (json['active'] as Map).cast<String, Object?>()
        : json;
    final rawPlugins = json['plugins'];
    final rawConfig = active['config'] ?? json['config'];
    return ComponentSummary(
      id: component['component_id']?.toString() ?? json['id']?.toString() ?? '',
      name: component['name']?.toString() ?? json['name']?.toString() ?? '',
      value: component['value']?.toString() ?? '',
      selectionMode: component['selection_mode']?.toString() ?? 'host',
      applyMode: component['apply_mode']?.toString() ?? 'locked',
      scope: component['scope']?.toString() ?? '',
      plugins: rawPlugins is List
          ? [
              for (final plugin in rawPlugins)
                if (plugin is Map)
                  ComponentPluginSummary.fromJson(
                    plugin.cast<String, Object?>(),
                  ),
            ]
          : const [],
      activePluginId:
          active['plugin_id']?.toString() ?? json['implementation']?.toString(),
      activeSource: active['source']?.toString() ?? '',
      activeConfig: rawConfig is Map
          ? rawConfig.cast<String, Object?>()
          : const {},
      pendingRestart: active['pending_restart'] == true,
    );
  }
}

List<String> _stringList(Object? value) =>
    value is List ? [for (final item in value) item.toString()] : const [];

class DesktopProject {
  const DesktopProject({
    required this.id,
    required this.name,
    required this.path,
  });

  final String id;
  final String name;
  final String path;

  factory DesktopProject.fromJson(Map<String, Object?> json) => DesktopProject(
    id: json['id']?.toString() ?? '',
    name: json['name']?.toString() ?? '',
    path: json['path']?.toString() ?? '',
  );

  Map<String, Object?> toJson() => {'id': id, 'name': name, 'path': path};
}

class DesktopSettings {
  const DesktopSettings({
    this.themeMode = 'system',
    this.language = 'system',
    this.defaultAgentId,
    this.projects = const [],
    this.agentWorkspacePath = '',
    this.maxPreviewBytes = 2000000,
    this.maxTreeEntries = 6000,
  });

  final String themeMode;
  final String language;
  final String? defaultAgentId;
  final List<DesktopProject> projects;
  final String agentWorkspacePath;
  final int maxPreviewBytes;
  final int maxTreeEntries;

  factory DesktopSettings.fromJson(Map<String, Object?> json) {
    final rawProjects = json['projects'];
    return DesktopSettings(
      themeMode: switch (json['theme_mode']?.toString()) {
        'light' => 'light',
        'dark' => 'dark',
        _ => 'system',
      },
      language: switch (json['language']?.toString()) {
        'zh' => 'zh',
        'en' => 'en',
        'pt' => 'pt',
        'es' => 'es',
        'fr' => 'fr',
        'de' => 'de',
        'ja' => 'ja',
        'ko' => 'ko',
        'ru' => 'ru',
        _ => 'system',
      },
      defaultAgentId: json['default_agent_id']?.toString(),
      projects: rawProjects is List
          ? [
              for (final value in rawProjects)
                if (value is Map)
                  DesktopProject.fromJson(value.cast<String, Object?>()),
            ]
          : const [],
      agentWorkspacePath: json['agent_workspace_path']?.toString() ?? '',
      maxPreviewBytes: (json['max_preview_bytes'] as num?)?.toInt() ?? 2000000,
      maxTreeEntries: (json['max_tree_entries'] as num?)?.toInt() ?? 6000,
    );
  }

  DesktopSettings copyWith({
    String? themeMode,
    String? language,
    String? defaultAgentId,
    bool clearDefaultAgent = false,
    List<DesktopProject>? projects,
    String? agentWorkspacePath,
    int? maxPreviewBytes,
    int? maxTreeEntries,
  }) => DesktopSettings(
    themeMode: themeMode ?? this.themeMode,
    language: language ?? this.language,
    defaultAgentId: clearDefaultAgent
        ? null
        : (defaultAgentId ?? this.defaultAgentId),
    projects: projects ?? this.projects,
    agentWorkspacePath: agentWorkspacePath ?? this.agentWorkspacePath,
    maxPreviewBytes: maxPreviewBytes ?? this.maxPreviewBytes,
    maxTreeEntries: maxTreeEntries ?? this.maxTreeEntries,
  );

  Map<String, Object?> toJson() => {
    'theme_mode': themeMode,
    'language': language,
    'default_agent_id': defaultAgentId,
    'projects': [for (final value in projects) value.toJson()],
    'agent_workspace_path': agentWorkspacePath,
    'max_preview_bytes': maxPreviewBytes,
    'max_tree_entries': maxTreeEntries,
  };
}

class WorkspaceFileNode {
  const WorkspaceFileNode({
    required this.name,
    required this.path,
    required this.isDirectory,
    required this.size,
    this.children = const [],
  });

  final String name;
  final String path;
  final bool isDirectory;
  final int size;
  final List<WorkspaceFileNode> children;

  factory WorkspaceFileNode.fromJson(Map<String, Object?> json) {
    final rawChildren = json['children'];
    return WorkspaceFileNode(
      name: json['name']?.toString() ?? '',
      path: json['path']?.toString() ?? '',
      isDirectory: json['is_directory'] == true,
      size: (json['size'] as num?)?.toInt() ?? 0,
      children: rawChildren is List
          ? [
              for (final value in rawChildren)
                if (value is Map)
                  WorkspaceFileNode.fromJson(value.cast<String, Object?>()),
            ]
          : const [],
    );
  }
}

class WorkspaceFileContent {
  const WorkspaceFileContent({required this.bytes, required this.mediaType});

  final Uint8List bytes;
  final String mediaType;

  bool get isImage => mediaType.startsWith('image/');
  bool get isText =>
      mediaType.startsWith('text/') || mediaType.contains('json');
}

class UploadedAttachment {
  const UploadedAttachment({
    required this.name,
    required this.path,
    required this.virtualPath,
    required this.size,
    this.isDirectory = false,
  });

  final String name;
  final String path;
  final String virtualPath;
  final int size;
  final bool isDirectory;

  factory UploadedAttachment.fromJson(Map<String, Object?> json) =>
      UploadedAttachment(
        name: json['name']?.toString() ?? '',
        path: json['path']?.toString() ?? '',
        virtualPath: json['virtual_path']?.toString() ?? '',
        size: (json['size'] as num?)?.toInt() ?? 0,
        isDirectory: json['is_directory'] == true,
      );
}

class ChatMessage {
  ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    this.streaming = false,
    this.processOnly = false,
    this.sequence = 0,
    DateTime? createdAt,
  }) : createdAt = createdAt ?? DateTime.now();

  final String id;
  final String role;
  String text;
  bool streaming;
  bool processOnly;
  final int sequence;
  final DateTime createdAt;

  factory ChatMessage.fromJson(Map<String, Object?> json) => ChatMessage(
    id: json['id']?.toString() ?? '',
    role: json['role']?.toString() ?? 'assistant',
    text: json['text']?.toString() ?? '',
    streaming: json['streaming'] == true,
    processOnly: json['process_only'] == true,
    sequence: (json['sequence'] as num?)?.toInt() ?? 0,
    createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'role': role,
    'text': text,
    'streaming': false,
    'process_only': processOnly,
    'sequence': sequence,
    'created_at': createdAt.toIso8601String(),
  };
}

class PendingInteraction {
  const PendingInteraction({
    required this.id,
    required this.type,
    this.allowedDecisions = const [],
    this.payload = const {},
  });

  final String id;
  final String type;
  final List<String> allowedDecisions;
  final Map<String, Object?> payload;

  factory PendingInteraction.fromJson(Map<String, Object?> json) {
    final decisions = json['allowed_decisions'];
    final rawPayload = json['payload'];
    return PendingInteraction(
      id: json['interaction_id']?.toString() ?? '',
      type: json['interaction_type']?.toString() ?? '',
      allowedDecisions: decisions is List
          ? [for (final value in decisions) value.toString()]
          : const [],
      payload: rawPayload is Map
          ? rawPayload.cast<String, Object?>()
          : const {},
    );
  }

  Map<String, Object?> toJson() => {
    'interaction_id': id,
    'interaction_type': type,
    'allowed_decisions': allowedDecisions,
    'payload': payload,
  };
}

class RuntimeActivity {
  RuntimeActivity({
    required this.id,
    required this.label,
    required this.active,
    this.failed = false,
    this.arguments = const {},
    this.result = '',
    this.sequence = 0,
    DateTime? startedAt,
    this.completedAt,
  }) : startedAt = startedAt ?? DateTime.now();

  final String id;
  final String label;
  bool active;
  bool failed;
  Map<String, Object?> arguments;
  String result;
  final int sequence;
  final DateTime startedAt;
  DateTime? completedAt;

  factory RuntimeActivity.fromJson(Map<String, Object?> json) {
    final rawArguments = json['arguments'];
    return RuntimeActivity(
      id: json['id']?.toString() ?? '',
      label: json['label']?.toString() ?? '',
      active: json['active'] == true,
      failed: json['failed'] == true,
      arguments: rawArguments is Map
          ? rawArguments.cast<String, Object?>()
          : const {},
      result: json['result']?.toString() ?? '',
      sequence: (json['sequence'] as num?)?.toInt() ?? 0,
      startedAt: DateTime.tryParse(json['started_at']?.toString() ?? ''),
      completedAt: DateTime.tryParse(json['completed_at']?.toString() ?? ''),
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'label': label,
    'active': active,
    'failed': failed,
    'arguments': arguments,
    'result': result,
    'sequence': sequence,
    'started_at': startedAt.toIso8601String(),
    'completed_at': completedAt?.toIso8601String(),
  };
}

class RuntimeProcessPanel {
  RuntimeProcessPanel({
    required this.id,
    required this.anchorMessageId,
    required this.startedAt,
    List<RuntimeActivity>? activities,
    this.completedAt,
    this.running = true,
  }) : activities = activities ?? [];

  final String id;
  final String anchorMessageId;
  final DateTime startedAt;
  DateTime? completedAt;
  bool running;
  final List<RuntimeActivity> activities;

  factory RuntimeProcessPanel.fromJson(Map<String, Object?> json) {
    final rawActivities = json['activities'];
    return RuntimeProcessPanel(
      id: json['id']?.toString() ?? '',
      anchorMessageId: json['anchor_message_id']?.toString() ?? '',
      startedAt:
          DateTime.tryParse(json['started_at']?.toString() ?? '') ??
          DateTime.now(),
      completedAt: DateTime.tryParse(json['completed_at']?.toString() ?? ''),
      running: json['running'] == true,
      activities: rawActivities is List
          ? [
              for (final value in rawActivities)
                if (value is Map)
                  RuntimeActivity.fromJson(value.cast<String, Object?>()),
            ]
          : [],
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'anchor_message_id': anchorMessageId,
    'started_at': startedAt.toIso8601String(),
    'completed_at': completedAt?.toIso8601String(),
    'running': running,
    'activities': [for (final value in activities) value.toJson()],
  };
}

class Conversation {
  Conversation({
    required this.id,
    this.title = '新会话',
    this.agentId = '',
    this.sessionId,
    this.runId = '',
    this.turnId = '',
    this.runSequence = 0,
    this.status = RunStatus.idle,
    List<ChatMessage>? messages,
    this.pendingInteraction,
    this.approvalMode = ApprovalMode.highRisk,
    List<RuntimeProcessPanel>? processPanels,
    this.archived = false,
    this.archivedAt,
  }) : messages = messages ?? [],
       processPanels = processPanels ?? [];

  final String id;
  String title;
  String agentId;
  String? sessionId;
  String runId;
  String turnId;
  int runSequence;
  RunStatus status;
  List<ChatMessage> messages;
  PendingInteraction? pendingInteraction;
  ApprovalMode approvalMode;
  bool archived;
  DateTime? archivedAt;
  final List<Map<String, Object?>> runtimeEvents = [];
  final List<RuntimeProcessPanel> processPanels;

  factory Conversation.fromJson(Map<String, Object?> json) {
    final rawMessages = json['messages'];
    final rawInteraction = json['pending_interaction'];
    final rawProcessPanels = json['process_panels'];
    final messages = rawMessages is List
        ? [
            for (final value in rawMessages)
              if (value is Map)
                ChatMessage.fromJson(value.cast<String, Object?>()),
          ]
        : <ChatMessage>[];
    final processPanels = rawProcessPanels is List
        ? [
            for (final value in rawProcessPanels)
              if (value is Map)
                RuntimeProcessPanel.fromJson(value.cast<String, Object?>()),
          ]
        : <RuntimeProcessPanel>[];
    final rawLegacyActivities = json['activities'];
    if (processPanels.isEmpty && rawLegacyActivities is List) {
      final legacyActivities = [
        for (final value in rawLegacyActivities)
          if (value is Map)
            RuntimeActivity.fromJson(value.cast<String, Object?>()),
      ];
      if (legacyActivities.isNotEmpty) {
        final anchor = messages
            .where((value) => value.role == 'user')
            .lastOrNull;
        final running = legacyActivities.any((value) => value.active);
        processPanels.add(
          RuntimeProcessPanel(
            id: 'legacy-process:${json['id']?.toString() ?? ''}',
            anchorMessageId: anchor?.id ?? messages.lastOrNull?.id ?? '',
            startedAt: legacyActivities.first.startedAt,
            completedAt: running ? null : DateTime.now(),
            running: running,
            activities: legacyActivities,
          ),
        );
      }
    }
    return Conversation(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? '新会话',
      agentId: json['agent_id']?.toString() ?? '',
      sessionId: json['session_id']?.toString(),
      runId: json['run_id']?.toString() ?? '',
      turnId: json['turn_id']?.toString() ?? '',
      runSequence: (json['run_sequence'] as num?)?.toInt() ?? 0,
      status: runStatusFromWire(json['status']?.toString()),
      messages: messages,
      pendingInteraction: rawInteraction is Map
          ? PendingInteraction.fromJson(rawInteraction.cast<String, Object?>())
          : null,
      approvalMode: approvalModeFromWire(json['approval_mode']?.toString()),
      processPanels: processPanels,
      archived: json['archived'] == true,
      archivedAt: DateTime.tryParse(json['archived_at']?.toString() ?? ''),
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'title': title,
    'agent_id': agentId,
    'session_id': sessionId,
    'run_id': runId,
    'turn_id': turnId,
    'run_sequence': runSequence,
    'status': status.name,
    'messages': [for (final value in messages) value.toJson()],
    'pending_interaction': pendingInteraction?.toJson(),
    'approval_mode': approvalMode.wireValue,
    'process_panels': [for (final value in processPanels) value.toJson()],
    'archived': archived,
    'archived_at': archivedAt?.toIso8601String(),
  };
}

class ArchivedConversationEntry {
  const ArchivedConversationEntry({
    required this.groupId,
    required this.groupName,
    required this.conversation,
  });

  final String groupId;
  final String groupName;
  final Conversation conversation;
}

class WorkspaceGroup {
  const WorkspaceGroup({
    required this.id,
    required this.name,
    required this.workspaceId,
    required this.conversations,
    this.project,
  });

  final String id;
  final String name;
  final String workspaceId;
  final List<Conversation> conversations;
  final DesktopProject? project;
}
