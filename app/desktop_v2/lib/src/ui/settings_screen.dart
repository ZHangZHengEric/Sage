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
  String? _workspaceError;
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

  @override
  void initState() {
    super.initState();
    _settingsAgentId = widget.controller.selectedAgentId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      widget.controller.loadSettingsCatalog(agentId: _settingsAgentId);
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _workspaceDebounce?.cancel();
    _name.dispose();
    _description.dispose();
    _systemPrefix.dispose();
    _systemContext.dispose();
    _maxLoopCount.dispose();
    _previewBytes.dispose();
    _treeEntries.dispose();
    _workspacePath.dispose();
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
    ).convert(value.systemContext);
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
        'system_context': decodedContext.cast<String, Object?>(),
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

  void _saveAgentTextLater(String field, TextEditingController controller) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 650), () {
      if (field == 'system_context') {
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
      0 => _general(),
      1 => _agents(agent),
      2 => _models(),
      3 => _tools(),
      4 => _skills(),
      5 => _mcp(),
      6 => _components(),
      7 => _security(),
      _ => _archived(),
    };
  }

  Widget _archived() =>
      _ArchivedConversationSettings(controller: widget.controller);

  Widget _security() => _SettingsContent(
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
              control: Text(context.l10n.text('security.autoAllowValue')),
            ),
            _SettingsRow(
              label: context.l10n.text('security.requestApproval'),
              control: Text(context.l10n.text('security.requestApprovalValue')),
            ),
            _SettingsRow(
              label: context.l10n.text('security.autoBlock'),
              control: Text(context.l10n.text('security.autoBlockValue')),
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

  Widget _components() => _SettingsContent(
    title: context.l10n.text('settings.components'),
    status: _saving,
    children: [
      for (final component in widget.controller.components)
        _ComponentSettingsCard(
          component: component,
          onSelect: (pluginId) async {
            setState(() => _saving = true);
            try {
              await widget.controller.selectComponent(component.id, pluginId);
            } finally {
              if (mounted) setState(() => _saving = false);
            }
          },
        ),
    ],
  );

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
            label: context.l10n.text('settings.defaultAgent'),
            control: _SettingsPicker<String>(
              width: 270,
              value: _draft.defaultAgentId ?? '',
              options: [
                _PickerOption(
                  value: '',
                  label: context.l10n.text('common.auto'),
                ),
                for (final agent in widget.controller.agents)
                  _PickerOption(value: agent.id, label: agent.name),
              ],
              onChanged: (value) => _saveDesktopSettings(
                _draft.copyWith(
                  defaultAgentId: value,
                  clearDefaultAgent: value.isEmpty,
                ),
              ),
            ),
          ),
          _SettingsRow(
            label: context.l10n.text('settings.defaultWorkspace'),
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
    final loadingSelection =
        widget.controller.settingsAgentLoadingId == _settingsAgentId ||
        agent.id != _settingsAgentId;
    return _SettingsContent(
      title: context.l10n.text('settings.agent'),
      status: _saving,
      fillRemaining: true,
      action: _SettingsActionButton(
        key: const ValueKey('settings-agent-edit'),
        onTap: _saving || loadingSelection ? null : _toggleAgentEditing,
        icon: Icon(
          _editingAgent ? CupertinoIcons.checkmark : CupertinoIcons.pencil,
          size: 15,
        ),
        label: context.l10n.text(_editingAgent ? 'common.save' : 'common.edit'),
      ),
      children: [
        _SettingsMasterDetail(
          selectorKey: const ValueKey('settings-agent-picker'),
          items: [
            for (final value in widget.controller.agents)
              _SettingsChoice(
                id: value.id,
                label: value.name,
                marked: value.isDefault,
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
                    _AgentLargeField(
                      key: const ValueKey('agent-system-context'),
                      label: context.l10n.text('agent.systemContext'),
                      value: const JsonEncoder.withIndent(
                        '  ',
                      ).convert(agent.systemContext),
                      controller: _systemContext,
                      editing: _editingAgent,
                      code: true,
                      view: _SystemContextView(value: agent.systemContext),
                      onChanged: (_) =>
                          _saveAgentTextLater('system_context', _systemContext),
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
                        final next = agent.availableTools.toSet();
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
                        final next = agent.availableSkills.toSet();
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
  (context.l10n.text('settings.general'), CupertinoIcons.gear),
  (context.l10n.text('settings.agent'), CupertinoIcons.person_2),
  (context.l10n.text('settings.models'), CupertinoIcons.slider_horizontal_3),
  (context.l10n.text('settings.tools'), CupertinoIcons.hammer),
  (context.l10n.text('settings.skills'), CupertinoIcons.wand_stars),
  ('MCP', CupertinoIcons.link),
  (context.l10n.text('settings.components'), CupertinoIcons.square_grid_2x2),
  (context.l10n.text('settings.security'), CupertinoIcons.shield),
  (context.l10n.text('settings.archive'), CupertinoIcons.archivebox),
];

class _ComponentSettingsCard extends StatelessWidget {
  const _ComponentSettingsCard({
    required this.component,
    required this.onSelect,
  });

  final ComponentSummary component;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final selectable = component.selectionMode == 'user';
    final available = [
      for (final plugin in component.plugins)
        if (plugin.available) plugin,
    ];
    final active = component.activePluginId ?? '';
    return Semantics(
      container: true,
      label: context.l10n.text('component.current', {
        'name': component.name,
        'implementation': component.implementation,
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
                      component.name,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      component.value,
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
                        value: active,
                        width: 250,
                        options: [
                          for (final plugin in available)
                            _PickerOption(value: plugin.id, label: plugin.name),
                        ],
                        onChanged: onSelect,
                      )
                    : _SettingsTag(
                        label: component.implementation.isEmpty
                            ? context.l10n.text('component.decidedBy', {
                                'owner': _selectionOwner(
                                  component.selectionMode,
                                  context.l10n,
                                ),
                              })
                            : component.implementation,
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
                    'scope': component.scope,
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
                          plugin.name,
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          plugin.value,
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
    this.marked = false,
    this.removable = false,
    this.busy = false,
    this.removeKeyPrefix = 'settings-choice-delete',
  });

  final String id;
  final String label;
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
  });

  final List<_SettingsChoice> items;
  final String selectedId;
  final ValueChanged<String> onSelected;
  final Widget detail;
  final Key? selectorKey;
  final ValueChanged<String>? onRemove;

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
                  _PickerOption(value: item.id, label: item.label),
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
  });

  final List<_SettingsChoice> items;
  final String selectedId;
  final ValueChanged<String> onSelected;
  final ValueChanged<String>? onRemove;

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
  Widget build(BuildContext context) => ScrollConfiguration(
    behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
    child: Scrollbar(
      controller: _scrollController,
      thumbVisibility: true,
      thickness: 5,
      radius: const Radius.circular(3),
      child: ListView.separated(
        key: const ValueKey('settings-choice-list'),
        controller: _scrollController,
        primary: false,
        padding: const EdgeInsets.only(right: 8),
        itemCount: widget.items.length,
        itemBuilder: (context, index) {
          final item = widget.items[index];
          return _SettingsChoiceButton(
            item: item,
            selected: item.id == widget.selectedId,
            onTap: () => widget.onSelected(item.id),
            onRemove: item.removable && widget.onRemove != null
                ? () => widget.onRemove!(item.id)
                : null,
          );
        },
        separatorBuilder: (context, index) => Divider(
          height: 1,
          color: Theme.of(context).colorScheme.outlineVariant,
        ),
      ),
    ),
  );
}

class _SettingsChoiceButton extends StatelessWidget {
  const _SettingsChoiceButton({
    required this.item,
    required this.selected,
    required this.onTap,
    this.onRemove,
  });

  final _SettingsChoice item;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: EdgeInsets.zero,
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
                Icon(CupertinoIcons.star_fill, size: 11, color: colors.primary),
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
                            key: ValueKey('${item.removeKeyPrefix}-${item.id}'),
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
    );
  }
}

class _SettingsRow extends StatelessWidget {
  const _SettingsRow({required this.label, required this.control});
  final String label;
  final Widget control;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final labelWidget = Text(
        label,
        style: Theme.of(
          context,
        ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
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
    super.key,
    required this.label,
    required this.value,
    required this.controller,
    required this.editing,
    required this.onChanged,
    this.code = false,
    this.view,
  });
  final String label;
  final String value;
  final TextEditingController controller;
  final bool editing;
  final ValueChanged<String> onChanged;
  final bool code;
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
          textStyle: code
              ? const TextStyle(fontFamily: 'Menlo', fontSize: 12.5)
              : null,
        )
      else
        view ??
            SelectableText(
              value.isEmpty ? '—' : value,
              style: code
                  ? const TextStyle(fontFamily: 'Menlo', fontSize: 12.5)
                  : null,
            ),
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

class _SystemContextView extends StatelessWidget {
  const _SystemContextView({required this.value});

  final Map<String, Object?> value;

  @override
  Widget build(BuildContext context) {
    if (value.isEmpty) return const Text('—');
    final entries = value.entries.toList()
      ..sort((left, right) => left.key.compareTo(right.key));
    final colors = Theme.of(context).colorScheme;
    return Column(
      key: const ValueKey('agent-system-context-formatted'),
      children: [
        for (var index = 0; index < entries.length; index++) ...[
          _SystemContextEntry(entry: entries[index]),
          if (index != entries.length - 1)
            Divider(height: 1, color: colors.outlineVariant),
        ],
      ],
    );
  }
}

class _SystemContextEntry extends StatelessWidget {
  const _SystemContextEntry({required this.entry});

  final MapEntry<String, Object?> entry;

  @override
  Widget build(BuildContext context) {
    final raw = entry.value;
    final formatted = raw is Map || raw is List
        ? const JsonEncoder.withIndent('  ').convert(raw)
        : raw?.toString() ?? 'null';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
            child: SelectableText(
              entry.key,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: SelectableText(
              formatted,
              style: raw is Map || raw is List
                  ? const TextStyle(
                      fontFamily: 'Menlo',
                      fontSize: 12.5,
                      height: 1.45,
                    )
                  : Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        ],
      ),
    );
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
  });
  final String title;
  final Iterable<String> values;
  final List<_AssignmentGroup> groups;
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
                        value: value,
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
    final source = tool.source.trim().isEmpty
        ? l10n.text('tool.baseTools')
        : tool.source.trim();
    grouped.putIfAbsent(source, () => []).add(tool.name);
  }
  return [
    for (final entry in grouped.entries)
      _AssignmentGroup(label: entry.key, values: entry.value),
  ];
}

class _AssignmentItem extends StatelessWidget {
  const _AssignmentItem({
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

class _ModelCapabilityButton extends StatelessWidget {
  const _ModelCapabilityButton({
    required this.checking,
    required this.verified,
    required this.enabled,
    required this.onTap,
  });

  final bool checking;
  final bool verified;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final label = context.l10n.text(
      checking
          ? 'common.validating'
          : verified
          ? 'common.applied'
          : 'common.validateApply',
    );
    final interactive = enabled && !checking && !verified;
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      enabled: interactive,
      label: label,
      child: IgnorePointer(
        ignoring: !interactive,
        child: AnimatedOpacity(
          duration: const Duration(milliseconds: 160),
          opacity: interactive || checking || verified ? 1 : 0.45,
          child: GlassButton.custom(
            key: const ValueKey('settings-model-capability-check'),
            width: 168,
            height: 38,
            label: label,
            onTap: onTap,
            shape: const LiquidRoundedRectangle(borderRadius: 10),
            settings: _glass(context),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (checking)
                  const CupertinoActivityIndicator(radius: 7)
                else
                  Icon(
                    verified
                        ? CupertinoIcons.checkmark_circle_fill
                        : CupertinoIcons.checkmark_shield,
                    size: 16,
                    color: verified ? colors.primary : null,
                  ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
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
          _detected = true;
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
            _ModelCapabilityButton(
              checking: _saving,
              verified: _detected,
              enabled: _dirty && !_saving,
              onTap: _verifyAndApply,
            ),
            const SizedBox(width: 10),
          ],
          _SettingsActionButton(
            key: const ValueKey('settings-model-add'),
            onTap: _saving || _editing ? null : _startCreating,
            icon: const Icon(CupertinoIcons.add, size: 15),
            label: context.l10n.text('common.add'),
          ),
          const SizedBox(width: 10),
          _SettingsActionButton(
            key: const ValueKey('settings-model-edit'),
            onTap: _saving || (_editing && _dirty) ? null : _toggleEditing,
            icon: Icon(
              _editing ? CupertinoIcons.checkmark : CupertinoIcons.pencil,
              size: 15,
            ),
            label: context.l10n.text(_editing ? 'common.save' : 'common.edit'),
          ),
        ],
      ),
      children: [
        _SettingsMasterDetail(
          selectorKey: const ValueKey('settings-model-picker'),
          items: [
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
          selectedId: _selectedId,
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
    this.detailBuilder,
  });
  final String title;
  final List<T> values;
  final String Function(T) name;
  final List<(String, String)> Function(T) rows;
  final Widget Function(T)? detailBuilder;

  @override
  State<_CatalogSettings<T>> createState() => _CatalogSettingsState<T>();
}

class _CatalogSettingsState<T> extends State<_CatalogSettings<T>> {
  String _selectedName = '';

  T? get _selected {
    if (widget.values.isEmpty) return null;
    if (!widget.values.any((value) => widget.name(value) == _selectedName)) {
      _selectedName = widget.name(widget.values.first);
    }
    return widget.values.firstWhere(
      (value) => widget.name(value) == _selectedName,
    );
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
              for (final value in widget.values)
                _SettingsChoice(
                  id: widget.name(value),
                  label: widget.name(value),
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
