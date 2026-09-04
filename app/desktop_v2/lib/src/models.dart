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

enum InvocationMode { normal, plan, goal }

InvocationMode invocationModeFromWire(String? value) => switch (value) {
  'plan' => InvocationMode.plan,
  'goal' => InvocationMode.goal,
  _ => InvocationMode.normal,
};

extension InvocationModeWire on InvocationMode {
  String get wireValue => name;
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
  const SkillSummary({
    required this.name,
    this.description = '',
    this.canDelete = false,
  });

  final String name;
  final String description;
  final bool canDelete;

  factory SkillSummary.fromJson(Map<String, Object?> json) => SkillSummary(
    name: json['name']?.toString() ?? '',
    description: json['description']?.toString() ?? '',
    canDelete: json['can_delete'] == true,
  );
}

class ToolSummary {
  const ToolSummary({
    required this.name,
    this.description = '',
    this.type = 'basic',
    this.source = '',
    this.category = '',
    this.inputSchema = const {},
    this.parameters = const {},
    this.required = const [],
  });

  final String name;
  final String description;
  final String type;
  final String source;
  final String category;
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
      category: json['category']?.toString() ?? '',
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
    this.supportsToolCalling = true,
    this.isDefault = false,
    this.maxTokens,
    this.temperature,
    this.topP,
    this.maxModelLength,
    this.compatibilityProfile,
  });

  final String id;
  final String name;
  final String model;
  final String baseUrl;
  final String protocol;
  final bool apiKeyConfigured;
  final bool supportsMultimodal;
  final bool supportsStructuredOutput;
  final bool supportsToolCalling;
  final bool isDefault;
  final int? maxTokens;
  final double? temperature;
  final double? topP;
  final int? maxModelLength;
  final Map<String, Object?>? compatibilityProfile;

  bool get hasVerifiedUsageProfile =>
      (compatibilityProfile?['schema_version'] as num?)?.toInt() == 2;

  String? get reasoningBehavior =>
      compatibilityProfile?['reasoning_behavior']?.toString();

  List<String> get supportedReasoningEfforts =>
      _stringList(compatibilityProfile?['supported_reasoning_efforts']);

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
        supportsToolCalling: json['supports_tool_calling'] != false,
        isDefault: json['is_default'] == true,
        maxTokens: (json['max_tokens'] as num?)?.toInt(),
        temperature: (json['temperature'] as num?)?.toDouble(),
        topP: (json['top_p'] as num?)?.toDouble(),
        maxModelLength: (json['max_model_len'] as num?)?.toInt(),
        compatibilityProfile: json['compatibility_profile'] is Map
            ? (json['compatibility_profile'] as Map).cast<String, Object?>()
            : null,
      );

  ModelProviderSummary copyWith({bool? isDefault}) => ModelProviderSummary(
    id: id,
    name: name,
    model: model,
    baseUrl: baseUrl,
    protocol: protocol,
    apiKeyConfigured: apiKeyConfigured,
    supportsMultimodal: supportsMultimodal,
    supportsStructuredOutput: supportsStructuredOutput,
    supportsToolCalling: supportsToolCalling,
    isDefault: isDefault ?? this.isDefault,
    maxTokens: maxTokens,
    temperature: temperature,
    topP: topP,
    maxModelLength: maxModelLength,
    compatibilityProfile: compatibilityProfile,
  );
}

class ShellPolicySummary {
  const ShellPolicySummary({
    this.autoExecuteKeywords = const [],
    this.approvalKeywords = const [],
    this.blockedKeywords = const [],
    this.userApprovedCommands = const [],
  });

  final List<String> autoExecuteKeywords;
  final List<String> approvalKeywords;
  final List<String> blockedKeywords;
  final List<String> userApprovedCommands;

  factory ShellPolicySummary.fromJson(Map<String, Object?> json) =>
      ShellPolicySummary(
        autoExecuteKeywords: _stringList(json['auto_execute_keywords']),
        approvalKeywords: _stringList(json['approval_keywords']),
        blockedKeywords: _stringList(json['blocked_keywords']),
        userApprovedCommands: _stringList(json['user_approved_commands']),
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
    this.subAgentSelectionMode = 'auto_all',
    this.availableSubAgentIds = const [],
    this.maxLoopCount = 100,
    this.deepThinking = false,
    this.thinkingLevel = 'medium',
    this.availableTools = const [],
    this.availableSkills = const [],
    this.shellPolicy = const ShellPolicySummary(),
    this.isDefault = false,
  });

  final String id;
  final String name;
  final String description;
  final String systemPrefix;
  final Map<String, Object?> systemContext;
  Map<String, Object?> get runtimeVariables => systemContext;
  final String? llmProviderId;
  final String? fastLlmProviderId;
  final String agentMode;
  final String subAgentSelectionMode;
  final List<String> availableSubAgentIds;
  final int maxLoopCount;
  final bool deepThinking;
  final String thinkingLevel;
  final List<String> availableTools;
  final List<String> availableSkills;
  final ShellPolicySummary shellPolicy;
  final bool isDefault;

  factory AgentConfiguration.fromJson(Map<String, Object?> json) {
    final context = json['runtime_variables'] ?? json['system_context'];
    final shellPolicy = json['shell_policy'];
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
      subAgentSelectionMode:
          json['sub_agent_selection_mode']?.toString() ?? 'auto_all',
      availableSubAgentIds: _stringList(json['available_sub_agent_ids']),
      maxLoopCount: (json['max_loop_count'] as num?)?.toInt() ?? 100,
      deepThinking: json['deep_thinking'] == true,
      thinkingLevel: json['thinking_level']?.toString() ?? 'medium',
      availableTools: _stringList(json['available_tools']),
      availableSkills: _stringList(json['available_skills']),
      shellPolicy: shellPolicy is Map
          ? ShellPolicySummary.fromJson(shellPolicy.cast<String, Object?>())
          : ShellPolicySummary(
              userApprovedCommands: _stringList(
                json['approved_shell_commands'],
              ),
            ),
      isDefault: json['is_default'] == true,
    );
  }

  AgentConfiguration applyPatch(Map<String, Object?> patch) {
    final hasRuntimeVariables = patch.containsKey('runtime_variables');
    final hasLegacyContext = patch.containsKey('system_context');
    final context = hasRuntimeVariables
        ? patch['runtime_variables']
        : patch['system_context'];
    return AgentConfiguration(
      id: id,
      name: patch.containsKey('name') ? patch['name']?.toString() ?? '' : name,
      description: patch.containsKey('description')
          ? patch['description']?.toString() ?? ''
          : description,
      systemPrefix: patch.containsKey('system_prefix')
          ? patch['system_prefix']?.toString() ?? ''
          : systemPrefix,
      systemContext: hasRuntimeVariables || hasLegacyContext
          ? (context is Map
                ? context.cast<String, Object?>()
                : const <String, Object?>{})
          : systemContext,
      llmProviderId: patch.containsKey('llm_provider_id')
          ? patch['llm_provider_id']?.toString()
          : llmProviderId,
      fastLlmProviderId: patch.containsKey('fast_llm_provider_id')
          ? patch['fast_llm_provider_id']?.toString()
          : fastLlmProviderId,
      agentMode: patch.containsKey('agent_mode')
          ? patch['agent_mode']?.toString() ?? 'simple'
          : agentMode,
      subAgentSelectionMode: patch.containsKey('sub_agent_selection_mode')
          ? patch['sub_agent_selection_mode']?.toString() ?? 'auto_all'
          : subAgentSelectionMode,
      availableSubAgentIds: patch.containsKey('available_sub_agent_ids')
          ? _stringList(patch['available_sub_agent_ids'])
          : availableSubAgentIds,
      maxLoopCount: patch.containsKey('max_loop_count')
          ? (patch['max_loop_count'] as num?)?.toInt() ?? maxLoopCount
          : maxLoopCount,
      deepThinking: patch.containsKey('deep_thinking')
          ? patch['deep_thinking'] == true
          : deepThinking,
      thinkingLevel: patch.containsKey('thinking_level')
          ? patch['thinking_level']?.toString() ?? 'medium'
          : thinkingLevel,
      availableTools: patch.containsKey('available_tools')
          ? _stringList(patch['available_tools'])
          : availableTools,
      availableSkills: patch.containsKey('available_skills')
          ? _stringList(patch['available_skills'])
          : availableSkills,
      shellPolicy: patch.containsKey('approved_shell_commands')
          ? ShellPolicySummary(
              autoExecuteKeywords: shellPolicy.autoExecuteKeywords,
              approvalKeywords: shellPolicy.approvalKeywords,
              blockedKeywords: shellPolicy.blockedKeywords,
              userApprovedCommands: _stringList(
                patch['approved_shell_commands'],
              ),
            )
          : shellPolicy,
      isDefault: isDefault,
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
    this.configSchema = const {},
  });

  final String id;
  final String name;
  final String value;
  final bool available;
  final bool builtIn;
  final List<String> dependencies;
  final Map<String, Object?> configSchema;

  factory ComponentPluginSummary.fromJson(Map<String, Object?> json) =>
      ComponentPluginSummary(
        id: json['plugin_id']?.toString() ?? json['id']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        value: json['value']?.toString() ?? '',
        available: json['available'] != false,
        builtIn: json['built_in'] != false,
        dependencies: _stringList(json['dependencies']),
        configSchema: json['config_schema'] is Map
            ? (json['config_schema'] as Map).cast<String, Object?>()
            : const {},
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
    this.selectedPluginId,
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
  final String? selectedPluginId;
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
      selectedPluginId:
          active['selected_plugin_id']?.toString() ??
          active['plugin_id']?.toString() ??
          json['implementation']?.toString(),
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
    this.componentSelections = const {},
    this.componentConfigs = const {},
  });

  final String themeMode;
  final String language;
  final String? defaultAgentId;
  final List<DesktopProject> projects;
  final String agentWorkspacePath;
  final int maxPreviewBytes;
  final int maxTreeEntries;
  final Map<String, String> componentSelections;
  final Map<String, Map<String, Object?>> componentConfigs;

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
      componentSelections: json['component_selections'] is Map
          ? {
              for (final entry in (json['component_selections'] as Map).entries)
                entry.key.toString(): entry.value.toString(),
            }
          : const {},
      componentConfigs: json['component_configs'] is Map
          ? {
              for (final entry in (json['component_configs'] as Map).entries)
                if (entry.value is Map)
                  entry.key.toString(): (entry.value as Map)
                      .cast<String, Object?>(),
            }
          : const {},
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
    Map<String, String>? componentSelections,
    Map<String, Map<String, Object?>>? componentConfigs,
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
    componentSelections: componentSelections ?? this.componentSelections,
    componentConfigs: componentConfigs ?? this.componentConfigs,
  );

  Map<String, Object?> toJson() => {
    'theme_mode': themeMode,
    'language': language,
    'default_agent_id': defaultAgentId,
    'projects': [for (final value in projects) value.toJson()],
    'agent_workspace_path': agentWorkspacePath,
    'max_preview_bytes': maxPreviewBytes,
    'max_tree_entries': maxTreeEntries,
    'component_selections': componentSelections,
    'component_configs': componentConfigs,
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

class ComposerReference {
  const ComposerReference({
    required this.fileName,
    required this.path,
    required this.text,
    this.isDirectory = false,
    this.citationLabel,
  });

  final String fileName;
  final String path;
  final String text;
  final bool isDirectory;
  final String? citationLabel;

  String get displayPath => citationLabel ?? path;

  ChatMessageContent toMessageContent() => ChatMessageContent.reference(
    fileName: fileName,
    path: path,
    quote: text,
    isDirectory: isDirectory,
    citationLabel: citationLabel,
  );
}

class ChatMessageContent {
  const ChatMessageContent.text(this.text)
    : type = 'text',
      fileName = '',
      path = '',
      quote = '',
      isDirectory = false,
      citationLabel = null;

  const ChatMessageContent.reference({
    required this.fileName,
    required this.path,
    this.quote = '',
    this.isDirectory = false,
    this.citationLabel,
  }) : type = 'reference',
       text = '';

  final String type;
  final String text;
  final String fileName;
  final String path;
  final String quote;
  final bool isDirectory;
  final String? citationLabel;

  bool get isText => type == 'text';
  bool get isReference => type == 'reference';

  factory ChatMessageContent.fromJson(Map<String, Object?> json) {
    if (json['type']?.toString() == 'reference') {
      return ChatMessageContent.reference(
        fileName: json['name']?.toString() ?? '',
        path: json['path']?.toString() ?? '',
        quote: json['quote']?.toString() ?? '',
        isDirectory: json['is_directory'] == true,
        citationLabel: json['citation_label']?.toString(),
      );
    }
    return ChatMessageContent.text(json['text']?.toString() ?? '');
  }

  Map<String, Object?> toJson() => isReference
      ? {
          'type': 'reference',
          'name': fileName,
          'path': path,
          if (quote.isNotEmpty) 'quote': quote,
          if (isDirectory) 'is_directory': true,
          if (citationLabel != null) 'citation_label': citationLabel,
        }
      : {'type': 'text', 'text': text};
}

class ChatMessage {
  ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    this.streaming = false,
    this.processOnly = false,
    this.sequence = 0,
    this.content = const [],
    DateTime? createdAt,
  }) : renderedText = text,
       createdAt = createdAt ?? DateTime.now();

  final String id;
  final String role;
  String text;

  /// The presentation copy can trail [text] briefly while a large streamed
  /// delta is revealed. It is deliberately excluded from persistence.
  String renderedText;
  bool streaming;
  bool processOnly;
  final int sequence;
  final List<ChatMessageContent> content;
  final DateTime createdAt;

  factory ChatMessage.fromJson(Map<String, Object?> json) {
    final rawContent = json['content'];
    return ChatMessage(
      id: json['id']?.toString() ?? '',
      role: json['role']?.toString() ?? 'assistant',
      text: json['text']?.toString() ?? '',
      streaming: json['streaming'] == true,
      processOnly: json['process_only'] == true,
      sequence: (json['sequence'] as num?)?.toInt() ?? 0,
      content: rawContent is List
          ? [
              for (final value in rawContent)
                if (value is Map)
                  ChatMessageContent.fromJson(value.cast<String, Object?>()),
            ]
          : const [],
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'role': role,
    'text': text,
    if (content.isNotEmpty)
      'content': [for (final value in content) value.toJson()],
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
    this.runId = '',
    List<RuntimeActivity>? activities,
    this.completedAt,
    this.running = true,
  }) : activities = activities ?? [];

  final String id;
  final String anchorMessageId;
  DateTime startedAt;
  String runId;
  DateTime? completedAt;
  bool running;
  final List<RuntimeActivity> activities;

  factory RuntimeProcessPanel.fromJson(Map<String, Object?> json) {
    final rawActivities = json['activities'];
    return RuntimeProcessPanel(
      id: json['id']?.toString() ?? '',
      anchorMessageId: json['anchor_message_id']?.toString() ?? '',
      runId: json['run_id']?.toString() ?? '',
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
    'run_id': runId,
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
    this.parentSessionId,
    this.parentRunId,
    this.forkBaseSessionRevision,
    this.parentToolCallId,
    this.runId = '',
    this.turnId = '',
    this.runSequence = 0,
    this.status = RunStatus.idle,
    this.thinking = false,
    List<ChatMessage>? messages,
    this.pendingInteraction,
    this.approvalMode = ApprovalMode.highRisk,
    this.invocationMode = InvocationMode.normal,
    this.pendingPlanExecution,
    List<RuntimeProcessPanel>? processPanels,
    List<Conversation>? subSessions,
    DateTime? createdAt,
    this.archived = false,
    this.archivedAt,
  }) : messages = messages ?? [],
       processPanels = processPanels ?? [],
       subSessions = subSessions ?? [],
       createdAt = createdAt ?? DateTime.now();

  final String id;
  String title;
  String agentId;
  String? sessionId;
  String? parentSessionId;
  String? parentRunId;
  int? forkBaseSessionRevision;
  String? parentToolCallId;
  String runId;
  String turnId;
  int runSequence;
  RunStatus status;

  /// Transient UI state driven by reasoning lifecycle events.
  /// Reasoning content is intentionally never retained or rendered.
  bool thinking;
  List<ChatMessage> messages;
  PendingInteraction? pendingInteraction;
  ApprovalMode approvalMode;
  InvocationMode invocationMode;
  Map<String, Object?>? pendingPlanExecution;
  bool get planMode => invocationMode == InvocationMode.plan;
  bool get goalMode => invocationMode == InvocationMode.goal;
  bool archived;
  DateTime? archivedAt;
  final List<Map<String, Object?>> runtimeEvents = [];
  final List<RuntimeProcessPanel> processPanels;
  final List<Conversation> subSessions;
  final DateTime createdAt;

  factory Conversation.fromJson(Map<String, Object?> json) {
    final rawMessages = json['messages'];
    final rawInteraction = json['pending_interaction'];
    final rawProcessPanels = json['process_panels'];
    final rawSubSessions = json['sub_sessions'];
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
      parentSessionId: json['parent_session_id']?.toString(),
      parentRunId: json['parent_run_id']?.toString(),
      forkBaseSessionRevision: (json['fork_base_session_revision'] as num?)
          ?.toInt(),
      parentToolCallId: json['parent_tool_call_id']?.toString(),
      runId: json['run_id']?.toString() ?? '',
      turnId: json['turn_id']?.toString() ?? '',
      runSequence: (json['run_sequence'] as num?)?.toInt() ?? 0,
      status: runStatusFromWire(json['status']?.toString()),
      messages: messages,
      pendingInteraction: rawInteraction is Map
          ? PendingInteraction.fromJson(rawInteraction.cast<String, Object?>())
          : null,
      approvalMode: approvalModeFromWire(json['approval_mode']?.toString()),
      invocationMode: invocationModeFromWire(
        json['invocation_mode']?.toString() ??
            (json['plan_mode'] == true ? 'plan' : null),
      ),
      pendingPlanExecution: (json['pending_plan_execution'] as Map?)
          ?.cast<String, Object?>(),
      processPanels: processPanels,
      subSessions: rawSubSessions is List
          ? [
              for (final value in rawSubSessions)
                if (value is Map)
                  Conversation.fromJson(value.cast<String, Object?>()),
            ]
          : <Conversation>[],
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
      archived: json['archived'] == true,
      archivedAt: DateTime.tryParse(json['archived_at']?.toString() ?? ''),
    );
  }

  Map<String, Object?> toJson() => {
    'id': id,
    'title': title,
    'agent_id': agentId,
    'session_id': sessionId,
    'parent_session_id': parentSessionId,
    'parent_run_id': parentRunId,
    'fork_base_session_revision': forkBaseSessionRevision,
    'parent_tool_call_id': parentToolCallId,
    'run_id': runId,
    'turn_id': turnId,
    'run_sequence': runSequence,
    'status': status.name,
    'messages': [for (final value in messages) value.toJson()],
    'pending_interaction': pendingInteraction?.toJson(),
    'approval_mode': approvalMode.wireValue,
    'invocation_mode': invocationMode.wireValue,
    'pending_plan_execution': pendingPlanExecution,
    'process_panels': [for (final value in processPanels) value.toJson()],
    'sub_sessions': [for (final value in subSessions) value.toJson()],
    'created_at': createdAt.toIso8601String(),
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
