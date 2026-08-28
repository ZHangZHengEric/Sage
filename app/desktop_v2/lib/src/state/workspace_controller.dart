import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:file_selector/file_selector.dart' as file_selector;
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/runtime_host.dart';
import '../api/v2_api.dart';
import '../models.dart';

typedef PreferencesLoader = Future<SharedPreferences> Function();

class WorkspaceController extends ChangeNotifier {
  factory WorkspaceController({
    V2ApiClient? api,
    RuntimeHost? runtimeHost,
    PreferencesLoader? preferencesLoader,
  }) {
    if (api == null && runtimeHost == null) {
      final host = RuntimeHost();
      return WorkspaceController._(
        api: host.api,
        runtimeHost: host,
        preferencesLoader: preferencesLoader,
      );
    }
    return WorkspaceController._(
      api: api ?? runtimeHost!.api,
      runtimeHost: runtimeHost,
      preferencesLoader: preferencesLoader,
    );
  }

  WorkspaceController._({
    required this._api,
    this._runtimeHost,
    PreferencesLoader? preferencesLoader,
  }) : _preferencesLoader = preferencesLoader ?? SharedPreferences.getInstance;

  static const agentWorkspaceId = 'agent-workspace';
  static const _conversationsKey = 'sage.desktop_v2.conversations.v1';
  static const archivedConversationsKey =
      'sage.desktop_v2.archived_conversations.v1';

  final V2ApiClient _api;
  final RuntimeHost? _runtimeHost;
  final PreferencesLoader _preferencesLoader;
  final Map<String, List<Conversation>> _conversations = {};
  final Map<String, List<Conversation>> _archivedConversationCache = {};
  final Map<String, StreamSubscription<Map<String, Object?>>> _streams = {};
  final Map<String, Set<String>> _preferredSkills = {};
  final Map<String, List<UploadedAttachment>> _attachments = {};
  final Map<String, List<String>> _composerInsertions = {};
  final Map<String, int> _reconnectAttempts = {};
  final Set<String> _recoveringStreams = {};
  final Random _sessionIdRandom = Random.secure();
  bool _disposed = false;

  SharedPreferences? _preferences;
  List<AgentSummary> agents = const [];
  List<SkillSummary> skills = const [];
  List<SkillSummary> skillCatalog = const [];
  List<ToolSummary> toolCatalog = const [];
  List<ModelProviderSummary> modelProviders = const [];
  List<McpConnectionSummary> mcpConnections = const [];
  List<ComponentSummary> components = const [];
  AgentConfiguration? agentConfiguration;
  bool settingsCatalogLoading = false;
  String settingsAgentLoadingId = '';
  DesktopSettings settings = const DesktopSettings();
  List<WorkspaceFileNode> files = const [];
  WorkspaceFileNode? selectedFile;
  WorkspaceFileContent? selectedFileContent;
  String selectedGroupId = agentWorkspaceId;
  String selectedAgentId = '';
  String selectedConversationId = '';
  bool loading = true;
  bool filesLoading = false;
  bool archivedConversationsLoaded = false;
  String? error;

  List<WorkspaceGroup> get groups => [
    WorkspaceGroup(
      id: agentWorkspaceId,
      name: 'Agent Workspace',
      workspaceId: '',
      conversations: _visibleConversations(agentWorkspaceId),
    ),
    for (final project in settings.projects)
      WorkspaceGroup(
        id: project.id,
        name: project.name,
        workspaceId: project.id,
        project: project,
        conversations: _visibleConversations(project.id),
      ),
  ];

  List<Conversation> _visibleConversations(String groupId) => [
    for (final value in _conversations.putIfAbsent(groupId, () => []))
      if (!value.archived) value,
  ];

  List<ArchivedConversationEntry> get archivedConversations {
    final groupNames = <String, String>{
      agentWorkspaceId: 'Agent Workspace',
      for (final project in settings.projects) project.id: project.name,
    };
    final values = <ArchivedConversationEntry>[
      for (final entry in _archivedConversationCache.entries)
        for (final conversation in entry.value)
          ArchivedConversationEntry(
            groupId: entry.key,
            groupName: groupNames[entry.key] ?? entry.key,
            conversation: conversation,
          ),
    ];
    values.sort(
      (left, right) => (right.conversation.archivedAt ?? DateTime(0)).compareTo(
        left.conversation.archivedAt ?? DateTime(0),
      ),
    );
    return values;
  }

  List<WorkspaceGroup> get projectGroups => [
    for (final group in groups)
      if (group.project != null) group,
  ];

  List<Conversation> get agentWorkspaceConversations =>
      _visibleConversations(agentWorkspaceId);

  WorkspaceGroup get selectedGroup => groups.firstWhere(
    (value) => value.id == selectedGroupId,
    orElse: () => groups.first,
  );

  Conversation? get selectedConversation {
    for (final value in _conversations.putIfAbsent(selectedGroupId, () => [])) {
      if (value.archived) continue;
      if (value.id == selectedConversationId) return value;
    }
    return null;
  }

  Set<String> get preferredSkills =>
      _preferredSkills.putIfAbsent(selectedConversationId, () => <String>{});

  List<UploadedAttachment> get attachments =>
      _attachments.putIfAbsent(selectedConversationId, () => []);

  bool get canSend {
    final conversation = selectedConversation;
    if (loading || selectedAgentId.isEmpty || conversation == null) {
      return false;
    }
    if (conversation.pendingInteraction != null ||
        conversation.status == RunStatus.suspended ||
        conversation.status == RunStatus.suspending) {
      return false;
    }
    if (conversation.status == RunStatus.running ||
        conversation.status == RunStatus.starting) {
      return conversation.runId.isNotEmpty && conversation.turnId.isNotEmpty;
    }
    return true;
  }

  Future<void> initialize() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      await _runtimeHost?.ensureReady();
      _preferences = await _preferencesLoader();
      _restoreConversations();
      final values = await Future.wait<Object>([
        _api.listAgents(),
        _api.getSettings(),
      ]);
      agents = values[0] as List<AgentSummary>;
      settings = values[1] as DesktopSettings;
      selectedAgentId = _initialAgentId();
      if (_visibleConversations(selectedGroupId).isEmpty) {
        createConversation(notify: false);
      }
      selectedConversationId = _visibleConversations(selectedGroupId).first.id;
      _adoptConversationAgent();
      await Future.wait([refreshSkills(), refreshFiles()]);
      await _reconnectRuns();
    } on Object catch (exception) {
      error = exception.toString();
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  String _initialAgentId() {
    final configured = settings.defaultAgentId;
    if (configured != null && agents.any((value) => value.id == configured)) {
      return configured;
    }
    for (final value in agents) {
      if (value.isDefault) return value.id;
    }
    return agents.isEmpty ? '' : agents.first.id;
  }

  void createConversation({bool notify = true}) {
    final conversation = Conversation(
      id: _id('conversation'),
      agentId: selectedAgentId,
    );
    _conversations
        .putIfAbsent(selectedGroupId, () => [])
        .insert(0, conversation);
    selectedConversationId = conversation.id;
    _persist();
    if (notify) notifyListeners();
  }

  Future<void> createAgentWorkspaceConversation() async {
    selectedGroupId = agentWorkspaceId;
    createConversation(notify: false);
    selectedFile = null;
    selectedFileContent = null;
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  Future<void> selectAgentWorkspaceConversation(String id) async {
    if (selectedGroupId == agentWorkspaceId && selectedConversationId == id) {
      return;
    }
    selectedGroupId = agentWorkspaceId;
    selectedConversationId = id;
    _adoptConversationAgent();
    selectedFile = null;
    selectedFileContent = null;
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  Future<void> selectGroup(String id) async {
    if (selectedGroupId == id) return;
    selectedGroupId = id;
    final values = _visibleConversations(selectedGroupId);
    if (values.isEmpty) createConversation(notify: false);
    selectedConversationId = _visibleConversations(selectedGroupId).first.id;
    _adoptConversationAgent();
    selectedFile = null;
    selectedFileContent = null;
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  Future<void> selectConversation(String id) async {
    if (selectedConversationId == id) return;
    selectedConversationId = id;
    _adoptConversationAgent();
    selectedFile = null;
    selectedFileContent = null;
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  Future<void> selectAgent(String id) async {
    if (id == selectedAgentId || !agents.any((value) => value.id == id)) return;
    selectedAgentId = id;
    final conversation = selectedConversation;
    if (conversation != null && conversation.status == RunStatus.idle) {
      conversation.agentId = id;
    }
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  void _adoptConversationAgent() {
    final value = selectedConversation?.agentId ?? '';
    if (agents.any((agent) => agent.id == value)) selectedAgentId = value;
  }

  Future<void> refreshSkills() async {
    if (selectedAgentId.isEmpty) {
      skills = const [];
      return;
    }
    try {
      skills = await _api.listSkills(selectedAgentId);
      preferredSkills.removeWhere(
        (name) => !skills.any((value) => value.name == name),
      );
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  void toggleSkill(String name) {
    final values = preferredSkills;
    values.contains(name) ? values.remove(name) : values.add(name);
    notifyListeners();
  }

  Future<void> refreshFiles() async {
    if (selectedAgentId.isEmpty) return;
    WorkspaceFileNode? selectionToReload;
    filesLoading = true;
    notifyListeners();
    try {
      files = await _api.workspaceTree(
        agentId: selectedAgentId,
        workspaceId: selectedGroup.workspaceId,
      );
      final selectedPath = selectedFile?.path;
      if (selectedPath != null) {
        selectionToReload = _findFile(files, selectedPath);
      }
      if (selectedPath != null && selectionToReload == null) {
        selectedFile = null;
        selectedFileContent = null;
      }
    } on Object catch (exception) {
      error = exception.toString();
    } finally {
      filesLoading = false;
      notifyListeners();
    }
    if (selectionToReload != null) {
      await openFile(selectionToReload);
    }
  }

  WorkspaceFileNode? _findFile(List<WorkspaceFileNode> nodes, String path) {
    for (final node in nodes) {
      if (node.path == path) return node;
      final nested = _findFile(node.children, path);
      if (nested != null) return nested;
    }
    return null;
  }

  Future<void> openFile(WorkspaceFileNode node) async {
    if (node.isDirectory) return;
    selectedFile = node;
    selectedFileContent = null;
    notifyListeners();
    try {
      final content = await _api.workspaceFile(
        agentId: selectedAgentId,
        workspaceId: selectedGroup.workspaceId,
        path: node.path,
      );
      if (selectedFile?.path == node.path) {
        selectedFileContent = content;
      }
    } on Object catch (exception) {
      error = exception.toString();
    }
    notifyListeners();
  }

  bool isWorkspaceNodeReferenced(WorkspaceFileNode? node) {
    if (node == null) return false;
    final virtualPath = _workspaceVirtualPath(node.path);
    return attachments.any((value) => value.virtualPath == virtualPath);
  }

  void referenceWorkspaceNode(WorkspaceFileNode node) {
    if (isWorkspaceNodeReferenced(node)) return;
    attachments.add(
      UploadedAttachment(
        name: node.name,
        path: node.path,
        virtualPath: _workspaceVirtualPath(node.path),
        size: node.size,
        isDirectory: node.isDirectory,
      ),
    );
    notifyListeners();
  }

  void referenceWorkspaceSelection(WorkspaceFileNode node, String selection) {
    final selectedText = selection.trim();
    if (selectedText.isEmpty || node.isDirectory) return;
    referenceWorkspaceNode(node);
    final quoted = selectedText
        .split('\n')
        .map((line) => line.isEmpty ? '>' : '> $line')
        .join('\n');
    _composerInsertions
        .putIfAbsent(selectedConversationId, () => [])
        .add('@${node.path}\n$quoted');
    notifyListeners();
  }

  String? takeComposerInsertion(String conversationId) {
    final values = _composerInsertions[conversationId];
    if (values == null || values.isEmpty) return null;
    final value = values.removeAt(0);
    if (values.isEmpty) _composerInsertions.remove(conversationId);
    return value;
  }

  String _workspaceVirtualPath(String path) {
    final normalized = path
        .replaceAll('\\', '/')
        .split('/')
        .where((part) => part.isNotEmpty && part != '.')
        .join('/');
    return '/workspace/$normalized';
  }

  Future<void> chooseAndUploadFile() async {
    final file = await file_selector.openFile();
    if (file == null || selectedAgentId.isEmpty) return;
    try {
      final uploaded = await _api.upload(
        agentId: selectedAgentId,
        workspaceId: selectedGroup.workspaceId,
        file: file,
      );
      attachments.add(uploaded);
      await refreshFiles();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  void removeAttachment(UploadedAttachment value) {
    attachments.remove(value);
    notifyListeners();
  }

  Future<void> addProject() async {
    final path = await file_selector.getDirectoryPath();
    if (path == null || path.isEmpty) return;
    try {
      final project = await _api.addProject(path);
      settings = settings.copyWith(projects: [...settings.projects, project]);
      _conversations.putIfAbsent(project.id, () => []);
      await selectGroup(project.id);
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  Future<void> removeSelectedProject() async {
    final project = selectedGroup.project;
    if (project == null) return;
    try {
      await _api.removeProject(project.id);
      settings = settings.copyWith(
        projects: settings.projects
            .where((value) => value.id != project.id)
            .toList(),
      );
      selectedGroupId = agentWorkspaceId;
      if (_visibleConversations(selectedGroupId).isEmpty) {
        createConversation(notify: false);
      }
      selectedConversationId = _visibleConversations(selectedGroupId).first.id;
      await refreshFiles();
    } on Object catch (exception) {
      error = exception.toString();
    }
    notifyListeners();
  }

  Future<void> saveSettings(DesktopSettings value) async {
    try {
      final workspaceChanged =
          settings.agentWorkspacePath != value.agentWorkspacePath;
      settings = await _api.saveSettings(value);
      if (workspaceChanged && selectedGroupId == agentWorkspaceId) {
        selectedFile = null;
        selectedFileContent = null;
        await refreshFiles();
      } else {
        notifyListeners();
      }
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<String?> chooseAgentWorkspace({required String confirmButtonText}) =>
      file_selector.getDirectoryPath(
        initialDirectory: settings.agentWorkspacePath.isEmpty
            ? null
            : settings.agentWorkspacePath,
        confirmButtonText: confirmButtonText,
        canCreateDirectories: true,
      );

  Future<void> loadSettingsCatalog({String? agentId}) async {
    final targetAgentId = agentId ?? selectedAgentId;
    if (settingsCatalogLoading || targetAgentId.isEmpty) return;
    settingsCatalogLoading = true;
    notifyListeners();
    try {
      final values = await Future.wait<Object>([
        _api.getAgentConfiguration(targetAgentId),
        _api.listTools(),
        _api.listSkillCatalog(),
        _api.listModelProviders(),
        _api.listMcpConnections(),
        _api.listComponents(),
      ]);
      agentConfiguration = values[0] as AgentConfiguration;
      toolCatalog = values[1] as List<ToolSummary>;
      skillCatalog = values[2] as List<SkillSummary>;
      modelProviders = values[3] as List<ModelProviderSummary>;
      mcpConnections = values[4] as List<McpConnectionSummary>;
      components = values[5] as List<ComponentSummary>;
    } on Object catch (exception) {
      error = exception.toString();
    } finally {
      settingsCatalogLoading = false;
      notifyListeners();
    }
  }

  Future<String> loadSkillContent(String skillName) =>
      _api.getSkillContent(skillName);

  Future<String?> chooseSkillFolder({required String confirmButtonText}) =>
      file_selector.getDirectoryPath(
        confirmButtonText: confirmButtonText,
        canCreateDirectories: false,
      );

  Future<List<String>> importSkillFolder(String path) async {
    try {
      final imported = await _api.importSkillFolder(path);
      skillCatalog = await _api.listSkillCatalog();
      notifyListeners();
      return imported;
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> selectSettingsAgent(String agentId) async {
    if (agentId.isEmpty ||
        (agentConfiguration?.id == agentId && settingsAgentLoadingId.isEmpty)) {
      return;
    }
    settingsAgentLoadingId = agentId;
    notifyListeners();
    try {
      final value = await _api.getAgentConfiguration(agentId);
      if (settingsAgentLoadingId != agentId) return;
      agentConfiguration = value;
    } on Object catch (exception) {
      if (settingsAgentLoadingId == agentId) error = exception.toString();
    } finally {
      if (settingsAgentLoadingId == agentId) {
        settingsAgentLoadingId = '';
        notifyListeners();
      }
    }
  }

  Future<void> patchAgentConfiguration(Map<String, Object?> patch) async {
    final current = agentConfiguration;
    if (current == null) return;
    try {
      agentConfiguration = await _api.patchAgentConfiguration(
        current.id,
        patch,
      );
      agents = [
        for (final agent in agents)
          agent.id == current.id
              ? AgentSummary(
                  id: agent.id,
                  name: agentConfiguration!.name,
                  isDefault: agent.isDefault,
                )
              : agent,
      ];
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<String> deleteAgent(String agentId) async {
    try {
      agents = await _api.deleteAgent(agentId);
      if (agents.isEmpty) {
        throw const SageApiException('至少需要保留一个 Agent');
      }
      final replacement = agents.firstWhere(
        (value) => value.isDefault,
        orElse: () => agents.first,
      );
      if (selectedAgentId == agentId) {
        selectedAgentId = replacement.id;
      }
      for (final values in _conversations.values) {
        for (final conversation in values) {
          if (conversation.agentId == agentId &&
              conversation.status == RunStatus.idle) {
            conversation.agentId = replacement.id;
          }
        }
      }
      if (settings.defaultAgentId == agentId) {
        settings = settings.copyWith(defaultAgentId: replacement.id);
      }
      agentConfiguration = null;
      notifyListeners();
      await loadSettingsCatalog(agentId: replacement.id);
      await Future.wait([refreshSkills(), refreshFiles()]);
      _persist();
      return replacement.id;
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  bool canManageConversation(Conversation conversation) => !{
    RunStatus.starting,
    RunStatus.running,
    RunStatus.suspending,
    RunStatus.suspended,
  }.contains(conversation.status);

  void archiveConversation(String groupId, String conversationId) {
    final conversation = _conversationIn(groupId, conversationId);
    if (conversation == null || conversation.archived) return;
    if (!canManageConversation(conversation)) {
      error = '运行中的会话不能归档';
      notifyListeners();
      return;
    }
    _loadArchivedConversations(notify: false);
    _conversations[groupId]?.removeWhere((value) => value.id == conversationId);
    _archivedConversationCache
        .putIfAbsent(groupId, () => [])
        .insert(0, conversation);
    conversation.archived = true;
    conversation.archivedAt = DateTime.now();
    _selectReplacementAfterRemoval(groupId, conversationId);
    _persist();
    notifyListeners();
  }

  void restoreConversation(String groupId, String conversationId) {
    _loadArchivedConversations(notify: false);
    final conversation = _conversationIn(groupId, conversationId);
    if (conversation == null || !conversation.archived) return;
    _archivedConversationCache[groupId]?.removeWhere(
      (value) => value.id == conversationId,
    );
    _conversations.putIfAbsent(groupId, () => []).insert(0, conversation);
    conversation.archived = false;
    conversation.archivedAt = null;
    _persist();
    notifyListeners();
  }

  Future<void> deleteConversation(String groupId, String conversationId) async {
    final conversation = _conversationIn(groupId, conversationId);
    if (conversation == null) return;
    if (!canManageConversation(conversation)) {
      try {
        await _refreshConversationSnapshot(conversation);
      } on Object catch (exception) {
        error = exception.toString();
        notifyListeners();
        return;
      }
      if (!canManageConversation(conversation)) {
        error = '运行中的会话不能删除';
        notifyListeners();
        return;
      }
    }
    try {
      final sessionId = conversation.sessionId;
      if (sessionId != null && sessionId.isNotEmpty) {
        await _api.deleteSession(sessionId);
      }
      await _streams.remove(conversation.id)?.cancel();
      _recoveringStreams.remove(conversation.id);
      _reconnectAttempts.remove(conversation.id);
      _preferredSkills.remove(conversation.id);
      _attachments.remove(conversation.id);
      _composerInsertions.remove(conversation.id);
      _conversations[groupId]?.removeWhere(
        (value) => value.id == conversationId,
      );
      _archivedConversationCache[groupId]?.removeWhere(
        (value) => value.id == conversationId,
      );
      _selectReplacementAfterRemoval(groupId, conversationId);
      _persist();
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Conversation? _conversationIn(String groupId, String conversationId) {
    for (final value in _conversations[groupId] ?? const <Conversation>[]) {
      if (value.id == conversationId) return value;
    }
    for (final value
        in _archivedConversationCache[groupId] ?? const <Conversation>[]) {
      if (value.id == conversationId) return value;
    }
    return null;
  }

  void loadArchivedConversations() => _loadArchivedConversations(notify: true);

  void _loadArchivedConversations({required bool notify}) {
    if (archivedConversationsLoaded) return;
    archivedConversationsLoaded = true;
    final raw = _preferences?.getString(archivedConversationsKey);
    if (raw != null && raw.isNotEmpty) {
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map) {
          for (final entry in decoded.entries) {
            final values = entry.value;
            if (values is! List) continue;
            _archivedConversationCache[entry.key.toString()] = [
              for (final value in values)
                if (value is Map)
                  Conversation.fromJson(value.cast<String, Object?>())
                    ..archived = true,
            ];
          }
        }
      } on FormatException {
        // A corrupt archive index must not prevent normal conversations.
      }
    }
    if (notify) notifyListeners();
  }

  void _selectReplacementAfterRemoval(String groupId, String conversationId) {
    if (selectedGroupId != groupId ||
        selectedConversationId != conversationId) {
      return;
    }
    var visible = _visibleConversations(groupId);
    if (visible.isEmpty) {
      createConversation(notify: false);
      visible = _visibleConversations(groupId);
    }
    selectedConversationId = visible.first.id;
    _adoptConversationAgent();
    selectedFile = null;
    selectedFileContent = null;
  }

  Future<void> setMcpConnectionEnabled(String name, bool enabled) async {
    try {
      final updated = await _api.setMcpConnectionEnabled(name, enabled);
      mcpConnections = [
        for (final value in mcpConnections)
          value.name == name ? updated : value,
      ];
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> patchModelProvider(
    String providerId,
    Map<String, Object?> patch,
  ) async {
    try {
      final updated = await _api.patchModelProvider(providerId, patch);
      modelProviders = [
        for (final value in modelProviders)
          value.id == providerId ? updated : value,
      ];
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<ModelProviderSummary> createModelProvider(
    Map<String, Object?> value,
  ) async {
    try {
      final created = await _api.createModelProvider(value);
      modelProviders = [...modelProviders, created];
      notifyListeners();
      return created;
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<String> revealModelProviderApiKey(String providerId) async {
    try {
      return await _api.revealModelProviderApiKey(providerId);
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> deleteModelProvider(String providerId) async {
    try {
      modelProviders = await _api.deleteModelProvider(providerId);
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> addMcpConnection(Map<String, Object?> value) async {
    try {
      final created = await _api.addMcpConnection(value);
      mcpConnections = [...mcpConnections, created];
      components = await _api.listComponents();
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> selectComponent(String componentId, String pluginId) async {
    try {
      await _api.selectComponent(componentId, pluginId);
      components = await _api.listComponents();
      notifyListeners();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> send(String text) async {
    final conversation = selectedConversation;
    final prompt = text.trim();
    if (conversation == null || prompt.isEmpty || selectedAgentId.isEmpty) {
      return;
    }
    if (conversation.status == RunStatus.running ||
        conversation.status == RunStatus.starting ||
        conversation.status == RunStatus.suspending) {
      await steer(prompt);
      return;
    }
    if (conversation.sessionId == null || conversation.sessionId!.isEmpty) {
      conversation.sessionId = _newSessionId();
    }
    conversation.agentId = selectedAgentId;
    final userMessage = ChatMessage(
      id: _id('message'),
      role: 'user',
      text: prompt,
    );
    conversation.messages.add(userMessage);
    conversation.processPanels.add(
      RuntimeProcessPanel(
        id: _id('process'),
        anchorMessageId: userMessage.id,
        startedAt: DateTime.now(),
      ),
    );
    if (conversation.title == '新会话') {
      conversation.title = prompt.length > 28
          ? '${prompt.substring(0, 28)}…'
          : prompt;
    }
    conversation.status = RunStatus.starting;
    conversation.pendingInteraction = null;
    final selectedAttachments = List<UploadedAttachment>.of(attachments);
    _attachments[conversation.id] = [];
    notifyListeners();
    _persist();
    final body = <String, Object?>{
      'agent_id': selectedAgentId,
      'messages': [
        {'role': 'user', 'text': prompt},
      ],
      if (conversation.sessionId != null) 'session_id': conversation.sessionId,
      if (selectedGroup.workspaceId.isNotEmpty)
        'workspace_id': selectedGroup.workspaceId,
      'preferred_skills': preferredSkills.toList()..sort(),
      'attachment_paths': [
        for (final value in selectedAttachments) value.virtualPath,
      ],
      'approval_mode': conversation.approvalMode.wireValue,
      'idempotency_key': _id('desktop'),
    };
    _listen(conversation, _api.startRun(body));
  }

  void setApprovalMode(ApprovalMode mode) {
    final conversation = selectedConversation;
    if (conversation == null ||
        {
          RunStatus.starting,
          RunStatus.running,
          RunStatus.suspending,
          RunStatus.suspended,
        }.contains(conversation.status)) {
      return;
    }
    conversation.approvalMode = mode;
    notifyListeners();
    _persist();
  }

  Future<void> pause() async {
    final value = selectedConversation;
    if (value == null || value.runId.isEmpty) return;
    value.status = RunStatus.suspending;
    notifyListeners();
    try {
      await _api.pause(value.runId);
    } on Object catch (exception) {
      value.status = RunStatus.running;
      error = exception.toString();
      notifyListeners();
    }
  }

  Future<void> resume() async {
    final value = selectedConversation;
    if (value == null || value.runId.isEmpty) return;
    value.status = RunStatus.running;
    value.pendingInteraction = null;
    notifyListeners();
    try {
      await _api.resume(value.runId);
      _subscribe(value);
    } on Object catch (exception) {
      value.status = RunStatus.suspended;
      error = exception.toString();
      notifyListeners();
    }
  }

  Future<void> cancel() async {
    final value = selectedConversation;
    if (value == null || value.runId.isEmpty) return;
    try {
      await _api.cancel(value.runId);
      await _refreshConversationSnapshot(value);
      if (_isTerminal(value.status)) {
        await _streams.remove(value.id)?.cancel();
      }
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  Future<void> steer(String text) async {
    final value = selectedConversation;
    final prompt = text.trim();
    if (value == null ||
        value.runId.isEmpty ||
        value.turnId.isEmpty ||
        prompt.isEmpty) {
      return;
    }
    value.messages.add(
      ChatMessage(id: _id('steer'), role: 'user', text: prompt),
    );
    notifyListeners();
    try {
      await _api.steer(value.runId, value.turnId, prompt);
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  Future<void> replyInteraction(String decision, {String text = ''}) async {
    final value = selectedConversation;
    final interaction = value?.pendingInteraction;
    if (value == null || interaction == null) return;
    try {
      await _api.replyInteraction(
        value.runId,
        interactionId: interaction.id,
        decision: decision,
        payload: text.trim().isEmpty ? const {} : {'text': text.trim()},
      );
      value.pendingInteraction = null;
      value.status = RunStatus.running;
      notifyListeners();
      _subscribe(value);
    } on Object catch (exception) {
      try {
        await _refreshConversationSnapshot(value);
      } on Object {
        // Preserve the original interaction error if reconciliation also fails.
      }
      error = value.pendingInteraction?.id == interaction.id
          ? exception.toString()
          : '任务状态已变化，此审批请求已失效';
      notifyListeners();
    }
  }

  void _listen(Conversation conversation, Stream<Map<String, Object?>> stream) {
    unawaited(_streams.remove(conversation.id)?.cancel());
    late final StreamSubscription<Map<String, Object?>> subscription;
    subscription = stream.listen(
      (event) {
        _reconnectAttempts[conversation.id] = 0;
        _applyEvent(conversation, event);
      },
      onError: (Object exception, StackTrace _) {
        if (identical(_streams[conversation.id], subscription)) {
          _streams.remove(conversation.id);
        }
        if (_disposed) return;
        error = exception.toString();
        if (conversation.runId.isEmpty) {
          conversation.status = RunStatus.failed;
        } else if (_isActive(conversation.status)) {
          unawaited(_recoverStream(conversation));
        }
        notifyListeners();
        _persist();
      },
      onDone: () {
        if (identical(_streams[conversation.id], subscription)) {
          _streams.remove(conversation.id);
        }
        if (!_disposed &&
            conversation.runId.isNotEmpty &&
            _isActive(conversation.status)) {
          unawaited(_recoverStream(conversation));
        }
        _persist();
      },
      cancelOnError: true,
    );
    _streams[conversation.id] = subscription;
  }

  bool _isActive(RunStatus status) => {
    RunStatus.starting,
    RunStatus.running,
    RunStatus.suspending,
  }.contains(status);

  bool _isTerminal(RunStatus status) => {
    RunStatus.completed,
    RunStatus.failed,
    RunStatus.cancelled,
  }.contains(status);

  Future<void> _refreshConversationSnapshot(Conversation conversation) async {
    final snapshot = await _api.getRun(conversation.runId);
    _applySnapshot(conversation, snapshot);
    notifyListeners();
    _persist();
  }

  Future<void> _recoverStream(Conversation conversation) async {
    if (_disposed || !_recoveringStreams.add(conversation.id)) return;
    var retry = false;
    try {
      final attempt = (_reconnectAttempts[conversation.id] ?? 0) + 1;
      _reconnectAttempts[conversation.id] = attempt;
      final delaySeconds = attempt > 4 ? 8 : 1 << (attempt - 1);
      await Future<void>.delayed(Duration(seconds: delaySeconds));
      if (_disposed || !_isActive(conversation.status)) return;
      final snapshot = await _api.getRun(conversation.runId);
      final remoteSequence = _snapshotRunSequence(snapshot);
      _applySnapshot(conversation, snapshot);
      notifyListeners();
      _persist();
      if (remoteSequence > conversation.runSequence ||
          _isActive(conversation.status)) {
        _subscribe(conversation);
      }
    } on Object catch (exception) {
      if (_disposed) return;
      error = exception.toString();
      notifyListeners();
      retry = _isActive(conversation.status);
    } finally {
      _recoveringStreams.remove(conversation.id);
    }
    if (retry) unawaited(_recoverStream(conversation));
  }

  void _subscribe(Conversation conversation) {
    if (conversation.runId.isEmpty || _streams.containsKey(conversation.id)) {
      return;
    }
    _listen(
      conversation,
      _api.subscribeRun(
        conversation.runId,
        afterSequence: conversation.runSequence,
      ),
    );
  }

  Future<void> _reconnectRuns() async {
    for (final values in _conversations.values) {
      for (final conversation in values) {
        if (conversation.archived) continue;
        if (conversation.runId.isEmpty ||
            !{
              RunStatus.starting,
              RunStatus.running,
              RunStatus.suspending,
              RunStatus.suspended,
            }.contains(conversation.status)) {
          continue;
        }
        try {
          final snapshot = await _api.getRun(conversation.runId);
          final remoteSequence = _snapshotRunSequence(snapshot);
          _applySnapshot(conversation, snapshot);
          if (remoteSequence > conversation.runSequence ||
              conversation.status == RunStatus.running ||
              conversation.status == RunStatus.starting ||
              conversation.status == RunStatus.suspending) {
            _subscribe(conversation);
          }
        } on Object catch (_) {
          conversation.status = RunStatus.failed;
        }
      }
    }
  }

  void _applyEvent(Conversation conversation, Map<String, Object?> event) {
    if (event['kind'] == 'stream.opened') {
      final handle = event['handle'];
      if (handle is Map) {
        conversation.runId = handle['run_id']?.toString() ?? conversation.runId;
        conversation.sessionId = handle['session_id']?.toString();
        conversation.runSequence =
            ((handle['event_cursor'] as Map?)?['run_sequence'] as num?)
                ?.toInt() ??
            conversation.runSequence;
      }
      conversation.status = RunStatus.starting;
      notifyListeners();
      _persist();
      return;
    }
    final type = event['type']?.toString() ?? '';
    final sequence = (event['run_sequence'] as num?)?.toInt() ?? 0;
    if (sequence <= conversation.runSequence) return;
    conversation.runSequence = sequence;
    conversation.runId = event['run_id']?.toString() ?? conversation.runId;
    conversation.sessionId = event['session_id']?.toString();
    conversation.turnId = event['turn_id']?.toString() ?? conversation.turnId;
    conversation.runtimeEvents.add(event);
    if (conversation.runtimeEvents.length > 300) {
      conversation.runtimeEvents.removeRange(0, 50);
    }
    final data = event['data'];
    final eventData = data is Map
        ? data.cast<String, Object?>()
        : const <String, Object?>{};
    if (type == 'message.delta') {
      _appendDelta(conversation, event, eventData['delta']);
    } else if (type == 'message.completed') {
      _completeMessage(conversation, eventData, sequence: sequence);
    } else if (type == 'item.completed') {
      _trackToolResult(conversation, eventData);
    } else if (type == 'turn.started') {
      conversation.status = RunStatus.running;
    } else if (type == 'run.suspend_requested') {
      conversation.status = RunStatus.suspending;
    } else if (type == 'run.suspended') {
      conversation.status = RunStatus.suspended;
      unawaited(_hydrateInteraction(conversation));
    } else if (type == 'run.resumed') {
      conversation.status = RunStatus.running;
      conversation.pendingInteraction = null;
    } else if (type == 'run.completed') {
      _applyTerminalState(
        conversation,
        RunStatus.completed,
        promoteFinal: true,
      );
    } else if (type == 'run.cancelled') {
      _applyTerminalState(conversation, RunStatus.cancelled);
    } else if (type == 'run.failed') {
      _applyTerminalState(conversation, RunStatus.failed);
      final rawError = eventData['error'];
      if (rawError is Map) error = rawError['message']?.toString();
    }
    _trackActivity(conversation, type, eventData, sequence: sequence);
    notifyListeners();
    _persist();
  }

  void _appendDelta(
    Conversation conversation,
    Map<String, Object?> event,
    Object? delta,
  ) {
    final text = delta is String ? delta : delta?.toString() ?? '';
    if (text.isEmpty) return;
    final id =
        event['item_id']?.toString() ?? 'assistant:${conversation.runId}';
    final existing = conversation.messages
        .where((value) => value.id == id)
        .firstOrNull;
    if (existing == null) {
      conversation.messages.add(
        ChatMessage(
          id: id,
          role: 'assistant',
          text: text,
          streaming: true,
          processOnly: true,
          sequence: (event['run_sequence'] as num?)?.toInt() ?? 0,
        ),
      );
    } else {
      existing.text += text;
      existing.streaming = true;
      existing.processOnly = true;
    }
  }

  void _completeMessage(
    Conversation conversation,
    Map<String, Object?> data, {
    required int sequence,
  }) {
    final rawItem = data['item'];
    if (rawItem is! Map) return;
    final item = rawItem.cast<String, Object?>();
    final rawMessage = item['data'];
    if (rawMessage is! Map || rawMessage['kind'] != 'message') return;
    final role = rawMessage['role']?.toString() ?? 'assistant';
    if (role != 'assistant') return;
    final id = item['item_id']?.toString() ?? _id('assistant');
    final text = _textFromContent(rawMessage['content']);
    final existing = conversation.messages
        .where((value) => value.id == id)
        .firstOrNull;
    if (existing == null) {
      conversation.messages.add(
        ChatMessage(
          id: id,
          role: role,
          text: text,
          processOnly: true,
          sequence: sequence,
        ),
      );
    } else {
      existing.text = text.isEmpty ? existing.text : text;
      existing.streaming = false;
      existing.processOnly = true;
    }
  }

  String _textFromContent(Object? content) {
    if (content is! List) return '';
    return [
      for (final block in content)
        if (block is Map && block['kind'] == 'text')
          block['text']?.toString() ?? '',
    ].join();
  }

  void _finishStreamingMessages(Conversation conversation) {
    for (final message in conversation.messages) {
      message.streaming = false;
    }
  }

  void _trackActivity(
    Conversation conversation,
    String type,
    Map<String, Object?> data, {
    required int sequence,
  }) {
    if (!type.startsWith('tool.') && !type.startsWith('flow.')) return;
    final id =
        data['tool_call_id']?.toString() ?? data['node_id']?.toString() ?? type;
    final terminal =
        type.endsWith('.succeeded') ||
        type.endsWith('.failed') ||
        type.endsWith('.cancelled') ||
        type.endsWith('.completed');
    final panel = _activeProcessPanel(conversation);
    final existing = panel.activities
        .where((value) => value.id == id)
        .firstOrNull;
    final rawArguments = data['arguments'];
    final arguments = rawArguments is Map
        ? rawArguments.cast<String, Object?>()
        : const <String, Object?>{};
    if (existing == null) {
      panel.activities.add(
        RuntimeActivity(
          id: id,
          label: data['tool_name']?.toString() ?? type,
          active: !terminal,
          failed: type.endsWith('.failed'),
          arguments: arguments,
          sequence: sequence,
          completedAt: terminal ? DateTime.now() : null,
        ),
      );
      return;
    }
    existing.active = !terminal;
    existing.failed = type.endsWith('.failed');
    if (arguments.isNotEmpty) existing.arguments = arguments;
    if (terminal) existing.completedAt = DateTime.now();
  }

  RuntimeProcessPanel _activeProcessPanel(Conversation conversation) {
    final running = conversation.processPanels
        .where((value) => value.running)
        .lastOrNull;
    if (running != null) return running;
    final anchor = conversation.messages
        .where((value) => value.role == 'user')
        .lastOrNull;
    final panel = RuntimeProcessPanel(
      id: _id('process'),
      anchorMessageId: anchor?.id ?? '',
      startedAt: DateTime.now(),
    );
    conversation.processPanels.add(panel);
    return panel;
  }

  void _finishProcessPanel(
    Conversation conversation, {
    bool promoteFinal = false,
  }) {
    final panel =
        conversation.processPanels.where((value) => value.running).lastOrNull ??
        (promoteFinal ? conversation.processPanels.lastOrNull : null);
    if (panel == null) return;
    if (promoteFinal) {
      final anchorIndex = conversation.messages.indexWhere(
        (value) => value.id == panel.anchorMessageId,
      );
      final finalMessage = conversation.messages
          .skip(anchorIndex < 0 ? 0 : anchorIndex + 1)
          .where((value) => value.role == 'assistant')
          .lastOrNull;
      if (finalMessage != null) finalMessage.processOnly = false;
    }
    panel.running = false;
    panel.completedAt = DateTime.now();
    for (final activity in panel.activities.where((value) => value.active)) {
      activity.active = false;
      activity.completedAt = DateTime.now();
    }
  }

  void _trackToolResult(Conversation conversation, Map<String, Object?> data) {
    final rawItem = data['item'];
    if (rawItem is! Map) return;
    final item = rawItem.cast<String, Object?>();
    final rawValue = item['data'];
    if (rawValue is! Map) return;
    final value = rawValue.cast<String, Object?>();
    if (value['kind']?.toString() != 'tool_result') return;
    final callId = value['tool_call_id']?.toString() ?? '';
    if (callId.isEmpty) return;
    for (final panel in conversation.processPanels.reversed) {
      final activity = panel.activities
          .where((entry) => entry.id == callId)
          .firstOrNull;
      if (activity == null) continue;
      activity.result = _toolResultText(value['content']);
      activity.active = false;
      activity.failed = value['error'] != null;
      activity.completedAt ??= DateTime.now();
      return;
    }
  }

  String _toolResultText(Object? content) {
    if (content is! List) return content?.toString() ?? '';
    final values = <String>[];
    for (final rawBlock in content) {
      if (rawBlock is! Map) continue;
      final block = rawBlock.cast<String, Object?>();
      final kind = block['kind']?.toString() ?? '';
      final value = switch (kind) {
        'text' => block['text'],
        'json' => block['value'] ?? block['data'],
        'file' ||
        'image' ||
        'audio' => block['name'] ?? block['uri'] ?? block['path'],
        _ => block['value'] ?? block['data'] ?? block['text'],
      };
      if (value == null) continue;
      values.add(value is String ? value : jsonEncode(value));
    }
    return values.join('\n');
  }

  Future<void> _hydrateInteraction(Conversation conversation) async {
    try {
      final snapshot = await _api.getRun(conversation.runId);
      _applySnapshot(conversation, snapshot);
      notifyListeners();
      _persist();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  void _applySnapshot(
    Conversation conversation,
    Map<String, Object?> snapshot,
  ) {
    final rawRun = snapshot['run'];
    RunStatus? nextStatus;
    if (rawRun is Map) {
      nextStatus = runStatusFromWire(rawRun['state']?.toString());
      conversation.sessionId = rawRun['session_id']?.toString();
      conversation.turnId =
          rawRun['active_turn_id']?.toString() ?? conversation.turnId;
    }
    final interaction = snapshot['interaction'];
    conversation.pendingInteraction =
        interaction is Map && interaction['status']?.toString() == 'pending'
        ? PendingInteraction.fromJson(interaction.cast<String, Object?>())
        : null;
    if (nextStatus != null) {
      if (_isTerminal(nextStatus)) {
        _applyTerminalState(
          conversation,
          nextStatus,
          promoteFinal: nextStatus == RunStatus.completed,
        );
      } else {
        conversation.status = nextStatus;
      }
    }
  }

  void _applyTerminalState(
    Conversation conversation,
    RunStatus status, {
    bool promoteFinal = false,
  }) {
    conversation.status = status;
    conversation.pendingInteraction = null;
    _finishStreamingMessages(conversation);
    _finishProcessPanel(conversation, promoteFinal: promoteFinal);
  }

  int _snapshotRunSequence(Map<String, Object?> snapshot) {
    final rawRun = snapshot['run'];
    if (rawRun is! Map) return 0;
    return (rawRun['last_run_sequence'] as num?)?.toInt() ?? 0;
  }

  void clearError() {
    error = null;
    notifyListeners();
  }

  void _restoreConversations() {
    final raw = _preferences?.getString(_conversationsKey);
    if (raw == null || raw.isEmpty) return;
    var migratedArchived = false;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return;
      for (final entry in decoded.entries) {
        final values = entry.value;
        if (values is! List) continue;
        final groupId = entry.key.toString();
        for (final value in values) {
          if (value is! Map) continue;
          final conversation = Conversation.fromJson(
            value.cast<String, Object?>(),
          );
          if (conversation.archived) {
            migratedArchived = true;
            _loadArchivedConversations(notify: false);
            _archivedConversationCache
                .putIfAbsent(groupId, () => [])
                .add(conversation);
          } else {
            _conversations.putIfAbsent(groupId, () => []).add(conversation);
          }
        }
      }
      if (migratedArchived) _persist();
    } on FormatException {
      // A corrupt UI cache must not prevent the runtime from starting.
    }
  }

  void _persist() {
    final preferences = _preferences;
    if (preferences == null) return;
    unawaited(
      preferences.setString(
        _conversationsKey,
        jsonEncode({
          for (final entry in _conversations.entries)
            entry.key: [for (final value in entry.value) value.toJson()],
        }),
      ),
    );
    if (archivedConversationsLoaded) {
      unawaited(
        preferences.setString(
          archivedConversationsKey,
          jsonEncode({
            for (final entry in _archivedConversationCache.entries)
              entry.key: [for (final value in entry.value) value.toJson()],
          }),
        ),
      );
    }
  }

  String _id(String prefix) =>
      '${prefix}_${DateTime.now().microsecondsSinceEpoch}_${_nextId++}';

  String _newSessionId() {
    final timestamp = DateTime.now().millisecondsSinceEpoch;
    final random = _sessionIdRandom.nextInt(1000000).toString().padLeft(6, '0');
    return 'session_${timestamp}_$random';
  }

  int _nextId = 0;

  @override
  void dispose() {
    _disposed = true;
    for (final subscription in _streams.values) {
      unawaited(subscription.cancel());
    }
    _streams.clear();
    _runtimeHost?.detach();
    super.dispose();
  }
}
