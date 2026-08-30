import 'dart:async';
import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import '../models.dart';
import '../localization/app_localizations.dart';
import '../state/workspace_controller.dart';
import 'shared/desktop_shell.dart';
import 'usage_overview.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    required this.controller,
    required this.themeMode,
    required this.onThemeModeChanged,
    required this.language,
    required this.onLanguageChanged,
    required this.railFraction,
    required this.onClose,
    super.key,
  });

  final WorkspaceController controller;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final String language;
  final ValueChanged<String> onLanguageChanged;
  final double railFraction;
  final VoidCallback onClose;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  int _section = 0;
  bool _editingAgent = false;
  bool _saving = false;
  String? _deletingAgentId;
  String _settingsAgentId = '';
  String _syncedAgentId = '';
  Timer? _debounce;
  Timer? _workspaceDebounce;
  Timer? _sandboxDebounce;
  String? _workspaceError;
  String? _sandboxRootError;
  late DesktopSettings _draft = widget.controller.settings;
  final _name = TextEditingController();
  final _description = TextEditingController();
  final _systemPrefix = TextEditingController();
  final _systemContext = TextEditingController();
  final _maxLoopCount = TextEditingController();
  late final TextEditingController _previewBytes = TextEditingController(
    text: _draft.maxPreviewBytes.toString(),
  );
  late final TextEditingController _treeEntries = TextEditingController(
    text: _draft.maxTreeEntries.toString(),
  );
  late final TextEditingController _workspacePath = TextEditingController(
    text: _draft.agentWorkspacePath,
  );
  late final TextEditingController _sandboxRoot = TextEditingController(
    text:
        _draft.componentConfigs['execution.sandbox']?['workspace_root']
            ?.toString() ??
        '/workspace',
  );

  @override
  void initState() {
    super.initState();
    _settingsAgentId = widget.controller.selectedAgentId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      widget.controller.loadSettingsCatalog(agentId: _settingsAgentId);
      widget.controller.loadUsageOverview();
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _workspaceDebounce?.cancel();
    _sandboxDebounce?.cancel();
    _name.dispose();
    _description.dispose();
    _systemPrefix.dispose();
    _systemContext.dispose();
    _maxLoopCount.dispose();
    _previewBytes.dispose();
    _treeEntries.dispose();
    _workspacePath.dispose();
    _sandboxRoot.dispose();
    super.dispose();
  }

  void _syncAgentControllers(AgentConfiguration value) {
    if (_syncedAgentId == value.id) return;
    _syncedAgentId = value.id;
    _name.text = value.name;
    _description.text = value.description;
    _systemPrefix.text = value.systemPrefix;
    _systemContext.text = const JsonEncoder.withIndent(
      '  ',
    ).convert(value.runtimeVariables);
    _maxLoopCount.text = value.maxLoopCount.toString();
  }

  Future<void> _saveDesktopSettings(DesktopSettings next) async {
    setState(() {
      _draft = next;
      _saving = true;
    });
    try {
      await widget.controller.saveSettings(next);
      if (mounted) setState(() => _draft = widget.controller.settings);
    } catch (_) {
      if (mounted) setState(() => _draft = widget.controller.settings);
      rethrow;
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _saveThemeMode(ThemeMode value) async {
    final previous = widget.themeMode;
    widget.onThemeModeChanged(value);
    try {
      await _saveDesktopSettings(_draft.copyWith(themeMode: value.name));
    } on Object {
      if (mounted) widget.onThemeModeChanged(previous);
    }
  }

  Future<void> _saveLanguage(String value) async {
    final previous = widget.language;
    widget.onLanguageChanged(value);
    try {
      await _saveDesktopSettings(_draft.copyWith(language: value));
    } on Object {
      if (mounted) widget.onLanguageChanged(previous);
    }
  }

  void _saveWorkspaceLater() {
    _workspaceDebounce?.cancel();
    if (_workspaceError != null) {
      setState(() => _workspaceError = null);
    }
    _workspaceDebounce = Timer(const Duration(milliseconds: 700), () {
      if (_workspacePath.text.trim().isEmpty) {
        if (mounted) {
          setState(
            () => _workspaceError = context.l10n.text('settings.pathRequired'),
          );
        }
        return;
      }
      _saveWorkspacePath(_workspacePath.text);
    });
  }

  Future<void> _saveWorkspacePath(String path) async {
    try {
      await _saveDesktopSettings(
        _draft.copyWith(agentWorkspacePath: path.trim()),
      );
      if (mounted) {
        setState(() => _workspaceError = null);
      }
    } on Object {
      if (mounted) {
        setState(
          () => _workspaceError = context.l10n.text('settings.pathUnavailable'),
        );
      }
    }
  }

  Future<void> _chooseWorkspacePath() async {
    final path = await widget.controller.chooseAgentWorkspace(
      confirmButtonText: context.l10n.text('settings.chooseDirectory'),
    );
    if (path == null || path.isEmpty || !mounted) return;
    _workspaceDebounce?.cancel();
    _workspacePath.text = path;
    await _saveWorkspacePath(path);
  }

  void _saveRuntimeLater() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 650), () {
      final preview = int.tryParse(_previewBytes.text.trim());
      final entries = int.tryParse(_treeEntries.text.trim());
      if (preview == null || preview < 1 || entries == null || entries < 100) {
        return;
      }
      _saveDesktopSettings(
        _draft.copyWith(maxPreviewBytes: preview, maxTreeEntries: entries),
      );
    });
  }

  Map<String, Object?> get _sandboxConfig => {
    'workspace_root': '/workspace',
    'workspace_path_mode': 'virtual',
    'workspace_mapping': 'active_workspace',
    'filesystem_mode': 'workspace',
    ...?_draft.componentConfigs['execution.sandbox'],
  };

  bool get _sandboxMapsWorkspace =>
      _sandboxConfig['workspace_mapping'] != 'isolated' &&
      _draft.componentSelections['execution.sandbox'] !=
          'sage.sandbox.ephemeral';

  bool get _sandboxUsesHostPath =>
      _sandboxMapsWorkspace && _sandboxConfig['workspace_path_mode'] == 'host';

  Future<void> _saveSandbox({
    bool? mapWorkspace,
    bool? useHostPath,
    String? workspaceRoot,
  }) async {
    final mapped = mapWorkspace ?? _sandboxMapsWorkspace;
    final hostPath = mapped && (useHostPath ?? _sandboxUsesHostPath);
    final selections = Map<String, String>.from(_draft.componentSelections);
    selections['execution.sandbox'] = mapped
        ? 'sage.sandbox.local-workspace'
        : 'sage.sandbox.ephemeral';
    final configs = {
      for (final entry in _draft.componentConfigs.entries)
        entry.key: Map<String, Object?>.from(entry.value),
    };
    configs['execution.sandbox'] = {
      ..._sandboxConfig,
      'workspace_root': workspaceRoot ?? _sandboxRoot.text.trim(),
      'workspace_path_mode': hostPath ? 'host' : 'virtual',
      'workspace_mapping': mapped ? 'active_workspace' : 'isolated',
      'filesystem_mode': 'workspace',
    };
    await _saveDesktopSettings(
      _draft.copyWith(
        componentSelections: selections,
        componentConfigs: configs,
      ),
    );
  }

  void _saveSandboxRootLater() {
    _sandboxDebounce?.cancel();
    final value = _sandboxRoot.text.trim().replaceAll('\\', '/');
    final invalid =
        !value.startsWith('/') ||
        value == '/' ||
        value.split('/').contains('..');
    setState(() {
      _sandboxRootError = invalid
          ? (context.l10n.languageCode == 'zh'
                ? '请输入受限的绝对虚拟路径，例如 /workspace'
                : 'Enter a contained absolute virtual path, such as /workspace')
          : null;
    });
    if (invalid) return;
    _sandboxDebounce = Timer(
      const Duration(milliseconds: 650),
      () => _saveSandbox(workspaceRoot: value),
    );
  }

  Future<void> _saveAgent(Map<String, Object?> patch) async {
    setState(() => _saving = true);
    try {
      await widget.controller.patchAgentConfiguration(patch);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _toggleAgentEditing() async {
    if (!_editingAgent) {
      setState(() => _editingAgent = true);
      return;
    }
    _debounce?.cancel();
    Object? decodedContext;
    try {
      decodedContext = jsonDecode(_systemContext.text);
    } on FormatException {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              context.l10n.text('settings.systemContextInvalidJson'),
            ),
          ),
        );
      }
      return;
    }
    if (decodedContext is! Map) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(context.l10n.text('settings.systemContextMustMap')),
          ),
        );
      }
      return;
    }
    try {
      await _saveAgent({
        'name': _name.text,
        'description': _description.text,
        'system_prefix': _systemPrefix.text,
        'runtime_variables': decodedContext.cast<String, Object?>(),
      });
      if (mounted) setState(() => _editingAgent = false);
    } on Object {
      // WorkspaceController exposes the backend error in the shared banner.
    }
  }

  Future<void> _deleteAgent(String agentId) async {
    AgentSummary? agent;
    for (final value in widget.controller.agents) {
      if (value.id == agentId) {
        agent = value;
        break;
      }
    }
    if (agent == null || _deletingAgentId != null) return;
    final target = agent;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          context.l10n.text('settings.deleteNamed', {'name': target.name}),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(context.l10n.text('common.cancel')),
          ),
          FilledButton(
            key: const ValueKey('settings-agent-delete-confirm'),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(context.l10n.text('common.delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deletingAgentId = agentId);
    try {
      final replacementId = await widget.controller.deleteAgent(agentId);
      if (!mounted) return;
      setState(() {
        _settingsAgentId = replacementId;
        _syncedAgentId = '';
        _editingAgent = false;
      });
    } on Object {
      // WorkspaceController exposes the backend error in the shared banner.
    } finally {
      if (mounted) setState(() => _deletingAgentId = null);
    }
  }

  Future<void> _createAgent() async {
    setState(() => _saving = true);
    try {
      final created = await widget.controller.createAgent(
        context.l10n.text('settings.newAgent'),
      );
      if (!mounted) return;
      setState(() {
        _settingsAgentId = created.id;
        _syncedAgentId = '';
        _editingAgent = true;
      });
    } on Object {
      // WorkspaceController exposes the backend error in the shared banner.
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _saveAgentTextLater(String field, TextEditingController controller) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 650), () {
      if (field == 'runtime_variables' || field == 'system_context') {
        try {
          final value = jsonDecode(controller.text);
          if (value is Map) {
            _saveAgent({field: value.cast<String, Object?>()});
          }
        } on FormatException {
          return;
        }
        return;
      }
      _saveAgent({field: controller.text});
    });
  }

  Widget _content() {
    final controller = widget.controller;
    final agent = controller.agentConfiguration;
    if (agent != null) _syncAgentControllers(agent);
    return switch (_section) {
      0 => UsageOverviewSettings(controller: widget.controller),
      1 => _general(),
      2 => _agents(agent),
      3 => _models(),
      4 => _tools(),
      5 => _skills(),
      6 => _mcp(),
      7 => _components(),
      8 => _sandbox(),
      9 => _security(),
      _ => _archived(),
    };
  }

  Widget _archived() =>
      _ArchivedConversationSettings(controller: widget.controller);

  Widget _sandbox() {
    final mapped = _sandboxMapsWorkspace;
    final useHostPath = _sandboxUsesHostPath;
    return _SettingsContent(
      title: context.l10n.languageCode == 'zh' ? '沙箱' : 'Sandbox',
      status: _saving,
      children: [
        GlassCard(
          key: const ValueKey('settings-sandbox-configuration'),
          padding: EdgeInsets.zero,
          shape: const LiquidRoundedSuperellipse(borderRadius: 16),
          useOwnLayer: true,
          settings: _glass(context),
          child: _SettingsRowGroup(
            children: [
              _SettingsRow(
                label: context.l10n.languageCode == 'zh'
                    ? '工作区访问'
                    : 'Workspace access',
                description: context.l10n.languageCode == 'zh'
                    ? '选择 Run 使用真实工作区，或使用与真实文件完全隔离的临时空白沙箱。空白沙箱看不到项目文件，产生的文件也不会写回项目。'
                    : 'Choose whether a run uses the real workspace or a temporary blank sandbox isolated from it. The blank sandbox cannot see project files, and generated files are not written back to the project.',
                control: SizedBox(
                  width: 300,
                  child: GlassSegmentedControl(
                    key: const ValueKey('settings-sandbox-mapping-control'),
                    height: 34,
                    segments: [
                      GlassSegment(
                        label: context.l10n.languageCode == 'zh'
                            ? '使用当前工作区'
                            : 'Use current workspace',
                      ),
                      GlassSegment(
                        label: context.l10n.languageCode == 'zh'
                            ? '使用临时空白沙箱'
                            : 'Use temporary blank sandbox',
                      ),
                    ],
                    selectedIndex: mapped ? 0 : 1,
                    onSegmentSelected: (index) =>
                        _saveSandbox(mapWorkspace: index == 0),
                  ),
                ),
              ),
              _SettingsRow(
                label: context.l10n.languageCode == 'zh'
                    ? '工作目录路径'
                    : 'Workspace path',
                description: context.l10n.languageCode == 'zh'
                    ? '选择 Agent 和工具使用固定虚拟路径，或直接使用当前宿主机工作区的真实绝对路径。'
                    : 'Choose a fixed virtual path, or use the current host workspace’s real absolute path.',
                control: SizedBox(
                  width: 300,
                  child: GlassSegmentedControl(
                    key: const ValueKey('settings-sandbox-path-mode-control'),
                    height: 34,
                    segments: [
                      GlassSegment(
                        label: context.l10n.languageCode == 'zh'
                            ? '固定虚拟路径'
                            : 'Fixed virtual path',
                      ),
                      GlassSegment(
                        label: context.l10n.languageCode == 'zh'
                            ? '与真实目录一致'
                            : 'Same as host path',
                      ),
                    ],
                    selectedIndex: useHostPath ? 1 : 0,
                    onSegmentSelected: (index) => _saveSandbox(
                      mapWorkspace: index == 1 ? true : null,
                      useHostPath: index == 1,
                    ),
                  ),
                ),
              ),
              _SettingsRow(
                label: context.l10n.languageCode == 'zh'
                    ? '固定虚拟路径'
                    : 'Fixed virtual path',
                description: useHostPath
                    ? (context.l10n.languageCode == 'zh'
                          ? '当前使用路径一致模式；每次 Run 会自动采用当前 Agent Workspace 或 Project 的真实目录。'
                          : 'Path parity is active; each run uses the real path of its Agent Workspace or Project.')
                    : (context.l10n.languageCode == 'zh'
                          ? 'Agent 和工具看到的固定沙箱路径。'
                          : 'The fixed sandbox path seen by the Agent and tools.'),
                control: SizedBox(
                  width: 300,
                  child: useHostPath
                      ? Text(
                          context.l10n.languageCode == 'zh'
                              ? '自动使用当前真实工作目录'
                              : 'Uses the active real workspace automatically',
                          key: const ValueKey('settings-sandbox-host-path'),
                        )
                      : TextField(
                          key: const ValueKey(
                            'settings-sandbox-workspace-root',
                          ),
                          controller: _sandboxRoot,
                          autocorrect: false,
                          enableSuggestions: false,
                          onChanged: (_) => _saveSandboxRootLater(),
                          decoration: InputDecoration(
                            isDense: true,
                            hintText: '/workspace',
                            errorText: _sandboxRootError,
                          ),
                        ),
                ),
              ),
              _SettingsRow(
                label: context.l10n.languageCode == 'zh'
                    ? '生效范围'
                    : 'Apply scope',
                control: Text(
                  context.l10n.languageCode == 'zh'
                      ? '下次 Run 生效'
                      : 'Applies to the next run',
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _security() {
    final shellPolicy = widget.controller.agentConfiguration?.shellPolicy;
    final approvedCommands = shellPolicy?.userApprovedCommands ?? const [];
    return _SettingsContent(
      title: context.l10n.text('settings.security'),
      children: [
        GlassCard(
          key: const ValueKey('settings-security-scope'),
          padding: EdgeInsets.zero,
          shape: const LiquidRoundedSuperellipse(borderRadius: 16),
          useOwnLayer: true,
          settings: _glass(context),
          child: _SettingsRowGroup(
            children: [
              _SettingsRow(
                label: context.l10n.text('security.policyGranularity'),
                control: Text(
                  context.l10n.text('security.policyGranularityValue'),
                ),
              ),
              _SettingsRow(
                label: context.l10n.text('security.fileBoundary'),
                control: Text(context.l10n.text('security.fileBoundaryValue')),
              ),
              _SettingsRow(
                label: context.l10n.text('security.autoAllow'),
                control: _SecurityKeywordList(
                  values: shellPolicy?.autoExecuteKeywords ?? const [],
                ),
              ),
              _SettingsRow(
                label: context.l10n.text('security.requestApproval'),
                control: _SecurityKeywordList(
                  values: shellPolicy?.approvalKeywords ?? const [],
                ),
              ),
              _SettingsRow(
                label: context.l10n.text('security.autoBlock'),
                control: _SecurityKeywordList(
                  values: shellPolicy?.blockedKeywords ?? const [],
                ),
              ),
              _SettingsRow(
                label: context.l10n.text('security.userApproved'),
                control: _SecurityKeywordList(
                  values: approvedCommands,
                  emptyLabel: context.l10n.text('security.userApprovedEmpty'),
                  onRemove: (command) =>
                      widget.controller.patchAgentConfiguration({
                        'approved_shell_commands': [
                          for (final value in approvedCommands)
                            if (value != command) value,
                        ],
                      }),
                ),
              ),
              _SettingsRow(
                label: context.l10n.text('security.isolation'),
                control: Text(context.l10n.text('security.isolationValue')),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _components() => _SettingsContent(
    title: context.l10n.text('settings.components'),
    status: _saving,
    children: [
      for (final component in _orderedRuntimeComponents(
        widget.controller.components,
      ))
        _ComponentSettingsCard(
          component: component,
          onSelect: (pluginId, config) async {
            setState(() => _saving = true);
            try {
              await widget.controller.selectComponent(
                component.id,
                pluginId,
                config: config,
              );
            } finally {
              if (mounted) setState(() => _saving = false);
            }
          },
        ),
    ],
  );

  Future<void> _setDefaultAgent(String agentId) async {
    if (_saving || agentId.isEmpty || agentId == _draft.defaultAgentId) return;
    await _saveDesktopSettings(_draft.copyWith(defaultAgentId: agentId));
  }

  Widget _general() => _SettingsContent(
    title: context.l10n.text('settings.general'),
    status: _saving,
    children: [
      _SettingsRowGroup(
        children: [
          _SettingsRow(
            label: context.l10n.text('settings.appearance'),
            control: SizedBox(
              width: 270,
              child: GlassSegmentedControl(
                height: 34,
                segments: [
                  GlassSegment(
                    label: context.l10n.text('settings.themeSystem'),
                  ),
                  GlassSegment(label: context.l10n.text('settings.themeLight')),
                  GlassSegment(label: context.l10n.text('settings.themeDark')),
                ],
                selectedIndex: ThemeMode.values.indexOf(widget.themeMode),
                onSegmentSelected: (index) =>
                    _saveThemeMode(ThemeMode.values[index]),
              ),
            ),
          ),
          _SettingsRow(
            label: context.l10n.text('settings.language'),
            control: _SettingsPicker<String>(
              key: const ValueKey('settings-language-picker'),
              width: 270,
              value: widget.language,
              options: [
                for (final value in const [
                  'system',
                  'zh',
                  'en',
                  'pt',
                  'es',
                  'fr',
                  'de',
                  'ja',
                  'ko',
                  'ru',
                ])
                  _PickerOption(
                    value: value,
                    label: context.l10n.localeName(value),
                  ),
              ],
              onChanged: _saveLanguage,
            ),
          ),
          _SettingsRow(
            label: context.l10n.text('settings.defaultWorkspace'),
            description: context.l10n.languageCode == 'zh'
                ? 'Agent Workspace 在宿主机上的持久化位置；是否映射到 Run 由“沙箱”设置决定。'
                : 'Persistent host location for Agent Workspace; whether it is mapped into runs is controlled in Sandbox settings.',
            control: SizedBox(
              width: 430,
              child: Row(
                children: [
                  Expanded(
                    child: Semantics(
                      label: context.l10n.text('settings.defaultWorkspacePath'),
                      textField: true,
                      child: GlassTextField(
                        key: const ValueKey('settings-agent-workspace-path'),
                        controller: _workspacePath,
                        height: 36,
                        padding: const EdgeInsets.symmetric(horizontal: 11),
                        settings: _glass(context),
                        onChanged: (_) => _saveWorkspaceLater(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    key: const ValueKey('settings-agent-workspace-picker'),
                    tooltip: context.l10n.text('settings.chooseDirectory'),
                    onPressed: _chooseWorkspacePath,
                    icon: const Icon(CupertinoIcons.folder, size: 18),
                  ),
                ],
              ),
            ),
          ),
          _SettingsRow(
            label: context.l10n.text('settings.previewLimit'),
            control: SizedBox(
              width: 132,
              child: GlassTextField(
                key: const ValueKey('settings-preview-bytes'),
                controller: _previewBytes,
                height: 36,
                padding: const EdgeInsets.symmetric(horizontal: 11),
                settings: _glass(context),
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                onChanged: (_) => _saveRuntimeLater(),
              ),
            ),
          ),
          _SettingsRow(
            label: context.l10n.text('settings.treeLimit'),
            control: SizedBox(
              width: 132,
              child: GlassTextField(
                key: const ValueKey('settings-tree-entries'),
                controller: _treeEntries,
                height: 36,
                padding: const EdgeInsets.symmetric(horizontal: 11),
                settings: _glass(context),
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                onChanged: (_) => _saveRuntimeLater(),
              ),
            ),
          ),
        ],
      ),
    ],
  );

  Widget _agents(AgentConfiguration? agent) {
    if (widget.controller.settingsCatalogLoading && agent == null) {
      return _LoadingContent(title: context.l10n.text('settings.agent'));
    }
    if (agent == null) {
      return _SettingsContent(
        title: context.l10n.text('settings.agent'),
        children: const [],
      );
    }
    final providers = widget.controller.modelProviders;
    final providersById = <String, ModelProviderSummary>{
      for (final value in providers)
        if (value.id.isNotEmpty) value.id: value,
    };
    final currentProviderId = agent.llmProviderId ?? '';
    final currentFastProviderId = agent.fastLlmProviderId ?? '';
    final memberCandidates = [
      for (final value in widget.controller.agents)
        if (value.id != agent.id) value,
    ];
    final customRoster = agent.subAgentSelectionMode == 'manual';
    final selectedMemberIds = customRoster
        ? agent.availableSubAgentIds.toSet()
        : memberCandidates.map((value) => value.id).toSet();
    final loadingSelection =
        widget.controller.settingsAgentLoadingId == _settingsAgentId ||
        agent.id != _settingsAgentId;
    return _SettingsContent(
      title: context.l10n.text('settings.agent'),
      status: _saving,
      fillRemaining: true,
      action: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _SettingsActionButton(
            key: const ValueKey('settings-agent-set-default'),
            onTap:
                _saving ||
                    (_draft.defaultAgentId?.isNotEmpty == true
                        ? agent.id == _draft.defaultAgentId
                        : agent.isDefault)
                ? null
                : () => _setDefaultAgent(agent.id),
            icon: Icon(
              (_draft.defaultAgentId?.isNotEmpty == true
                      ? agent.id == _draft.defaultAgentId
                      : agent.isDefault)
                  ? CupertinoIcons.star_fill
                  : CupertinoIcons.star,
              size: 15,
            ),
            label: context.l10n.text(
              (_draft.defaultAgentId?.isNotEmpty == true
                      ? agent.id == _draft.defaultAgentId
                      : agent.isDefault)
                  ? 'settings.currentDefault'
                  : 'settings.setAsDefault',
            ),
          ),
          const SizedBox(width: 10),
          _SettingsActionButton(
            key: const ValueKey('settings-agent-add'),
            onTap: _saving || loadingSelection || _editingAgent
                ? null
                : _createAgent,
            icon: const Icon(CupertinoIcons.add, size: 15),
            label: context.l10n.text('common.add'),
          ),
          const SizedBox(width: 10),
          _SettingsActionButton(
            key: const ValueKey('settings-agent-edit'),
            onTap: _saving || loadingSelection ? null : _toggleAgentEditing,
            icon: Icon(
              _editingAgent ? CupertinoIcons.checkmark : CupertinoIcons.pencil,
              size: 15,
            ),
            label: context.l10n.text(
              _editingAgent ? 'common.save' : 'common.edit',
            ),
          ),
        ],
      ),
      children: [
        _SettingsMasterDetail(
          selectorKey: const ValueKey('settings-agent-picker'),
          items: [
            for (final value in widget.controller.agents)
              _SettingsChoice(
                id: value.id,
                label: value.name,
                marked: _draft.defaultAgentId?.isNotEmpty == true
                    ? value.id == _draft.defaultAgentId
                    : value.isDefault,
                removable: widget.controller.agents.length > 1 && !_saving,
                busy: _deletingAgentId == value.id,
                removeKeyPrefix: 'settings-agent-delete',
              ),
          ],
          selectedId: _settingsAgentId,
          onSelected: (value) {
            setState(() {
              _settingsAgentId = value;
              _syncedAgentId = '';
              _editingAgent = false;
            });
            widget.controller.selectSettingsAgent(value);
          },
          onRemove: _deleteAgent,
          onSetDefault: _setDefaultAgent,
          detail: loadingSelection
              ? const Center(
                  key: ValueKey('settings-agent-detail-loading'),
                  child: CupertinoActivityIndicator(),
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _SettingsRowGroup(
                      children: [
                        _AgentTextRow(
                          fieldKey: const ValueKey('agent-name-field'),
                          label: context.l10n.text('common.name'),
                          value: agent.name,
                          controller: _name,
                          editing: _editingAgent,
                          onChanged: (_) => _saveAgentTextLater('name', _name),
                        ),
                        _AgentTextRow(
                          label: context.l10n.text('common.description'),
                          value: agent.description,
                          controller: _description,
                          editing: _editingAgent,
                          onChanged: (_) =>
                              _saveAgentTextLater('description', _description),
                        ),
                        _SettingsRow(
                          label: context.l10n.text('agent.primaryModel'),
                          control: _editingAgent
                              ? _SettingsPicker<String>(
                                  key: const ValueKey('agent-main-model'),
                                  value: currentProviderId,
                                  width: 390,
                                  options: [
                                    _PickerOption(
                                      value: '',
                                      label: context.l10n.text(
                                        'common.default',
                                      ),
                                    ),
                                    if (currentProviderId.isNotEmpty &&
                                        !providersById.containsKey(
                                          currentProviderId,
                                        ))
                                      _PickerOption(
                                        value: currentProviderId,
                                        label: currentProviderId,
                                      ),
                                    for (final value in providersById.values)
                                      _PickerOption(
                                        value: value.id,
                                        label: '${value.name} · ${value.model}',
                                      ),
                                  ],
                                  onChanged: (value) => _saveAgent({
                                    'llm_provider_id': value.isEmpty
                                        ? null
                                        : value,
                                  }),
                                )
                              : Text(
                                  _providerLabel(
                                    agent.llmProviderId,
                                    providers,
                                    context.l10n,
                                  ),
                                ),
                        ),
                        _SettingsRow(
                          label: context.l10n.text('agent.fastModel'),
                          control: _editingAgent
                              ? _SettingsPicker<String>(
                                  key: const ValueKey('agent-fast-model'),
                                  value: currentFastProviderId,
                                  width: 390,
                                  options: [
                                    _PickerOption(
                                      value: '',
                                      label:
                                          '${context.l10n.text('common.default')} · ${context.l10n.text('agent.primaryModel')}',
                                    ),
                                    if (currentFastProviderId.isNotEmpty &&
                                        !providersById.containsKey(
                                          currentFastProviderId,
                                        ))
                                      _PickerOption(
                                        value: currentFastProviderId,
                                        label: currentFastProviderId,
                                      ),
                                    for (final value in providersById.values)
                                      _PickerOption(
                                        value: value.id,
                                        label: '${value.name} · ${value.model}',
                                      ),
                                  ],
                                  onChanged: (value) => _saveAgent({
                                    'fast_llm_provider_id': value.isEmpty
                                        ? null
                                        : value,
                                  }),
                                )
                              : Text(
                                  currentFastProviderId.isEmpty
                                      ? '${context.l10n.text('common.default')} · ${_providerLabel(agent.llmProviderId, providers, context.l10n)}'
                                      : _providerLabel(
                                          agent.fastLlmProviderId,
                                          providers,
                                          context.l10n,
                                        ),
                                ),
                        ),
                        _SettingsRow(
                          label: context.l10n.text('agent.mode'),
                          control: _editingAgent
                              ? SizedBox(
                                  width: 300,
                                  child: GlassSegmentedControl(
                                    height: 34,
                                    segments: const [
                                      GlassSegment(label: 'Simple'),
                                      GlassSegment(label: 'Fibre'),
                                      GlassSegment(label: 'Team'),
                                    ],
                                    selectedIndex: const [
                                      'simple',
                                      'fibre',
                                      'team',
                                    ].indexOf(agent.agentMode).clamp(0, 2),
                                    onSegmentSelected: (index) => _saveAgent({
                                      'agent_mode': const [
                                        'simple',
                                        'fibre',
                                        'team',
                                      ][index],
                                    }),
                                  ),
                                )
                              : Text(agent.agentMode),
                        ),
                        if (agent.agentMode == 'fibre' ||
                            agent.agentMode == 'team')
                          _SettingsRow(
                            label: context.l10n.text('agent.teamScope'),
                            control: _editingAgent
                                ? SizedBox(
                                    width: 300,
                                    child: GlassSegmentedControl(
                                      key: const ValueKey('agent-team-scope'),
                                      height: 34,
                                      segments: [
                                        GlassSegment(
                                          label: context.l10n.text(
                                            'agent.teamScopeAll',
                                          ),
                                        ),
                                        GlassSegment(
                                          label: context.l10n.text(
                                            'agent.teamScopeCustom',
                                          ),
                                        ),
                                      ],
                                      selectedIndex: customRoster ? 1 : 0,
                                      onSegmentSelected: (index) => _saveAgent({
                                        'sub_agent_selection_mode': index == 1
                                            ? 'manual'
                                            : 'auto_all',
                                      }),
                                    ),
                                  )
                                : Text(
                                    context.l10n.text(
                                      customRoster
                                          ? 'agent.teamScopeCustom'
                                          : 'agent.teamScopeAll',
                                    ),
                                  ),
                          ),
                        _SettingsRow(
                          label: context.l10n.text('agent.loopLimit'),
                          control: _editingAgent
                              ? SizedBox(
                                  width: 132,
                                  child: GlassTextField(
                                    controller: _maxLoopCount,
                                    height: 36,
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 11,
                                    ),
                                    settings: _glass(context),
                                    keyboardType: TextInputType.number,
                                    onSubmitted: (value) {
                                      final parsed = int.tryParse(value);
                                      if (parsed != null) {
                                        _saveAgent({'max_loop_count': parsed});
                                      }
                                    },
                                  ),
                                )
                              : Text('${agent.maxLoopCount}'),
                        ),
                        _SettingsRow(
                          label: context.l10n.text('agent.deepThinking'),
                          control: _editingAgent
                              ? SizedBox(
                                  width: 190,
                                  child: GlassSegmentedControl(
                                    key: const ValueKey('agent-deep-thinking'),
                                    height: 34,
                                    segments: [
                                      GlassSegment(
                                        label: context.l10n.text(
                                          'common.disable',
                                        ),
                                      ),
                                      GlassSegment(
                                        label: context.l10n.text(
                                          'common.enable',
                                        ),
                                      ),
                                    ],
                                    selectedIndex: agent.deepThinking ? 1 : 0,
                                    onSegmentSelected: (index) => _saveAgent({
                                      'deep_thinking': index == 1,
                                    }),
                                  ),
                                )
                              : Text(
                                  context.l10n.text(
                                    agent.deepThinking
                                        ? 'common.enable'
                                        : 'common.disable',
                                  ),
                                ),
                        ),
                        _SettingsRow(
                          label: context.l10n.text('agent.thinkingLevel'),
                          control: _editingAgent
                              ? _SettingsPicker<String>(
                                  key: const ValueKey('agent-thinking-level'),
                                  value: agent.thinkingLevel,
                                  width: 220,
                                  enabled: agent.deepThinking,
                                  options: [
                                    for (final value in _thinkingLevels)
                                      _PickerOption(
                                        value: value,
                                        label: _thinkingLevelLabel(
                                          value,
                                          context.l10n,
                                        ),
                                      ),
                                  ],
                                  onChanged: (value) =>
                                      _saveAgent({'thinking_level': value}),
                                )
                              : Text(
                                  _thinkingLevelLabel(
                                    agent.thinkingLevel,
                                    context.l10n,
                                  ),
                                ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 22),
                    if (agent.agentMode == 'fibre' ||
                        agent.agentMode == 'team') ...[
                      _AssignmentSection(
                        title: context.l10n.text('agent.teamMembers'),
                        description: context.l10n.text('agent.teamMembersLeaf'),
                        values: memberCandidates.map((value) => value.id),
                        labels: {
                          for (final value in memberCandidates)
                            value.id: value.name,
                        },
                        selected: selectedMemberIds,
                        editing: _editingAgent && customRoster,
                        onToggle: (id) {
                          final next =
                              (widget
                                          .controller
                                          .agentConfiguration
                                          ?.availableSubAgentIds ??
                                      agent.availableSubAgentIds)
                                  .toSet();
                          next.contains(id) ? next.remove(id) : next.add(id);
                          _saveAgent({
                            'available_sub_agent_ids': next.toList()..sort(),
                          });
                        },
                      ),
                      const SizedBox(height: 22),
                    ],
                    _AgentLargeField(
                      label: context.l10n.text('agent.systemPrompt'),
                      value: agent.systemPrefix,
                      controller: _systemPrefix,
                      editing: _editingAgent,
                      view: _SystemPromptMarkdown(value: agent.systemPrefix),
                      onChanged: (_) =>
                          _saveAgentTextLater('system_prefix', _systemPrefix),
                    ),
                    const SizedBox(height: 22),
                    _RuntimeVariablesField(
                      value: agent.runtimeVariables,
                      editing: _editingAgent,
                      onChanged: (value) {
                        _systemContext.text = jsonEncode(value);
                        _saveAgentTextLater(
                          'runtime_variables',
                          _systemContext,
                        );
                      },
                    ),
                    const SizedBox(height: 22),
                    _AssignmentSection(
                      title: context.l10n.text('settings.tools'),
                      groups: _toolAssignmentGroups(
                        widget.controller.toolCatalog,
                        context.l10n,
                      ),
                      selected: agent.availableTools.toSet(),
                      editing: _editingAgent,
                      onToggle: (name) {
                        final next =
                            (widget
                                        .controller
                                        .agentConfiguration
                                        ?.availableTools ??
                                    agent.availableTools)
                                .toSet();
                        next.contains(name)
                            ? next.remove(name)
                            : next.add(name);
                        _saveAgent({'available_tools': next.toList()..sort()});
                      },
                    ),
                    const SizedBox(height: 22),
                    _AssignmentSection(
                      title: context.l10n.text('settings.skills'),
                      values: widget.controller.skillCatalog.map(
                        (value) => value.name,
                      ),
                      selected: agent.availableSkills.toSet(),
                      editing: _editingAgent,
                      onToggle: (name) {
                        final next =
                            (widget
                                        .controller
                                        .agentConfiguration
                                        ?.availableSkills ??
                                    agent.availableSkills)
                                .toSet();
                        next.contains(name)
                            ? next.remove(name)
                            : next.add(name);
                        _saveAgent({'available_skills': next.toList()..sort()});
                      },
                    ),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _models() => _ModelSettings(controller: widget.controller);

  Widget _tools() => _CatalogSettings<ToolSummary>(
    title: context.l10n.text('settings.tools'),
    values: widget.controller.toolCatalog,
    name: (value) => value.name,
    group: (value) => _toolGroupLabel(value, context.l10n),
    rows: (value) => [
      (context.l10n.text('common.name'), value.name),
      (context.l10n.text('common.source'), value.source),
      (context.l10n.text('common.type'), value.type),
      (context.l10n.text('common.description'), value.description),
    ],
    detailBuilder: (value) => _ToolDetails(tool: value),
  );

  Widget _skills() => _SkillSettings(
    controller: widget.controller,
    values: widget.controller.skillCatalog,
  );

  Widget _mcp() =>
      _McpSettings(controller: widget.controller, onAdd: _showAddMcpDialog);

  Future<void> _showAddMcpDialog() async {
    final name = TextEditingController();
    final endpoint = TextEditingController();
    final apiKey = TextEditingController();
    var protocol = 'streamable_http';
    final value = await showDialog<Map<String, Object?>>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => Dialog(
          backgroundColor: Colors.transparent,
          insetPadding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: GlassCard(
              padding: const EdgeInsets.fromLTRB(22, 20, 22, 16),
              shape: const LiquidRoundedSuperellipse(borderRadius: 20),
              useOwnLayer: true,
              settings: _glass(dialogContext),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    context.l10n.text('mcp.connect'),
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 18),
                  _SettingsRowGroup(
                    children: [
                      _SettingsRow(
                        label: context.l10n.text('common.name'),
                        control: SizedBox(
                          width: 290,
                          child: GlassTextField(
                            controller: name,
                            height: 36,
                            padding: const EdgeInsets.symmetric(horizontal: 11),
                            useOwnLayer: true,
                            settings: _glass(context),
                          ),
                        ),
                      ),
                      _SettingsRow(
                        label: context.l10n.text('common.protocol'),
                        control: _SettingsPicker<String>(
                          value: protocol,
                          width: 290,
                          options: const [
                            _PickerOption(
                              value: 'streamable_http',
                              label: 'Streamable HTTP',
                            ),
                            _PickerOption(value: 'sse', label: 'SSE'),
                            _PickerOption(value: 'stdio', label: 'stdio'),
                          ],
                          onChanged: (value) =>
                              setDialogState(() => protocol = value),
                        ),
                      ),
                      _SettingsRow(
                        label: protocol == 'stdio'
                            ? context.l10n.text('mcp.command')
                            : 'URL',
                        control: SizedBox(
                          width: 290,
                          child: GlassTextField(
                            controller: endpoint,
                            height: 36,
                            padding: const EdgeInsets.symmetric(horizontal: 11),
                            useOwnLayer: true,
                            settings: _glass(context),
                          ),
                        ),
                      ),
                      if (protocol != 'stdio')
                        _SettingsRow(
                          label: context.l10n.text('mcp.apiKey'),
                          control: SizedBox(
                            width: 290,
                            child: GlassTextField(
                              controller: apiKey,
                              height: 36,
                              obscureText: true,
                              padding: const EdgeInsets.symmetric(
                                horizontal: 11,
                              ),
                              useOwnLayer: true,
                              settings: _glass(context),
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      TextButton(
                        onPressed: () => Navigator.pop(dialogContext),
                        child: Text(context.l10n.text('common.cancel')),
                      ),
                      const SizedBox(width: 8),
                      GlassButton.custom(
                        width: 76,
                        height: 36,
                        label: context.l10n.text('common.connect'),
                        onTap: () => Navigator.pop(dialogContext, {
                          'name': name.text.trim(),
                          'protocol': protocol,
                          if (protocol == 'streamable_http')
                            'streamable_http_url': endpoint.text.trim(),
                          if (protocol == 'sse')
                            'sse_url': endpoint.text.trim(),
                          if (protocol == 'stdio')
                            'command': endpoint.text.trim(),
                          if (apiKey.text.trim().isNotEmpty)
                            'api_key': apiKey.text.trim(),
                        }),
                        shape: const LiquidRoundedRectangle(borderRadius: 10),
                        settings: _glass(context),
                        child: Center(
                          child: Text(context.l10n.text('common.connect')),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    name.dispose();
    endpoint.dispose();
    apiKey.dispose();
    if (value == null || (value['name']?.toString().isEmpty ?? true)) return;
    setState(() => _saving = true);
    try {
      await widget.controller.addMcpConnection(value);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _selectSection(int value) {
    if (value == _navItems(context).length - 1) {
      widget.controller.loadArchivedConversations();
    }
    setState(() => _section = value);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    Widget surface() => ColoredBox(
      key: const ValueKey('settings-content'),
      color: colors.surface,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(30, 42, 30, 32),
        child: _content(),
      ),
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < desktopCompactBreakpoint) {
          return Column(
            children: [
              SizedBox(
                height: desktopCompactRailHeight(constraints.maxHeight),
                child: _SettingsRail(
                  key: const ValueKey('settings-rail'),
                  selected: _section,
                  onSelect: _selectSection,
                  onBack: widget.onClose,
                  horizontal: true,
                ),
              ),
              Expanded(child: surface()),
            ],
          );
        }
        return Row(
          children: [
            SizedBox(
              width: constraints.maxWidth * widget.railFraction,
              child: _SettingsRail(
                key: const ValueKey('settings-rail'),
                selected: _section,
                onSelect: _selectSection,
                onBack: widget.onClose,
              ),
            ),
            SizedBox(
              width: desktopSplitHandleWidth,
              child: VerticalDivider(
                width: desktopSplitHandleWidth,
                color: colors.outlineVariant,
              ),
            ),
            Expanded(child: surface()),
          ],
        );
      },
    );
  }
}

String _providerLabel(
  String? id,
  List<ModelProviderSummary> values,
  SageLocalizations l10n,
) {
  if (id == null || id.isEmpty) return l10n.text('common.default');
  for (final value in values) {
    if (value.id == id) return '${value.name} · ${value.model}';
  }
  return id;
}

const _thinkingLevels = <String>[
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
];

String _thinkingLevelLabel(String value, SageLocalizations l10n) =>
    _thinkingLevels.contains(value) ? l10n.text('thinking.$value') : value;

List<(String, IconData)> _navItems(BuildContext context) => [
  (
    context.l10n.languageCode == 'zh' ? '概览' : 'Overview',
    CupertinoIcons.chart_bar,
  ),
  (context.l10n.text('settings.general'), CupertinoIcons.gear),
  (context.l10n.text('settings.agent'), CupertinoIcons.person_2),
  (context.l10n.text('settings.models'), CupertinoIcons.slider_horizontal_3),
  (context.l10n.text('settings.tools'), CupertinoIcons.hammer),
  (context.l10n.text('settings.skills'), CupertinoIcons.wand_stars),
  ('MCP', CupertinoIcons.link),
  (context.l10n.text('settings.components'), CupertinoIcons.square_grid_2x2),
  (
    context.l10n.languageCode == 'zh' ? '沙箱' : 'Sandbox',
    CupertinoIcons.cube_box,
  ),
  (context.l10n.text('settings.security'), CupertinoIcons.shield),
  (context.l10n.text('settings.archive'), CupertinoIcons.archivebox),
];

class _ComponentSettingsCard extends StatelessWidget {
  const _ComponentSettingsCard({
    required this.component,
    required this.onSelect,
  });

  final ComponentSummary component;
  final void Function(String, Map<String, Object?>) onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final componentName = _runtimeComponentName(component, context.l10n);
    final componentValue = _runtimeComponentValue(component, context.l10n);
    final selectable = component.selectionMode == 'user';
    final available = [
      for (final plugin in component.plugins)
        if (plugin.available) plugin,
    ];
    final active = component.activePluginId ?? '';
    final selected = component.selectedPluginId ?? active;
    return Semantics(
      container: true,
      label: context.l10n.text('component.current', {
        'name': componentName,
        'implementation': _runtimePluginName(
          component.activePluginId ?? '',
          component.implementation,
          context.l10n,
        ),
      }),
      child: GlassCard(
        key: ValueKey('settings-component-${component.id}'),
        padding: const EdgeInsets.all(18),
        shape: const LiquidRoundedSuperellipse(borderRadius: 16),
        useOwnLayer: true,
        settings: _glass(context),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            LayoutBuilder(
              builder: (context, constraints) {
                final title = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      componentName,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      componentValue,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: colors.onSurfaceVariant,
                        height: 1.35,
                      ),
                    ),
                  ],
                );
                final selection = selectable && available.isNotEmpty
                    ? _SettingsPicker<String>(
                        key: ValueKey(
                          'settings-component-picker-${component.id}',
                        ),
                        value: selected,
                        width: 250,
                        options: [
                          for (final plugin in available)
                            _PickerOption(
                              value: plugin.id,
                              label: _runtimePluginName(
                                plugin.id,
                                plugin.name,
                                context.l10n,
                              ),
                            ),
                        ],
                        onChanged: (pluginId) => onSelect(
                          pluginId,
                          component.id == 'tool.selection-policy'
                              ? const {}
                              : const {},
                        ),
                      )
                    : _SettingsTag(
                        label: component.implementation.isEmpty
                            ? context.l10n.text('component.decidedBy', {
                                'owner': _selectionOwner(
                                  component.selectionMode,
                                  context.l10n,
                                ),
                              })
                            : _runtimePluginName(
                                component.activePluginId ?? '',
                                component.implementation,
                                context.l10n,
                              ),
                      );
                if (constraints.maxWidth < 620) {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [title, const SizedBox(height: 14), selection],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: title),
                    const SizedBox(width: 18),
                    selection,
                  ],
                );
              },
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                _SettingsTag(
                  label: context.l10n.text('component.scope', {
                    'scope': _componentScopeLabel(
                      component.scope,
                      context.l10n,
                    ),
                  }),
                ),
                _SettingsTag(
                  label: _applyModeLabel(component.applyMode, context.l10n),
                ),
                if (component.pendingRestart)
                  _SettingsTag(
                    label: context.l10n.text('component.restartRequired'),
                  ),
              ],
            ),
            if (component.id == 'execution.sandbox')
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Container(
                  key: const ValueKey('settings-sandbox-workspace-config'),
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHighest.withValues(
                      alpha: 0.36,
                    ),
                    borderRadius: BorderRadius.circular(9),
                    border: Border.all(color: colors.outlineVariant),
                  ),
                  child: Text(
                    _sandboxComponentSummary(component, context.l10n),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colors.onSurfaceVariant,
                      fontFamily: 'Menlo',
                      height: 1.4,
                    ),
                  ),
                ),
              ),
            if ({
                  'observability.log-sink',
                  'observability.diagnostic-sink',
                  'memory.provider',
                  'session-memory.provider',
                  'session.store',
                }.contains(component.id) &&
                (component.activeConfig['path']?.toString() ?? '').isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Container(
                  key: ValueKey(
                    component.id == 'observability.log-sink'
                        ? 'settings-log-file-path'
                        : 'settings-component-path-${component.id}',
                  ),
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHighest.withValues(
                      alpha: 0.36,
                    ),
                    borderRadius: BorderRadius.circular(9),
                    border: Border.all(color: colors.outlineVariant),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _runtimeComponentPathLabel(component.id, context.l10n),
                        style: Theme.of(context).textTheme.labelMedium
                            ?.copyWith(color: colors.onSurfaceVariant),
                      ),
                      const SizedBox(height: 4),
                      SelectionArea(
                        child: Text(
                          component.activeConfig['path'].toString(),
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(fontFamily: 'Menlo', height: 1.35),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            if (component.id == 'agent.continuation-policy')
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Container(
                  key: const ValueKey('settings-continuation-policy-details'),
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHighest.withValues(
                      alpha: 0.36,
                    ),
                    borderRadius: BorderRadius.circular(9),
                    border: Border.all(color: colors.outlineVariant),
                  ),
                  child: Text(
                    _continuationPolicyDetails(
                      component.activePluginId ?? '',
                      context.l10n,
                    ),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colors.onSurfaceVariant,
                      height: 1.4,
                    ),
                  ),
                ),
              ),
            if (component.id == 'tool.selection-policy')
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: _ToolSelectionConfigEditor(
                  component: component,
                  onSave: (config) => onSelect(selected, config),
                ),
              ),
            const SizedBox(height: 14),
            Divider(height: 1, color: colors.outlineVariant),
            const SizedBox(height: 12),
            for (final plugin in component.plugins) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    plugin.id == active
                        ? CupertinoIcons.checkmark_circle_fill
                        : plugin.available
                        ? CupertinoIcons.circle
                        : CupertinoIcons.nosign,
                    size: 16,
                    color: plugin.id == active
                        ? colors.primary
                        : colors.onSurfaceVariant,
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _runtimePluginName(
                            plugin.id,
                            plugin.name,
                            context.l10n,
                          ),
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          _runtimePluginValue(
                            plugin.id,
                            plugin.value,
                            context.l10n,
                          ),
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(
                                color: colors.onSurfaceVariant,
                                height: 1.35,
                              ),
                        ),
                        if (!plugin.available && plugin.dependencies.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 3),
                            child: Text(
                              context.l10n.text('component.requires', {
                                'dependencies': plugin.dependencies.join(', '),
                              }),
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(color: colors.error),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
              if (plugin != component.plugins.last) const SizedBox(height: 11),
            ],
          ],
        ),
      ),
    );
  }

  String _sandboxComponentSummary(
    ComponentSummary component,
    SageLocalizations l10n,
  ) {
    final config = component.activeConfig;
    final hostPath = config['workspace_path_mode'] == 'host';
    final mapped = config['workspace_mapping'] == 'active_workspace';
    if (l10n.languageCode == 'zh') {
      final path = hostPath
          ? '工作目录：与真实目录一致（每次 Run 动态解析）'
          : '固定虚拟路径：${config['workspace_root'] ?? '—'}';
      return '$path\n'
          '工作区模式：${mapped ? '使用当前工作区' : '使用临时空白沙箱'} · '
          '文件系统：${config['filesystem_mode'] ?? '—'}';
    }
    final path = hostPath
        ? 'Workspace path: same as host path (resolved for each run)'
        : 'Fixed virtual path: ${config['workspace_root'] ?? '—'}';
    return '$path\n'
        'Workspace mode: ${mapped ? 'use current workspace' : 'use temporary blank sandbox'} · '
        'Filesystem: ${config['filesystem_mode'] ?? '—'}';
  }
}

class _ToolSelectionConfigEditor extends StatefulWidget {
  const _ToolSelectionConfigEditor({
    required this.component,
    required this.onSave,
  });

  final ComponentSummary component;
  final ValueChanged<Map<String, Object?>> onSave;

  @override
  State<_ToolSelectionConfigEditor> createState() =>
      _ToolSelectionConfigEditorState();
}

class _ToolSelectionConfigEditorState
    extends State<_ToolSelectionConfigEditor> {
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, bool> _booleans = {};
  String _configFingerprint = '';

  ComponentPluginSummary? get _plugin {
    final selected = widget.component.selectedPluginId;
    for (final plugin in widget.component.plugins) {
      if (plugin.id == selected) return plugin;
    }
    return null;
  }

  Map<String, Map<String, Object?>> get _properties {
    final raw = _plugin?.configSchema['properties'];
    if (raw is! Map) return const {};
    return {
      for (final entry in raw.entries)
        if (entry.value is Map)
          entry.key.toString(): (entry.value as Map).cast<String, Object?>(),
    };
  }

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(covariant _ToolSelectionConfigEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    final fingerprint = jsonEncode([
      widget.component.activeConfig,
      widget.component.selectedPluginId,
      _plugin?.configSchema,
    ]);
    if (fingerprint != _configFingerprint) {
      _sync();
    }
  }

  void _sync() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    _controllers.clear();
    _booleans.clear();
    _configFingerprint = jsonEncode([
      widget.component.activeConfig,
      widget.component.selectedPluginId,
      _plugin?.configSchema,
    ]);
    for (final entry in _properties.entries) {
      final schema = entry.value;
      final value =
          widget.component.activeConfig[entry.key] ?? schema['default'];
      if (schema['type'] == 'boolean') {
        _booleans[entry.key] = value == true;
      } else {
        _controllers[entry.key] = TextEditingController(
          text: value?.toString() ?? '',
        );
      }
    }
  }

  Map<String, Object?>? _value() {
    final result = <String, Object?>{};
    for (final entry in _properties.entries) {
      final schema = entry.value;
      if (schema['type'] == 'boolean') {
        result[entry.key] = _booleans[entry.key] ?? false;
        continue;
      }
      final raw = _controllers[entry.key]?.text.trim() ?? '';
      Object? value;
      if (schema['type'] == 'integer') {
        value = int.tryParse(raw);
      } else if (schema['type'] == 'number') {
        value = double.tryParse(raw);
      } else {
        value = raw;
      }
      if (value == null) return null;
      if (value is num) {
        final minimum = schema['minimum'];
        final maximum = schema['maximum'];
        if (minimum is num && value < minimum) return null;
        if (maximum is num && value > maximum) return null;
      }
      result[entry.key] = value;
    }
    return result;
  }

  void _restoreDefaults() {
    setState(() {
      for (final entry in _properties.entries) {
        final value = entry.value['default'];
        if (entry.value['type'] == 'boolean') {
          _booleans[entry.key] = value == true;
        } else {
          _controllers[entry.key]?.text = value?.toString() ?? '';
        }
      }
    });
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final properties = _properties;
    final config = _value();
    return Container(
      key: const ValueKey('settings-tool-selection-config'),
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.36),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.l10n.text('component.toolSelection.settings'),
            style: Theme.of(
              context,
            ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          Text(
            context.l10n.text('component.toolSelection.settingsHelp'),
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.onSurfaceVariant),
          ),
          if (properties.isEmpty) ...[
            const SizedBox(height: 10),
            Text(
              context.l10n.text('component.plugin.toolSelectionDirect.value'),
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.onSurfaceVariant),
            ),
          ] else ...[
            const SizedBox(height: 12),
            LayoutBuilder(
              builder: (context, constraints) {
                final fieldWidth = constraints.maxWidth < 540
                    ? constraints.maxWidth
                    : (constraints.maxWidth - 12) / 2;
                return Wrap(
                  spacing: 12,
                  runSpacing: 10,
                  children: [
                    for (final entry in properties.entries)
                      SizedBox(
                        width: fieldWidth,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              entry.key == 'max_visible_tools'
                                  ? context.l10n.text(
                                      'component.toolSelection.max_visible_tools',
                                    )
                                  : (entry.value['title']?.toString() ??
                                        entry.key),
                              style: Theme.of(context).textTheme.labelMedium,
                            ),
                            const SizedBox(height: 5),
                            if (entry.value['type'] == 'boolean')
                              Switch(
                                value: _booleans[entry.key] ?? false,
                                onChanged: (value) => setState(
                                  () => _booleans[entry.key] = value,
                                ),
                              )
                            else
                              GlassTextField(
                                key: ValueKey(
                                  'settings-tool-selection-${entry.key}',
                                ),
                                controller: _controllers[entry.key],
                                height: 34,
                                keyboardType:
                                    {
                                      'integer',
                                      'number',
                                    }.contains(entry.value['type'])
                                    ? TextInputType.number
                                    : TextInputType.text,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 9,
                                ),
                                useOwnLayer: true,
                                settings: _glass(context),
                                onChanged: (_) => setState(() {}),
                              ),
                          ],
                        ),
                      ),
                  ],
                );
              },
            ),
          ],
          if (config == null) ...[
            const SizedBox(height: 8),
            Text(
              context.l10n.text('component.toolSelection.invalid'),
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.error),
            ),
          ],
          if (properties.isNotEmpty) ...[
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: _restoreDefaults,
                  child: Text(
                    context.l10n.text(
                      'component.toolSelection.restoreDefaults',
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  key: const ValueKey('settings-tool-selection-save'),
                  onPressed: config == null
                      ? null
                      : () => widget.onSave(config),
                  child: Text(context.l10n.text('common.save')),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

String _selectionOwner(String value, SageLocalizations l10n) => switch (value) {
  'model_route' => l10n.text('component.owner.modelRoute'),
  'host' => l10n.text('component.owner.host'),
  _ => l10n.text('component.owner.user'),
};

String _applyModeLabel(String value, SageLocalizations l10n) => switch (value) {
  'immediate' => l10n.text('component.apply.immediate'),
  'next_run' => l10n.text('component.apply.nextRun'),
  'restart' => l10n.text('component.apply.restart'),
  _ => l10n.text('component.apply.unavailable'),
};

List<ComponentSummary> _orderedRuntimeComponents(
  List<ComponentSummary> components,
) {
  const priority = {
    'agent.continuation-policy': 0,
    'tool.selection-policy': 1,
    'memory.provider': 2,
    'memory.recall-query': 3,
    'session-memory.provider': 4,
  };
  final indexed = components.indexed.toList();
  indexed.sort((left, right) {
    final leftPriority = priority[left.$2.id] ?? 100 + left.$1;
    final rightPriority = priority[right.$2.id] ?? 100 + right.$1;
    return leftPriority.compareTo(rightPriority);
  });
  return [for (final value in indexed) value.$2];
}

String _runtimeComponentName(
  ComponentSummary component,
  SageLocalizations l10n,
) => switch (component.id) {
  'agent.continuation-policy' =>
    l10n.languageCode == 'zh' ? 'Run 完成判定' : 'Run completion policy',
  'context.token-estimator' => l10n.text('component.tokenEstimator.name'),
  'context.reducer' => l10n.text('component.reducer.name'),
  'context.summarizer' =>
    l10n.languageCode == 'zh' ? '上下文摘要器' : 'Context summarizer',
  'context.summary-store' =>
    l10n.languageCode == 'zh' ? '摘要存储' : 'Summary store',
  'memory.provider' => l10n.languageCode == 'zh' ? '长期记忆' : 'Long-term memory',
  'memory.recall-query' =>
    l10n.languageCode == 'zh' ? '记忆检索词生成' : 'Memory query generation',
  'tool.selection-policy' => l10n.text('component.toolSelection.name'),
  'session-memory.provider' => l10n.text('component.sessionMemory.name'),
  'observability.diagnostic-sink' => l10n.text(
    'component.modelRequestRecords.name',
  ),
  'observability.log-sink' =>
    l10n.languageCode == 'zh' ? '结构化日志' : 'Structured logging',
  'execution.sandbox' =>
    l10n.languageCode == 'zh' ? '执行沙箱' : 'Execution sandbox',
  'session.store' => l10n.languageCode == 'zh' ? '会话存储' : 'Session store',
  'workspace.initializer' =>
    l10n.languageCode == 'zh' ? '工作区初始化' : 'Workspace initialization',
  _ => component.name,
};

String _runtimeComponentValue(
  ComponentSummary component,
  SageLocalizations l10n,
) => switch (component.id) {
  'agent.continuation-policy' =>
    l10n.languageCode == 'zh'
        ? '决定 Agent 继续调用工具、请求用户输入、完成或失败'
        : 'Decides whether an Agent continues, asks the user, completes, or fails',
  'context.token-estimator' => l10n.text('component.tokenEstimator.value'),
  'context.reducer' => l10n.text('component.reducer.value'),
  'context.summarizer' =>
    l10n.languageCode == 'zh'
        ? '上下文超出预算时生成可持久复用的历史摘要'
        : 'Produces reusable history summaries when context exceeds its budget',
  'context.summary-store' =>
    l10n.languageCode == 'zh'
        ? '保存由 Session 事件派生的摘要，不改写原始会话记录'
        : 'Stores summaries derived from Session events without rewriting history',
  'memory.provider' =>
    l10n.languageCode == 'zh'
        ? '运行前召回相关记忆，成功结束后自动写入长期记忆'
        : 'Recalls relevant memory before a run and ingests it after successful completion',
  'memory.recall-query' =>
    l10n.languageCode == 'zh'
        ? '决定 search_memory 使用原始用户输入，还是先由快速模型生成关键词'
        : 'Chooses whether search_memory uses the raw user input or keywords generated by a fast model',
  'tool.selection-policy' => l10n.text('component.toolSelection.value'),
  'session-memory.provider' => l10n.text('component.sessionMemory.value'),
  'observability.diagnostic-sink' => l10n.text(
    'component.modelRequestRecords.value',
  ),
  'observability.log-sink' =>
    l10n.languageCode == 'zh'
        ? '统一记录应用、Agent、模型、工具和运行时错误'
        : 'Records application, Agent, model, tool, and runtime failures uniformly',
  'execution.sandbox' =>
    l10n.languageCode == 'zh'
        ? '按当前沙箱配置决定虚拟工作目录、是否映射宿主工作区，并执行路径与进程策略'
        : 'Uses the active sandbox configuration for its virtual root and host mapping, then enforces path and process policy',
  'session.store' =>
    l10n.languageCode == 'zh'
        ? '权威保存 Session、Run、事件、检查点、暂停与审批状态'
        : 'Authoritatively stores Sessions, Runs, events, checkpoints, suspensions, and approvals',
  'workspace.initializer' =>
    l10n.languageCode == 'zh'
        ? '首次使用时预置 Agent Workspace 的文件和目录'
        : 'Seeds Agent Workspace files and folders on first use',
  _ => component.value,
};

String _runtimePluginName(
  String pluginId,
  String fallback,
  SageLocalizations l10n,
) => switch (pluginId) {
  'sage.agent.continuation.deterministic' =>
    l10n.languageCode == 'zh' ? '无工具调用即完成' : 'Complete without Tool calls',
  'sage.agent.continuation.llm-judge' =>
    l10n.languageCode == 'zh'
        ? '无工具调用 + LLM Judge'
        : 'No Tool call + LLM Judge',
  'sage.agent.continuation.hybrid' =>
    l10n.languageCode == 'zh' ? '混合完成判定' : 'Hybrid completion policy',
  'sage.agent.continuation.explicit-status' =>
    l10n.languageCode == 'zh'
        ? '结束工具（turn_status）'
        : 'Completion Tool (turn_status)',
  'sage.context.token-estimator.json-heuristic' ||
  'json-heuristic' => l10n.text('component.plugin.jsonHeuristic.name'),
  'sage.context.token-estimator.unicode-heuristic' ||
  'unicode-heuristic' => l10n.text('component.plugin.unicodeHeuristic.name'),
  'sage.context.token-estimator.tiktoken' ||
  'tiktoken' => l10n.text('component.plugin.tiktoken.name'),
  'sage.context.reducer.persistent-summary' ||
  'persistent-summary' => l10n.text('component.plugin.persistentSummary.name'),
  'sage.context.reducer.window' ||
  'window' => l10n.text('component.plugin.window.name'),
  'sage.context.summarizer.model' =>
    l10n.languageCode == 'zh' ? '模型摘要' : 'Model summary',
  'sage.context.summarizer.extractive' =>
    l10n.languageCode == 'zh' ? '抽取式摘要' : 'Extractive summary',
  'sage.context.summary-store.session-derived' =>
    l10n.languageCode == 'zh' ? 'Session 派生存储' : 'Session-derived store',
  'sage.context.summary-store.ephemeral' =>
    l10n.languageCode == 'zh' ? '临时摘要存储' : 'Ephemeral summary store',
  'sage.memory.filesystem-bm25' =>
    l10n.languageCode == 'zh' ? '本地 BM25 记忆' : 'Local BM25 memory',
  'sage.memory.noop' =>
    l10n.languageCode == 'zh' ? '关闭长期记忆' : 'Long-term memory off',
  'sage.memory.recall-query.direct' =>
    l10n.languageCode == 'zh' ? '直接使用用户输入' : 'Direct user input',
  'sage.memory.recall-query.llm' =>
    l10n.languageCode == 'zh' ? 'LLM 生成检索词' : 'LLM-generated keywords',
  'sage.tool-selection.direct' => l10n.text(
    'component.plugin.toolSelectionDirect.name',
  ),
  'sage.tool-selection.lexical' => l10n.text(
    'component.plugin.toolSelectionLexical.name',
  ),
  'sage.tool-selection.llm' => l10n.text(
    'component.plugin.toolSelectionLlm.name',
  ),
  'sage.tool-selection.recent' => l10n.text(
    'component.plugin.toolSelectionRecent.name',
  ),
  'sage.session-memory.sqlite-bm25' => l10n.text(
    'component.plugin.sessionMemorySqliteBm25.name',
  ),
  'sage.session-memory.noop' => l10n.text(
    'component.plugin.sessionMemoryNoop.name',
  ),
  'sage.observability.filesystem' => l10n.text(
    'component.plugin.filesystemModelRequests.name',
  ),
  'sage.observability.noop' => l10n.text(
    'component.plugin.modelRequestsOff.name',
  ),
  'sage.logging.filesystem' =>
    l10n.languageCode == 'zh' ? '轮转文件日志' : 'Rotating file logs',
  'sage.logging.noop' => l10n.languageCode == 'zh' ? '关闭日志' : 'Logging off',
  'sage.sandbox.local-workspace' =>
    l10n.languageCode == 'zh' ? '本地工作区沙箱' : 'Local workspace sandbox',
  'sage.sandbox.ephemeral' =>
    l10n.languageCode == 'zh' ? '临时内存沙箱' : 'Ephemeral sandbox',
  'sage.session.filesystem' =>
    l10n.languageCode == 'zh' ? '文件 Session 存储' : 'Filesystem Session store',
  'sage.session.ephemeral' =>
    l10n.languageCode == 'zh' ? '临时 Session 存储' : 'Ephemeral Session store',
  'sage.workspace.initializer.claw' =>
    l10n.languageCode == 'zh' ? 'Claw Mode' : 'Claw Mode',
  'sage.workspace.initializer.bare' =>
    l10n.languageCode == 'zh' ? '空白工作区' : 'Bare workspace',
  _ => fallback,
};

String _runtimePluginValue(
  String pluginId,
  String fallback,
  SageLocalizations l10n,
) => switch (pluginId) {
  'sage.agent.continuation.deterministic' =>
    l10n.languageCode == 'zh'
        ? '模型没有调用工具且返回最终文本时完成；工具调用后继续运行'
        : 'Completes on final text without Tool calls; continues after Tool calls',
  'sage.agent.continuation.llm-judge' =>
    l10n.languageCode == 'zh'
        ? '模型无工具调用后，再由 V1 Judge 二次判定继续、完成、请求输入或阻塞'
        : 'After a response without Tool calls, the V1 Judge decides whether to continue, complete, request input, or block',
  'sage.agent.continuation.hybrid' =>
    l10n.languageCode == 'zh'
        ? '确定性规则优先，最终文本交给 V1 Judge；Judge 输出无效或失败时安全回退'
        : 'Prioritizes deterministic rules and sends final text to the V1 Judge, with fallback for invalid output or failure',
  'sage.agent.continuation.explicit-status' =>
    l10n.languageCode == 'zh'
        ? '由 turn_status 明确返回完成、继续、请求输入、阻塞或失败'
        : 'Uses turn_status to explicitly complete, continue, request input, block, or fail',
  'sage.context.token-estimator.json-heuristic' ||
  'json-heuristic' => l10n.text('component.plugin.jsonHeuristic.value'),
  'sage.context.token-estimator.unicode-heuristic' ||
  'unicode-heuristic' => l10n.text('component.plugin.unicodeHeuristic.value'),
  'sage.context.token-estimator.tiktoken' ||
  'tiktoken' => l10n.text('component.plugin.tiktoken.value'),
  'sage.context.reducer.persistent-summary' ||
  'persistent-summary' => l10n.text('component.plugin.persistentSummary.value'),
  'sage.context.reducer.window' ||
  'window' => l10n.text('component.plugin.window.value'),
  'sage.context.summarizer.model' =>
    l10n.languageCode == 'zh'
        ? '使用当前 Agent 的模型生成结构化摘要；请求会进入模型诊断记录'
        : 'Uses the current Agent model to produce a structured summary and records the request in diagnostics',
  'sage.context.summarizer.extractive' =>
    l10n.languageCode == 'zh'
        ? '无需额外模型请求，按内容抽取生成保守摘要'
        : 'Creates a conservative extractive summary without another model request',
  'sage.context.summary-store.session-derived' =>
    l10n.languageCode == 'zh'
        ? '摘要与 Session 事件关联，原始消息保持完整且可审计'
        : 'Associates summaries with Session events while preserving auditable original messages',
  'sage.context.summary-store.ephemeral' =>
    l10n.languageCode == 'zh'
        ? '仅在当前进程保存摘要，重启后丢失'
        : 'Keeps summaries only for the current process',
  'sage.memory.filesystem-bm25' =>
    l10n.languageCode == 'zh'
        ? '按用户与 Agent 隔离，在本地持久化并用 BM25 检索；默认开启召回与自动写入'
        : 'Persists locally per user and Agent with BM25 retrieval; recall and auto-write are enabled by default',
  'sage.memory.recall-query.direct' =>
    l10n.languageCode == 'zh'
        ? '直接把本轮用户输入作为 search_memory.query，不增加模型 Token 和延迟'
        : 'Uses the current user input as search_memory.query with no extra model tokens or latency',
  'sage.memory.recall-query.llm' =>
    l10n.languageCode == 'zh'
        ? '先调用快速模型提取 3–10 个关键词，再执行 search_memory；召回更聚焦，但会增加一次模型请求'
        : 'Calls a fast model for 3–10 keywords before search_memory; retrieval is more focused but adds one model request',
  'sage.memory.noop' =>
    l10n.languageCode == 'zh'
        ? '不召回或写入长期记忆；切换后需重启应用'
        : 'Does not recall or write long-term memory; switching requires an app restart',
  'sage.tool-selection.direct' => l10n.text(
    'component.plugin.toolSelectionDirect.value',
  ),
  'sage.tool-selection.lexical' => l10n.text(
    'component.plugin.toolSelectionLexical.value',
  ),
  'sage.tool-selection.llm' => l10n.text(
    'component.plugin.toolSelectionLlm.value',
  ),
  'sage.tool-selection.recent' => l10n.text(
    'component.plugin.toolSelectionRecent.value',
  ),
  'sage.session-memory.sqlite-bm25' => l10n.text(
    'component.plugin.sessionMemorySqliteBm25.value',
  ),
  'sage.session-memory.noop' => l10n.text(
    'component.plugin.sessionMemoryNoop.value',
  ),
  'sage.observability.filesystem' => l10n.text(
    'component.plugin.filesystemModelRequests.value',
  ),
  'sage.observability.noop' => l10n.text(
    'component.plugin.modelRequestsOff.value',
  ),
  'sage.logging.filesystem' =>
    l10n.languageCode == 'zh'
        ? '写入经过脱敏的 JSONL，并自动限制文件大小与保留数量'
        : 'Writes redacted JSONL with bounded size and retention',
  'sage.logging.noop' =>
    l10n.languageCode == 'zh'
        ? '不保存运行日志（Session 事件仍正常持久化）'
        : 'Does not retain operational logs; Session events remain durable',
  'sage.sandbox.local-workspace' =>
    l10n.languageCode == 'zh'
        ? '文件工具只描述虚拟路径；主机路径映射、越界检查与权限由沙箱实现'
        : 'File tools use virtual paths; host mapping, boundary checks, and permissions are enforced by the sandbox',
  'sage.sandbox.ephemeral' =>
    l10n.languageCode == 'zh'
        ? '使用隔离的临时文件系统，不映射当前项目'
        : 'Uses an isolated temporary filesystem without mapping the active project',
  'sage.session.filesystem' =>
    l10n.languageCode == 'zh'
        ? '按 Session 保存紧凑状态，并生成结构化的 Runs、事件与嵌套子 Session'
        : 'Persists compact Session state with structured Runs, events, and child references',
  'sage.session.ephemeral' =>
    l10n.languageCode == 'zh'
        ? '仅用于短期进程内运行，重启后状态丢失'
        : 'Keeps run state only in the current process',
  'sage.workspace.initializer.claw' =>
    l10n.languageCode == 'zh'
        ? '按 desktop-v1.1.8 模板预置身份与记忆文档，以及 memory、data、projects、temp、logs 目录；不会读取旧版数据'
        : 'Seeds desktop-v1.1.8 identity and memory templates plus memory, data, projects, temp, and logs directories without reading legacy data',
  'sage.workspace.initializer.bare' =>
    l10n.languageCode == 'zh'
        ? '不预置内容，由用户或 Agent 自行创建'
        : 'Seeds nothing; the user or Agent creates all content',
  _ => fallback,
};

String _continuationPolicyDetails(String pluginId, SageLocalizations l10n) {
  final zh = l10n.languageCode == 'zh';
  return switch (pluginId) {
    'sage.agent.continuation.llm-judge' =>
      zh
          ? '模型有工具调用时继续执行；只有模型未调用工具时，才追加一次 V1 LLM Judge 请求进行二次判定。Judge 使用最近请求执行轨迹、Todo 硬约束、系统要求与工具清单，输出继续、完成、请求输入或阻塞；无效 JSON 默认继续。Judge 使用 fast 模型绑定，Token 计入 Run 用量。'
          : 'Tool calls continue execution. Only a response without Tool calls triggers one additional V1 LLM Judge request. The Judge uses the recent execution trace, Todo invariant, system requirements, and Tool list to decide continue, complete, request input, or block; invalid JSON continues. It uses the fast model binding and its tokens count toward Run usage.',
    'sage.agent.continuation.hybrid' =>
      zh
          ? '判定顺序：预算与截止时间 → turn_status → 重复停滞 → Flow 边界 → 工具或空响应 → V1 LLM Judge 审查最终文本。Judge 输出无效或调用失败时，回退到“无工具且有最终文本即完成”的确定性规则；没有置信度字段。Judge Token 计入 Run 用量。'
          : 'Order: budgets and deadline → turn_status → repeated stalls → Flow boundary → Tools or empty response → V1 LLM Judge review of final text. Invalid Judge output or failure falls back to deterministic final-text completion. There is no confidence field. Judge usage counts toward the Run.',
    'sage.agent.continuation.explicit-status' =>
      zh
          ? '预算、截止时间、重复停滞和 Flow 边界继续生效。普通文本不会自动完成：Agent 必须调用 turn_status。task_done 完成；need_user_input / blocked 暂停；continue_work 继续；failed 失败。达到最大步数仍无显式状态时，Run 明确失败。不调用 LLM Judge，也不依赖 finish_reason。'
          : 'Budgets, deadlines, repeated stalls, and Flow boundaries remain active. Ordinary text never completes automatically: the Agent must call turn_status. task_done completes; need_user_input / blocked suspend; continue_work continues; failed fails. Missing status at the step limit explicitly fails the Run. No LLM Judge or finish_reason dependency.',
    _ =>
      zh
          ? '判定顺序：预算与截止时间 → turn_status → 重复停滞 → Flow 边界 → 工具或最终文本。工具调用后继续，空响应重试，无工具且有最终文本时完成。重复停滞 3 次请求用户介入。不调用 LLM Judge，也不依赖 finish_reason。'
          : 'Order: budgets and deadline → turn_status → repeated stalls → Flow boundary → Tools or final text. Tool calls continue, empty responses retry, and final text without Tools completes. Three repeated stalls ask the user. No LLM Judge or finish_reason dependency.',
  };
}

String _runtimeComponentPathLabel(String componentId, SageLocalizations l10n) =>
    switch (componentId) {
      'memory.provider' =>
        l10n.languageCode == 'zh' ? '当前记忆目录' : 'Current memory directory',
      'session-memory.provider' => l10n.text('component.path.sessionMemory'),
      'observability.diagnostic-sink' => l10n.text(
        'component.path.modelRequestRecords',
      ),
      'session.store' =>
        l10n.languageCode == 'zh' ? '当前会话目录' : 'Current Session directory',
      _ => l10n.languageCode == 'zh' ? '当前日志文件' : 'Current log file',
    };

String _componentScopeLabel(String value, SageLocalizations l10n) =>
    switch (value) {
      'process' => l10n.text('component.scope.process'),
      'tenant' => l10n.text('component.scope.tenant'),
      'agent' => l10n.text('component.scope.agent'),
      'run' => l10n.text('component.scope.run'),
      _ => value,
    };

class _ArchivedConversationSettings extends StatelessWidget {
  const _ArchivedConversationSettings({required this.controller});

  final WorkspaceController controller;

  Future<void> _delete(
    BuildContext context,
    ArchivedConversationEntry entry,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: GlassCard(
            padding: const EdgeInsets.fromLTRB(22, 20, 22, 16),
            shape: const LiquidRoundedSuperellipse(borderRadius: 20),
            useOwnLayer: true,
            settings: _glass(dialogContext),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  dialogContext.l10n.text('settings.deleteForeverNamed', {
                    'name': dialogContext.l10n.conversationTitle(
                      entry.conversation.title,
                    ),
                  }),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    dialogContext,
                  ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 20),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: () => Navigator.pop(dialogContext, false),
                      child: Text(dialogContext.l10n.text('common.cancel')),
                    ),
                    const SizedBox(width: 8),
                    GlassButton.custom(
                      key: const ValueKey(
                        'archived-conversation-delete-confirm',
                      ),
                      width: 94,
                      height: 36,
                      label: dialogContext.l10n.text('settings.deleteForever'),
                      onTap: () => Navigator.pop(dialogContext, true),
                      shape: const LiquidRoundedRectangle(borderRadius: 10),
                      settings: _glass(dialogContext),
                      child: Text(
                        dialogContext.l10n.text('settings.deleteForever'),
                        style: TextStyle(
                          color: Theme.of(dialogContext).colorScheme.error,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (confirmed != true) return;
    try {
      await controller.deleteConversation(entry.groupId, entry.conversation.id);
    } on Object {
      // The controller reports the error through the shared error banner.
    }
  }

  @override
  Widget build(BuildContext context) {
    final values = controller.archivedConversations;
    final colors = Theme.of(context).colorScheme;
    return _SettingsContent(
      title: context.l10n.text('settings.archive'),
      fillRemaining: true,
      children: [
        if (values.isEmpty)
          Center(
            child: Text(
              context.l10n.text('settings.emptyArchive'),
              key: const ValueKey('settings-archived-empty'),
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          )
        else
          ListView(
            key: const ValueKey('settings-archived-list'),
            padding: const EdgeInsets.only(right: 12, bottom: 8),
            children: [
              GlassGroupedSection(
                margin: EdgeInsets.zero,
                useOwnLayer: true,
                settings: _glass(context),
                shape: const LiquidRoundedSuperellipse(borderRadius: 14),
                children: [
                  for (final entry in values)
                    GlassListTile(
                      key: ValueKey(
                        'settings-archived-${entry.conversation.id}',
                      ),
                      leading: const Icon(CupertinoIcons.bubble_left, size: 17),
                      title: Text(
                        context.l10n.conversationTitle(
                          entry.conversation.title,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: _ArchivedConversationMetadata(
                        conversation: entry.conversation,
                        color: colors.onSurfaceVariant,
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          GlassButton.custom(
                            key: ValueKey(
                              'settings-archived-restore-${entry.conversation.id}',
                            ),
                            width: 62,
                            height: 32,
                            label: context.l10n.text('common.restore'),
                            onTap: () => controller.restoreConversation(
                              entry.groupId,
                              entry.conversation.id,
                            ),
                            shape: const LiquidRoundedRectangle(
                              borderRadius: 9,
                            ),
                            child: Text(context.l10n.text('common.restore')),
                          ),
                          const SizedBox(width: 8),
                          Tooltip(
                            message: context.l10n.text(
                              'settings.deleteForever',
                            ),
                            child: GlassIconButton(
                              key: ValueKey(
                                'settings-archived-delete-${entry.conversation.id}',
                              ),
                              size: 32,
                              iconSize: 15,
                              shape: GlassIconButtonShape.roundedSquare,
                              borderRadius: 9,
                              onPressed: () => _delete(context, entry),
                              icon: Icon(
                                CupertinoIcons.trash,
                                color: Theme.of(context).colorScheme.error,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ],
          ),
      ],
    );
  }
}

class _ArchivedConversationMetadata extends StatelessWidget {
  const _ArchivedConversationMetadata({
    required this.conversation,
    required this.color,
  });

  final Conversation conversation;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final preview = _archivedConversationPreview(conversation);
    final time = _formatArchivedConversationTime(
      _archivedConversationTimestamp(conversation),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (preview.isNotEmpty)
          Text(
            preview,
            key: ValueKey('settings-archived-preview-${conversation.id}'),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: color, height: 1.35),
          ),
        if (preview.isNotEmpty && time.isNotEmpty) const SizedBox(height: 3),
        if (time.isNotEmpty)
          Text(
            time,
            key: ValueKey('settings-archived-time-${conversation.id}'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: color.withValues(alpha: 0.78),
            ),
          ),
      ],
    );
  }
}

DateTime? _archivedConversationTimestamp(Conversation conversation) {
  for (final message in conversation.messages.reversed) {
    if (message.processOnly || message.text.trim().isEmpty) continue;
    return message.createdAt;
  }
  return conversation.archivedAt;
}

String _formatArchivedConversationTime(DateTime? value) {
  if (value == null) return '';
  final local = value.toLocal();
  String twoDigits(int part) => part.toString().padLeft(2, '0');
  return '${local.year}/${twoDigits(local.month)}/${twoDigits(local.day)} '
      '${twoDigits(local.hour)}:${twoDigits(local.minute)}';
}

String _archivedConversationPreview(Conversation conversation) {
  ChatMessage? selected;
  for (final message in conversation.messages.reversed) {
    if (message.processOnly || message.text.trim().isEmpty) continue;
    selected = message;
    break;
  }
  if (selected == null) return '';
  var value = selected.text;
  value = value.replaceAll(RegExp(r'^```[^\n]*', multiLine: true), '');
  value = value.replaceAll('```', '');
  value = value.replaceAllMapped(
    RegExp(r'!\[([^\]]*)\]\([^)]+\)'),
    (match) => match.group(1) ?? '',
  );
  value = value.replaceAllMapped(
    RegExp(r'\[([^\]]+)\]\([^)]+\)'),
    (match) => match.group(1) ?? '',
  );
  value = value.replaceAll(
    RegExp(r'^\s*(?:#{1,6}|>|[-+*]|\d+[.)])\s+', multiLine: true),
    '',
  );
  value = value.replaceAll(RegExp(r'\*\*|__|~~|`'), '');
  return value.replaceAll(RegExp(r'\s+'), ' ').trim();
}

class _SettingsRail extends StatelessWidget {
  const _SettingsRail({
    super.key,
    required this.selected,
    required this.onSelect,
    required this.onBack,
    this.horizontal = false,
  });
  final int selected;
  final ValueChanged<int> onSelect;
  final VoidCallback onBack;
  final bool horizontal;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final navItems = _navItems(context);
    return GlassCard(
      width: double.infinity,
      padding: EdgeInsets.zero,
      shape: const LiquidRoundedRectangle(borderRadius: 0),
      useOwnLayer: true,
      settings: desktopSidebarGlassSettings(context),
      child: DesktopSidebarSurface(
        child: horizontal
            ? Row(
                children: [
                  _CompactBack(onTap: onBack),
                  VerticalDivider(width: 1, color: colors.outlineVariant),
                  Expanded(
                    child: ListView.builder(
                      scrollDirection: Axis.horizontal,
                      itemCount: navItems.length,
                      itemBuilder: (context, index) => _NavButton(
                        label: navItems[index].$1,
                        icon: navItems[index].$2,
                        selected: selected == index,
                        onTap: () => onSelect(index),
                        compact: true,
                      ),
                    ),
                  ),
                ],
              )
            : Column(
                children: [
                  const SizedBox(height: desktopPaneHeaderHeight),
                  Expanded(
                    child: ListView.builder(
                      padding: const EdgeInsets.fromLTRB(12, 14, 12, 12),
                      itemCount: navItems.length,
                      itemBuilder: (context, index) => _NavButton(
                        label: navItems[index].$1,
                        icon: navItems[index].$2,
                        selected: selected == index,
                        onTap: () => onSelect(index),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(14, 2, 14, 8),
                    child: Semantics(
                      button: true,
                      label: context.l10n.text('settings.backWorkspace'),
                      child: InkWell(
                        key: const ValueKey('settings-back-button'),
                        borderRadius: BorderRadius.circular(9),
                        onTap: onBack,
                        child: SizedBox(
                          height: 36,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 10),
                            child: Row(
                              children: [
                                Icon(
                                  CupertinoIcons.arrow_left,
                                  size: 16,
                                  color: colors.onSurfaceVariant,
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Text(
                                    context.l10n.text('common.back'),
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelLarge
                                        ?.copyWith(
                                          fontSize: 13,
                                          color: colors.onSurface,
                                        ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

class _CompactBack extends StatelessWidget {
  const _CompactBack({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => IconButton(
    key: const ValueKey('settings-back-button'),
    tooltip: context.l10n.text('common.back'),
    onPressed: onTap,
    icon: const Icon(CupertinoIcons.arrow_left, size: 17),
  );
}

class _NavButton extends StatelessWidget {
  const _NavButton({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
    this.compact = false,
  });
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;
  final bool compact;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: compact
          ? const EdgeInsets.symmetric(horizontal: 2, vertical: 8)
          : const EdgeInsets.only(bottom: 3),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            color: selected
                ? colors.onSurface.withValues(alpha: 0.1)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            mainAxisSize: compact ? MainAxisSize.min : MainAxisSize.max,
            children: [
              Icon(
                icon,
                size: 17,
                color: selected ? colors.primary : colors.onSurfaceVariant,
              ),
              const SizedBox(width: 10),
              if (compact)
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 160),
                  child: Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                    ),
                  ),
                )
              else
                Expanded(
                  child: Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SettingsContent extends StatelessWidget {
  const _SettingsContent({
    required this.title,
    required this.children,
    this.action,
    this.status = false,
    this.fillRemaining = false,
  });
  final String title;
  final List<Widget> children;
  final Widget? action;
  final bool status;
  final bool fillRemaining;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              title,
              key: const ValueKey('settings-content-title'),
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 160),
            child: status
                ? const CupertinoActivityIndicator(
                    key: ValueKey('settings-saving'),
                  )
                : const SizedBox.shrink(key: ValueKey('settings-saved')),
          ),
          if (action != null) ...[const SizedBox(width: 14), action!],
        ],
      ),
      const SizedBox(height: 28),
      Expanded(
        child: fillRemaining
            ? (children.isEmpty ? const SizedBox.shrink() : children.single)
            : _SettingsBodyScroll(children: children),
      ),
    ],
  );
}

class _SettingsBodyScroll extends StatefulWidget {
  const _SettingsBodyScroll({required this.children});

  final List<Widget> children;

  @override
  State<_SettingsBodyScroll> createState() => _SettingsBodyScrollState();
}

class _SettingsBodyScrollState extends State<_SettingsBodyScroll> {
  final ScrollController _controller = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scrollbar(
    controller: _controller,
    thickness: 5,
    radius: const Radius.circular(3),
    child: SingleChildScrollView(
      key: const ValueKey('settings-body-scroll'),
      controller: _controller,
      primary: false,
      padding: const EdgeInsets.only(right: 12, bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var index = 0; index < widget.children.length; index++) ...[
            widget.children[index],
            if (index != widget.children.length - 1) const SizedBox(height: 14),
          ],
        ],
      ),
    ),
  );
}

class _LoadingContent extends StatelessWidget {
  const _LoadingContent({required this.title});
  final String title;
  @override
  Widget build(BuildContext context) => _SettingsContent(
    title: title,
    children: const [
      Center(
        child: Padding(
          padding: EdgeInsets.all(40),
          child: CupertinoActivityIndicator(),
        ),
      ),
    ],
  );
}

class _SettingsRowGroup extends StatelessWidget {
  const _SettingsRowGroup({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        for (var index = 0; index < children.length; index++) ...[
          children[index],
          if (index != children.length - 1)
            Divider(height: 1, color: colors.outlineVariant),
        ],
      ],
    );
  }
}

class _SecurityKeywordList extends StatelessWidget {
  const _SecurityKeywordList({
    required this.values,
    this.emptyLabel,
    this.onRemove,
  });

  final List<String> values;
  final String? emptyLabel;
  final ValueChanged<String>? onRemove;

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) {
      return Text(
        emptyLabel ?? '—',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
      );
    }
    return Wrap(
      spacing: 7,
      runSpacing: 7,
      children: [
        for (final value in values)
          InputChip(
            key: ValueKey('security-command:$value'),
            label: Text(
              value,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 11.5),
            ),
            visualDensity: VisualDensity.compact,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            onDeleted: onRemove == null ? null : () => onRemove!(value),
          ),
      ],
    );
  }
}

class _PickerOption<T> {
  const _PickerOption({required this.value, required this.label});

  final T value;
  final String label;
}

class _SettingsPicker<T> extends StatelessWidget {
  const _SettingsPicker({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    this.width = 250,
    this.enabled = true,
  });

  final T value;
  final List<_PickerOption<T>> options;
  final ValueChanged<T> onChanged;
  final double width;
  final bool enabled;

  _PickerOption<T>? get _selected {
    for (final option in options) {
      if (option.value == value) return option;
    }
    return options.isEmpty ? null : options.first;
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    return Semantics(
      button: true,
      enabled: enabled,
      value: selected?.label,
      child: IgnorePointer(
        ignoring: !enabled,
        child: AnimatedOpacity(
          duration: const Duration(milliseconds: 160),
          opacity: enabled ? 1 : 0.45,
          child: SizedBox(
            width: width,
            child: GlassPicker(
              value: selected?.label,
              onTap: () => _showOptions(context),
              height: 34,
              width: width,
              padding: const EdgeInsets.symmetric(horizontal: 11),
              useOwnLayer: true,
              settings: _glass(context),
              textStyle: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _showOptions(BuildContext context) {
    return showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360, maxHeight: 520),
          child: GlassCard(
            padding: const EdgeInsets.all(8),
            shape: const LiquidRoundedSuperellipse(borderRadius: 18),
            useOwnLayer: true,
            settings: _glass(dialogContext),
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final option in options)
                  Material(
                    color: Colors.transparent,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(11),
                      onTap: () {
                        Navigator.of(dialogContext).pop();
                        if (option.value != value) onChanged(option.value);
                      },
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                option.label,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            if (option.value == value)
                              Icon(
                                CupertinoIcons.checkmark,
                                size: 15,
                                color: Theme.of(
                                  dialogContext,
                                ).colorScheme.primary,
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SettingsActionButton extends StatelessWidget {
  const _SettingsActionButton({
    super.key,
    required this.onTap,
    required this.icon,
    required this.label,
    this.width = 88,
  });

  final VoidCallback? onTap;
  final Widget icon;
  final String label;
  final double width;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    enabled: onTap != null,
    label: label,
    child: IgnorePointer(
      ignoring: onTap == null,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 160),
        opacity: onTap == null ? 0.45 : 1,
        child: GlassButton.custom(
          width: width,
          height: 36,
          label: label,
          onTap: onTap ?? () {},
          shape: const LiquidRoundedRectangle(borderRadius: 10),
          settings: _glass(context),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [icon, const SizedBox(width: 7), Text(label)],
          ),
        ),
      ),
    ),
  );
}

class _SettingsTag extends StatelessWidget {
  const _SettingsTag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      constraints: const BoxConstraints(minHeight: 30),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: colors.onSurface.withValues(alpha: 0.055),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
      ),
      child: Text(
        label,
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _SettingsChoice {
  const _SettingsChoice({
    required this.id,
    required this.label,
    this.group = '',
    this.marked = false,
    this.removable = false,
    this.busy = false,
    this.removeKeyPrefix = 'settings-choice-delete',
  });

  final String id;
  final String label;
  final String group;
  final bool marked;
  final bool removable;
  final bool busy;
  final String removeKeyPrefix;
}

class _SettingsMasterDetail extends StatelessWidget {
  const _SettingsMasterDetail({
    required this.items,
    required this.selectedId,
    required this.onSelected,
    required this.detail,
    this.selectorKey,
    this.onRemove,
    this.onSetDefault,
  });

  final List<_SettingsChoice> items;
  final String selectedId;
  final ValueChanged<String> onSelected;
  final Widget detail;
  final Key? selectorKey;
  final ValueChanged<String>? onRemove;
  final Future<void> Function(String)? onSetDefault;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      if (constraints.maxWidth < 700) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _SettingsPicker<String>(
              key: selectorKey,
              width: constraints.maxWidth,
              value: items.any((value) => value.id == selectedId)
                  ? selectedId
                  : (items.isEmpty ? '' : items.first.id),
              options: [
                for (final item in items)
                  _PickerOption(
                    value: item.id,
                    label: item.group.isEmpty
                        ? item.label
                        : '${item.group} · ${item.label}',
                  ),
              ],
              onChanged: onSelected,
            ),
            const SizedBox(height: 22),
            Expanded(
              child: _SettingsDetailScroll(
                key: ValueKey('settings-detail-$selectedId'),
                child: detail,
              ),
            ),
          ],
        );
      }
      return Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            key: selectorKey,
            width: 250,
            child: _SettingsChoiceList(
              items: items,
              selectedId: selectedId,
              onSelected: onSelected,
              onRemove: onRemove,
              onSetDefault: onSetDefault,
            ),
          ),
          const SizedBox(width: 32),
          Expanded(
            child: _SettingsDetailScroll(
              key: ValueKey('settings-detail-$selectedId'),
              child: detail,
            ),
          ),
        ],
      );
    },
  );
}

class _SettingsDetailScroll extends StatefulWidget {
  const _SettingsDetailScroll({required this.child, super.key});

  final Widget child;

  @override
  State<_SettingsDetailScroll> createState() => _SettingsDetailScrollState();
}

class _SettingsDetailScrollState extends State<_SettingsDetailScroll> {
  final ScrollController _controller = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ScrollConfiguration(
    behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
    child: Scrollbar(
      controller: _controller,
      thumbVisibility: true,
      thickness: 5,
      radius: const Radius.circular(3),
      child: SingleChildScrollView(
        key: const ValueKey('settings-detail-scroll'),
        controller: _controller,
        primary: false,
        padding: const EdgeInsets.only(right: 16, bottom: 16),
        child: widget.child,
      ),
    ),
  );
}

class _SettingsChoiceList extends StatefulWidget {
  const _SettingsChoiceList({
    required this.items,
    required this.selectedId,
    required this.onSelected,
    this.onRemove,
    this.onSetDefault,
  });

  final List<_SettingsChoice> items;
  final String selectedId;
  final ValueChanged<String> onSelected;
  final ValueChanged<String>? onRemove;
  final Future<void> Function(String)? onSetDefault;

  @override
  State<_SettingsChoiceList> createState() => _SettingsChoiceListState();
}

class _SettingsChoiceListState extends State<_SettingsChoiceList> {
  final ScrollController _scrollController = ScrollController();

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    for (var index = 0; index < widget.items.length; index++) {
      final item = widget.items[index];
      final previousGroup = index == 0 ? null : widget.items[index - 1].group;
      if (item.group.isNotEmpty && item.group != previousGroup) {
        children.add(
          Padding(
            padding: EdgeInsets.fromLTRB(12, index == 0 ? 5 : 18, 8, 7),
            child: Text(
              item.group,
              key: ValueKey('settings-choice-group-${item.group}'),
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        );
      }
      children.add(
        _SettingsChoiceButton(
          item: item,
          selected: item.id == widget.selectedId,
          onTap: () => widget.onSelected(item.id),
          onRemove: item.removable && widget.onRemove != null
              ? () => widget.onRemove!(item.id)
              : null,
          onSetDefault: widget.onSetDefault == null
              ? null
              : () => widget.onSetDefault!(item.id),
        ),
      );
      final next = index + 1 < widget.items.length
          ? widget.items[index + 1]
          : null;
      if (next != null && (item.group.isEmpty || next.group == item.group)) {
        children.add(
          Divider(
            height: 1,
            color: Theme.of(context).colorScheme.outlineVariant,
          ),
        );
      }
    }
    return ScrollConfiguration(
      behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
      child: Scrollbar(
        controller: _scrollController,
        thumbVisibility: true,
        thickness: 5,
        radius: const Radius.circular(3),
        child: ListView(
          key: const ValueKey('settings-choice-list'),
          controller: _scrollController,
          primary: false,
          padding: const EdgeInsets.only(right: 8),
          children: children,
        ),
      ),
    );
  }
}

class _SettingsChoiceButton extends StatelessWidget {
  const _SettingsChoiceButton({
    required this.item,
    required this.selected,
    required this.onTap,
    this.onRemove,
    this.onSetDefault,
  });

  final _SettingsChoice item;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onRemove;
  final Future<void> Function()? onSetDefault;

  Future<void> _showContextMenu(
    BuildContext context,
    TapDownDetails details,
  ) async {
    if (onSetDefault == null) return;
    final overlay = Overlay.of(context).context.findRenderObject() as RenderBox;
    final colors = Theme.of(context).colorScheme;
    final point = details.globalPosition;
    final action = await showMenu<bool>(
      context: context,
      position: RelativeRect.fromLTRB(
        point.dx,
        point.dy,
        overlay.size.width - point.dx,
        overlay.size.height - point.dy,
      ),
      color: colors.surfaceContainerHigh.withValues(alpha: 0.98),
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.black.withValues(alpha: 0.3),
      elevation: 10,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(9),
        side: BorderSide(color: colors.outlineVariant.withValues(alpha: 0.8)),
      ),
      constraints: const BoxConstraints(minWidth: 120, maxWidth: 240),
      menuPadding: const EdgeInsets.all(4),
      items: [
        PopupMenuItem<bool>(
          key: ValueKey('settings-set-default-${item.id}'),
          value: true,
          enabled: !item.marked,
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                item.marked ? CupertinoIcons.star_fill : CupertinoIcons.star,
                size: 14,
                color: item.marked ? colors.primary : colors.onSurface,
              ),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  context.l10n.text(
                    item.marked
                        ? 'settings.currentDefault'
                        : 'settings.setAsDefault',
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: item.marked
                        ? colors.onSurfaceVariant
                        : colors.onSurface,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
    if (action == true && !item.marked) await onSetDefault!();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: EdgeInsets.zero,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onSecondaryTapDown: onSetDefault == null
            ? null
            : (details) => _showContextMenu(context, details),
        child: InkWell(
          borderRadius: BorderRadius.circular(11),
          mouseCursor: SystemMouseCursors.click,
          onTap: onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOutCubic,
            constraints: const BoxConstraints(minHeight: 46),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: selected
                  ? colors.onSurface.withValues(alpha: 0.1)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(11),
            ),
            child: Row(
              children: [
                Icon(
                  selected
                      ? CupertinoIcons.checkmark_circle_fill
                      : CupertinoIcons.circle,
                  size: 15,
                  color: selected ? colors.primary : colors.onSurfaceVariant,
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    item.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                    ),
                  ),
                ),
                if (item.marked)
                  Tooltip(
                    message: context.l10n.text('settings.currentDefault'),
                    child: Icon(
                      CupertinoIcons.star_fill,
                      size: 11,
                      color: colors.primary,
                    ),
                  ),
                if (onRemove != null) ...[
                  const SizedBox(width: 3),
                  Semantics(
                    button: true,
                    label: context.l10n.text('settings.deleteNamed', {
                      'name': item.label,
                    }),
                    child: item.busy
                        ? const SizedBox.square(
                            dimension: 30,
                            child: Center(
                              child: CupertinoActivityIndicator(radius: 7),
                            ),
                          )
                        : Tooltip(
                            message: context.l10n.text('settings.deleteNamed', {
                              'name': item.label,
                            }),
                            child: InkWell(
                              key: ValueKey(
                                '${item.removeKeyPrefix}-${item.id}',
                              ),
                              borderRadius: BorderRadius.circular(7),
                              onTap: onRemove,
                              child: Padding(
                                padding: const EdgeInsets.all(7),
                                child: Icon(
                                  CupertinoIcons.trash,
                                  size: 14,
                                  color: colors.error,
                                ),
                              ),
                            ),
                          ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SettingsRow extends StatelessWidget {
  const _SettingsRow({
    required this.label,
    required this.control,
    this.description,
  });
  final String label;
  final Widget control;
  final String? description;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final labelWidget = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
          ),
          if (description != null) ...[
            const SizedBox(height: 3),
            Text(
              description!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
                height: 1.3,
              ),
            ),
          ],
        ],
      );
      if (constraints.maxWidth < 560) {
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              labelWidget,
              const SizedBox(height: 9),
              Align(alignment: Alignment.centerLeft, child: control),
            ],
          ),
        );
      }
      return ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 50),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          child: Row(
            children: [
              Expanded(child: labelWidget),
              const SizedBox(width: 24),
              Flexible(child: control),
            ],
          ),
        ),
      );
    },
  );
}

class _AgentTextRow extends StatelessWidget {
  const _AgentTextRow({
    this.fieldKey,
    required this.label,
    required this.value,
    required this.controller,
    required this.editing,
    required this.onChanged,
  });
  final Key? fieldKey;
  final String label;
  final String value;
  final TextEditingController controller;
  final bool editing;
  final ValueChanged<String> onChanged;
  @override
  Widget build(BuildContext context) => _SettingsRow(
    label: label,
    control: editing
        ? SizedBox(
            width: 390,
            child: GlassTextField(
              key: fieldKey,
              controller: controller,
              height: 36,
              padding: const EdgeInsets.symmetric(horizontal: 11),
              useOwnLayer: true,
              settings: _glass(context),
              onChanged: onChanged,
            ),
          )
        : Text(value, textAlign: TextAlign.end),
  );
}

class _AgentLargeField extends StatelessWidget {
  const _AgentLargeField({
    required this.label,
    required this.value,
    required this.controller,
    required this.editing,
    required this.onChanged,
    this.view,
  });
  final String label;
  final String value;
  final TextEditingController controller;
  final bool editing;
  final ValueChanged<String> onChanged;
  final Widget? view;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: Theme.of(
          context,
        ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 10),
      if (editing)
        GlassTextField(
          controller: controller,
          minLines: 3,
          maxLines: 8,
          minHeight: 92,
          maxHeight: 150,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          useOwnLayer: true,
          settings: _glass(context),
          onChanged: onChanged,
        )
      else
        view ?? SelectableText(value.isEmpty ? '—' : value),
    ],
  );
}

class _SystemPromptMarkdown extends StatelessWidget {
  const _SystemPromptMarkdown({required this.value});

  final String value;

  @override
  Widget build(BuildContext context) {
    if (value.trim().isEmpty) return const Text('—');
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final base = MarkdownStyleSheet.fromTheme(theme);
    return Padding(
      key: const ValueKey('agent-system-prompt-markdown'),
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: MarkdownBody(
        data: value,
        selectable: true,
        styleSheet: base.copyWith(
          p: theme.textTheme.bodyMedium?.copyWith(height: 1.5),
          code: theme.textTheme.bodySmall?.copyWith(
            fontFamily: 'Menlo',
            color: colors.onSurface,
            backgroundColor: colors.onSurface.withValues(alpha: 0.08),
          ),
          codeblockDecoration: BoxDecoration(
            color: colors.onSurface.withValues(alpha: 0.06),
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
    );
  }
}

class _RuntimeVariablesField extends StatelessWidget {
  const _RuntimeVariablesField({
    required this.value,
    required this.editing,
    required this.onChanged,
  });

  final Map<String, Object?> value;
  final bool editing;
  final ValueChanged<Map<String, Object?>> onChanged;

  @override
  Widget build(BuildContext context) => Column(
    key: const ValueKey('agent-runtime-variables'),
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        context.l10n.text('agent.systemContext'),
        style: Theme.of(
          context,
        ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 10),
      if (editing)
        _RuntimeVariablesEditor(value: value, onChanged: onChanged)
      else
        _RuntimeVariablesView(value: value),
    ],
  );
}

class _RuntimeVariablesEditor extends StatefulWidget {
  const _RuntimeVariablesEditor({required this.value, required this.onChanged});

  final Map<String, Object?> value;
  final ValueChanged<Map<String, Object?>> onChanged;

  @override
  State<_RuntimeVariablesEditor> createState() =>
      _RuntimeVariablesEditorState();
}

class _RuntimeVariablesEditorState extends State<_RuntimeVariablesEditor> {
  late Map<String, Object?> _draft;
  late String _sourceSignature;

  @override
  void initState() {
    super.initState();
    _sourceSignature = jsonEncode(widget.value);
    _draft = _copyRuntimeVariables(widget.value);
  }

  @override
  void didUpdateWidget(covariant _RuntimeVariablesEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    final nextSignature = jsonEncode(widget.value);
    if (nextSignature == _sourceSignature) return;
    _sourceSignature = nextSignature;
    _draft = _copyRuntimeVariables(widget.value);
  }

  void _change(Map<String, Object?> value) {
    setState(() => _draft = value);
    widget.onChanged(value);
  }

  @override
  Widget build(BuildContext context) => _RuntimeVariableMapEditor(
    key: const ValueKey('agent-runtime-variables-editor'),
    value: _draft,
    onChanged: _change,
  );
}

Map<String, Object?> _copyRuntimeVariables(Map<String, Object?> value) {
  final decoded = jsonDecode(jsonEncode(value));
  return decoded is Map ? decoded.cast<String, Object?>() : <String, Object?>{};
}

class _RuntimeVariableMapEditor extends StatelessWidget {
  const _RuntimeVariableMapEditor({
    required this.value,
    required this.onChanged,
    this.nested = false,
    super.key,
  });

  final Map<String, Object?> value;
  final ValueChanged<Map<String, Object?>> onChanged;
  final bool nested;

  void _replace(String key, Object? nextValue) {
    final next = Map<String, Object?>.of(value)..[key] = nextValue;
    onChanged(next);
  }

  bool _rename(String oldKey, String candidate) {
    final nextKey = candidate.trim();
    if (nextKey.isEmpty || (nextKey != oldKey && value.containsKey(nextKey))) {
      return false;
    }
    if (nextKey == oldKey) return true;
    final next = <String, Object?>{};
    for (final entry in value.entries) {
      next[entry.key == oldKey ? nextKey : entry.key] = entry.value;
    }
    onChanged(next);
    return true;
  }

  void _remove(String key) {
    final next = Map<String, Object?>.of(value)..remove(key);
    onChanged(next);
  }

  void _add() {
    var index = 1;
    var key = 'variable';
    while (value.containsKey(key)) {
      index += 1;
      key = 'variable_$index';
    }
    final next = Map<String, Object?>.of(value)..[key] = '';
    onChanged(next);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final content = Column(
      children: [
        for (final entry in value.entries) ...[
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: nested ? 126 : 160,
                  child: _RuntimeVariableKeyInput(
                    key: ValueKey('runtime-variable-key:${entry.key}'),
                    value: entry.key,
                    onCommitted: (next) => _rename(entry.key, next),
                  ),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: _RuntimeVariableValueEditor(
                    key: ValueKey('runtime-variable-value:${entry.key}'),
                    value: entry.value,
                    onChanged: (next) => _replace(entry.key, next),
                  ),
                ),
                const SizedBox(width: 3),
                IconButton(
                  key: ValueKey('runtime-variable-delete:${entry.key}'),
                  tooltip: context.l10n.text('common.delete'),
                  visualDensity: VisualDensity.compact,
                  icon: Icon(
                    CupertinoIcons.trash,
                    size: 15,
                    color: colors.error,
                  ),
                  onPressed: () => _remove(entry.key),
                ),
              ],
            ),
          ),
          Divider(height: 1, color: colors.outlineVariant),
        ],
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            key: ValueKey(
              nested ? 'runtime-variable-add-nested' : 'runtime-variable-add',
            ),
            onPressed: _add,
            icon: const Icon(CupertinoIcons.add, size: 14),
            label: Text(context.l10n.text('agent.addRuntimeVariable')),
          ),
        ),
      ],
    );
    if (!nested) return content;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 4, 8, 2),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
      ),
      child: content,
    );
  }
}

class _RuntimeVariableKeyInput extends StatefulWidget {
  const _RuntimeVariableKeyInput({
    required this.value,
    required this.onCommitted,
    super.key,
  });

  final String value;
  final bool Function(String value) onCommitted;

  @override
  State<_RuntimeVariableKeyInput> createState() =>
      _RuntimeVariableKeyInputState();
}

class _RuntimeVariableKeyInputState extends State<_RuntimeVariableKeyInput> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.value,
  );

  @override
  void didUpdateWidget(covariant _RuntimeVariableKeyInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != oldWidget.value && _controller.text != widget.value) {
      _controller.text = widget.value;
    }
  }

  void _commit() {
    if (!widget.onCommitted(_controller.text)) {
      _controller.text = widget.value;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => GlassTextField(
    controller: _controller,
    height: 34,
    padding: const EdgeInsets.symmetric(horizontal: 9),
    placeholder: context.l10n.text('agent.runtimeVariableKey'),
    useOwnLayer: true,
    settings: _glass(context),
    onSubmitted: (_) => _commit(),
    onTapOutside: (_) {
      _commit();
      FocusManager.instance.primaryFocus?.unfocus();
    },
  );
}

class _RuntimeVariableValueEditor extends StatelessWidget {
  const _RuntimeVariableValueEditor({
    required this.value,
    required this.onChanged,
    super.key,
  });

  final Object? value;
  final ValueChanged<Object?> onChanged;

  @override
  Widget build(BuildContext context) {
    final raw = value;
    if (raw is Map) {
      return _RuntimeVariableMapEditor(
        value: raw.cast<String, Object?>(),
        nested: true,
        onChanged: onChanged,
      );
    }
    if (raw is List) {
      return _RuntimeVariableListEditor(value: raw, onChanged: onChanged);
    }
    if (raw is bool) {
      return SizedBox(
        height: 34,
        child: Row(
          children: [
            Switch.adaptive(value: raw, onChanged: onChanged),
            const SizedBox(width: 6),
            Text(raw.toString()),
          ],
        ),
      );
    }
    return _RuntimeVariableScalarInput(value: raw, onChanged: onChanged);
  }
}

class _RuntimeVariableScalarInput extends StatefulWidget {
  const _RuntimeVariableScalarInput({
    required this.value,
    required this.onChanged,
  });

  final Object? value;
  final ValueChanged<Object?> onChanged;

  @override
  State<_RuntimeVariableScalarInput> createState() =>
      _RuntimeVariableScalarInputState();
}

class _RuntimeVariableScalarInputState
    extends State<_RuntimeVariableScalarInput> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.value?.toString() ?? '',
  );

  @override
  void didUpdateWidget(covariant _RuntimeVariableScalarInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    final next = widget.value?.toString() ?? '';
    if (widget.value != oldWidget.value && _controller.text != next) {
      _controller.text = next;
    }
  }

  void _change(String text) {
    final raw = widget.value;
    if (raw is int) {
      final parsed = int.tryParse(text);
      if (parsed != null) widget.onChanged(parsed);
      return;
    }
    if (raw is double) {
      final parsed = double.tryParse(text);
      if (parsed != null) widget.onChanged(parsed);
      return;
    }
    widget.onChanged(text);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => GlassTextField(
    controller: _controller,
    height: 34,
    padding: const EdgeInsets.symmetric(horizontal: 9),
    placeholder: context.l10n.text('agent.runtimeVariableValue'),
    useOwnLayer: true,
    settings: _glass(context),
    onChanged: _change,
  );
}

class _RuntimeVariableListEditor extends StatelessWidget {
  const _RuntimeVariableListEditor({
    required this.value,
    required this.onChanged,
  });

  final List<Object?> value;
  final ValueChanged<Object?> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.fromLTRB(9, 4, 7, 2),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
      ),
      child: Column(
        children: [
          for (var index = 0; index < value.length; index++)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: 28, child: Text('${index + 1}.')),
                Expanded(
                  child: _RuntimeVariableValueEditor(
                    value: value[index],
                    onChanged: (nextValue) {
                      final next = List<Object?>.of(value)..[index] = nextValue;
                      onChanged(next);
                    },
                  ),
                ),
                IconButton(
                  tooltip: context.l10n.text('common.delete'),
                  visualDensity: VisualDensity.compact,
                  icon: Icon(
                    CupertinoIcons.trash,
                    size: 14,
                    color: colors.error,
                  ),
                  onPressed: () {
                    final next = List<Object?>.of(value)..removeAt(index);
                    onChanged(next);
                  },
                ),
              ],
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => onChanged([...value, '']),
              icon: const Icon(CupertinoIcons.add, size: 14),
              label: Text(context.l10n.text('common.add')),
            ),
          ),
        ],
      ),
    );
  }
}

class _RuntimeVariablesView extends StatelessWidget {
  const _RuntimeVariablesView({required this.value});

  final Map<String, Object?> value;

  @override
  Widget build(BuildContext context) {
    if (value.isEmpty) return const Text('—');
    return _RuntimeVariableReadOnlyMap(
      key: const ValueKey('agent-runtime-variables-formatted'),
      value: value,
    );
  }
}

class _RuntimeVariableReadOnlyMap extends StatelessWidget {
  const _RuntimeVariableReadOnlyMap({
    required this.value,
    this.nested = false,
    super.key,
  });

  final Map<String, Object?> value;
  final bool nested;

  @override
  Widget build(BuildContext context) {
    final entries = value.entries.toList()
      ..sort((left, right) => left.key.compareTo(right.key));
    final colors = Theme.of(context).colorScheme;
    final content = Column(
      children: [
        for (var index = 0; index < entries.length; index++) ...[
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 9),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: nested ? 126 : 150,
                  child: SelectableText(
                    entries[index].key,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: _RuntimeVariableReadOnlyValue(
                    value: entries[index].value,
                  ),
                ),
              ],
            ),
          ),
          if (index != entries.length - 1)
            Divider(height: 1, color: colors.outlineVariant),
        ],
      ],
    );
    if (!nested) return content;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.22),
        borderRadius: BorderRadius.circular(9),
      ),
      child: content,
    );
  }
}

class _RuntimeVariableReadOnlyValue extends StatelessWidget {
  const _RuntimeVariableReadOnlyValue({required this.value});

  final Object? value;

  @override
  Widget build(BuildContext context) {
    final raw = value;
    if (raw is Map) {
      if (raw.isEmpty) return const Text('—');
      return _RuntimeVariableReadOnlyMap(
        value: raw.cast<String, Object?>(),
        nested: true,
      );
    }
    if (raw is List) {
      if (raw.isEmpty) return const Text('—');
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var index = 0; index < raw.length; index++)
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(width: 28, child: Text('${index + 1}.')),
                  Expanded(
                    child: _RuntimeVariableReadOnlyValue(value: raw[index]),
                  ),
                ],
              ),
            ),
        ],
      );
    }
    return SelectableText(raw?.toString() ?? 'null');
  }
}

class _AssignmentSection extends StatelessWidget {
  const _AssignmentSection({
    required this.title,
    required this.selected,
    required this.editing,
    required this.onToggle,
    this.values = const [],
    this.groups = const [],
    this.labels = const {},
    this.description,
  });
  final String title;
  final String? description;
  final Iterable<String> values;
  final List<_AssignmentGroup> groups;
  final Map<String, String> labels;
  final Set<String> selected;
  final bool editing;
  final ValueChanged<String> onToggle;
  @override
  Widget build(BuildContext context) {
    final sourceGroups = groups.isEmpty
        ? [_AssignmentGroup(label: '', values: values.toList())]
        : groups;
    final visibleGroups = [
      for (final group in sourceGroups)
        (
          label: group.label,
          values: [
            for (final value in group.values)
              if (editing || selected.contains(value)) value,
          ],
        ),
    ];
    visibleGroups.removeWhere((group) => group.values.isEmpty);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(
            context,
          ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
        ),
        if (description case final description?) ...[
          const SizedBox(height: 5),
          Text(
            description,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        const SizedBox(height: 10),
        if (visibleGroups.isEmpty)
          const Text('—')
        else
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var index = 0; index < visibleGroups.length; index++) ...[
                if (index > 0) const SizedBox(height: 14),
                if (visibleGroups[index].label.isNotEmpty) ...[
                  Text(
                    visibleGroups[index].label,
                    key: ValueKey(
                      'assignment-group-$title-${visibleGroups[index].label}',
                    ),
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 7),
                ],
                Wrap(
                  spacing: 7,
                  runSpacing: 7,
                  children: [
                    for (final value in visibleGroups[index].values)
                      _AssignmentItem(
                        key: ValueKey('assignment-$title-$value'),
                        value: labels[value] ?? value,
                        selected: selected.contains(value),
                        enabled: editing,
                        onTap: () => onToggle(value),
                      ),
                  ],
                ),
              ],
            ],
          ),
      ],
    );
  }
}

class _AssignmentGroup {
  const _AssignmentGroup({required this.label, required this.values});

  final String label;
  final List<String> values;
}

List<_AssignmentGroup> _toolAssignmentGroups(
  Iterable<ToolSummary> tools,
  SageLocalizations l10n,
) {
  final grouped = <String, List<String>>{};
  for (final tool in tools) {
    final source = _toolGroupLabel(tool, l10n);
    grouped.putIfAbsent(source, () => []).add(tool.name);
  }
  return [
    for (final entry in grouped.entries)
      _AssignmentGroup(label: entry.key, values: entry.value),
  ];
}

String _toolGroupLabel(ToolSummary tool, SageLocalizations l10n) {
  final category = tool.category.trim();
  if (category.isNotEmpty) {
    final labels = l10n.languageCode == 'zh'
        ? const <String, String>{
            'code_quality': '代码质量',
            'code_search': '代码检索',
            'files': '文件',
            'image': '图像',
            'interaction': '交互',
            'memory': '记忆',
            'multi_agent': '多智能体',
            'planning': '任务规划',
            'shell': '终端',
            'system': '系统',
            'web': '网页',
          }
        : const <String, String>{
            'code_quality': 'Code quality',
            'code_search': 'Code search',
            'files': 'Files',
            'image': 'Image',
            'interaction': 'Interaction',
            'memory': 'Memory',
            'multi_agent': 'Multi-agent',
            'planning': 'Planning',
            'shell': 'Terminal',
            'system': 'System',
            'web': 'Web',
          };
    return labels[category] ?? category;
  }
  final source = tool.source.trim();
  return source.isEmpty ? l10n.text('tool.baseTools') : source;
}

class _AssignmentItem extends StatelessWidget {
  const _AssignmentItem({
    super.key,
    required this.value,
    required this.selected,
    required this.enabled,
    required this.onTap,
  });

  final String value;
  final bool selected;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      button: enabled,
      selected: selected,
      label: value,
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        mouseCursor: enabled
            ? SystemMouseCursors.click
            : SystemMouseCursors.basic,
        onTap: enabled ? onTap : null,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          constraints: const BoxConstraints(minHeight: 32),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: selected
                ? colors.onSurface.withValues(alpha: 0.08)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: selected
                  ? colors.primary.withValues(alpha: 0.18)
                  : colors.outlineVariant.withValues(alpha: 0.7),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                selected ? CupertinoIcons.checkmark : CupertinoIcons.circle,
                size: 13,
                color: selected ? colors.primary : colors.onSurfaceVariant,
              ),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: selected
                        ? colors.onSurface
                        : colors.onSurfaceVariant,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ModelSettings extends StatefulWidget {
  const _ModelSettings({required this.controller});
  final WorkspaceController controller;

  @override
  State<_ModelSettings> createState() => _ModelSettingsState();
}

class _ModelSettingsState extends State<_ModelSettings> {
  bool _editing = false;
  bool _creating = false;
  bool _saving = false;
  bool _dirty = false;
  bool _apiKeyVisible = false;
  bool _revealingApiKey = false;
  String? _deletingId;
  String _selectedId = '';
  String _syncedId = '';
  String _protocol = 'openai-responses';
  String? _detectionError;
  bool _detected = false;
  final _name = TextEditingController();
  final _baseUrl = TextEditingController();
  final _model = TextEditingController();
  final _apiKey = TextEditingController();
  final _maxTokens = TextEditingController();
  final _temperature = TextEditingController();
  final _topP = TextEditingController();
  final _maxModelLength = TextEditingController();

  @override
  void dispose() {
    for (final value in [
      _name,
      _baseUrl,
      _model,
      _apiKey,
      _maxTokens,
      _temperature,
      _topP,
      _maxModelLength,
    ]) {
      value.dispose();
    }
    super.dispose();
  }

  ModelProviderSummary? get _selected {
    if (_creating) return null;
    final values = widget.controller.modelProviders;
    if (values.isEmpty) return null;
    _selectedId = values.any((value) => value.id == _selectedId)
        ? _selectedId
        : values.first.id;
    return values.firstWhere((value) => value.id == _selectedId);
  }

  void _sync(ModelProviderSummary value) {
    if (_syncedId == value.id) return;
    _syncedId = value.id;
    _name.text = value.name;
    _protocol = value.protocol;
    _baseUrl.text = value.baseUrl;
    _model.text = value.model;
    _apiKey.clear();
    _apiKeyVisible = false;
    _revealingApiKey = false;
    _maxTokens.text = value.maxTokens?.toString() ?? '';
    _temperature.text = value.temperature?.toString() ?? '';
    _topP.text = value.topP?.toString() ?? '';
    _maxModelLength.text = value.maxModelLength?.toString() ?? '';
    _dirty = false;
  }

  Future<void> _toggleApiKey(ModelProviderSummary selected) async {
    if (_apiKeyVisible) {
      setState(() => _apiKeyVisible = false);
      return;
    }
    if (_apiKey.text.isNotEmpty || !selected.apiKeyConfigured) {
      setState(() => _apiKeyVisible = true);
      return;
    }
    setState(() {
      _revealingApiKey = true;
      _detectionError = null;
    });
    try {
      final value = await widget.controller.revealModelProviderApiKey(
        selected.id,
      );
      if (!mounted || selected.id != _selectedId) return;
      _apiKey.text = value;
      setState(() => _apiKeyVisible = true);
    } on Object {
      if (mounted && selected.id == _selectedId) {
        setState(
          () => _detectionError = context.l10n.text('model.apiKeyReadFailed'),
        );
      }
    } finally {
      if (mounted && selected.id == _selectedId) {
        setState(() => _revealingApiKey = false);
      }
    }
  }

  Future<void> _deleteProvider(String providerId) async {
    ModelProviderSummary? provider;
    for (final value in widget.controller.modelProviders) {
      if (value.id == providerId) {
        provider = value;
        break;
      }
    }
    if (provider == null || _deletingId != null) return;
    final target = provider;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          context.l10n.text('settings.deleteNamed', {'name': target.name}),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(context.l10n.text('common.cancel')),
          ),
          FilledButton(
            key: const ValueKey('settings-model-delete-confirm'),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(context.l10n.text('common.delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deletingId = providerId);
    try {
      await widget.controller.deleteModelProvider(providerId);
      if (!mounted) return;
      final remaining = widget.controller.modelProviders;
      setState(() {
        _selectedId = remaining.isEmpty ? '' : remaining.first.id;
        _syncedId = '';
        _editing = false;
        _apiKeyVisible = false;
      });
    } on Object {
      // WorkspaceController exposes the backend error in the shared banner.
    } finally {
      if (mounted) setState(() => _deletingId = null);
    }
  }

  Future<void> _setDefaultProvider(String providerId) async {
    if (_saving || providerId.isEmpty) return;
    ModelProviderSummary? provider;
    for (final value in widget.controller.modelProviders) {
      if (value.id == providerId) {
        provider = value;
        break;
      }
    }
    if (provider == null || provider.isDefault) return;
    setState(() => _saving = true);
    try {
      await widget.controller.setDefaultModelProvider(providerId);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _markDraftChanged() {
    if (_dirty && _detectionError == null && !_detected) return;
    setState(() {
      _dirty = true;
      _detectionError = null;
      _detected = false;
    });
  }

  void _startCreating() {
    if (_saving || _editing) return;
    setState(() {
      _creating = true;
      _editing = true;
      _selectedId = '';
      _syncedId = '';
      _protocol = 'openai-responses';
      _name.text = context.l10n.text('settings.newModel');
      _baseUrl.text = 'https://api.openai.com/v1';
      _model.text = 'gpt-5.4';
      _apiKey.clear();
      _maxTokens.text = '8192';
      _temperature.clear();
      _topP.clear();
      _maxModelLength.text = '128000';
      _dirty = true;
      _apiKeyVisible = false;
      _detectionError = null;
      _detected = false;
    });
  }

  Map<String, Object?>? _draftPatch() {
    int? integer(TextEditingController controller) {
      final value = controller.text.trim();
      if (value.isEmpty) return null;
      return int.tryParse(value);
    }

    double? decimal(TextEditingController controller) {
      final value = controller.text.trim();
      if (value.isEmpty) return null;
      return double.tryParse(value);
    }

    if ((_maxTokens.text.trim().isNotEmpty && integer(_maxTokens) == null) ||
        (_maxModelLength.text.trim().isNotEmpty &&
            integer(_maxModelLength) == null) ||
        (_temperature.text.trim().isNotEmpty &&
            decimal(_temperature) == null) ||
        (_topP.text.trim().isNotEmpty && decimal(_topP) == null)) {
      return null;
    }
    final maxTokens = integer(_maxTokens);
    final maxModelLength = integer(_maxModelLength);
    return {
      'name': _name.text.trim(),
      'protocol': _protocol,
      'base_url': _baseUrl.text.trim(),
      'model': _model.text.trim(),
      if (_apiKey.text.trim().isNotEmpty) 'api_keys': [_apiKey.text.trim()],
      'max_tokens': ?maxTokens,
      'temperature': decimal(_temperature),
      'top_p': decimal(_topP),
      'max_model_len': ?maxModelLength,
    };
  }

  Future<void> _verifyAndApply() async {
    if (!mounted || (!_creating && _selectedId.isEmpty) || _saving || !_dirty) {
      return;
    }
    final providerId = _selectedId;
    final patch = _draftPatch();
    if (patch == null) {
      setState(
        () => _detectionError = context.l10n.text('model.invalidFormat'),
      );
      return;
    }
    setState(() {
      _saving = true;
      _detectionError = null;
      _detected = false;
    });
    try {
      if (_creating) {
        final created = await widget.controller.createModelProvider(patch);
        if (!mounted) return;
        _selectedId = created.id;
        _syncedId = '';
        _creating = false;
      } else {
        await widget.controller.patchModelProvider(providerId, patch);
      }
      if (mounted) {
        setState(() {
          _dirty = false;
          _detected = false;
          _editing = false;
          _creating = false;
          _syncedId = '';
        });
      }
    } on Object {
      if (mounted && providerId == _selectedId) {
        setState(
          () => _detectionError = context.l10n.text('model.invalidConfig'),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _toggleEditing() {
    if (_saving) return;
    setState(() {
      if (_editing) {
        _syncedId = '';
        _dirty = false;
        _apiKeyVisible = false;
        _creating = false;
      }
      _editing = !_editing;
      _detectionError = null;
      _detected = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    if (selected == null && !_creating) {
      return _SettingsContent(
        title: context.l10n.text('settings.models'),
        children: const [],
      );
    }
    final displayed =
        selected ??
        ModelProviderSummary(
          id: '',
          name: context.l10n.text('settings.newModel'),
          model: 'gpt-5.4',
          baseUrl: 'https://api.openai.com/v1',
          supportsMultimodal: true,
          supportsStructuredOutput: true,
          maxTokens: 8192,
          maxModelLength: 128000,
        );
    if (!_creating) _sync(displayed);
    Widget field(
      String label,
      String value,
      TextEditingController controller, {
      bool secret = false,
      Key? fieldKey,
    }) {
      final canReveal =
          secret && (displayed.apiKeyConfigured || controller.text.isNotEmpty);
      final revealButton = secret
          ? Semantics(
              button: true,
              label: context.l10n.text(
                _apiKeyVisible ? 'model.hideApiKey' : 'model.showApiKey',
              ),
              child: _revealingApiKey
                  ? const SizedBox.square(
                      dimension: 32,
                      child: Center(
                        child: CupertinoActivityIndicator(radius: 8),
                      ),
                    )
                  : IconButton(
                      key: const ValueKey('settings-model-api-key-toggle'),
                      tooltip: context.l10n.text(
                        _apiKeyVisible
                            ? 'model.hideApiKey'
                            : 'model.showApiKey',
                      ),
                      onPressed: canReveal
                          ? () => _toggleApiKey(displayed)
                          : null,
                      icon: Icon(
                        _apiKeyVisible
                            ? CupertinoIcons.eye_slash
                            : CupertinoIcons.eye,
                        size: 17,
                      ),
                    ),
            )
          : null;
      return _SettingsRow(
        label: label,
        control: _editing
            ? SizedBox(
                width: 380,
                child: GlassTextField(
                  key: fieldKey,
                  controller: controller,
                  height: 36,
                  padding: const EdgeInsets.symmetric(horizontal: 11),
                  useOwnLayer: true,
                  settings: _glass(context),
                  obscureText: secret && !_apiKeyVisible,
                  placeholder: secret && displayed.apiKeyConfigured
                      ? context.l10n.text('model.keepApiKey')
                      : null,
                  suffixIcon: secret
                      ? (_revealingApiKey
                            ? const CupertinoActivityIndicator(radius: 7)
                            : Icon(
                                key: const ValueKey(
                                  'settings-model-api-key-toggle',
                                ),
                                _apiKeyVisible
                                    ? CupertinoIcons.eye_slash
                                    : CupertinoIcons.eye,
                                size: 16,
                              ))
                      : null,
                  onSuffixTap: secret && canReveal
                      ? () => _toggleApiKey(displayed)
                      : null,
                  onChanged: (_) => _markDraftChanged(),
                ),
              )
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Flexible(
                    child: SelectableText(
                      secret && _apiKeyVisible
                          ? controller.text
                          : (value.isEmpty ? '—' : value),
                      textAlign: TextAlign.end,
                    ),
                  ),
                  if (revealButton != null) ...[
                    const SizedBox(width: 6),
                    revealButton,
                  ],
                ],
              ),
      );
    }

    return _SettingsContent(
      title: context.l10n.text('settings.models'),
      fillRemaining: true,
      action: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_detectionError != null) ...[
            Text(
              _detectionError!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
            const SizedBox(width: 12),
          ],
          if (_editing) ...[
            _SettingsActionButton(
              key: const ValueKey('settings-model-cancel'),
              onTap: _saving ? null : _toggleEditing,
              icon: const Icon(CupertinoIcons.xmark, size: 15),
              label: context.l10n.text('common.cancel'),
            ),
            const SizedBox(width: 10),
            _SettingsActionButton(
              key: const ValueKey('settings-model-save'),
              onTap: _saving || !_dirty ? null : _verifyAndApply,
              icon: const Icon(CupertinoIcons.checkmark, size: 15),
              label: context.l10n.text('common.save'),
            ),
          ] else ...[
            if (!_creating) ...[
              _SettingsActionButton(
                key: const ValueKey('settings-model-set-default'),
                onTap: _saving || displayed.isDefault
                    ? null
                    : () => _setDefaultProvider(displayed.id),
                icon: Icon(
                  displayed.isDefault
                      ? CupertinoIcons.star_fill
                      : CupertinoIcons.star,
                  size: 15,
                ),
                label: context.l10n.text(
                  displayed.isDefault
                      ? 'settings.currentDefault'
                      : 'settings.setAsDefault',
                ),
              ),
              const SizedBox(width: 10),
            ],
            _SettingsActionButton(
              key: const ValueKey('settings-model-add'),
              onTap: _saving ? null : _startCreating,
              icon: const Icon(CupertinoIcons.add, size: 15),
              label: context.l10n.text('common.add'),
            ),
            const SizedBox(width: 10),
            _SettingsActionButton(
              key: const ValueKey('settings-model-edit'),
              onTap: _saving ? null : _toggleEditing,
              icon: const Icon(CupertinoIcons.pencil, size: 15),
              label: context.l10n.text('common.edit'),
            ),
          ],
        ],
      ),
      children: [
        _SettingsMasterDetail(
          selectorKey: const ValueKey('settings-model-picker'),
          items: [
            if (_creating)
              _SettingsChoice(
                id: '__new_model__',
                label: context.l10n.text('settings.newModel'),
              ),
            for (final value in widget.controller.modelProviders)
              _SettingsChoice(
                id: value.id,
                label: value.name,
                marked: value.isDefault,
                removable:
                    widget.controller.modelProviders.length > 1 && !_saving,
                busy: _deletingId == value.id,
                removeKeyPrefix: 'settings-model-delete',
              ),
          ],
          selectedId: _creating ? '__new_model__' : _selectedId,
          onSelected: (value) => setState(() {
            _creating = false;
            _selectedId = value;
            _syncedId = '';
            _editing = false;
            _apiKeyVisible = false;
            _revealingApiKey = false;
            _detectionError = null;
            _detected = false;
            _dirty = false;
          }),
          onRemove: _deleteProvider,
          onSetDefault: _setDefaultProvider,
          detail: _SettingsRowGroup(
            children: [
              field(context.l10n.text('common.name'), displayed.name, _name),
              _SettingsRow(
                label: context.l10n.text('model.protocol'),
                control: _editing
                    ? _SettingsPicker<String>(
                        key: const ValueKey('settings-model-protocol-picker'),
                        value: _protocol,
                        width: 250,
                        options: const [
                          _PickerOption(
                            value: 'openai-responses',
                            label: 'OpenAI Responses',
                          ),
                          _PickerOption(
                            value: 'openai-chat-completions',
                            label: 'OpenAI Chat Completions',
                          ),
                          _PickerOption(
                            value: 'anthropic-messages',
                            label: 'Anthropic Messages',
                          ),
                        ],
                        onChanged: (value) {
                          if (value == _protocol) return;
                          _protocol = value;
                          _markDraftChanged();
                        },
                      )
                    : Text(_modelProtocolLabel(displayed.protocol)),
              ),
              field(
                context.l10n.text('model.baseUrl'),
                displayed.baseUrl,
                _baseUrl,
                fieldKey: const ValueKey('settings-model-base-url-field'),
              ),
              field(
                context.l10n.text('model.model'),
                displayed.model,
                _model,
                fieldKey: const ValueKey('settings-model-id-field'),
              ),
              field(
                context.l10n.text('model.apiKey'),
                context.l10n.text(
                  displayed.apiKeyConfigured
                      ? 'model.configured'
                      : 'model.notConfigured',
                ),
                _apiKey,
                secret: true,
              ),
              field(
                context.l10n.text('model.maxTokens'),
                displayed.maxTokens?.toString() ?? '',
                _maxTokens,
              ),
              field(
                context.l10n.text('model.temperature'),
                displayed.temperature?.toString() ?? '',
                _temperature,
              ),
              field(
                context.l10n.text('model.topP'),
                displayed.topP?.toString() ?? '',
                _topP,
              ),
              field(
                context.l10n.text('model.contextWindow'),
                displayed.maxModelLength?.toString() ?? '',
                _maxModelLength,
              ),
              _SettingsRow(
                label: context.l10n.text('model.capabilities'),
                control: Wrap(
                  spacing: 7,
                  runSpacing: 7,
                  alignment: WrapAlignment.end,
                  children: [
                    _SettingsTag(label: context.l10n.text('model.text')),
                    if (displayed.supportsMultimodal)
                      _SettingsTag(
                        label: context.l10n.text('model.multimodal'),
                      ),
                    if (displayed.supportsStructuredOutput)
                      _SettingsTag(
                        label: context.l10n.text('model.structured'),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

String _modelProtocolLabel(String value) => switch (value) {
  'openai-chat-completions' => 'OpenAI Chat Completions',
  'anthropic-messages' => 'Anthropic Messages',
  _ => 'OpenAI Responses',
};

class _CatalogSettings<T> extends StatefulWidget {
  const _CatalogSettings({
    required this.title,
    required this.values,
    required this.name,
    required this.rows,
    this.group,
    this.detailBuilder,
  });
  final String title;
  final List<T> values;
  final String Function(T) name;
  final String Function(T)? group;
  final List<(String, String)> Function(T) rows;
  final Widget Function(T)? detailBuilder;

  @override
  State<_CatalogSettings<T>> createState() => _CatalogSettingsState<T>();
}

class _CatalogSettingsState<T> extends State<_CatalogSettings<T>> {
  String _selectedName = '';

  List<T> get _orderedValues {
    final values = widget.values.toList();
    final group = widget.group;
    if (group == null) return values;
    values.sort((left, right) {
      final byGroup = group(left).compareTo(group(right));
      return byGroup != 0
          ? byGroup
          : widget.name(left).compareTo(widget.name(right));
    });
    return values;
  }

  T? get _selected {
    final values = _orderedValues;
    if (values.isEmpty) return null;
    if (!values.any((value) => widget.name(value) == _selectedName)) {
      _selectedName = widget.name(values.first);
    }
    return values.firstWhere((value) => widget.name(value) == _selectedName);
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    return _SettingsContent(
      title: widget.title,
      fillRemaining: true,
      children: [
        if (selected != null)
          _SettingsMasterDetail(
            items: [
              for (final value in _orderedValues)
                _SettingsChoice(
                  id: widget.name(value),
                  label: widget.name(value),
                  group: widget.group?.call(value) ?? '',
                ),
            ],
            selectedId: _selectedName,
            onSelected: (value) => setState(() => _selectedName = value),
            detail:
                widget.detailBuilder?.call(selected) ??
                _SettingsRowGroup(
                  children: [
                    for (final row in widget.rows(selected))
                      _SettingsRow(
                        label: row.$1,
                        control: Text(
                          row.$2.isEmpty ? '—' : row.$2,
                          textAlign: TextAlign.end,
                        ),
                      ),
                  ],
                ),
          ),
      ],
    );
  }
}

enum _SkillDocumentMode { rendered, source }

class _SkillSettings extends StatefulWidget {
  const _SkillSettings({required this.controller, required this.values});

  final WorkspaceController controller;
  final List<SkillSummary> values;

  @override
  State<_SkillSettings> createState() => _SkillSettingsState();
}

class _SkillSettingsState extends State<_SkillSettings> {
  final Map<String, String> _contents = {};
  String _selectedName = '';
  String? _loadingName;
  String? _loadError;
  bool _importing = false;
  _SkillDocumentMode _mode = _SkillDocumentMode.rendered;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncSelection());
  }

  @override
  void didUpdateWidget(covariant _SkillSettings oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.values != widget.values) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _syncSelection());
    }
  }

  void _syncSelection() {
    if (!mounted) return;
    final values = widget.values;
    if (values.isEmpty) {
      if (_selectedName.isNotEmpty) setState(() => _selectedName = '');
      return;
    }
    final next = values.any((value) => value.name == _selectedName)
        ? _selectedName
        : values.first.name;
    if (next != _selectedName) {
      setState(() {
        _selectedName = next;
        _mode = _SkillDocumentMode.rendered;
      });
    }
    _loadContent(next);
  }

  Future<void> _select(String name) async {
    if (name == _selectedName) return;
    setState(() {
      _selectedName = name;
      _mode = _SkillDocumentMode.rendered;
      _loadError = null;
    });
    await _loadContent(name);
  }

  Future<void> _loadContent(String name, {bool refresh = false}) async {
    if (name.isEmpty || (!refresh && _contents.containsKey(name))) return;
    setState(() {
      _loadingName = name;
      _loadError = null;
    });
    try {
      final content = await widget.controller.loadSkillContent(name);
      if (!mounted) return;
      setState(() => _contents[name] = content);
    } on Object {
      if (mounted && _selectedName == name) {
        setState(() => _loadError = context.l10n.text('skill.readFailed'));
      }
    } finally {
      if (mounted && _loadingName == name) {
        setState(() => _loadingName = null);
      }
    }
  }

  Future<void> _importFolder() async {
    if (_importing) return;
    final path = await widget.controller.chooseSkillFolder(
      confirmButtonText: context.l10n.text('common.upload'),
    );
    if (path == null || path.isEmpty || !mounted) return;
    setState(() => _importing = true);
    try {
      final imported = await widget.controller.importSkillFolder(path);
      if (!mounted) return;
      _contents.clear();
      final catalog = widget.controller.skillCatalog;
      final next = imported.isNotEmpty
          ? imported.first
          : (_selectedName.isNotEmpty
                ? _selectedName
                : (catalog.isEmpty ? '' : catalog.first.name));
      setState(() {
        _selectedName = next;
        _mode = _SkillDocumentMode.rendered;
      });
      await _loadContent(next, refresh: true);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(context.l10n.text('skill.uploadSuccess'))),
        );
      }
    } on Object {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(context.l10n.text('skill.uploadFailed'))),
        );
      }
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    SkillSummary? selected;
    for (final value in widget.values) {
      if (value.name == _selectedName) {
        selected = value;
        break;
      }
    }
    final content = selected == null ? null : _contents[selected.name];
    return _SettingsContent(
      title: context.l10n.text('settings.skills'),
      fillRemaining: true,
      action: _SettingsActionButton(
        key: const ValueKey('settings-skill-upload-folder'),
        width: 118,
        onTap: _importing ? null : _importFolder,
        icon: _importing
            ? const CupertinoActivityIndicator(radius: 7)
            : const Icon(CupertinoIcons.folder_badge_plus, size: 16),
        label: context.l10n.text('skill.uploadFolder'),
      ),
      children: [
        if (selected != null)
          _SettingsMasterDetail(
            selectorKey: const ValueKey('settings-skill-picker'),
            items: [
              for (final value in widget.values)
                _SettingsChoice(id: value.name, label: value.name),
            ],
            selectedId: selected.name,
            onSelected: _select,
            detail: _SkillDocument(
              skill: selected,
              content: content,
              loading: _loadingName == selected.name,
              error: _loadError,
              mode: _mode,
              onModeChanged: (value) => setState(() => _mode = value),
              onRetry: () => _loadContent(selected!.name, refresh: true),
            ),
          ),
      ],
    );
  }
}

class _SkillDocument extends StatelessWidget {
  const _SkillDocument({
    required this.skill,
    required this.content,
    required this.loading,
    required this.error,
    required this.mode,
    required this.onModeChanged,
    required this.onRetry,
  });

  final SkillSummary skill;
  final String? content;
  final bool loading;
  final String? error;
  final _SkillDocumentMode mode;
  final ValueChanged<_SkillDocumentMode> onModeChanged;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return GlassCard(
      key: const ValueKey('settings-skill-document'),
      padding: EdgeInsets.zero,
      shape: const LiquidRoundedSuperellipse(borderRadius: 20),
      useOwnLayer: true,
      settings: _glass(context),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 14, 12, 14),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: colors.primary.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    CupertinoIcons.doc_text_fill,
                    size: 17,
                    color: colors.primary,
                  ),
                ),
                const SizedBox(width: 11),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        skill.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                      Text(
                        'SKILL.md',
                        style: Theme.of(context).textTheme.labelMedium
                            ?.copyWith(
                              color: colors.onSurfaceVariant,
                              fontFamily: 'Menlo',
                            ),
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  key: const ValueKey('settings-skill-document-mode'),
                  width: 132,
                  child: GlassSegmentedControl(
                    height: 32,
                    segments: [
                      GlassSegment(label: context.l10n.text('skill.read')),
                      GlassSegment(
                        label: context.l10n.text('common.sourceCode'),
                      ),
                    ],
                    selectedIndex: mode.index,
                    onSegmentSelected: (index) =>
                        onModeChanged(_SkillDocumentMode.values[index]),
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  key: const ValueKey('settings-skill-copy'),
                  tooltip: context.l10n.text('skill.copy'),
                  onPressed: content == null
                      ? null
                      : () {
                          Clipboard.setData(ClipboardData(text: content!));
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(context.l10n.text('skill.copied')),
                            ),
                          );
                        },
                  icon: const Icon(CupertinoIcons.doc_on_doc, size: 17),
                ),
              ],
            ),
          ),
          Divider(height: 1, color: colors.outlineVariant),
          if (loading && content == null)
            const SizedBox(
              height: 280,
              child: Center(child: CupertinoActivityIndicator()),
            )
          else if (error != null && content == null)
            SizedBox(
              height: 280,
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      CupertinoIcons.exclamationmark_circle,
                      color: colors.error,
                    ),
                    const SizedBox(height: 10),
                    Text(error!),
                    const SizedBox(height: 10),
                    TextButton(
                      onPressed: onRetry,
                      child: Text(context.l10n.text('common.retry')),
                    ),
                  ],
                ),
              ),
            )
          else
            Padding(
              key: ValueKey('settings-skill-view-${mode.name}'),
              padding: const EdgeInsets.fromLTRB(22, 20, 22, 28),
              child: mode == _SkillDocumentMode.rendered
                  ? _SkillMarkdown(
                      content: content ?? '',
                      skillName: skill.name,
                    )
                  : _SkillSource(content: content ?? ''),
            ),
        ],
      ),
    );
  }
}

class _SkillMarkdown extends StatelessWidget {
  const _SkillMarkdown({required this.content, required this.skillName});

  final String content;
  final String skillName;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final base = MarkdownStyleSheet.fromTheme(theme);
    return Align(
      alignment: Alignment.topLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 840),
        child: MarkdownBody(
          key: const ValueKey('settings-skill-markdown'),
          data: _skillMarkdownForReading(content, skillName),
          selectable: true,
          styleSheet: base.copyWith(
            h1: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
              height: 1.3,
            ),
            h2: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w700,
              height: 1.35,
            ),
            h3: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
              height: 1.4,
            ),
            p: theme.textTheme.bodyMedium?.copyWith(height: 1.58),
            listBullet: theme.textTheme.bodyMedium?.copyWith(
              color: colors.primary,
              height: 1.58,
            ),
            blockquoteDecoration: BoxDecoration(
              color: colors.primary.withValues(alpha: 0.07),
              border: Border(left: BorderSide(color: colors.primary, width: 3)),
              borderRadius: BorderRadius.circular(8),
            ),
            code: theme.textTheme.bodySmall?.copyWith(
              fontFamily: 'Menlo',
              color: colors.onSurface,
              backgroundColor: Colors.transparent,
            ),
            codeblockPadding: const EdgeInsets.all(16),
            codeblockDecoration: BoxDecoration(
              color: colors.onSurface.withValues(alpha: 0.055),
              border: Border.all(
                color: colors.outlineVariant.withValues(alpha: 0.72),
              ),
              borderRadius: BorderRadius.circular(10),
            ),
            horizontalRuleDecoration: BoxDecoration(
              border: Border(top: BorderSide(color: colors.outlineVariant)),
            ),
          ),
        ),
      ),
    );
  }
}

String _skillMarkdownForReading(String content, String skillName) {
  final frontmatter = RegExp(
    r'^\uFEFF?---[ \t]*\r?\n.*?^(?:---|\.\.\.)[ \t]*(?:\r?\n|$)',
    multiLine: true,
    dotAll: true,
  ).firstMatch(content);
  var body = frontmatter == null ? content : content.substring(frontmatter.end);
  body = body.replaceFirst(RegExp(r'^[\r\n]+'), '');

  final lines = body.split('\n');
  final firstContent = lines.indexWhere((line) => line.trim().isNotEmpty);
  if (firstContent >= 0) {
    final heading = RegExp(r'^#\s+(.+?)\s*$').firstMatch(lines[firstContent]);
    if (heading != null &&
        heading.group(1)?.trim().toLowerCase() ==
            skillName.trim().toLowerCase()) {
      lines.removeAt(firstContent);
      while (firstContent < lines.length &&
          lines[firstContent].trim().isEmpty) {
        lines.removeAt(firstContent);
      }
    }
  }
  return lines.join('\n').trimRight();
}

class _SkillSource extends StatelessWidget {
  const _SkillSource({required this.content});

  final String content;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      key: const ValueKey('settings-skill-source'),
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.onSurface.withValues(alpha: 0.055),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: 0.72),
        ),
        borderRadius: BorderRadius.circular(12),
      ),
      child: SelectableText(
        content,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          fontFamily: 'Menlo',
          height: 1.58,
          color: colors.onSurface,
        ),
      ),
    );
  }
}

class _ToolDetails extends StatelessWidget {
  const _ToolDetails({required this.tool});

  final ToolSummary tool;

  @override
  Widget build(BuildContext context) {
    final schema = tool.inputSchema.isNotEmpty
        ? tool.inputSchema
        : <String, Object?>{
            'type': 'object',
            'properties': tool.parameters,
            if (tool.required.isNotEmpty) 'required': tool.required,
          };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _ToolOverview(tool: tool),
        const SizedBox(height: 22),
        _ToolSchema(schema: schema),
      ],
    );
  }
}

class _ToolOverview extends StatelessWidget {
  const _ToolOverview({required this.tool});

  final ToolSummary tool;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final description = tool.description.trim();
    return Semantics(
      key: const ValueKey('settings-tool-overview'),
      container: true,
      label: context.l10n.text('tool.information', {'name': tool.name}),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Icon(CupertinoIcons.hammer_fill, size: 18, color: colors.primary),
              const SizedBox(width: 10),
              Expanded(
                child: SelectableText(
                  tool.name,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontFamily: 'monospace',
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 13),
          Wrap(
            spacing: 18,
            runSpacing: 8,
            children: [
              _ToolMetadataBadge(
                label: context.l10n.text('common.source'),
                value: tool.source.isEmpty ? '—' : tool.source,
                icon: CupertinoIcons.link,
              ),
              _ToolMetadataBadge(
                label: context.l10n.text('common.type'),
                value: tool.type.isEmpty ? '—' : tool.type,
                icon: CupertinoIcons.cube_box,
              ),
            ],
          ),
          if (description.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 14),
              child: Divider(height: 1, color: colors.outlineVariant),
            ),
            SelectableText(
              description,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: colors.onSurfaceVariant,
                height: 1.55,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ToolMetadataBadge extends StatelessWidget {
  const _ToolMetadataBadge({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      label: '$label：$value',
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: colors.onSurfaceVariant),
          const SizedBox(width: 6),
          Text(
            '$label · ',
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: colors.onSurfaceVariant,
              fontWeight: FontWeight.w500,
            ),
          ),
          Flexible(
            child: SelectableText(
              value,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: colors.onSurface,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ToolSchema extends StatelessWidget {
  const _ToolSchema({required this.schema});

  final Map<String, Object?> schema;

  @override
  Widget build(BuildContext context) {
    final properties = _schemaMap(schema['properties']);
    final required = _schemaStrings(schema['required']);
    final hasProperties = properties.isNotEmpty;
    final emptyObject =
        _schemaType(schema) == 'object' &&
        schema.containsKey('properties') &&
        properties.isEmpty;
    final hasRootSchema = schema.isNotEmpty && !hasProperties && !emptyObject;
    final count = hasProperties ? properties.length : (hasRootSchema ? 1 : 0);
    return Semantics(
      key: const ValueKey('settings-tool-schema'),
      container: true,
      label: context.l10n.text('tool.schemaCount', {'count': count}),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                context.l10n.text('tool.schema'),
                style: Theme.of(
                  context,
                ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(width: 9),
              _SchemaBadge(
                label: context.l10n.text('tool.parameterCount', {
                  'count': count,
                }),
                emphasized: false,
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (count == 0)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(context.l10n.text('tool.noParameters')),
            )
          else if (hasProperties)
            _SchemaPropertyList(properties: properties, required: required)
          else
            _SchemaParameter(
              name: context.l10n.text('tool.input'),
              schema: schema,
              required: false,
              showRequirement: false,
            ),
        ],
      ),
    );
  }
}

class _SchemaPropertyList extends StatelessWidget {
  const _SchemaPropertyList({required this.properties, required this.required});

  final Map<String, Object?> properties;
  final Set<String> required;

  @override
  Widget build(BuildContext context) {
    final entries = properties.entries.toList(growable: false);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var index = 0; index < entries.length; index++) ...[
          _SchemaParameter(
            name: entries[index].key,
            schema: _schemaMap(entries[index].value),
            required: required.contains(entries[index].key),
          ),
          if (index != entries.length - 1)
            Divider(
              height: 1,
              color: Theme.of(context).colorScheme.outlineVariant,
            ),
        ],
      ],
    );
  }
}

class _SchemaParameter extends StatelessWidget {
  const _SchemaParameter({
    required this.name,
    required this.schema,
    required this.required,
    this.showRequirement = true,
  });

  final String name;
  final Map<String, Object?> schema;
  final bool required;
  final bool showRequirement;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final description = schema['description']?.toString().trim() ?? '';
    final nested = _schemaMap(schema['properties']);
    final nestedRequired = _schemaStrings(schema['required']);
    final itemSchema = _schemaMap(schema['items']);
    final itemProperties = _schemaMap(itemSchema['properties']);
    final facts = _schemaFacts(schema, context.l10n);
    return Semantics(
      container: true,
      label: [
        name,
        _schemaType(schema),
        if (required) context.l10n.text('common.required'),
      ].join(', '),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 7,
              runSpacing: 7,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SelectableText(
                  name,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontFamily: 'monospace',
                    fontWeight: FontWeight.w700,
                  ),
                ),
                _SchemaBadge(label: _schemaType(schema)),
                if (showRequirement)
                  _SchemaBadge(
                    label: context.l10n.text(
                      required ? 'common.required' : 'common.optional',
                    ),
                    emphasized: required,
                  ),
              ],
            ),
            if (description.isNotEmpty) ...[
              const SizedBox(height: 9),
              SelectableText(
                description,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: colors.onSurfaceVariant,
                  height: 1.5,
                ),
              ),
            ],
            if (facts.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 7,
                runSpacing: 7,
                children: [
                  for (final fact in facts)
                    _SchemaBadge(label: fact, emphasized: false),
                ],
              ),
            ],
            if (nested.isNotEmpty) ...[
              const SizedBox(height: 12),
              _NestedSchemaSurface(
                properties: nested,
                required: nestedRequired,
              ),
            ] else if (itemProperties.isNotEmpty) ...[
              const SizedBox(height: 12),
              _NestedSchemaSurface(
                label: context.l10n.text('schema.arrayItems'),
                properties: itemProperties,
                required: _schemaStrings(itemSchema['required']),
              ),
            ] else if (itemSchema.isNotEmpty) ...[
              const SizedBox(height: 10),
              _SchemaBadge(
                label: context.l10n.text('schema.arrayItemsType', {
                  'type': _schemaType(itemSchema),
                }),
                emphasized: false,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _NestedSchemaSurface extends StatelessWidget {
  const _NestedSchemaSurface({
    required this.properties,
    required this.required,
    this.label,
  });

  final Map<String, Object?> properties;
  final Set<String> required;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.only(left: 14),
      decoration: BoxDecoration(
        border: Border(
          left: BorderSide(
            color: colors.outlineVariant.withValues(alpha: 0.9),
            width: 2,
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (label != null)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                label!,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: colors.onSurfaceVariant,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          _SchemaPropertyList(properties: properties, required: required),
        ],
      ),
    );
  }
}

class _SchemaBadge extends StatelessWidget {
  const _SchemaBadge({required this.label, this.emphasized = true});

  final String label;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final foreground = emphasized ? colors.primary : colors.onSurfaceVariant;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: emphasized
            ? colors.primary.withValues(alpha: 0.11)
            : colors.onSurface.withValues(alpha: 0.055),
        borderRadius: BorderRadius.circular(7),
        border: Border.all(
          color: emphasized
              ? colors.primary.withValues(alpha: 0.18)
              : colors.outlineVariant.withValues(alpha: 0.75),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
        child: Text(
          label,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
            color: foreground,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

Map<String, Object?> _schemaMap(Object? value) {
  if (value is! Map) return const {};
  return {for (final entry in value.entries) entry.key.toString(): entry.value};
}

Set<String> _schemaStrings(Object? value) {
  if (value is! Iterable) return const {};
  return {for (final item in value) item.toString()};
}

String _schemaType(Map<String, Object?> schema) {
  final raw = schema['type'];
  if (raw is Iterable) return raw.map((value) => value.toString()).join(' | ');
  if (raw != null && raw.toString().isNotEmpty) return raw.toString();
  if (_schemaMap(schema['properties']).isNotEmpty) return 'object';
  if (schema['items'] != null) return 'array';
  if (schema['enum'] is Iterable) return 'enum';
  final alternatives = schema['anyOf'] ?? schema['oneOf'];
  if (alternatives is Iterable) {
    final values = alternatives
        .map(_schemaMap)
        .map(_schemaType)
        .where((value) => value != 'any')
        .toSet();
    if (values.isNotEmpty) return values.join(' | ');
  }
  final reference = schema[r'$ref']?.toString();
  if (reference != null && reference.isNotEmpty) {
    return reference.split('/').last;
  }
  return 'any';
}

List<String> _schemaFacts(Map<String, Object?> schema, SageLocalizations l10n) {
  final facts = <String>[];
  final format = schema['format'];
  if (format != null && format.toString().isNotEmpty) {
    facts.add(l10n.text('schema.format', {'value': format}));
  }
  final values = schema['enum'];
  if (values is Iterable) {
    facts.add(
      l10n.text('schema.enum', {'value': values.map(_schemaValue).join(' / ')}),
    );
  }
  if (schema.containsKey('default')) {
    facts.add(
      l10n.text('schema.default', {'value': _schemaValue(schema['default'])}),
    );
  }
  for (final entry in const {
    'minimum': 'schema.minimum',
    'maximum': 'schema.maximum',
    'minLength': 'schema.minLength',
    'maxLength': 'schema.maxLength',
    'minItems': 'schema.minItems',
    'maxItems': 'schema.maxItems',
    'pattern': 'schema.pattern',
  }.entries) {
    final value = schema[entry.key];
    if (value != null) {
      facts.add('${l10n.text(entry.value)} · ${_schemaValue(value)}');
    }
  }
  return facts;
}

String _schemaValue(Object? value) {
  if (value == null) return 'null';
  if (value is Map || value is Iterable) return jsonEncode(value);
  return value.toString();
}

class _McpSettings extends StatefulWidget {
  const _McpSettings({required this.controller, required this.onAdd});

  final WorkspaceController controller;
  final VoidCallback onAdd;

  @override
  State<_McpSettings> createState() => _McpSettingsState();
}

class _McpSettingsState extends State<_McpSettings> {
  String _selectedName = '';
  bool _saving = false;

  McpConnectionSummary? get _selected {
    final values = widget.controller.mcpConnections;
    if (values.isEmpty) return null;
    if (!values.any((value) => value.name == _selectedName)) {
      _selectedName = values.first.name;
    }
    return values.firstWhere((value) => value.name == _selectedName);
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    return _SettingsContent(
      title: 'MCP',
      status: _saving,
      fillRemaining: true,
      action: IconButton(
        key: const ValueKey('settings-add-mcp'),
        tooltip: context.l10n.text('mcp.connect'),
        onPressed: widget.onAdd,
        icon: const Icon(CupertinoIcons.add, size: 18),
      ),
      children: [
        if (selected != null)
          _SettingsMasterDetail(
            items: [
              for (final value in widget.controller.mcpConnections)
                _SettingsChoice(id: value.name, label: value.name),
            ],
            selectedId: _selectedName,
            onSelected: (value) => setState(() => _selectedName = value),
            detail: _SettingsRowGroup(
              children: [
                _SettingsRow(
                  label: context.l10n.text('common.name'),
                  control: Text(selected.name),
                ),
                _SettingsRow(
                  label: context.l10n.text('common.protocol'),
                  control: Text(selected.protocol),
                ),
                _SettingsRow(
                  label: context.l10n.text('common.address'),
                  control: SelectableText(
                    selected.url.isNotEmpty ? selected.url : selected.command,
                    textAlign: TextAlign.end,
                  ),
                ),
                _SettingsRow(
                  label: context.l10n.text('settings.tools'),
                  control: Text('${selected.toolCount}'),
                ),
                if (selected.connectionError.isNotEmpty)
                  _SettingsRow(
                    label: context.l10n.text('mcp.connectionError'),
                    control: SelectableText(
                      selected.connectionError,
                      textAlign: TextAlign.end,
                    ),
                  ),
                _SettingsRow(
                  label: context.l10n.text('common.enabled'),
                  control: SizedBox(
                    width: 190,
                    child: GlassSegmentedControl(
                      height: 34,
                      segments: [
                        GlassSegment(
                          label: context.l10n.text('common.disable'),
                        ),
                        GlassSegment(label: context.l10n.text('common.enable')),
                      ],
                      selectedIndex: selected.disabled ? 0 : 1,
                      onSegmentSelected: (index) async {
                        final enabled = index == 1;
                        setState(() => _saving = true);
                        try {
                          await widget.controller.setMcpConnectionEnabled(
                            selected.name,
                            enabled,
                          );
                        } finally {
                          if (mounted) setState(() => _saving = false);
                        }
                      },
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

LiquidGlassSettings _glass(BuildContext context) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return LiquidGlassSettings(
    visibility: dark ? 0.86 : 0.9,
    glassColor: dark
        ? const Color(0xFF2B2C2E).withValues(alpha: 0.84)
        : Colors.white.withValues(alpha: 0.92),
    thickness: 4,
    blur: 3,
    chromaticAberration: 0,
    lightIntensity: 0.1,
    saturation: 1,
    glowIntensity: 0,
    standardOpacityMultiplier: dark ? 0.88 : 0.92,
    shadowElevation: 0.04,
  );
}
