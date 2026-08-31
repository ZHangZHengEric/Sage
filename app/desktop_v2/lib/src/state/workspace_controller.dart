import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:file_selector/file_selector.dart' as file_selector;
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/runtime_host.dart';
import '../api/v2_api.dart';
import '../models.dart';
import '../services/terminal_service.dart';
import '../usage_models.dart';

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
  final Map<String, StreamSubscription<Map<String, Object?>>> _treeStreams = {};
  final Map<String, Timer> _treeReconnectTimers = {};
  final Map<String, Set<String>> _preferredSkills = {};
  final Map<String, List<UploadedAttachment>> _attachments = {};
  final Map<String, List<ComposerReference>> _composerReferences = {};
  final Map<String, int> _reconnectAttempts = {};
  final Set<String> _recoveringStreams = {};
  final Random _sessionIdRandom = Random.secure();
  Timer? _workspaceRefreshTimer;
  Future<void> _agentPatchTail = Future<void>.value();
  int _agentPatchRevision = 0;
  int _usageOverviewRevision = 0;
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
  String selectedSubSessionId = '';
  bool loading = true;
  bool filesLoading = false;
  bool archivedConversationsLoaded = false;
  String? error;
  UsageOverview? usageOverview;
  bool usageOverviewLoading = false;
  String? usageOverviewError;
  late final TerminalService terminalService = TerminalService(_api);

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

  Conversation? get selectedDisplayConversation {
    final root = selectedConversation;
    if (root == null || selectedSubSessionId.isEmpty) return root;
    return root.subSessions
        .where((value) => value.sessionId == selectedSubSessionId)
        .firstOrNull;
  }

  bool get viewingSubSession => selectedSubSessionId.isNotEmpty;

  Set<String> get preferredSkills =>
      _preferredSkills.putIfAbsent(selectedConversationId, () => <String>{});

  List<UploadedAttachment> get attachments =>
      _attachments.putIfAbsent(selectedConversationId, () => []);

  List<ComposerReference> get composerReferences {
    final references = _composerReferences.putIfAbsent(
      selectedConversationId,
      () => <ComposerReference>[],
    );
    var hydratedAttachment = false;
    for (final attachment in attachments) {
      final alreadyRepresented = references.any(
        (reference) =>
            reference.path == attachment.path ||
            reference.path == attachment.virtualPath,
      );
      if (alreadyRepresented) continue;
      references.add(
        ComposerReference(
          fileName: attachment.name,
          path: attachment.virtualPath.isEmpty
              ? attachment.path
              : attachment.virtualPath,
          text: '',
          isDirectory: attachment.isDirectory,
        ),
      );
      hydratedAttachment = true;
    }
    if (hydratedAttachment) {
      scheduleMicrotask(() {
        if (!_disposed) notifyListeners();
      });
    }
    return references;
  }

  bool get canSend {
    final conversation = selectedConversation;
    if (loading ||
        viewingSubSession ||
        selectedAgentId.isEmpty ||
        conversation == null) {
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
      await _hydrateSessionTrees();
    } on Object catch (exception) {
      error = exception.toString();
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> loadUsageOverview({int days = 30}) async {
    final revision = ++_usageOverviewRevision;
    usageOverviewLoading = true;
    usageOverviewError = null;
    notifyListeners();
    try {
      final value = await _api.getUsageOverview(days: days);
      if (revision != _usageOverviewRevision) return;
      usageOverview = value;
    } on Object catch (exception) {
      if (revision != _usageOverviewRevision) return;
      usageOverviewError = exception.toString();
    } finally {
      if (revision == _usageOverviewRevision) {
        usageOverviewLoading = false;
        notifyListeners();
      }
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
    selectedSubSessionId = '';
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
    if (selectedGroupId == agentWorkspaceId &&
        selectedConversationId == id &&
        selectedSubSessionId.isEmpty) {
      return;
    }
    selectedGroupId = agentWorkspaceId;
    selectedConversationId = id;
    selectedSubSessionId = '';
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
    selectedSubSessionId = '';
    _adoptConversationAgent();
    selectedFile = null;
    selectedFileContent = null;
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  Future<void> selectConversation(String groupId, String id) async {
    final conversation = _visibleConversations(
      groupId,
    ).where((value) => value.id == id).firstOrNull;
    if (conversation == null) return;
    if (selectedGroupId == groupId &&
        selectedConversationId == id &&
        selectedSubSessionId.isEmpty) {
      return;
    }
    selectedGroupId = groupId;
    selectedConversationId = id;
    selectedSubSessionId = '';
    _adoptConversationAgent();
    selectedFile = null;
    selectedFileContent = null;
    notifyListeners();
    await Future.wait([refreshSkills(), refreshFiles()]);
  }

  void selectSubSession(String conversationId, String sessionId) {
    selectedConversationId = conversationId;
    selectedSubSessionId = sessionId;
    notifyListeners();
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
    var changed = false;
    if (!isWorkspaceNodeReferenced(node)) {
      _addWorkspaceNodeAttachment(node);
      changed = true;
    }
    final references = _composerReferences.putIfAbsent(
      selectedConversationId,
      () => [],
    );
    if (!references.any((reference) => reference.path == node.path)) {
      references.add(
        ComposerReference(
          fileName: node.name,
          path: node.path,
          text: '',
          isDirectory: node.isDirectory,
        ),
      );
      changed = true;
    }
    if (changed) notifyListeners();
  }

  void _addWorkspaceNodeAttachment(WorkspaceFileNode node) {
    attachments.add(
      UploadedAttachment(
        name: node.name,
        path: node.path,
        virtualPath: _workspaceVirtualPath(node.path),
        size: node.size,
        isDirectory: node.isDirectory,
      ),
    );
  }

  void referenceWorkspaceSelection(WorkspaceFileNode node, String selection) {
    final selectedText = selection.trim();
    if (selectedText.isEmpty || node.isDirectory) return;
    if (!isWorkspaceNodeReferenced(node)) {
      _addWorkspaceNodeAttachment(node);
    }
    final references = _composerReferences.putIfAbsent(
      selectedConversationId,
      () => [],
    );
    references
      ..removeWhere(
        (reference) =>
            (reference.path == node.path ||
                reference.path == _workspaceVirtualPath(node.path)) &&
            reference.text.isEmpty,
      )
      ..add(
        ComposerReference(
          fileName: node.name,
          path: node.path,
          text: selectedText,
        ),
      );
    notifyListeners();
  }

  void removeComposerReference(ComposerReference value) {
    final references = _composerReferences.putIfAbsent(
      selectedConversationId,
      () => <ComposerReference>[],
    );
    references.remove(value);
    final sameSourceRemains = references.any(
      (reference) => reference.path == value.path,
    );
    if (!sameSourceRemains) {
      attachments.removeWhere(
        (attachment) =>
            attachment.path == value.path ||
            attachment.virtualPath == value.path,
      );
    }
    notifyListeners();
  }

  void clearComposerReferences(String conversationId) {
    if (_composerReferences.remove(conversationId) != null) {
      notifyListeners();
    }
  }

  String _workspaceVirtualPath(String path) {
    final normalized = path
        .replaceAll('\\', '/')
        .split('/')
        .where((part) => part.isNotEmpty && part != '.')
        .join('/');
    String? configured;
    for (final component in components) {
      if (component.id != 'execution.sandbox') continue;
      final useHostPath =
          component.activeConfig['workspace_path_mode'] == 'host';
      final value = useHostPath
          ? (selectedGroup.project?.path ?? settings.agentWorkspacePath)
          : component.activeConfig['workspace_root']?.toString();
      if (value != null && value.startsWith('/') && value != '/') {
        configured = value.replaceAll('\\', '/');
      }
      break;
    }
    final workspaceRoot = (configured ?? '/workspace').replaceFirst(
      RegExp(r'/+$'),
      '',
    );
    return '$workspaceRoot/$normalized';
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
      _composerReferences
          .putIfAbsent(selectedConversationId, () => [])
          .add(
            ComposerReference(
              fileName: uploaded.name,
              path: uploaded.virtualPath.isEmpty
                  ? uploaded.path
                  : uploaded.virtualPath,
              text: '',
              isDirectory: uploaded.isDirectory,
            ),
          );
      await refreshFiles();
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
    }
  }

  void removeAttachment(UploadedAttachment value) {
    attachments.remove(value);
    composerReferences.removeWhere(
      (reference) =>
          reference.path == value.path || reference.path == value.virtualPath,
    );
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

  Future<void> removeProject(String projectId) async {
    final project = settings.projects
        .where((value) => value.id == projectId)
        .firstOrNull;
    if (project == null) return;
    try {
      await _api.removeProject(project.id);
      settings = settings.copyWith(
        projects: settings.projects
            .where((value) => value.id != project.id)
            .toList(),
      );
      if (selectedGroupId == project.id) {
        selectedGroupId = agentWorkspaceId;
        if (_visibleConversations(selectedGroupId).isEmpty) {
          createConversation(notify: false);
        }
        selectedConversationId = _visibleConversations(
          selectedGroupId,
        ).first.id;
        selectedSubSessionId = '';
        _adoptConversationAgent();
        selectedFile = null;
        selectedFileContent = null;
        await refreshFiles();
      }
    } on Object catch (exception) {
      error = exception.toString();
    }
    notifyListeners();
  }

  Future<void> removeSelectedProject() async {
    final project = selectedGroup.project;
    if (project == null) return;
    await removeProject(project.id);
  }

  Future<void> saveSettings(DesktopSettings value) async {
    try {
      final languageChanged = settings.language != value.language;
      final workspaceChanged =
          settings.agentWorkspacePath != value.agentWorkspacePath;
      final componentConfigurationChanged =
          !mapEquals(settings.componentSelections, value.componentSelections) ||
          jsonEncode(settings.componentConfigs) !=
              jsonEncode(value.componentConfigs);
      settings = await _api.saveSettings(value);
      if (languageChanged) {
        _syncToolCatalogLanguage();
        toolCatalog = await _api.listTools();
      }
      if (componentConfigurationChanged) {
        components = await _api.listComponents();
      }
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
      _syncToolCatalogLanguage();
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

  void _syncToolCatalogLanguage() {
    final configured = settings.language;
    _api.toolCatalogLanguage = configured == 'system'
        ? PlatformDispatcher.instance.locale.languageCode
        : configured;
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

  Future<void> deleteSkill(String skillName) async {
    try {
      await _api.deleteSkill(skillName);
      skillCatalog = await _api.listSkillCatalog();
      final configuredAgent = agentConfiguration;
      if (configuredAgent != null) {
        agentConfiguration = await _api.getAgentConfiguration(
          configuredAgent.id,
        );
      }
      if (selectedAgentId.isNotEmpty) {
        skills = await _api.listSkills(selectedAgentId);
      }
      notifyListeners();
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

  Future<void> patchAgentConfiguration(Map<String, Object?> patch) {
    final current = agentConfiguration;
    if (current == null) return Future<void>.value();
    final revision = ++_agentPatchRevision;
    final optimistic = current.applyPatch(patch);
    agentConfiguration = optimistic;
    _updateAgentSummary(optimistic);
    notifyListeners();
    final previous = _agentPatchTail;
    final operation = _sendAgentPatch(
      previous: previous,
      agentId: current.id,
      patch: Map<String, Object?>.from(patch),
      rollback: current,
      revision: revision,
    );
    _agentPatchTail = operation;
    return operation;
  }

  Future<void> _sendAgentPatch({
    required Future<void> previous,
    required String agentId,
    required Map<String, Object?> patch,
    required AgentConfiguration rollback,
    required int revision,
  }) async {
    try {
      await previous;
    } on Object {
      // A later optimistic patch still needs a chance to converge the server.
    }
    try {
      final saved = await _api.patchAgentConfiguration(agentId, patch);
      if (agentConfiguration?.id == agentId &&
          revision == _agentPatchRevision) {
        agentConfiguration = saved;
        _updateAgentSummary(saved);
      }
      notifyListeners();
    } on Object catch (exception) {
      if (agentConfiguration?.id == agentId &&
          revision == _agentPatchRevision) {
        agentConfiguration = rollback;
        _updateAgentSummary(rollback);
      }
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  void _updateAgentSummary(AgentConfiguration configuration) {
    agents = [
      for (final agent in agents)
        agent.id == configuration.id
            ? AgentSummary(
                id: agent.id,
                name: configuration.name,
                isDefault: agent.isDefault,
              )
            : agent,
    ];
  }

  Future<AgentConfiguration> createAgent(String name) async {
    try {
      final created = await _api.createAgent(name);
      agents = [...agents, AgentSummary(id: created.id, name: created.name)];
      agentConfiguration = created;
      notifyListeners();
      return created;
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

  bool canManageConversation(Conversation conversation) =>
      !_treeHasActiveRun(conversation);

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
    var authoritativeSessionMissing = false;
    try {
      await _refreshConversationTree(conversation);
    } on SageApiException catch (exception) {
      // A stale local row remains deletable when the authoritative Session has
      // already disappeared. Any other reconciliation failure is actionable.
      if (exception.statusCode != 404) {
        error = exception.toString();
        notifyListeners();
        return;
      }
      authoritativeSessionMissing = true;
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      return;
    }
    if (!authoritativeSessionMissing && !canManageConversation(conversation)) {
      error = '运行中的会话不能删除';
      notifyListeners();
      return;
    }
    try {
      final sessionId = conversation.sessionId;
      if (sessionId != null && sessionId.isNotEmpty) {
        await _api.deleteSession(sessionId);
      }
      await _streams.remove(conversation.id)?.cancel();
      final treeSubscription = _treeStreams.remove(conversation.id);
      if (treeSubscription != null) {
        unawaited(treeSubscription.cancel());
      }
      _treeReconnectTimers.remove(conversation.id)?.cancel();
      _recoveringStreams.remove(conversation.id);
      _reconnectAttempts.remove(conversation.id);
      _preferredSkills.remove(conversation.id);
      _attachments.remove(conversation.id);
      _composerReferences.remove(conversation.id);
      _conversations[groupId]?.removeWhere(
        (value) => value.id == conversationId,
      );
      _archivedConversationCache[groupId]?.removeWhere(
        (value) => value.id == conversationId,
      );
      _selectReplacementAfterRemoval(groupId, conversationId);
      _persist();
      notifyListeners();
    } on SageApiException catch (exception) {
      if (exception.code == 'session.active_run') {
        try {
          await _refreshConversationTree(conversation);
        } on Object {
          // Preserve the typed deletion conflict if reconciliation also fails.
        }
        error = '运行中的会话不能删除';
        notifyListeners();
        return;
      }
      error = exception.toString();
      notifyListeners();
      rethrow;
    } on Object catch (exception) {
      error = exception.toString();
      notifyListeners();
      rethrow;
    }
  }

  Future<void> _refreshConversationTree(Conversation conversation) async {
    if (conversation.runId.isNotEmpty) {
      await _refreshConversationSnapshot(conversation);
    }
    final sessionId = conversation.sessionId;
    if (sessionId == null || sessionId.isEmpty) return;
    final nodes = await _api.getSessionTree(sessionId);
    final authoritativeSessionIds = <String>{};
    for (final node in nodes) {
      final rawSession = node['session'];
      if (rawSession is Map) {
        final childSessionId = rawSession['session_id']?.toString() ?? '';
        if (childSessionId.isNotEmpty) {
          authoritativeSessionIds.add(childSessionId);
        }
      }
      _upsertSubSession(conversation, node);
    }
    conversation.subSessions.removeWhere(
      (value) =>
          (value.sessionId ?? '').isNotEmpty &&
          !authoritativeSessionIds.contains(value.sessionId),
    );
    notifyListeners();
    _persist();
  }

  bool _treeHasActiveRun(Conversation root) =>
      _isControllable(root.status) ||
      root.subSessions.any((value) => _isControllable(value.status));

  bool _isControllable(RunStatus status) => {
    RunStatus.starting,
    RunStatus.running,
    RunStatus.suspending,
    RunStatus.suspended,
  }.contains(status);

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
    selectedSubSessionId = '';
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

  Future<void> setDefaultModelProvider(String providerId) async {
    try {
      final updated = await _api.patchModelProvider(providerId, const {
        'is_default': true,
      });
      modelProviders = [
        for (final value in modelProviders)
          value.id == providerId
              ? updated.copyWith(isDefault: true)
              : value.copyWith(isDefault: false),
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

  Future<void> selectComponent(
    String componentId,
    String pluginId, {
    Map<String, Object?> config = const {},
  }) async {
    try {
      await _api.selectComponent(componentId, pluginId, config: config);
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
    if (conversation == null ||
        viewingSubSession ||
        prompt.isEmpty ||
        selectedAgentId.isEmpty) {
      return;
    }
    if (conversation.status == RunStatus.running ||
        conversation.status == RunStatus.starting ||
        conversation.status == RunStatus.suspending) {
      _attachments[conversation.id] = [];
      notifyListeners();
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
    conversation.thinking = false;
    conversation.pendingInteraction = null;
    final selectedAttachments = List<UploadedAttachment>.of(attachments);
    _attachments[conversation.id] = [];
    notifyListeners();
    _persist();
    final body = <String, Object?>{
      'agent_id': selectedAgentId,
      'response_language': settings.language == 'system'
          ? PlatformDispatcher.instance.locale.languageCode
          : settings.language,
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
      'invocation_mode': conversation.invocationMode.wireValue,
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

  void setInvocationMode(InvocationMode mode) {
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
    conversation.invocationMode = mode;
    notifyListeners();
    _persist();
  }

  Future<void> pause() async {
    final value = selectedDisplayConversation;
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
    final value = selectedDisplayConversation;
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
    final value = selectedDisplayConversation;
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

  Future<void> replyInteraction(
    String decision, {
    String text = '',
    Map<String, Object?> payload = const {},
  }) => _replyInteractionFor(
    selectedConversation,
    decision,
    text: text,
    payload: payload,
  );

  Future<void> replyDisplayInteraction(
    String decision, {
    String text = '',
    Map<String, Object?> payload = const {},
  }) => _replyInteractionFor(
    selectedDisplayConversation,
    decision,
    text: text,
    payload: payload,
  );

  Future<void> _replyInteractionFor(
    Conversation? value,
    String decision, {
    String text = '',
    Map<String, Object?> payload = const {},
  }) async {
    final interaction = value?.pendingInteraction;
    if (value == null || interaction == null) return;
    final approvingPlan =
        interaction.payload['tool_name']?.toString() == 'goal_submit' &&
        {'approve', 'approve_once', 'approve_and_remember'}.contains(decision);
    try {
      await _api.replyInteraction(
        value.runId,
        interactionId: interaction.id,
        decision: decision,
        payload: {...payload, if (text.trim().isNotEmpty) 'text': text.trim()},
      );
      final interactionAgentId = value.agentId.isNotEmpty
          ? value.agentId
          : selectedAgentId;
      if (decision == 'approve_and_remember' &&
          interactionAgentId.isNotEmpty &&
          agentConfiguration?.id == interactionAgentId) {
        try {
          agentConfiguration = await _api.getAgentConfiguration(
            interactionAgentId,
          );
        } on Object {
          // The approval has already succeeded; refresh lazily in settings.
        }
      }
      if (approvingPlan) value.invocationMode = InvocationMode.goal;
      value.pendingInteraction = null;
      value.status = RunStatus.running;
      notifyListeners();
      _persist();
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
        conversation.thinking = false;
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
      if (conversation.runId.isNotEmpty) {
        _activeProcessPanel(conversation).runId = conversation.runId;
      }
      conversation.status = RunStatus.starting;
      _subscribeSessionTree(conversation);
      notifyListeners();
      _persist();
      return;
    }
    final type = event['type']?.toString() ?? '';
    final sequence = (event['run_sequence'] as num?)?.toInt() ?? 0;
    final occurredAt = DateTime.tryParse(
      event['occurred_at']?.toString() ?? '',
    );
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
    if (type == 'reasoning.started' || type == 'reasoning.delta') {
      conversation.thinking = true;
    } else if (type == 'reasoning.completed' ||
        type == 'message.delta' ||
        type == 'message.completed' ||
        type.startsWith('tool.') ||
        type == 'interaction.requested' ||
        type == 'run.suspend_requested' ||
        type == 'run.suspended' ||
        type == 'run.completed' ||
        type == 'run.cancelled' ||
        type == 'run.failed') {
      conversation.thinking = false;
    }
    if (type == 'message.delta') {
      _appendDelta(conversation, event, eventData['delta']);
    } else if (type == 'message.completed') {
      _completeMessage(conversation, eventData, sequence: sequence);
    } else if (type == 'item.completed') {
      _trackToolResult(conversation, eventData);
    } else if (type == 'turn.started') {
      conversation.status = RunStatus.running;
    } else if (type == 'interaction.requested') {
      conversation.pendingInteraction = PendingInteraction.fromJson(eventData);
    } else if (type == 'run.suspend_requested') {
      conversation.status = RunStatus.suspending;
    } else if (type == 'run.suspended') {
      conversation.status = RunStatus.suspended;
      if (conversation.pendingInteraction == null) {
        unawaited(_hydrateInteraction(conversation));
      }
    } else if (type == 'run.resumed') {
      conversation.status = RunStatus.running;
      conversation.pendingInteraction = null;
    } else if (type == 'run.completed') {
      _applyTerminalState(
        conversation,
        RunStatus.completed,
        promoteFinal: true,
        completedAt: occurredAt,
      );
    } else if (type == 'run.cancelled') {
      _applyTerminalState(
        conversation,
        RunStatus.cancelled,
        completedAt: occurredAt,
      );
    } else if (type == 'run.failed') {
      _applyTerminalState(
        conversation,
        RunStatus.failed,
        completedAt: occurredAt,
      );
      final rawError = eventData['error'];
      if (rawError is Map) error = rawError['message']?.toString();
    }
    if (_shouldRefreshWorkspace(type)) {
      _scheduleWorkspaceRefresh(conversation);
    }
    _trackActivity(
      conversation,
      type,
      eventData,
      sequence: sequence,
      occurredAt: occurredAt,
    );
    notifyListeners();
    _persist();
  }

  bool _shouldRefreshWorkspace(String eventType) =>
      eventType == 'tool.call.succeeded' ||
      eventType == 'tool.call.failed' ||
      eventType == 'tool.call.cancelled' ||
      eventType == 'run.completed' ||
      eventType == 'run.failed' ||
      eventType == 'run.cancelled';

  void _scheduleWorkspaceRefresh(Conversation conversation) {
    if (selectedConversationId != conversation.id) return;
    _workspaceRefreshTimer?.cancel();
    _workspaceRefreshTimer = Timer(const Duration(milliseconds: 120), () {
      if (_disposed || selectedConversationId != conversation.id) return;
      unawaited(refreshFiles());
    });
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
    DateTime? occurredAt,
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
          startedAt: occurredAt,
          completedAt: terminal ? occurredAt ?? DateTime.now() : null,
        ),
      );
      return;
    }
    existing.active = !terminal;
    existing.failed = type.endsWith('.failed');
    if (arguments.isNotEmpty) existing.arguments = arguments;
    if (terminal) existing.completedAt = occurredAt ?? DateTime.now();
  }

  RuntimeProcessPanel _activeProcessPanel(Conversation conversation) {
    final running = conversation.processPanels
        .where((value) => value.running)
        .lastOrNull;
    if (running != null) return running;
    final sameRun = conversation.processPanels
        .where(
          (value) =>
              conversation.runId.isNotEmpty &&
              value.runId == conversation.runId,
        )
        .lastOrNull;
    if (sameRun != null) return sameRun;
    final anchor = conversation.messages
        .where((value) => value.role == 'user')
        .lastOrNull;
    final panel = RuntimeProcessPanel(
      id: _id('process'),
      anchorMessageId: anchor?.id ?? '',
      startedAt: DateTime.now(),
      runId: conversation.runId,
    );
    conversation.processPanels.add(panel);
    return panel;
  }

  void _finishProcessPanel(
    Conversation conversation, {
    bool promoteFinal = false,
    DateTime? completedAt,
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
    panel.completedAt = completedAt ?? DateTime.now();
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
    DateTime? completedAt;
    if (rawRun is Map) {
      nextStatus = runStatusFromWire(rawRun['state']?.toString());
      completedAt = DateTime.tryParse(rawRun['updated_at']?.toString() ?? '');
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
          completedAt: completedAt,
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
    DateTime? completedAt,
  }) {
    conversation.status = status;
    conversation.thinking = false;
    conversation.pendingInteraction = null;
    _finishStreamingMessages(conversation);
    _finishProcessPanel(
      conversation,
      promoteFinal: promoteFinal,
      completedAt: completedAt,
    );
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

  Future<void> _hydrateSessionTrees() async {
    var hydratedAnyNodes = false;
    for (final values in _conversations.values) {
      for (final conversation in values) {
        if (conversation.archived || (conversation.sessionId ?? '').isEmpty) {
          continue;
        }
        try {
          final nodes = await _api.getSessionTree(conversation.sessionId!);
          hydratedAnyNodes = hydratedAnyNodes || nodes.isNotEmpty;
          for (final node in nodes) {
            _upsertSubSession(conversation, node);
          }
          // Completed history only needs the one-shot snapshot above. Opening
          // a follow stream for every old conversation adds avoidable startup
          // work and briefly retains an HTTP stream even though the backend
          // will close it immediately. Active roots or children still receive
          // the live tree stream and its reconnect protection.
          if (_treeHasActiveRun(conversation)) {
            _subscribeSessionTree(conversation);
          }
        } on Object {
          // A stale local conversation must not block Desktop startup.
        }
      }
    }
    // Avoid serializing the entire local conversation cache on every startup
    // when hydration did not discover anything new.
    if (hydratedAnyNodes) _persist();
  }

  void _subscribeSessionTree(Conversation root) {
    final sessionId = root.sessionId;
    if (sessionId == null ||
        sessionId.isEmpty ||
        !_treeHasActiveRun(root) ||
        _treeStreams.containsKey(root.id)) {
      return;
    }
    _treeReconnectTimers.remove(root.id)?.cancel();
    late final StreamSubscription<Map<String, Object?>> subscription;
    subscription = _api
        .subscribeSessionTree(sessionId)
        .listen(
          (value) => _applySessionTreeEnvelope(root, value),
          onError: (Object _, StackTrace _) {
            if (identical(_treeStreams[root.id], subscription)) {
              _treeStreams.remove(root.id);
            }
            _scheduleSessionTreeReconnect(root);
          },
          onDone: () {
            if (identical(_treeStreams[root.id], subscription)) {
              _treeStreams.remove(root.id);
            }
            // A normal HTTP stream close is still premature while the root or
            // one of its children is active. Reconnect just as we do for an
            // error so a transient/proxy close cannot hide later child
            // Sessions and their message events from the conversation flow.
            _scheduleSessionTreeReconnect(root);
          },
          cancelOnError: true,
        );
    _treeStreams[root.id] = subscription;
  }

  void _scheduleSessionTreeReconnect(Conversation root) {
    if (_disposed || !_treeHasActiveRun(root)) return;
    _treeReconnectTimers.putIfAbsent(
      root.id,
      () => Timer(const Duration(seconds: 1), () {
        _treeReconnectTimers.remove(root.id);
        if (!_disposed && _treeHasActiveRun(root)) {
          _subscribeSessionTree(root);
        }
      }),
    );
  }

  void _applySessionTreeEnvelope(
    Conversation root,
    Map<String, Object?> envelope,
  ) {
    final kind = envelope['kind']?.toString();
    if (kind == 'session.discovered') {
      _upsertSubSession(root, envelope);
    } else if (kind == 'session.event') {
      final sessionId = envelope['session_id']?.toString() ?? '';
      final child = root.subSessions
          .where((value) => value.sessionId == sessionId)
          .firstOrNull;
      final rawEvent = envelope['event'];
      if (child != null && rawEvent is Map) {
        _applyEvent(child, rawEvent.cast<String, Object?>());
      }
    }
    notifyListeners();
    _persist();
  }

  Conversation? _upsertSubSession(
    Conversation root,
    Map<String, Object?> node,
  ) {
    final rawSession = node['session'];
    final rawRun = node['run'];
    if (rawSession is! Map || rawRun is! Map) return null;
    final session = rawSession.cast<String, Object?>();
    final run = rawRun.cast<String, Object?>();
    final sessionId = session['session_id']?.toString() ?? '';
    if (sessionId.isEmpty) return null;
    var child = root.subSessions
        .where((value) => value.sessionId == sessionId)
        .firstOrNull;
    final taskName = node['task_name']?.toString().trim() ?? '';
    final task = node['task']?.toString().trim() ?? '';
    final originalTask = node['original_task']?.toString().trim() ?? '';
    final prompt = task.isNotEmpty ? task : originalTask;
    final runId = run['run_id']?.toString() ?? '';
    final nextStatus = runStatusFromWire(run['state']?.toString());
    final parentToolCallId =
        node['parent_tool_call_id']?.toString().trim() ?? '';
    if (child == null) {
      child = Conversation(
        id: 'sub-session:$sessionId',
        title: taskName.isEmpty ? '子任务' : taskName,
        agentId: node['agent_id']?.toString() ?? '',
        sessionId: sessionId,
        parentSessionId: session['parent_session_id']?.toString(),
        parentRunId: node['parent_run_id']?.toString(),
        parentToolCallId: parentToolCallId.isEmpty ? null : parentToolCallId,
        runId: runId,
        status: nextStatus,
        createdAt: DateTime.tryParse(session['created_at']?.toString() ?? ''),
      );
      root.subSessions.add(child);
      root.subSessions.sort(
        (left, right) => left.createdAt.compareTo(right.createdAt),
      );
    } else {
      if (taskName.isNotEmpty) child.title = taskName;
      child.agentId = node['agent_id']?.toString() ?? child.agentId;
      child.parentSessionId =
          session['parent_session_id']?.toString() ?? child.parentSessionId;
      child.parentRunId =
          node['parent_run_id']?.toString() ?? child.parentRunId;
      if (parentToolCallId.isNotEmpty) {
        child.parentToolCallId = parentToolCallId;
      }
      if (runId.isNotEmpty && runId != child.runId) {
        child.runId = runId;
        child.runSequence = 0;
      }
    }
    _syncSubSessionRunPresentation(
      child,
      run,
      prompt: prompt,
      status: nextStatus,
    );
    if (_isTerminal(nextStatus)) {
      _applyTerminalState(
        child,
        nextStatus,
        promoteFinal: nextStatus == RunStatus.completed,
        completedAt: DateTime.tryParse(run['updated_at']?.toString() ?? ''),
      );
    } else {
      child.status = nextStatus;
    }
    return child;
  }

  void _syncSubSessionRunPresentation(
    Conversation child,
    Map<String, Object?> run, {
    required String prompt,
    required RunStatus status,
  }) {
    final runId = run['run_id']?.toString() ?? child.runId;
    if (runId.isEmpty) return;
    final promptId = 'sub-task:${child.sessionId}:$runId';
    if (prompt.isNotEmpty &&
        !child.messages.any((message) => message.id == promptId)) {
      child.messages.add(
        ChatMessage(
          id: promptId,
          role: 'user',
          text: prompt,
          createdAt: DateTime.tryParse(run['created_at']?.toString() ?? ''),
        ),
      );
    }
    final startedAt =
        DateTime.tryParse(run['created_at']?.toString() ?? '') ??
        child.createdAt;
    final completedAt = DateTime.tryParse(run['updated_at']?.toString() ?? '');
    final terminal = _isTerminal(status);
    var panel = child.processPanels
        .where((value) => value.runId == runId)
        .firstOrNull;
    if (panel == null) {
      panel = RuntimeProcessPanel(
        id: 'sub-process:$runId',
        anchorMessageId: promptId,
        runId: runId,
        startedAt: startedAt,
        completedAt: terminal ? completedAt : null,
        running: !terminal,
      );
      child.processPanels.add(panel);
    } else {
      panel.startedAt = startedAt;
      panel.running = !terminal;
      panel.completedAt = terminal ? completedAt : null;
    }
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
    _workspaceRefreshTimer?.cancel();
    for (final subscription in _streams.values) {
      unawaited(subscription.cancel());
    }
    _streams.clear();
    for (final subscription in _treeStreams.values) {
      unawaited(subscription.cancel());
    }
    _treeStreams.clear();
    for (final timer in _treeReconnectTimers.values) {
      timer.cancel();
    }
    _treeReconnectTimers.clear();
    _runtimeHost?.detach();
    super.dispose();
  }
}
