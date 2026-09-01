import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import '../models.dart';
import '../localization/app_localizations.dart';
import '../services/terminal_service.dart';
import '../state/workspace_controller.dart';
import 'file_preview.dart';
import 'settings_screen.dart';
import 'shared/desktop_shell.dart';
import 'tool_activity_presentation.dart';
import 'workspace_panels/terminal/terminal_workspace_panel_plugin.dart';
import 'workspace_panels/workspace_panel_plugin.dart';

const double _splitHandleHitWidth = 12;
const double _minRailFraction = 0.16;
const double _defaultRailFraction = 0.16;
const double _maxRailFraction = 0.28;
const WorkspacePanelSizing _defaultWorkspacePanelSizing =
    WorkspacePanelSizing();

class WorkspaceScreen extends StatefulWidget {
  const WorkspaceScreen({
    required this.controller,
    required this.themeMode,
    required this.onThemeModeChanged,
    required this.language,
    required this.onLanguageChanged,
    this.panelPlugins = const [],
    this.panelDockController,
    super.key,
  });

  final WorkspaceController controller;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final String language;
  final ValueChanged<String> onLanguageChanged;
  final List<WorkspacePanelPlugin> panelPlugins;
  final WorkspacePanelDockController? panelDockController;

  @override
  State<WorkspaceScreen> createState() => _WorkspaceScreenState();
}

class _WorkspaceScreenState extends State<WorkspaceScreen> {
  bool _railCollapsed = false;
  bool _workspaceCollapsed = false;
  bool _settingsOpen = false;
  double _railFraction = _defaultRailFraction;
  double _workspaceFraction =
      _defaultWorkspacePanelSizing.preferredWidthFraction;
  late WorkspacePanelRegistry _panelRegistry;
  late WorkspacePanelDockController _panelDockController;
  late bool _ownsPanelDockController;

  WorkspacePanelServices get _panelServices => WorkspacePanelServices({
    WorkspaceController: widget.controller,
    TerminalService: widget.controller.terminalService,
    WorkspacePanelSelection: WorkspacePanelSelection(
      agentId: widget.controller.selectedAgentId,
      workspaceId: widget.controller.selectedGroup.workspaceId,
      workspaceName: widget.controller.selectedGroup.name,
    ),
  });

  WorkspacePanelSizing get _activePanelSizing =>
      _panelDockController.activePlugin?.sizing ?? _defaultWorkspacePanelSizing;

  @override
  void initState() {
    super.initState();
    _panelDockController =
        widget.panelDockController ?? WorkspacePanelDockController();
    _ownsPanelDockController = widget.panelDockController == null;
    _rebuildPanelRegistry();
  }

  @override
  void didUpdateWidget(covariant WorkspaceScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.panelDockController != widget.panelDockController) {
      if (_ownsPanelDockController) _panelDockController.dispose();
      _panelDockController =
          widget.panelDockController ?? WorkspacePanelDockController();
      _ownsPanelDockController = widget.panelDockController == null;
    }
    if (oldWidget.controller != widget.controller ||
        oldWidget.panelPlugins != widget.panelPlugins ||
        oldWidget.panelDockController != widget.panelDockController) {
      _rebuildPanelRegistry();
    }
  }

  @override
  void dispose() {
    if (_ownsPanelDockController) _panelDockController.dispose();
    super.dispose();
  }

  void _rebuildPanelRegistry() {
    _panelRegistry = WorkspacePanelRegistry([
      const _FileWorkspacePanelPlugin(),
      const TerminalWorkspacePanelPlugin(),
      ...widget.panelPlugins,
    ]);
    _panelDockController.syncPlugins(
      _panelRegistry.plugins.where((plugin) => plugin.supports(_panelServices)),
    );
  }

  void _resizeRail(double delta, double width) {
    setState(() {
      _railFraction = (_railFraction + delta / width)
          .clamp(_minRailFraction, _maxRailFraction)
          .toDouble();
    });
  }

  void _resizeWorkspace(double delta, double width) {
    final sizing = _activePanelSizing;
    setState(() {
      _workspaceFraction = (_workspaceFraction - delta / width)
          .clamp(sizing.minWidthFraction, sizing.maxWidthFraction)
          .toDouble();
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _panelDockController,
      builder: (context, _) {
        return ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final colors = Theme.of(context).colorScheme;
            return GlassScaffold(
              statusBarStyle: GlassStatusBarStyle.auto,
              backgroundColor: Colors.transparent,
              background: _Background(colors: colors),
              enableBackgroundSampling: false,
              edgeToEdge: true,
              edgeFade: false,
              body: Stack(
                children: [
                  Positioned.fill(
                    child: widget.controller.loading
                        ? const Center(child: CupertinoActivityIndicator())
                        : _settingsOpen
                        ? SettingsScreen(
                            controller: widget.controller,
                            themeMode: widget.themeMode,
                            onThemeModeChanged: widget.onThemeModeChanged,
                            language: widget.language,
                            onLanguageChanged: widget.onLanguageChanged,
                            railFraction: _railFraction,
                            onClose: () =>
                                setState(() => _settingsOpen = false),
                          )
                        : _buildWorkspaceShell(),
                  ),
                  if (widget.controller.error case final message?)
                    Positioned(
                      top: 70,
                      right: 18,
                      width: min(
                        380,
                        max(0, MediaQuery.sizeOf(context).width - 36),
                      ),
                      child: _ErrorNotice(
                        message: message,
                        onClose: widget.controller.clearError,
                      ),
                    ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  Widget _buildWorkspaceShell() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final panelSizing = _activePanelSizing;
        if (constraints.maxWidth < desktopCompactBreakpoint) {
          final railHeight = _railCollapsed
              ? 0.0
              : desktopCompactRailHeight(constraints.maxHeight);
          final workspaceHeight = _workspaceCollapsed
              ? 0.0
              : (constraints.maxHeight * panelSizing.compactHeightFraction)
                    .clamp(
                      panelSizing.minCompactHeight,
                      panelSizing.maxCompactHeight,
                    )
                    .toDouble();
          return Column(
            children: [
              if (!_railCollapsed)
                RepaintBoundary(
                  key: const ValueKey('project-rail-repaint-boundary'),
                  child: SizedBox(
                    height: railHeight,
                    child: _ProjectRail(
                      controller: widget.controller,
                      onOpenSettings: () =>
                          setState(() => _settingsOpen = true),
                      horizontal: true,
                    ),
                  ),
                ),
              Expanded(
                child: RepaintBoundary(
                  key: const ValueKey('thread-repaint-boundary'),
                  child: _ThreadPanel(
                    controller: widget.controller,
                    compact: true,
                    railCollapsed: _railCollapsed,
                    workspaceCollapsed: _workspaceCollapsed,
                    onToggleRail: () =>
                        setState(() => _railCollapsed = !_railCollapsed),
                    onToggleWorkspace: () => setState(
                      () => _workspaceCollapsed = !_workspaceCollapsed,
                    ),
                  ),
                ),
              ),
              if (!_workspaceCollapsed)
                SizedBox(
                  height: workspaceHeight,
                  child: RepaintBoundary(
                    key: const ValueKey('workspace-repaint-boundary'),
                    child: WorkspacePanelDock(
                      registry: _panelRegistry,
                      services: _panelServices,
                      controller: _panelDockController,
                      compact: true,
                    ),
                  ),
                ),
            ],
          );
        }

        const minThreadWidth = 420.0;
        final railWidth = _railCollapsed
            ? 0.0
            : constraints.maxWidth * _railFraction;
        final widthAfterRail =
            constraints.maxWidth -
            railWidth -
            (_railCollapsed ? 0 : desktopSplitHandleWidth);
        final minWorkspaceWidth =
            constraints.maxWidth * panelSizing.minWidthFraction;
        final maxWorkspaceWidth = min(
          constraints.maxWidth * panelSizing.maxWidthFraction,
          max(0.0, widthAfterRail - desktopSplitHandleWidth - minThreadWidth),
        );
        final showWorkspace =
            !_workspaceCollapsed && maxWorkspaceWidth >= minWorkspaceWidth;
        final workspaceWidth = showWorkspace
            ? (constraints.maxWidth * _workspaceFraction)
                  .clamp(minWorkspaceWidth, maxWorkspaceWidth)
                  .toDouble()
            : 0.0;
        return Stack(
          children: [
            Row(
              children: [
                if (!_railCollapsed) ...[
                  RepaintBoundary(
                    key: const ValueKey('project-rail-repaint-boundary'),
                    child: SizedBox(
                      width: railWidth,
                      child: _ProjectRail(
                        controller: widget.controller,
                        onOpenSettings: () =>
                            setState(() => _settingsOpen = true),
                        onToggleRail: () =>
                            setState(() => _railCollapsed = true),
                      ),
                    ),
                  ),
                  _SplitResizeHandle(
                    key: const ValueKey('rail-split-handle'),
                    onDragUpdate: (details) =>
                        _resizeRail(details.delta.dx, constraints.maxWidth),
                  ),
                ],
                Expanded(
                  child: RepaintBoundary(
                    key: const ValueKey('thread-repaint-boundary'),
                    child: _ThreadPanel(
                      controller: widget.controller,
                      railCollapsed: _railCollapsed,
                      workspaceCollapsed: _workspaceCollapsed || !showWorkspace,
                      onToggleRail: () =>
                          setState(() => _railCollapsed = !_railCollapsed),
                      onToggleWorkspace: () => setState(
                        () => _workspaceCollapsed = !_workspaceCollapsed,
                      ),
                    ),
                  ),
                ),
                if (showWorkspace) ...[
                  _SplitResizeHandle(
                    key: const ValueKey('workspace-split-handle'),
                    onDragUpdate: (details) => _resizeWorkspace(
                      details.delta.dx,
                      constraints.maxWidth,
                    ),
                  ),
                  SizedBox(
                    width: workspaceWidth,
                    child: RepaintBoundary(
                      key: const ValueKey('workspace-repaint-boundary'),
                      child: WorkspacePanelDock(
                        registry: _panelRegistry,
                        services: _panelServices,
                        controller: _panelDockController,
                      ),
                    ),
                  ),
                ],
              ],
            ),
            if (!_railCollapsed &&
                _splitHandleHitWidth > desktopSplitHandleWidth)
              Positioned(
                top: 0,
                bottom: 0,
                left:
                    railWidth -
                    ((_splitHandleHitWidth - desktopSplitHandleWidth) / 2),
                width: _splitHandleHitWidth,
                child: _SplitResizeHitTarget(
                  onDragUpdate: (details) =>
                      _resizeRail(details.delta.dx, constraints.maxWidth),
                ),
              ),
            if (showWorkspace && _splitHandleHitWidth > desktopSplitHandleWidth)
              Positioned(
                top: 0,
                bottom: 0,
                left:
                    constraints.maxWidth -
                    workspaceWidth -
                    desktopSplitHandleWidth -
                    ((_splitHandleHitWidth - desktopSplitHandleWidth) / 2),
                width: _splitHandleHitWidth,
                child: _SplitResizeHitTarget(
                  onDragUpdate: (details) =>
                      _resizeWorkspace(details.delta.dx, constraints.maxWidth),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _Background extends StatelessWidget {
  const _Background({required this.colors});

  final ColorScheme colors;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: dark ? 0.48 : 0.36),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: dark
              ? [
                  const Color(0xFF0E1A1F).withValues(alpha: 0.64),
                  const Color(0xFF030405).withValues(alpha: 0.5),
                  const Color(0xFF081316).withValues(alpha: 0.58),
                ]
              : [
                  const Color(0xFFF7FBFD).withValues(alpha: 0.56),
                  const Color(0xFFFFFFFF).withValues(alpha: 0.38),
                  const Color(0xFFEFF7FA).withValues(alpha: 0.5),
                ],
          stops: const [0, 0.55, 1],
        ),
      ),
    );
  }
}

class _ProjectRail extends StatefulWidget {
  const _ProjectRail({
    required this.controller,
    required this.onOpenSettings,
    this.onToggleRail,
    this.horizontal = false,
  });

  final WorkspaceController controller;
  final VoidCallback onOpenSettings;
  final VoidCallback? onToggleRail;
  final bool horizontal;

  @override
  State<_ProjectRail> createState() => _ProjectRailState();
}

class _ProjectRailState extends State<_ProjectRail> {
  final Set<String> _collapsedProjectIds = <String>{};
  final Set<String> _collapsedConversationIds = <String>{};

  // Project conversations stay open while the user moves between projects or
  // Agent Workspace. Only an explicit disclosure-button click may collapse a
  // project; changing the current selection must not rewrite navigation state.
  bool _isExpanded(WorkspaceGroup group) =>
      !_collapsedProjectIds.contains(group.id);

  void _selectProject(WorkspaceGroup group) {
    if (_collapsedProjectIds.remove(group.id)) setState(() {});
    unawaited(widget.controller.selectGroup(group.id));
  }

  void _toggleProject(WorkspaceGroup group) {
    if (group.id != widget.controller.selectedGroupId) {
      _selectProject(group);
      return;
    }
    setState(() {
      if (!_collapsedProjectIds.add(group.id)) {
        _collapsedProjectIds.remove(group.id);
      }
    });
  }

  List<Widget> _conversationBranch(
    String groupId,
    Conversation conversation, {
    required bool agentWorkspace,
  }) {
    final hasChildren = conversation.subSessions.isNotEmpty;
    final expanded = !_collapsedConversationIds.contains(conversation.id);
    return [
      _ConversationTile(
        conversation: conversation,
        selected:
            widget.controller.selectedGroupId == groupId &&
            widget.controller.selectedConversationId == conversation.id &&
            !widget.controller.viewingSubSession,
        hasChildren: hasChildren,
        expanded: expanded,
        onToggleExpanded: hasChildren
            ? () => setState(() {
                if (!_collapsedConversationIds.add(conversation.id)) {
                  _collapsedConversationIds.remove(conversation.id);
                }
              })
            : null,
        onTap: () => agentWorkspace
            ? widget.controller.selectAgentWorkspaceConversation(
                conversation.id,
              )
            : widget.controller.selectConversation(groupId, conversation.id),
        onArchive: () =>
            widget.controller.archiveConversation(groupId, conversation.id),
        onDelete: () => _deleteConversation(context, groupId, conversation),
      ),
      if (hasChildren && expanded)
        ..._subSessionTiles(conversation, conversation.sessionId, depth: 0),
    ];
  }

  List<Widget> _subSessionTiles(
    Conversation root,
    String? parentSessionId, {
    required int depth,
  }) {
    final children = root.subSessions
        .where((value) => value.parentSessionId == parentSessionId)
        .toList();
    return [
      for (final child in children) ...[
        _SubSessionTile(
          conversation: child,
          depth: depth,
          selected:
              widget.controller.selectedConversationId == root.id &&
              widget.controller.selectedSubSessionId == child.sessionId,
          onTap: () => widget.controller.selectSubSession(
            root.id,
            child.sessionId ?? '',
          ),
        ),
        ..._subSessionTiles(root, child.sessionId, depth: depth + 1),
      ],
    ];
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    if (widget.horizontal) {
      final projects = widget.controller.projectGroups;
      return GlassCard(
        width: double.infinity,
        padding: EdgeInsets.zero,
        shape: const LiquidRoundedRectangle(borderRadius: 0),
        useOwnLayer: true,
        settings: desktopSidebarGlassSettings(context),
        child: DesktopSidebarSurface(
          child: Row(
            children: [
              Padding(
                padding: const EdgeInsets.only(left: 12),
                child: _SidebarIconButton(
                  tooltip: context.l10n.text('workspace.settings'),
                  icon: CupertinoIcons.gear,
                  onTap: widget.onOpenSettings,
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 150,
                child: _NewConversationAction(
                  onTap: widget.controller.createAgentWorkspaceConversation,
                  compact: true,
                ),
              ),
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.all(12),
                  scrollDirection: Axis.horizontal,
                  itemCount: projects.length,
                  separatorBuilder: (_, _) => const SizedBox(width: 10),
                  itemBuilder: (context, index) {
                    final group = projects[index];
                    return SizedBox(
                      width: 210,
                      child: _WorkspaceHeader(
                        group: group,
                        selected: group.id == widget.controller.selectedGroupId,
                        expanded: group.id == widget.controller.selectedGroupId,
                        onTap: () => _selectProject(group),
                        onToggleExpanded: () => _selectProject(group),
                        onNewConversation: widget.controller.createConversation,
                        onRemoveProject: () => unawaited(
                          widget.controller.removeProject(group.id),
                        ),
                      ),
                    );
                  },
                ),
              ),
              _SidebarIconButton(
                tooltip: context.l10n.text('workspace.addProject'),
                icon: CupertinoIcons.add,
                keyValue: 'add-project-button',
                onTap: widget.controller.addProject,
              ),
              const SizedBox(width: 12),
            ],
          ),
        ),
      );
    }
    return GlassCard(
      width: double.infinity,
      padding: EdgeInsets.zero,
      shape: const LiquidRoundedRectangle(borderRadius: 0),
      useOwnLayer: true,
      settings: desktopSidebarGlassSettings(context),
      child: DesktopSidebarSurface(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              height: desktopPaneHeaderHeight,
              child: Align(
                alignment: Alignment.centerRight,
                child: Padding(
                  padding: const EdgeInsets.only(right: 10),
                  child: _HeaderIconButton(
                    keyValue: 'rail-collapse-button',
                    icon: CupertinoIcons.sidebar_left,
                    tooltip: context.l10n.text('workspace.collapseSidebar'),
                    semanticsLabel: context.l10n.text(
                      'workspace.collapseSidebar',
                    ),
                    onTap: widget.onToggleRail,
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 6),
              child: _NewConversationAction(
                onTap: widget.controller.createAgentWorkspaceConversation,
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 12, 16, 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      context.l10n.text('workspace.projects'),
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontSize: 13.5,
                        color: colors.onSurfaceVariant,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  _SidebarIconButton(
                    tooltip: context.l10n.text('workspace.addProject'),
                    icon: CupertinoIcons.add,
                    keyValue: 'add-project-button',
                    onTap: widget.controller.addProject,
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
                children: [
                  for (final group in widget.controller.projectGroups) ...[
                    _WorkspaceHeader(
                      group: group,
                      selected: group.id == widget.controller.selectedGroupId,
                      expanded: _isExpanded(group),
                      onTap: () => _selectProject(group),
                      onToggleExpanded: () => _toggleProject(group),
                      onNewConversation: widget.controller.createConversation,
                      onRemoveProject: () =>
                          unawaited(widget.controller.removeProject(group.id)),
                    ),
                    if (_isExpanded(group))
                      for (final conversation in group.conversations)
                        ..._conversationBranch(
                          group.id,
                          conversation,
                          agentWorkspace: false,
                        ),
                    const SizedBox(height: 10),
                  ],
                  if (widget
                      .controller
                      .agentWorkspaceConversations
                      .isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(10, 8, 8, 6),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              context.l10n.text('workspace.recent'),
                              style: Theme.of(context).textTheme.titleMedium
                                  ?.copyWith(
                                    fontSize: 12.5,
                                    color: colors.onSurfaceVariant,
                                    fontWeight: FontWeight.w600,
                                  ),
                            ),
                          ),
                          _SidebarIconButton(
                            tooltip: context.l10n.text(
                              'workspace.newConversation',
                            ),
                            icon: CupertinoIcons.square_pencil,
                            keyValue: 'recent-new-conversation',
                            onTap: widget
                                .controller
                                .createAgentWorkspaceConversation,
                          ),
                        ],
                      ),
                    ),
                    for (final conversation
                        in widget.controller.agentWorkspaceConversations)
                      ..._conversationBranch(
                        WorkspaceController.agentWorkspaceId,
                        conversation,
                        agentWorkspace: true,
                      ),
                  ],
                ],
              ),
            ),
            _SidebarFooterAction(
              icon: CupertinoIcons.gear,
              label: context.l10n.text('workspace.settings'),
              onTap: widget.onOpenSettings,
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _deleteConversation(
    BuildContext context,
    String groupId,
    Conversation conversation,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => Dialog(
        backgroundColor: Colors.transparent,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: GlassCard(
            padding: const EdgeInsets.fromLTRB(22, 20, 22, 16),
            shape: const LiquidRoundedSuperellipse(borderRadius: 20),
            useOwnLayer: true,
            settings: _composerGlassSettings(dialogContext),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.l10n.text('settings.deleteForeverNamed', {
                    'name': context.l10n.conversationTitle(conversation.title),
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
                      child: Text(context.l10n.text('common.cancel')),
                    ),
                    const SizedBox(width: 8),
                    GlassButton.custom(
                      key: const ValueKey('conversation-delete-confirm'),
                      width: 94,
                      height: 36,
                      label: context.l10n.text('settings.deleteForever'),
                      onTap: () => Navigator.pop(dialogContext, true),
                      shape: const LiquidRoundedRectangle(borderRadius: 10),
                      settings: _composerGlassSettings(dialogContext),
                      child: Text(
                        context.l10n.text('settings.deleteForever'),
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
      await widget.controller.deleteConversation(groupId, conversation.id);
    } on Object {
      // The controller exposes the failure through the workspace error banner.
    }
  }
}

class _NewConversationAction extends StatelessWidget {
  const _NewConversationAction({required this.onTap, this.compact = false});

  final VoidCallback onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      label: context.l10n.text('workspace.newConversation'),
      child: InkWell(
        key: const ValueKey('new-agent-workspace-conversation'),
        borderRadius: BorderRadius.circular(9),
        onTap: onTap,
        child: SizedBox(
          height: 38,
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: compact ? 8 : 10),
            child: Row(
              children: [
                Icon(
                  CupertinoIcons.square_pencil,
                  size: 17,
                  color: colors.onSurface,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    context.l10n.text('workspace.newConversation'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontSize: 13.5,
                      color: colors.onSurface,
                      fontWeight: FontWeight.w700,
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

class _WorkspaceHeader extends StatelessWidget {
  const _WorkspaceHeader({
    required this.group,
    required this.selected,
    required this.expanded,
    required this.onTap,
    required this.onToggleExpanded,
    required this.onNewConversation,
    required this.onRemoveProject,
  });

  final WorkspaceGroup group;
  final bool selected;
  final bool expanded;
  final VoidCallback onTap;
  final VoidCallback onToggleExpanded;
  final VoidCallback onNewConversation;
  final VoidCallback onRemoveProject;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return GlassMenu(
      key: ValueKey('project-context-menu:${group.id}'),
      menuWidth: 176,
      menuBorderRadius: 16,
      itemBorderRadius: 10,
      autoAdjustToScreen: true,
      menuPadding: const EdgeInsets.all(8),
      menuAlignment: GlassMenuAlignment.topRight,
      settings: _composerGlassSettings(context),
      triggerBuilder: (context, toggleMenu) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onSecondaryTapDown: (_) => toggleMenu(),
        child: Semantics(
          selected: selected,
          button: true,
          child: InkWell(
            key: ValueKey('workspace-header:${group.id}'),
            borderRadius: BorderRadius.circular(10),
            onTap: onTap,
            child: Container(
              height: 39,
              padding: const EdgeInsets.only(left: 8, right: 4),
              decoration: BoxDecoration(
                color: Colors.transparent,
                borderRadius: BorderRadius.circular(9),
              ),
              child: Row(
                children: [
                  Icon(
                    group.project == null
                        ? CupertinoIcons.sparkles
                        : CupertinoIcons.square_stack_3d_up,
                    size: 16,
                    color: colors.onSurface,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      group.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontSize: 13.5,
                        color: colors.onSurface,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  if (selected)
                    _SidebarIconButton(
                      tooltip: context.l10n.text('workspace.newConversation'),
                      icon: CupertinoIcons.square_pencil,
                      keyValue: 'project-new-conversation:${group.id}',
                      onTap: onNewConversation,
                    ),
                  _SidebarIconButton(
                    tooltip: context.l10n.text(
                      expanded
                          ? 'workspace.collapseProject'
                          : 'workspace.expandProject',
                    ),
                    icon: expanded
                        ? CupertinoIcons.chevron_down
                        : CupertinoIcons.chevron_right,
                    keyValue: 'project-disclosure:${group.id}',
                    onTap: onToggleExpanded,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
      items: [
        GlassMenuItem(
          key: ValueKey('project-remove:${group.id}'),
          title: context.l10n.text('workspace.removeProject'),
          height: 38,
          isDestructive: true,
          icon: const Icon(CupertinoIcons.folder_badge_minus, size: 16),
          onTap: onRemoveProject,
        ),
      ],
    );
  }
}

class _ConversationTile extends StatefulWidget {
  const _ConversationTile({
    required this.conversation,
    required this.selected,
    required this.onTap,
    required this.onArchive,
    required this.onDelete,
    this.hasChildren = false,
    this.expanded = false,
    this.onToggleExpanded,
  });

  final Conversation conversation;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback onArchive;
  final VoidCallback onDelete;
  final bool hasChildren;
  final bool expanded;
  final VoidCallback? onToggleExpanded;

  @override
  State<_ConversationTile> createState() => _ConversationTileState();
}

class _ConversationTileState extends State<_ConversationTile> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final manageable = [widget.conversation, ...widget.conversation.subSessions]
        .every(
          (conversation) => !{
            RunStatus.starting,
            RunStatus.running,
            RunStatus.suspending,
            RunStatus.suspended,
          }.contains(conversation.status),
        );
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: Semantics(
        selected: widget.selected,
        button: true,
        child: InkWell(
          key: ValueKey('conversation-tile:${widget.conversation.id}'),
          borderRadius: BorderRadius.circular(8),
          onTap: widget.onTap,
          child: Container(
            height: 31,
            padding: const EdgeInsets.only(left: 4, right: 8),
            decoration: BoxDecoration(
              color: widget.selected
                  ? colors.onSurface.withValues(alpha: 0.095)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                if (widget.hasChildren)
                  InkWell(
                    key: ValueKey(
                      'conversation-disclosure:${widget.conversation.id}',
                    ),
                    onTap: widget.onToggleExpanded,
                    borderRadius: BorderRadius.circular(6),
                    child: SizedBox.square(
                      dimension: 18,
                      child: Icon(
                        widget.expanded
                            ? CupertinoIcons.chevron_down
                            : CupertinoIcons.chevron_right,
                        size: 11,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  )
                else
                  const SizedBox(width: 18),
                Icon(
                  CupertinoIcons.bubble_left,
                  size: 14,
                  color: widget.selected
                      ? colors.primary
                      : const Color(0xFFB36BFF).withValues(alpha: 0.9),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    context.l10n.conversationTitle(widget.conversation.title),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontSize: 13,
                      color: colors.onSurface,
                      fontWeight: widget.selected
                          ? FontWeight.w600
                          : FontWeight.w500,
                    ),
                  ),
                ),
                if (widget.conversation.status != RunStatus.idle &&
                    widget.conversation.status != RunStatus.completed)
                  _StatusDot(status: widget.conversation.status),
                IgnorePointer(
                  ignoring: !_hovered && !widget.selected,
                  child: AnimatedOpacity(
                    duration: const Duration(milliseconds: 140),
                    opacity: _hovered || widget.selected ? 1 : 0,
                    child: GlassMenu(
                      key: ValueKey(
                        'conversation-actions-${widget.conversation.id}',
                      ),
                      menuWidth: 148,
                      menuBorderRadius: 16,
                      itemBorderRadius: 10,
                      autoAdjustToScreen: true,
                      menuPadding: const EdgeInsets.all(8),
                      settings: _composerGlassSettings(context),
                      triggerBuilder: (context, toggle) => Tooltip(
                        message: context.l10n.text('workspace.moreActions'),
                        child: IconButton(
                          key: ValueKey(
                            'conversation-actions-button-${widget.conversation.id}',
                          ),
                          constraints: const BoxConstraints.tightFor(
                            width: 24,
                            height: 24,
                          ),
                          padding: EdgeInsets.zero,
                          splashRadius: 12,
                          onPressed: toggle,
                          icon: Icon(
                            CupertinoIcons.ellipsis,
                            size: 14,
                            color: colors.onSurfaceVariant,
                          ),
                        ),
                      ),
                      items: [
                        GlassMenuItem(
                          key: ValueKey(
                            'conversation-archive-${widget.conversation.id}',
                          ),
                          title: context.l10n.text('workspace.archive'),
                          height: 38,
                          enabled: manageable,
                          icon: const Icon(CupertinoIcons.archivebox, size: 16),
                          onTap: widget.onArchive,
                        ),
                        GlassMenuDivider(height: 6, indent: 8),
                        GlassMenuItem(
                          key: ValueKey(
                            'conversation-delete-${widget.conversation.id}',
                          ),
                          title: context.l10n.text('common.delete'),
                          height: 38,
                          enabled: true,
                          isDestructive: true,
                          icon: const Icon(CupertinoIcons.trash, size: 16),
                          onTap: widget.onDelete,
                        ),
                      ],
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

class _SubSessionTile extends StatelessWidget {
  const _SubSessionTile({
    required this.conversation,
    required this.depth,
    required this.selected,
    required this.onTap,
  });

  final Conversation conversation;
  final int depth;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return InkWell(
      key: ValueKey('sub-session-tile:${conversation.sessionId}'),
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Container(
        height: 30,
        padding: EdgeInsets.only(left: 42 + depth * 14, right: 10),
        decoration: BoxDecoration(
          color: selected
              ? colors.onSurface.withValues(alpha: 0.095)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            Icon(
              CupertinoIcons.arrow_turn_down_right,
              size: 13,
              color: selected
                  ? colors.primary
                  : colors.onSurfaceVariant.withValues(alpha: 0.72),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                conversation.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontSize: 12.5,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                ),
              ),
            ),
            if (conversation.pendingInteraction != null)
              Icon(
                CupertinoIcons.exclamationmark_circle_fill,
                size: 13,
                color: colors.tertiary,
              )
            else if (conversation.status != RunStatus.idle &&
                conversation.status != RunStatus.completed)
              _StatusDot(status: conversation.status),
          ],
        ),
      ),
    );
  }
}

class _ThreadPanel extends StatelessWidget {
  const _ThreadPanel({
    required this.controller,
    required this.railCollapsed,
    required this.workspaceCollapsed,
    required this.onToggleRail,
    required this.onToggleWorkspace,
    this.compact = false,
  });

  final WorkspaceController controller;
  final bool railCollapsed;
  final bool workspaceCollapsed;
  final VoidCallback onToggleRail;
  final VoidCallback onToggleWorkspace;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final conversation = controller.selectedDisplayConversation;
    if (conversation == null) return const SizedBox.shrink();
    final readOnly = controller.viewingSubSession;
    return DecoratedBox(
      decoration: BoxDecoration(color: Theme.of(context).colorScheme.surface),
      child: Column(
        children: [
          _ThreadHeader(
            controller: controller,
            conversation: conversation,
            railCollapsed: railCollapsed,
            compact: compact,
            workspaceCollapsed: workspaceCollapsed,
            onToggleRail: onToggleRail,
            onToggleWorkspace: onToggleWorkspace,
          ),
          if (conversation.messages.isEmpty)
            Expanded(
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 900),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          context.l10n.text('workspace.emptyPrompt'),
                          style: Theme.of(context).textTheme.headlineMedium
                              ?.copyWith(
                                fontSize: 30,
                                fontWeight: FontWeight.w500,
                                letterSpacing: -0.6,
                              ),
                        ),
                        const SizedBox(height: 42),
                        if (!readOnly)
                          _Composer(
                            controller: controller,
                            conversation: conversation,
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            )
          else ...[
            Expanded(
              child: _MessageList(
                controller: controller,
                conversation: conversation,
                subSessions:
                    controller.selectedConversation?.subSessions ?? const [],
              ),
            ),
            if (conversation.pendingInteraction case final interaction?)
              _InteractionCard(
                interaction: interaction,
                onReply: readOnly
                    ? controller.replyDisplayInteraction
                    : controller.replyInteraction,
              ),
            if (!readOnly)
              Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 820),
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(34, 8, 34, compact ? 18 : 24),
                    child: _Composer(
                      controller: controller,
                      conversation: conversation,
                    ),
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _ThreadHeader extends StatelessWidget {
  const _ThreadHeader({
    required this.controller,
    required this.conversation,
    required this.railCollapsed,
    required this.compact,
    required this.workspaceCollapsed,
    required this.onToggleRail,
    required this.onToggleWorkspace,
  });

  final WorkspaceController controller;
  final Conversation conversation;
  final bool railCollapsed;
  final bool compact;
  final bool workspaceCollapsed;
  final VoidCallback onToggleRail;
  final VoidCallback onToggleWorkspace;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: desktopPaneHeaderHeight,
      padding: EdgeInsets.only(left: railCollapsed ? 136 : 10, right: 18),
      child: Row(
        children: [
          if (railCollapsed || compact) ...[
            _HeaderIconButton(
              keyValue: railCollapsed
                  ? 'rail-expand-button'
                  : 'rail-collapse-button',
              icon: CupertinoIcons.sidebar_left,
              tooltip: context.l10n.text(
                railCollapsed
                    ? 'workspace.expandSidebar'
                    : 'workspace.collapseSidebar',
              ),
              semanticsLabel: context.l10n.text(
                railCollapsed
                    ? 'workspace.expandSidebar'
                    : 'workspace.collapseSidebar',
              ),
              highlighted: railCollapsed,
              onTap: onToggleRail,
            ),
            const SizedBox(width: 14),
          ],
          Expanded(
            child: Text(
              context.l10n.conversationTitle(conversation.title),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontSize: 15,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          if (conversation.status != RunStatus.idle) ...[
            _RunStatusChip(status: conversation.status),
            const SizedBox(width: 4),
          ],
          if ({
            RunStatus.starting,
            RunStatus.running,
          }.contains(conversation.status))
            _HeaderIconButton(
              icon: CupertinoIcons.pause,
              onTap: controller.pause,
            ),
          if (conversation.status == RunStatus.suspended &&
              conversation.pendingInteraction == null)
            _HeaderIconButton(
              icon: CupertinoIcons.play,
              onTap: controller.resume,
            ),
          if ({
            RunStatus.starting,
            RunStatus.running,
            RunStatus.suspending,
            RunStatus.suspended,
          }.contains(conversation.status))
            _HeaderIconButton(
              icon: CupertinoIcons.stop_fill,
              onTap: controller.cancel,
            ),
          const SizedBox(width: 8),
          _HeaderIconButton(
            keyValue: workspaceCollapsed
                ? 'canvas-expand-button'
                : 'canvas-collapse-button',
            icon: CupertinoIcons.sidebar_right,
            onTap: onToggleWorkspace,
          ),
        ],
      ),
    );
  }
}

class _MessageList extends StatefulWidget {
  const _MessageList({
    required this.controller,
    required this.conversation,
    this.subSessions = const [],
  });

  final WorkspaceController controller;
  final Conversation conversation;
  final List<Conversation> subSessions;

  @override
  State<_MessageList> createState() => _MessageListState();
}

class _MessageListState extends State<_MessageList> {
  final _scrollController = ScrollController();
  bool _showScrollToBottom = false;
  String _contentSignature = '';

  Conversation get conversation => widget.conversation;

  @override
  void initState() {
    super.initState();
    _contentSignature = _signature();
    _scrollController.addListener(_updateScrollButton);
    WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToBottom());
  }

  @override
  void didUpdateWidget(covariant _MessageList oldWidget) {
    super.didUpdateWidget(oldWidget);
    final nextSignature = _signature();
    if (nextSignature == _contentSignature) return;
    final shouldFollow =
        !_scrollController.hasClients ||
        _scrollController.position.maxScrollExtent -
                _scrollController.position.pixels <
            96;
    _contentSignature = nextSignature;
    if (shouldFollow) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
    }
  }

  @override
  void dispose() {
    _scrollController
      ..removeListener(_updateScrollButton)
      ..dispose();
    super.dispose();
  }

  String _signature() {
    final messageSignature = conversation.messages
        .map(
          (message) =>
              '${message.id}:${message.text.length}:${message.streaming}:${message.processOnly}',
        )
        .join('|');
    final processSignature = conversation.processPanels
        .map(
          (panel) =>
              '${panel.id}:${panel.running}:${panel.activities.length}:'
              '${panel.activities.where((value) => value.active).length}:'
              '${panel.activities.fold<int>(0, (sum, value) => sum + value.result.length)}',
        )
        .join('|');
    final subSessionSignature = widget.subSessions
        .map(
          (value) =>
              '${value.sessionId}:${value.status}:${value.runSequence}:'
              '${value.messages.fold<int>(0, (sum, message) => sum + message.text.length)}:'
              '${value.pendingInteraction?.id ?? ''}',
        )
        .join('|');
    return '$messageSignature:$processSignature:$subSessionSignature:'
        '${conversation.thinking}';
  }

  void _updateScrollButton() {
    if (!_scrollController.hasClients) return;
    final next =
        _scrollController.position.maxScrollExtent -
            _scrollController.position.pixels >
        140;
    if (next != _showScrollToBottom && mounted) {
      setState(() => _showScrollToBottom = next);
    }
  }

  void _jumpToBottom() {
    if (!mounted || !_scrollController.hasClients) return;
    _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
  }

  void _scrollToBottom() {
    if (!mounted || !_scrollController.hasClients) return;
    _scrollController.animateTo(
      _scrollController.position.maxScrollExtent,
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
    );
  }

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    final attachedPanelIds = <String>{};
    for (final message in conversation.messages) {
      if (message.processOnly) continue;
      final panel = message.role == 'assistant'
          ? _panelForMessage(message)
          : null;
      children.add(
        _MessageBubble(
          key: ValueKey(message.id),
          message: message,
          onEdit:
              widget.controller.canRewriteLastUserMessage(conversation, message)
              ? (value) =>
                    widget.controller.rewriteLastUserMessage(message.id, value)
              : null,
          onBranch:
              panel != null &&
                  panel.runId.isNotEmpty &&
                  !panel.running &&
                  panel.completedAt != null &&
                  !widget.controller.viewingSubSession
              ? () => widget.controller.branchFromRun(panel.runId)
              : null,
        ),
      );
      final attachedPanels = conversation.processPanels
          .where(
            (value) =>
                value.anchorMessageId == message.id && _shouldShowPanel(value),
          )
          .toList(growable: false);
      for (final panel in attachedPanels) {
        attachedPanelIds.add(panel.id);
        children.add(const SizedBox(height: 14));
        children.add(
          _ProcessPanel(
            key: ValueKey(panel.id),
            panel: panel,
            messages: _processMessagesFor(panel),
            subSessions: _subSessionsFor(panel),
          ),
        );
      }
      children.add(SizedBox(height: attachedPanels.isEmpty ? 26 : 16));
    }
    for (final panel in conversation.processPanels.where(
      (value) =>
          !attachedPanelIds.contains(value.id) && _shouldShowPanel(value),
    )) {
      children.add(
        _ProcessPanel(
          key: ValueKey(panel.id),
          panel: panel,
          messages: _processMessagesFor(panel),
          subSessions: _subSessionsFor(panel),
        ),
      );
      children.add(const SizedBox(height: 26));
    }
    if (conversation.thinking) {
      children.add(const _RunningThinkingStatus());
      children.add(const SizedBox(height: 14));
    }
    return Stack(
      children: [
        ListView(
          key: const ValueKey('thread-message-list'),
          controller: _scrollController,
          padding: const EdgeInsets.fromLTRB(34, 28, 34, 34),
          children: children,
        ),
        if (_showScrollToBottom)
          Positioned(
            right: 34,
            bottom: 12,
            child: _ThreadScrollToBottomButton(onTap: _scrollToBottom),
          ),
      ],
    );
  }

  bool _shouldShowPanel(RuntimeProcessPanel panel) {
    return panel.running ||
        panel.activities.isNotEmpty ||
        _processMessagesFor(panel).isNotEmpty ||
        _subSessionsFor(panel).isNotEmpty;
  }

  RuntimeProcessPanel? _panelForMessage(ChatMessage message) {
    final messageIndex = conversation.messages.indexWhere(
      (value) => value.id == message.id,
    );
    if (messageIndex < 0) return null;
    RuntimeProcessPanel? result;
    var resultAnchorIndex = -1;
    for (final panel in conversation.processPanels) {
      final anchorIndex = conversation.messages.indexWhere(
        (value) => value.id == panel.anchorMessageId,
      );
      if (anchorIndex < 0 || anchorIndex >= messageIndex) continue;
      final hasLaterUser = conversation.messages
          .sublist(anchorIndex + 1, messageIndex)
          .any((value) => value.role == 'user');
      if (!hasLaterUser && anchorIndex > resultAnchorIndex) {
        result = panel;
        resultAnchorIndex = anchorIndex;
      }
    }
    return result;
  }

  List<ChatMessage> _processMessagesFor(RuntimeProcessPanel panel) {
    final anchorIndex = conversation.messages.indexWhere(
      (value) => value.id == panel.anchorMessageId,
    );
    if (anchorIndex < 0) return const [];
    var endIndex = conversation.messages.length;
    for (
      var index = anchorIndex + 1;
      index < conversation.messages.length;
      index++
    ) {
      if (conversation.messages[index].role == 'user') {
        endIndex = index;
        break;
      }
    }
    return [
      for (final message in conversation.messages.sublist(
        anchorIndex + 1,
        endIndex,
      ))
        if (message.role == 'assistant' && message.processOnly) message,
    ];
  }

  List<Conversation> _subSessionsFor(RuntimeProcessPanel panel) {
    final parentSessionId = conversation.sessionId;
    final values = <Conversation>[
      for (final value in widget.subSessions)
        if (value.parentSessionId == parentSessionId &&
            (panel.runId.isEmpty || value.parentRunId == panel.runId))
          value,
    ];
    final includedSessionIds = {for (final value in values) value.sessionId};
    var added = true;
    while (added) {
      added = false;
      for (final value in widget.subSessions) {
        if (values.contains(value) ||
            !includedSessionIds.contains(value.parentSessionId)) {
          continue;
        }
        values.add(value);
        includedSessionIds.add(value.sessionId);
        added = true;
      }
    }
    return values;
  }
}

class _RunningThinkingStatus extends StatefulWidget {
  const _RunningThinkingStatus();

  @override
  State<_RunningThinkingStatus> createState() => _RunningThinkingStatusState();
}

class _RunningThinkingStatusState extends State<_RunningThinkingStatus> {
  late final Timer _timer;
  var _dotCount = 1;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 420), (_) {
      if (mounted) setState(() => _dotCount = (_dotCount % 3) + 1);
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final label =
        '${context.l10n.text('workspace.thinking')}'
        '${'.' * _dotCount}';
    return Semantics(
      key: const ValueKey('thread-thinking-status'),
      liveRegion: true,
      label: context.l10n.text('workspace.thinking'),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CupertinoActivityIndicator(
                  radius: 7,
                  color: colors.onSurfaceVariant,
                ),
                const SizedBox(width: 9),
                Text(
                  label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: colors.onSurface.withValues(alpha: 0.82),
                    fontWeight: FontWeight.w600,
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

class _ToolActivityShimmer extends StatefulWidget {
  const _ToolActivityShimmer({
    required this.child,
    this.enabled = true,
    required this.shimmerKey,
  });

  final Widget child;
  final bool enabled;
  final Key shimmerKey;

  @override
  State<_ToolActivityShimmer> createState() => _ToolActivityShimmerState();
}

class _ToolActivityShimmerState extends State<_ToolActivityShimmer>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    );
    if (widget.enabled) _controller.repeat();
  }

  @override
  void didUpdateWidget(covariant _ToolActivityShimmer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled) {
      _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.maybeOf(context);
    final animationsDisabled =
        (media?.disableAnimations ?? false) ||
        (media?.accessibleNavigation ?? false);
    if (!widget.enabled || animationsDisabled) return widget.child;

    final colors = Theme.of(context).colorScheme;
    final base = colors.onSurfaceVariant.withValues(alpha: 0.72);
    final highlight = colors.onSurface;
    return RepaintBoundary(
      key: widget.shimmerKey,
      child: AnimatedBuilder(
        animation: _controller,
        child: widget.child,
        builder: (context, child) => ShaderMask(
          blendMode: BlendMode.srcIn,
          shaderCallback: (bounds) {
            final sweepWidth = max(bounds.width * 0.52, 42.0);
            final travel = bounds.width + sweepWidth * 2;
            final left = -sweepWidth + travel * _controller.value;
            return LinearGradient(
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
              colors: [base, base, highlight, base, base],
              stops: const [0, 0.32, 0.5, 0.68, 1],
            ).createShader(Rect.fromLTWH(left, 0, sweepWidth, bounds.height));
          },
          child: child,
        ),
      ),
    );
  }
}

class _MessageBubble extends StatefulWidget {
  const _MessageBubble({
    required this.message,
    this.onEdit,
    this.onBranch,
    super.key,
  });

  final ChatMessage message;
  final Future<void> Function(String value)? onEdit;
  final Future<bool> Function()? onBranch;

  @override
  State<_MessageBubble> createState() => _MessageBubbleState();
}

class _MessageBubbleState extends State<_MessageBubble> {
  late final TextEditingController _editor = TextEditingController(
    text: widget.message.text,
  );
  bool _editing = false;
  bool _submitting = false;

  ChatMessage get message => widget.message;

  Future<void> _copy() => Clipboard.setData(ClipboardData(text: message.text));

  @override
  void didUpdateWidget(covariant _MessageBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_editing && oldWidget.message.text != widget.message.text) {
      _editor.text = widget.message.text;
    }
  }

  @override
  void dispose() {
    _editor.dispose();
    super.dispose();
  }

  Future<void> _submitEdit() async {
    final value = _editor.text.trim();
    if (value.isEmpty || _submitting || widget.onEdit == null) return;
    setState(() => _submitting = true);
    try {
      await widget.onEdit!(value);
      if (mounted) setState(() => _editing = false);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final user = message.role == 'user';
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: Column(
          crossAxisAlignment: user
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            Align(
              alignment: user ? Alignment.centerRight : Alignment.centerLeft,
              child: _editing
                  ? GlassCard(
                      key: ValueKey('message-edit-card:${message.id}'),
                      width: min(608, MediaQuery.sizeOf(context).width - 68),
                      padding: const EdgeInsets.all(12),
                      shape: const LiquidRoundedSuperellipse(borderRadius: 18),
                      useOwnLayer: true,
                      settings: _composerGlassSettings(context),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          TextField(
                            key: ValueKey('message-edit-field:${message.id}'),
                            controller: _editor,
                            autofocus: true,
                            minLines: 2,
                            maxLines: 8,
                            onSubmitted: (_) => _submitEdit(),
                          ),
                          const SizedBox(height: 10),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              TextButton(
                                onPressed: _submitting
                                    ? null
                                    : () => setState(() => _editing = false),
                                child: Text(context.l10n.text('common.cancel')),
                              ),
                              const SizedBox(width: 8),
                              GlassButton.custom(
                                key: ValueKey(
                                  'message-edit-submit:${message.id}',
                                ),
                                width: 76,
                                height: 34,
                                label: context.l10n.text('common.save'),
                                enabled: !_submitting,
                                onTap: _submitEdit,
                                shape: const LiquidRoundedRectangle(
                                  borderRadius: 10,
                                ),
                                settings: _composerGlassSettings(context),
                                child: _submitting
                                    ? const CupertinoActivityIndicator(
                                        radius: 7,
                                      )
                                    : Text(context.l10n.text('common.save')),
                              ),
                            ],
                          ),
                        ],
                      ),
                    )
                  : Container(
                      constraints: BoxConstraints(maxWidth: user ? 608 : 760),
                      padding: user
                          ? const EdgeInsets.symmetric(
                              horizontal: 15,
                              vertical: 12,
                            )
                          : EdgeInsets.zero,
                      decoration: BoxDecoration(
                        color: user
                            ? colors.surfaceContainerHighest.withValues(
                                alpha: 0.48,
                              )
                            : Colors.transparent,
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: MarkdownBody(
                        data: message.text + (message.streaming ? '\n\n▍' : ''),
                        selectable: true,
                        styleSheet: _messageMarkdownStyle(context),
                      ),
                    ),
            ),
            const SizedBox(height: 5),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _ThreadActionButton(
                  keyValue: 'message-copy:${message.id}',
                  icon: CupertinoIcons.doc_on_doc,
                  tooltip: context.l10n.text('common.copy'),
                  onTap: _copy,
                ),
                if (widget.onEdit != null) ...[
                  const SizedBox(width: 4),
                  _ThreadActionButton(
                    keyValue: 'message-edit:${message.id}',
                    icon: CupertinoIcons.pencil,
                    tooltip: context.l10n.text('common.edit'),
                    onTap: () => setState(() => _editing = true),
                  ),
                ],
                if (widget.onBranch != null) ...[
                  const SizedBox(width: 4),
                  _ThreadActionButton(
                    keyValue: 'message-branch:${message.id}',
                    icon: CupertinoIcons.arrow_branch,
                    tooltip: context.l10n.text('workspace.branchToNewChat'),
                    onTap: () => widget.onBranch!(),
                  ),
                ],
                const SizedBox(width: 7),
                Text(
                  _messageTime(message.createdAt),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    fontSize: 10.5,
                    color: colors.onSurfaceVariant.withValues(alpha: 0.68),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ProcessPanel extends StatefulWidget {
  const _ProcessPanel({
    required this.panel,
    required this.messages,
    this.subSessions = const [],
    super.key,
  });

  final RuntimeProcessPanel panel;
  final List<ChatMessage> messages;
  final List<Conversation> subSessions;

  @override
  State<_ProcessPanel> createState() => _ProcessPanelState();
}

class _ProcessPanelState extends State<_ProcessPanel> {
  late bool _expanded;
  late bool _wasRunning;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _expanded = widget.panel.running;
    _wasRunning = widget.panel.running;
    _syncTimer();
  }

  @override
  void didUpdateWidget(covariant _ProcessPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_wasRunning && !widget.panel.running) _expanded = false;
    _wasRunning = widget.panel.running;
    _syncTimer();
  }

  void _syncTimer() {
    if (!widget.panel.running) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    _timer ??= Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final panel = widget.panel;
    final colors = Theme.of(context).colorScheme;
    final elapsed = (panel.completedAt ?? DateTime.now()).difference(
      panel.startedAt,
    );
    final items = _orderedProcessItems(panel, widget.messages);
    final childSessionIds = {
      for (final value in widget.subSessions) value.sessionId,
    };
    final rootSubSessions = [
      for (final value in widget.subSessions)
        if (!childSessionIds.contains(value.parentSessionId)) value,
    ];
    final unlinkedRootSubSessions = _unlinkedSubSessions(
      items,
      rootSubSessions,
    );
    return Center(
      child: ConstrainedBox(
        key: const ValueKey('process-panel'),
        constraints: const BoxConstraints(maxWidth: 760),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              button: true,
              expanded: _expanded,
              label: context.l10n.text(
                panel.running ? 'workspace.processing' : 'workspace.processed',
              ),
              child: InkWell(
                key: const ValueKey('process-panel-toggle'),
                borderRadius: BorderRadius.circular(8),
                onTap: () => setState(() => _expanded = !_expanded),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      if (panel.running) ...[
                        SizedBox.square(
                          dimension: 15,
                          child: CupertinoActivityIndicator(
                            color: colors.primary,
                          ),
                        ),
                        const SizedBox(width: 8),
                      ],
                      Text(
                        panel.running
                            ? context.l10n.text('workspace.processing')
                            : context.l10n.text('workspace.processedTime', {
                                'time': _elapsedLabel(elapsed),
                              }),
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: colors.onSurfaceVariant.withValues(
                            alpha: 0.86,
                          ),
                        ),
                      ),
                      if (panel.running) ...[
                        const SizedBox(width: 5),
                        Text(
                          _elapsedLabel(elapsed),
                          style: Theme.of(context).textTheme.labelMedium
                              ?.copyWith(
                                fontSize: 11.5,
                                color: colors.onSurfaceVariant,
                              ),
                        ),
                      ],
                      const Spacer(),
                      Icon(
                        _expanded
                            ? CupertinoIcons.chevron_up
                            : CupertinoIcons.chevron_right,
                        size: 14,
                        color: colors.onSurfaceVariant,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Divider(
              height: 1,
              color: colors.outlineVariant.withValues(alpha: 0.36),
            ),
            if (_expanded && items.isNotEmpty) ...[
              const SizedBox(height: 12),
              _ProcessStreamLog(
                items: items,
                subSessions: rootSubSessions,
                allSubSessions: widget.subSessions,
              ),
            ],
            if (_expanded && unlinkedRootSubSessions.isNotEmpty) ...[
              if (items.isNotEmpty) const SizedBox(height: 10),
              for (final child in unlinkedRootSubSessions) ...[
                _SubSessionProcessGroup(
                  conversation: child,
                  allSubSessions: widget.subSessions,
                ),
                if (child != unlinkedRootSubSessions.last)
                  const SizedBox(height: 8),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

sealed class _ProcessStreamItem {
  const _ProcessStreamItem({
    required this.sequence,
    required this.createdAt,
    required this.sourceIndex,
  });

  final int sequence;
  final DateTime createdAt;
  final int sourceIndex;
}

class _ProcessActivityItem extends _ProcessStreamItem {
  _ProcessActivityItem({required this.activity, required super.sourceIndex})
    : super(sequence: activity.sequence, createdAt: activity.startedAt);

  final RuntimeActivity activity;
}

class _ProcessMessageItem extends _ProcessStreamItem {
  _ProcessMessageItem({required this.message, required super.sourceIndex})
    : super(sequence: message.sequence, createdAt: message.createdAt);

  final ChatMessage message;
}

List<_ProcessStreamItem> _orderedProcessItems(
  RuntimeProcessPanel panel,
  List<ChatMessage> messages,
) {
  var sourceIndex = 0;
  final items = <_ProcessStreamItem>[
    for (final activity in panel.activities)
      _ProcessActivityItem(activity: activity, sourceIndex: sourceIndex++),
    for (final message in messages)
      _ProcessMessageItem(message: message, sourceIndex: sourceIndex++),
  ];
  items.sort((left, right) {
    if (left.sequence > 0 && right.sequence > 0) {
      final bySequence = left.sequence.compareTo(right.sequence);
      if (bySequence != 0) return bySequence;
    }
    final byTime = left.createdAt.compareTo(right.createdAt);
    if (byTime != 0) return byTime;
    return left.sourceIndex.compareTo(right.sourceIndex);
  });
  return items;
}

class _ProcessStreamLog extends StatelessWidget {
  const _ProcessStreamLog({
    required this.items,
    this.subSessions = const [],
    this.allSubSessions = const [],
  });

  final List<_ProcessStreamItem> items;
  final List<Conversation> subSessions;
  final List<Conversation> allSubSessions;

  @override
  Widget build(BuildContext context) {
    final anchoredActivityIds = {
      for (final child in subSessions)
        if ((child.parentToolCallId ?? '').isNotEmpty) child.parentToolCallId!,
    };
    final entries = _processStreamEntries(
      items,
      separateActivityIds: anchoredActivityIds,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var index = 0; index < entries.length; index++) ...[
          entries[index].build(context),
          for (final child in subSessions.where(
            (value) =>
                (value.parentToolCallId ?? '').isNotEmpty &&
                entries[index].containsActivity(value.parentToolCallId!),
          )) ...[
            const SizedBox(height: 8),
            _SubSessionProcessGroup(
              conversation: child,
              allSubSessions: allSubSessions,
            ),
          ],
          if (index != entries.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

List<_ProcessStreamEntry> _processStreamEntries(
  List<_ProcessStreamItem> items, {
  Set<String> separateActivityIds = const {},
}) {
  final entries = <_ProcessStreamEntry>[];
  var pendingActivities = <RuntimeActivity>[];

  void flushActivities() {
    if (pendingActivities.isEmpty) return;
    if (pendingActivities.length == 1) {
      entries.add(_SingleProcessActivityEntry(pendingActivities.single));
    } else {
      entries.add(_GroupedProcessActivityEntry(List.of(pendingActivities)));
    }
    pendingActivities = <RuntimeActivity>[];
  }

  for (final item in items) {
    if (item is _ProcessActivityItem) {
      if (separateActivityIds.contains(item.activity.id)) {
        flushActivities();
        entries.add(_SingleProcessActivityEntry(item.activity));
        continue;
      }
      if (pendingActivities.isNotEmpty &&
          _activityCategory(pendingActivities.first) !=
              _activityCategory(item.activity)) {
        flushActivities();
      }
      pendingActivities.add(item.activity);
      continue;
    }
    final message = (item as _ProcessMessageItem).message;
    if (message.text.trim().isEmpty) continue;
    flushActivities();
    entries.add(_ProcessMessageEntry(message));
  }
  flushActivities();
  return entries;
}

sealed class _ProcessStreamEntry {
  bool containsActivity(String activityId) => false;

  Widget build(BuildContext context);
}

class _SingleProcessActivityEntry extends _ProcessStreamEntry {
  _SingleProcessActivityEntry(this.activity);

  final RuntimeActivity activity;

  @override
  bool containsActivity(String activityId) => activity.id == activityId;

  @override
  Widget build(BuildContext context) => _ProcessActivityLine(
    key: ValueKey('process-activity:${activity.id}'),
    activity: activity,
  );
}

class _GroupedProcessActivityEntry extends _ProcessStreamEntry {
  _GroupedProcessActivityEntry(this.activities);

  final List<RuntimeActivity> activities;

  @override
  bool containsActivity(String activityId) =>
      activities.any((activity) => activity.id == activityId);

  @override
  Widget build(BuildContext context) => _ProcessActivityGroup(
    key: ValueKey('process-operation-group:${activities.first.id}'),
    activities: activities,
  );
}

class _ProcessMessageEntry extends _ProcessStreamEntry {
  _ProcessMessageEntry(this.message);

  final ChatMessage message;

  @override
  Widget build(BuildContext context) => SizedBox(
    key: ValueKey('process-message:${message.id}'),
    width: double.infinity,
    child: MarkdownBody(
      data: message.text + (message.streaming ? '\n\n▍' : ''),
      selectable: true,
      styleSheet: _messageMarkdownStyle(context),
    ),
  );
}

class _ProcessActivityGroup extends StatefulWidget {
  const _ProcessActivityGroup({required this.activities, super.key});

  final List<RuntimeActivity> activities;

  @override
  State<_ProcessActivityGroup> createState() => _ProcessActivityGroupState();
}

class _ProcessActivityGroupState extends State<_ProcessActivityGroup> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final running = widget.activities.any((activity) => activity.active);
    final title = _processSummary(context, widget.activities);
    return Semantics(
      button: true,
      expanded: _expanded,
      label: title,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            borderRadius: BorderRadius.circular(7),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  _ProcessActivityIcon(
                    icon: _processGroupIcon(widget.activities),
                    running: running,
                    failed: widget.activities.any(
                      (activity) => activity.failed,
                    ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: _processTextStyle(
                        context,
                      )?.copyWith(fontWeight: FontWeight.w600),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Icon(
                    _expanded
                        ? CupertinoIcons.chevron_up
                        : CupertinoIcons.chevron_right,
                    size: 13,
                    color: colors.onSurfaceVariant.withValues(alpha: 0.7),
                  ),
                ],
              ),
            ),
          ),
          if (_expanded) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.only(left: 25),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (
                    var index = 0;
                    index < widget.activities.length;
                    index++
                  ) ...[
                    _ProcessActivityLine(
                      key: ValueKey(
                        'process-activity:${widget.activities[index].id}',
                      ),
                      activity: widget.activities[index],
                    ),
                    if (index != widget.activities.length - 1)
                      const SizedBox(height: 8),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SubSessionProcessGroup extends StatefulWidget {
  const _SubSessionProcessGroup({
    required this.conversation,
    required this.allSubSessions,
  });

  final Conversation conversation;
  final List<Conversation> allSubSessions;

  @override
  State<_SubSessionProcessGroup> createState() =>
      _SubSessionProcessGroupState();
}

class _SubSessionProcessGroupState extends State<_SubSessionProcessGroup> {
  late bool _expanded;

  bool get _active => {
    RunStatus.starting,
    RunStatus.running,
    RunStatus.suspending,
    RunStatus.suspended,
  }.contains(widget.conversation.status);

  @override
  void initState() {
    super.initState();
    _expanded = _active;
  }

  @override
  Widget build(BuildContext context) {
    final conversation = widget.conversation;
    final colors = Theme.of(context).colorScheme;
    final items = _subSessionProcessItems(conversation);
    final children = widget.allSubSessions
        .where((value) => value.parentSessionId == conversation.sessionId)
        .toList();
    final unlinkedChildren = _unlinkedSubSessions(items, children);
    final failed =
        conversation.status == RunStatus.failed ||
        conversation.status == RunStatus.cancelled;
    final waiting = conversation.pendingInteraction != null;
    return Container(
      key: ValueKey('sub-session-process:${conversation.sessionId}'),
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: 0.34),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            borderRadius: BorderRadius.circular(7),
            child: Row(
              children: [
                _ProcessActivityIcon(
                  icon: CupertinoIcons.person_2,
                  running: _active && !waiting,
                  failed: failed,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    conversation.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: _processTextStyle(context)?.copyWith(
                      color: waiting ? colors.tertiary : null,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (waiting) ...[
                  Icon(
                    CupertinoIcons.exclamationmark_circle_fill,
                    size: 13,
                    color: colors.tertiary,
                  ),
                  const SizedBox(width: 5),
                  Text(
                    '等待审批',
                    style: _processTextStyle(
                      context,
                    )?.copyWith(fontSize: 11.5, color: colors.tertiary),
                  ),
                ],
                const SizedBox(width: 7),
                Icon(
                  _expanded
                      ? CupertinoIcons.chevron_up
                      : CupertinoIcons.chevron_right,
                  size: 12,
                  color: colors.onSurfaceVariant,
                ),
              ],
            ),
          ),
          if (_expanded && (items.isNotEmpty || children.isNotEmpty)) ...[
            const SizedBox(height: 9),
            Padding(
              padding: const EdgeInsets.only(left: 23),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (items.isNotEmpty)
                    _ProcessStreamLog(
                      items: items,
                      subSessions: children,
                      allSubSessions: widget.allSubSessions,
                    ),
                  if (items.isNotEmpty && unlinkedChildren.isNotEmpty)
                    const SizedBox(height: 8),
                  for (
                    var index = 0;
                    index < unlinkedChildren.length;
                    index++
                  ) ...[
                    _SubSessionProcessGroup(
                      conversation: unlinkedChildren[index],
                      allSubSessions: widget.allSubSessions,
                    ),
                    if (index != unlinkedChildren.length - 1)
                      const SizedBox(height: 8),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

List<_ProcessStreamItem> _subSessionProcessItems(Conversation conversation) {
  var sourceIndex = 0;
  final items = <_ProcessStreamItem>[
    for (final panel in conversation.processPanels)
      for (final activity in panel.activities)
        _ProcessActivityItem(activity: activity, sourceIndex: sourceIndex++),
    for (final message in conversation.messages)
      if (message.role == 'assistant')
        _ProcessMessageItem(message: message, sourceIndex: sourceIndex++),
  ];
  items.sort((left, right) {
    if (left.sequence > 0 && right.sequence > 0) {
      final bySequence = left.sequence.compareTo(right.sequence);
      if (bySequence != 0) return bySequence;
    }
    final byTime = left.createdAt.compareTo(right.createdAt);
    if (byTime != 0) return byTime;
    return left.sourceIndex.compareTo(right.sourceIndex);
  });
  return items;
}

List<Conversation> _unlinkedSubSessions(
  List<_ProcessStreamItem> items,
  List<Conversation> subSessions,
) {
  final activityIds = {
    for (final item in items)
      if (item is _ProcessActivityItem) item.activity.id,
  };
  return [
    for (final child in subSessions)
      if ((child.parentToolCallId ?? '').isEmpty ||
          !activityIds.contains(child.parentToolCallId))
        child,
  ];
}

class _ProcessActivityIcon extends StatelessWidget {
  const _ProcessActivityIcon({
    required this.icon,
    required this.running,
    required this.failed,
  });

  final IconData icon;
  final bool running;
  final bool failed;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final color = failed
        ? colors.error
        : colors.onSurfaceVariant.withValues(alpha: 0.54);
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: SizedBox.square(
        dimension: 16,
        child: running
            ? CupertinoActivityIndicator(color: color, radius: 6)
            : Icon(
                failed ? CupertinoIcons.exclamationmark_circle : icon,
                size: 15,
                color: color,
              ),
      ),
    );
  }
}

class _ProcessActivityLine extends StatelessWidget {
  const _ProcessActivityLine({required this.activity, super.key});

  final RuntimeActivity activity;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final language = toolPresentationLanguage(context);
    final name = localizedToolName(activity.label, language);
    final arguments = toolArgumentPresentation(
      activity.label,
      activity.arguments,
      language,
    );
    final result = localizedToolResultSummary(activity.result, language);
    final titleColor = activity.failed
        ? colors.error
        : colors.onSurfaceVariant.withValues(alpha: dark ? 0.76 : 0.82);
    final detailColor = colors.onSurfaceVariant.withValues(
      alpha: dark ? 0.58 : 0.66,
    );
    return SizedBox(
      width: double.infinity,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ProcessActivityIcon(
            icon: _processGroupIcon([activity]),
            running: activity.active,
            failed: activity.failed,
          ),
          const SizedBox(width: 9),
          Expanded(
            child: _ToolActivityShimmer(
              enabled: activity.active,
              shimmerKey: ValueKey('tool-activity-shimmer:${activity.id}'),
              child: Text.rich(
                TextSpan(
                  children: [
                    TextSpan(
                      text: activity.failed
                          ? '$name · ${localizedToolFailure(language)}'
                          : name,
                      style: _processTextStyle(context)?.copyWith(
                        color: titleColor,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (arguments.primary.isNotEmpty)
                      TextSpan(
                        text: '  ${arguments.primary}',
                        style: _processTextStyle(context)?.copyWith(
                          color: detailColor,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    if (arguments.metadata.isNotEmpty)
                      TextSpan(
                        text: '  ·  ${arguments.metadata.join(' · ')}',
                        style: _processTextStyle(context)?.copyWith(
                          color: detailColor.withValues(alpha: 0.82),
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    if (result.isNotEmpty)
                      TextSpan(
                        text: '  ·  $result',
                        style: _processTextStyle(context)?.copyWith(
                          color: detailColor.withValues(alpha: 0.72),
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                  ],
                ),
                maxLines: 1,
                softWrap: false,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

TextStyle? _processTextStyle(BuildContext context) {
  final colors = Theme.of(context).colorScheme;
  return Theme.of(context).textTheme.bodyMedium?.copyWith(
    fontSize: 12.5,
    height: 1.35,
    color: colors.onSurfaceVariant.withValues(alpha: 0.8),
    fontWeight: FontWeight.w500,
  );
}

String _elapsedLabel(Duration value) {
  final seconds = value.inSeconds.clamp(0, 999999);
  if (seconds < 60) return '${seconds}s';
  if (seconds < 3600) {
    return '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')}';
  }
  return '${seconds ~/ 3600}h ${((seconds % 3600) ~/ 60).toString().padLeft(2, '0')}m';
}

String _processSummary(BuildContext context, List<RuntimeActivity> activities) {
  final categories = {for (final value in activities) _activityCategory(value)};
  return localizedProcessSummary(
    categories.length == 1 ? categories.first : 'other',
    activities.length,
    toolPresentationLanguage(context),
    mixed: categories.length != 1,
  );
}

IconData _processGroupIcon(List<RuntimeActivity> activities) =>
    switch (activities.isEmpty ? '' : _activityCategory(activities.first)) {
      'search' => CupertinoIcons.search,
      'read' => CupertinoIcons.doc_text,
      'write' => CupertinoIcons.pencil,
      'shell' => CupertinoIcons.chevron_left_slash_chevron_right,
      'agent' => CupertinoIcons.person_2,
      'planning' => CupertinoIcons.checkmark_square,
      'interaction' => CupertinoIcons.question_circle,
      'browser' => CupertinoIcons.globe,
      'memory' => CupertinoIcons.archivebox,
      'skill' => CupertinoIcons.sparkles,
      'image' => CupertinoIcons.photo,
      _ => CupertinoIcons.square_stack_3d_up,
    };

String _activityCategory(RuntimeActivity activity) =>
    toolPresentationCategory(activity.label);

class _ThreadScrollToBottomButton extends StatelessWidget {
  const _ThreadScrollToBottomButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => _GlassSurface(
    child: InkWell(
      key: const ValueKey('thread-scroll-to-bottom'),
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      child: const SizedBox(
        width: 36,
        height: 36,
        child: Icon(CupertinoIcons.arrow_down, size: 16),
      ),
    ),
  );
}

class _ThreadActionButton extends StatelessWidget {
  const _ThreadActionButton({
    required this.keyValue,
    required this.icon,
    required this.tooltip,
    required this.onTap,
  });

  final String keyValue;
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: InkWell(
          key: ValueKey(keyValue),
          borderRadius: BorderRadius.circular(8),
          hoverColor: colors.onSurface.withValues(alpha: 0.055),
          focusColor: colors.primary.withValues(alpha: 0.1),
          highlightColor: colors.onSurface.withValues(alpha: 0.075),
          splashColor: colors.onSurface.withValues(alpha: 0.08),
          onTap: onTap,
          child: SizedBox(
            width: 26,
            height: 26,
            child: Icon(
              icon,
              size: 12.5,
              color: colors.onSurfaceVariant.withValues(alpha: 0.62),
            ),
          ),
        ),
      ),
    );
  }
}

MarkdownStyleSheet _messageMarkdownStyle(BuildContext context) {
  final theme = Theme.of(context);
  final colors = theme.colorScheme;
  final base = MarkdownStyleSheet.fromTheme(theme);
  final body = theme.textTheme.bodyMedium?.copyWith(
    fontSize: 14.5,
    height: 1.55,
  );
  return base.copyWith(
    p: body,
    h1: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
    h2: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
    h3: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
    listBullet: body,
    blockquote: body?.copyWith(color: colors.onSurfaceVariant),
    code: theme.textTheme.bodySmall?.copyWith(
      fontFamily: 'Menlo',
      color: colors.onSurface,
      backgroundColor: colors.onSurface.withValues(alpha: 0.08),
    ),
    codeblockDecoration: BoxDecoration(
      color: colors.onSurface.withValues(alpha: 0.06),
      borderRadius: BorderRadius.circular(9),
    ),
  );
}

String _messageTime(DateTime value) {
  final local = value.toLocal();
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$hour:$minute';
}

class _InteractionCard extends StatefulWidget {
  const _InteractionCard({required this.interaction, required this.onReply});

  final PendingInteraction interaction;
  final Future<void> Function(
    String decision, {
    String text,
    Map<String, Object?> payload,
  })
  onReply;

  @override
  State<_InteractionCard> createState() => _InteractionCardState();
}

class _InteractionCardState extends State<_InteractionCard> {
  final _answer = TextEditingController();
  final Map<String, TextEditingController> _questionControllers = {};
  final Map<String, Object?> _questionAnswers = {};
  bool _submitting = false;

  Future<void> _reply(String decision) async {
    if (_submitting) return;
    setState(() => _submitting = true);
    try {
      final answers = <String, Object?>{..._questionAnswers};
      for (final entry in _questionControllers.entries) {
        answers[entry.key] = entry.value.text.trim();
      }
      await widget.onReply(
        decision,
        text: answers.isEmpty ? _answer.text : jsonEncode({'answers': answers}),
        payload: answers.isEmpty ? const {} : {'answers': answers},
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  List<String> _visibleDecisions(bool approval) {
    final decisions = widget.interaction.allowedDecisions;
    if (!approval || !decisions.contains('deny')) return decisions;
    return decisions.where((value) => value != 'cancel').toList();
  }

  @override
  void dispose() {
    _answer.dispose();
    for (final controller in _questionControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  List<Map<String, Object?>> _questions(Map<String, Object?> payload) {
    final raw = payload['questions'];
    if (raw is! List) return const [];
    return [
      for (final value in raw)
        if (value is Map) value.cast<String, Object?>(),
    ];
  }

  String _questionId(Map<String, Object?> question, int index) =>
      question['id']?.toString() ?? 'q${index + 1}';

  Widget _questionField(
    BuildContext context,
    Map<String, Object?> question,
    int index,
  ) {
    final id = _questionId(question, index);
    final type = question['type']?.toString() ?? 'text';
    final title =
        question['title']?.toString() ?? question['question']?.toString() ?? id;
    final rawOptions = question['options'];
    final options = rawOptions is List ? rawOptions : const <Object?>[];
    String optionValue(Object? option) => option is Map
        ? option['value']?.toString() ?? option['label']?.toString() ?? ''
        : option?.toString() ?? '';
    String optionLabel(Object? option) => option is Map
        ? option['label']?.toString() ?? option['value']?.toString() ?? ''
        : option?.toString() ?? '';
    if (type == 'single') {
      final selected = _questionAnswers[id]?.toString();
      return Padding(
        padding: const EdgeInsets.only(top: 10),
        child: DropdownButtonFormField<String>(
          key: ValueKey('interaction-question-$id'),
          initialValue: selected,
          decoration: InputDecoration(labelText: title, isDense: true),
          items: [
            for (final option in options)
              DropdownMenuItem(
                value: optionValue(option),
                child: Text(optionLabel(option)),
              ),
          ],
          onChanged: (value) => setState(() => _questionAnswers[id] = value),
        ),
      );
    }
    if (type == 'multiple') {
      final selected = <String>{
        ...((_questionAnswers[id] as List?)?.map((value) => value.toString()) ??
            const <String>[]),
      };
      return Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 6),
            Wrap(
              spacing: 7,
              runSpacing: 5,
              children: [
                for (final option in options)
                  FilterChip(
                    label: Text(optionLabel(option)),
                    selected: selected.contains(optionValue(option)),
                    onSelected: (enabled) {
                      final updated = {...selected};
                      enabled
                          ? updated.add(optionValue(option))
                          : updated.remove(optionValue(option));
                      setState(
                        () => _questionAnswers[id] = updated.toList(
                          growable: false,
                        ),
                      );
                    },
                  ),
              ],
            ),
          ],
        ),
      );
    }
    final controller = _questionControllers.putIfAbsent(
      id,
      () => TextEditingController(text: question['default']?.toString() ?? ''),
    );
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: TextField(
        key: ValueKey('interaction-question-$id'),
        controller: controller,
        decoration: InputDecoration(
          labelText: title,
          hintText: question['placeholder']?.toString(),
          isDense: true,
        ),
        minLines: 1,
        maxLines: 4,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final payload = widget.interaction.payload;
    final questions = _questions(payload);
    final approval = widget.interaction.type == 'approval';
    final prompt =
        payload['prompt']?.toString() ??
        payload['reason']?.toString() ??
        (approval
            ? context.l10n.text('workspace.requestApproval')
            : widget.interaction.type);
    final toolName = payload['tool_name']?.toString();
    final language = toolPresentationLanguage(context);
    final rawArguments = payload['arguments'];
    final arguments = rawArguments is Map
        ? rawArguments.map((key, value) => MapEntry(key.toString(), value))
        : <String, Object?>{};
    final presentation = approval && toolName != null
        ? approvalToolPresentation(toolName, arguments, language)
        : null;
    final riskReason = payload['risk_reason']?.toString();
    final riskCategory = payload['risk_category']?.toString();
    final sideEffectLevel = payload['side_effect_level']?.toString();
    final displayedRiskReason = _riskReason(
      riskCategory,
      riskReason,
      context.l10n,
    );
    final decisions = _visibleDecisions(approval);
    final colors = Theme.of(context).colorScheme;
    final title = approval && toolName != null
        ? toolName == 'goal_submit' && riskCategory == 'plan_approval'
              ? _planApprovalTitle(language)
              : localizedToolName(toolName, language)
        : prompt;
    final elevatedRisk =
        sideEffectLevel == 'irreversible' ||
        riskCategory == 'destructive_filesystem' ||
        riskCategory == 'filesystem_delete' ||
        riskCategory == 'external_side_effect';
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 580),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(0, 4, 0, 8),
          child: _GlassSurface(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 11),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 30,
                        height: 30,
                        decoration: BoxDecoration(
                          color: approval
                              ? colors.tertiaryContainer.withValues(alpha: 0.7)
                              : colors.secondaryContainer.withValues(
                                  alpha: 0.7,
                                ),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Icon(
                          approval
                              ? CupertinoIcons.shield_lefthalf_fill
                              : CupertinoIcons.question_circle,
                          size: 17,
                          color: approval
                              ? colors.onTertiaryContainer
                              : colors.onSecondaryContainer,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          title,
                          style: Theme.of(context).textTheme.titleSmall
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ),
                      if (approval)
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color:
                                (elevatedRisk
                                        ? colors.errorContainer
                                        : colors.tertiaryContainer)
                                    .withValues(alpha: 0.55),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            _riskLabel(
                              riskCategory,
                              sideEffectLevel,
                              context.l10n,
                            ),
                            style: Theme.of(context).textTheme.labelSmall
                                ?.copyWith(
                                  color: elevatedRisk
                                      ? colors.onErrorContainer
                                      : colors.onTertiaryContainer,
                                  fontWeight: FontWeight.w600,
                                ),
                          ),
                        ),
                    ],
                  ),
                  if (payload['guidance'] case final String guidance)
                    if (guidance.isNotEmpty && guidance != title)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(
                          guidance,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: colors.onSurfaceVariant),
                        ),
                      ),
                  if (presentation != null) ...[
                    const SizedBox(height: 9),
                    Container(
                      key: const ValueKey('interaction-command'),
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: colors.surfaceContainerHighest.withValues(
                          alpha: 0.62,
                        ),
                        borderRadius: BorderRadius.circular(11),
                        border: Border.all(
                          color: colors.outlineVariant.withValues(alpha: 0.7),
                        ),
                      ),
                      child: Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          SelectableText(
                            presentation.summary,
                            style: TextStyle(
                              color: colors.onSurface,
                              fontFamily: 'monospace',
                              fontSize: 12.5,
                              height: 1.45,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          for (final fact in presentation.facts)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 7,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: colors.surface.withValues(alpha: 0.5),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                fact,
                                style: Theme.of(context).textTheme.labelSmall
                                    ?.copyWith(color: colors.onSurfaceVariant),
                              ),
                            ),
                        ],
                      ),
                    ),
                    if (presentation.preview case final preview?) ...[
                      const SizedBox(height: 7),
                      Text(
                        presentation.previewLabel ?? '',
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: colors.onSurfaceVariant,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Container(
                        key: const ValueKey('interaction-preview'),
                        width: double.infinity,
                        constraints: BoxConstraints(
                          maxHeight: toolName == 'goal_submit' ? 360 : 112,
                        ),
                        padding: const EdgeInsets.all(9),
                        decoration: BoxDecoration(
                          color: colors.surfaceContainerLowest.withValues(
                            alpha: 0.58,
                          ),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(
                            color: colors.outlineVariant.withValues(alpha: 0.5),
                          ),
                        ),
                        child: SingleChildScrollView(
                          child: SelectableText(
                            preview,
                            style: TextStyle(
                              color: colors.onSurface,
                              fontFamily: 'monospace',
                              fontSize: 12,
                              height: 1.42,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ],
                  if (approval &&
                      displayedRiskReason != null &&
                      displayedRiskReason.isNotEmpty) ...[
                    const SizedBox(height: 9),
                    Text(
                      displayedRiskReason,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                  if (widget.interaction.type == 'user_input' &&
                      questions.isNotEmpty)
                    for (final entry in questions.indexed)
                      _questionField(context, entry.$2, entry.$1),
                  if (widget.interaction.type == 'user_input' &&
                      questions.isEmpty) ...[
                    const SizedBox(height: 10),
                    TextField(
                      key: const ValueKey('interaction-input'),
                      controller: _answer,
                      autofocus: true,
                      onSubmitted: (_) => _reply(decisions.first),
                    ),
                  ],
                  const SizedBox(height: 10),
                  Wrap(
                    alignment: WrapAlignment.end,
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final decision in decisions)
                        if (decision == 'deny')
                          TextButton(
                            key: ValueKey('interaction-submit-$decision'),
                            onPressed: _submitting
                                ? null
                                : () => _reply(decision),
                            child: Text(
                              _interactionDecisionLabel(
                                decision,
                                toolName,
                                context.l10n,
                              ),
                            ),
                          )
                        else
                          GlassButton.custom(
                            key: ValueKey('interaction-submit-$decision'),
                            width: switch (decision) {
                              'approve_and_remember' => 132,
                              'approve_once' => 108,
                              _ => 92,
                            },
                            height: 36,
                            label: _interactionDecisionLabel(
                              decision,
                              toolName,
                              context.l10n,
                            ),
                            enabled: !_submitting,
                            onTap: () => _reply(decision),
                            shape: const LiquidRoundedRectangle(
                              borderRadius: 10,
                            ),
                            settings: _composerGlassSettings(context),
                            child: _submitting
                                ? const CupertinoActivityIndicator(radius: 7)
                                : Text(
                                    _interactionDecisionLabel(
                                      decision,
                                      toolName,
                                      context.l10n,
                                    ),
                                    style: const TextStyle(
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
      ),
    );
  }
}

class _Composer extends StatefulWidget {
  const _Composer({required this.controller, required this.conversation});

  final WorkspaceController controller;
  final Conversation conversation;

  @override
  State<_Composer> createState() => _ComposerState();
}

class _ComposerState extends State<_Composer> {
  late final _ComposerTextEditingController _text;
  final _focus = FocusNode();
  final _editorRegionKey = GlobalKey();
  OverlayEntry? _referenceHoverOverlay;
  ComposerReference? _hoveredReference;
  Offset _hoverPosition = Offset.zero;

  @override
  void initState() {
    super.initState();
    _text = _ComposerTextEditingController(
      onReferencesRemoved: _removeDeletedReferences,
    );
    widget.controller.addListener(_syncComposerReferences);
    _syncComposerReferences();
  }

  @override
  void didUpdateWidget(covariant _Composer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_syncComposerReferences);
      widget.controller.addListener(_syncComposerReferences);
    }
    if (oldWidget.conversation.id != widget.conversation.id) {
      _text.reset();
    }
    _syncComposerReferences();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_syncComposerReferences);
    _hideReferenceHover();
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _syncComposerReferences() {
    final references = widget.controller.composerReferences;
    _text.syncReferences(references);
    if (_hoveredReference != null && !references.contains(_hoveredReference)) {
      _hideReferenceHover();
    }
  }

  void _removeDeletedReferences(List<ComposerReference> references) {
    for (final reference in references) {
      if (widget.controller.composerReferences.contains(reference)) {
        widget.controller.removeComposerReference(reference);
      }
    }
  }

  void _submit() {
    final value = _text.promptText.trim();
    if (value.isEmpty) return;
    widget.controller.send(value);
    _text.reset();
    widget.controller.clearComposerReferences(widget.conversation.id);
    _focus.requestFocus();
  }

  void _handleEditorHover(PointerHoverEvent event) {
    final reference = _referenceAt(event.position);
    if (reference == null) {
      _hideReferenceHover();
      return;
    }
    _hoveredReference = reference;
    _hoverPosition = event.position;
    if (_referenceHoverOverlay == null) {
      _referenceHoverOverlay = OverlayEntry(builder: _buildReferenceHover);
      Overlay.of(context, rootOverlay: true).insert(_referenceHoverOverlay!);
    } else {
      _referenceHoverOverlay!.markNeedsBuild();
    }
  }

  ComposerReference? _referenceAt(Offset globalPosition) {
    final root = _editorRegionKey.currentContext?.findRenderObject();
    final editable = _findRenderEditable(root);
    if (editable == null) return null;
    final origin = editable.localToGlobal(Offset.zero);
    for (final token in _text.referenceTokens) {
      final boxes = editable.getBoxesForSelection(
        TextSelection(baseOffset: token.offset, extentOffset: token.offset + 1),
      );
      for (final box in boxes) {
        if (box.toRect().shift(origin).inflate(2).contains(globalPosition)) {
          return token.reference;
        }
      }
    }
    return null;
  }

  Widget _buildReferenceHover(BuildContext overlayContext) {
    final reference = _hoveredReference;
    if (reference == null) return const SizedBox.shrink();
    final screen = MediaQuery.sizeOf(overlayContext);
    final width = min(520.0, max(220.0, screen.width - 32));
    final left = (_hoverPosition.dx + 12)
        .clamp(16.0, max(16.0, screen.width - width - 16))
        .toDouble();
    final top = (_hoverPosition.dy + 18)
        .clamp(16.0, max(16.0, screen.height - 260))
        .toDouble();
    final colors = Theme.of(overlayContext).colorScheme;
    return Positioned(
      left: left,
      top: top,
      width: width,
      child: IgnorePointer(
        child: Material(
          key: const ValueKey('composer-inline-reference-hover'),
          elevation: 10,
          color: colors.surfaceContainerHigh,
          shadowColor: colors.shadow.withValues(alpha: 0.28),
          borderRadius: BorderRadius.circular(12),
          clipBehavior: Clip.antiAlias,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 240),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    reference.path,
                    style: Theme.of(overlayContext).textTheme.labelMedium
                        ?.copyWith(
                          color: colors.primary,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  const SizedBox(height: 8),
                  if (reference.text.isNotEmpty)
                    Text(
                      reference.text,
                      style: Theme.of(
                        overlayContext,
                      ).textTheme.bodyMedium?.copyWith(height: 1.45),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _hideReferenceHover() {
    _referenceHoverOverlay?.remove();
    _referenceHoverOverlay = null;
    _hoveredReference = null;
  }

  KeyEventResult _handleKey(KeyEvent event) {
    if (event is! KeyDownEvent ||
        (event.logicalKey != LogicalKeyboardKey.enter &&
            event.logicalKey != LogicalKeyboardKey.numpadEnter)) {
      return KeyEventResult.ignored;
    }
    final composing = _text.value.composing;
    if (composing.isValid && !composing.isCollapsed) {
      return KeyEventResult.ignored;
    }
    if (HardwareKeyboard.instance.isShiftPressed) {
      final value = _text.value;
      final selection = value.selection;
      final offset = selection.isValid ? selection.start : value.text.length;
      final end = selection.isValid ? selection.end : value.text.length;
      final next = value.text.replaceRange(offset, end, '\n');
      _text.value = value.copyWith(
        text: next,
        selection: TextSelection.collapsed(offset: offset + 1),
        composing: TextRange.empty,
      );
      return KeyEventResult.handled;
    }
    _submit();
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) {
    final running = {
      RunStatus.starting,
      RunStatus.running,
      RunStatus.suspending,
    }.contains(widget.conversation.status);
    final approvalLocked = {
      RunStatus.starting,
      RunStatus.running,
      RunStatus.suspending,
      RunStatus.suspended,
    }.contains(widget.conversation.status);
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return DecoratedBox(
      key: const ValueKey('thread-composer-surface'),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: dark ? 0.48 : 0.95),
          width: dark ? 1 : 1.15,
        ),
        boxShadow: dark
            ? [
                BoxShadow(
                  color: colors.shadow.withValues(alpha: 0.16),
                  blurRadius: 18,
                  offset: const Offset(0, 10),
                ),
              ]
            : [
                BoxShadow(
                  color: colors.shadow.withValues(alpha: 0.12),
                  blurRadius: 28,
                  spreadRadius: 1,
                  offset: const Offset(0, 14),
                ),
                BoxShadow(
                  color: const Color(0xFF667085).withValues(alpha: 0.12),
                  blurRadius: 8,
                  offset: const Offset(0, 1),
                ),
              ],
      ),
      child: GlassCard(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
        shape: const LiquidRoundedSuperellipse(borderRadius: 24),
        useOwnLayer: true,
        settings: _composerGlassSettings(context),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _ComposerAssetShelf(
              assets: widget.controller.attachments,
              onRemoved: widget.controller.removeAttachment,
            ),
            _ComposerSkillShelf(
              skills: widget.controller.preferredSkills.toList()..sort(),
              onRemoved: widget.controller.toggleSkill,
            ),
            ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 36, maxHeight: 124),
              child: MouseRegion(
                key: _editorRegionKey,
                onHover: _handleEditorHover,
                onExit: (_) => _hideReferenceHover(),
                child: Focus(
                  onKeyEvent: (_, event) => _handleKey(event),
                  child: TextField(
                    key: const ValueKey('agent-composer'),
                    controller: _text,
                    focusNode: _focus,
                    minLines: 1,
                    maxLines: null,
                    textInputAction: TextInputAction.newline,
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                      fontSize: 14.5,
                      height: 1.35,
                      color: colors.onSurface,
                    ),
                    decoration: InputDecoration(
                      hintText: context.l10n.text(
                        running
                            ? 'workspace.inputSteer'
                            : widget.conversation.planMode
                            ? 'workspace.inputPlan'
                            : widget.conversation.goalMode
                            ? 'workspace.inputGoal'
                            : 'workspace.inputAgent',
                      ),
                      hintStyle: Theme.of(context).textTheme.bodyLarge
                          ?.copyWith(
                            fontSize: 14.5,
                            color: colors.onSurfaceVariant.withValues(
                              alpha: dark ? 0.68 : 0.76,
                            ),
                          ),
                      isDense: true,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      filled: false,
                      contentPadding: EdgeInsets.zero,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            LayoutBuilder(
              builder: (context, constraints) {
                final approvalLabelPainter = TextPainter(
                  text: TextSpan(
                    text: _approvalModeLabel(
                      widget.conversation.approvalMode,
                      context.l10n,
                    ),
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  textDirection: Directionality.of(context),
                  textScaler: MediaQuery.textScalerOf(context),
                  maxLines: 1,
                )..layout();
                final compactApproval =
                    constraints.maxWidth < 400 + approvalLabelPainter.width;
                final compactAgent = constraints.maxWidth < 310;
                final controlGap = compactApproval ? 5.0 : 8.0;
                return Row(
                  children: [
                    _SkillPicker(
                      controller: widget.controller,
                      conversation: widget.conversation,
                    ),
                    SizedBox(width: controlGap),
                    Container(
                      key: const ValueKey('composer-control-cluster'),
                      padding: const EdgeInsets.symmetric(horizontal: 2),
                      decoration: BoxDecoration(
                        color: colors.surfaceContainerHighest.withValues(
                          alpha: dark ? 0.18 : 0.28,
                        ),
                        borderRadius: BorderRadius.circular(11),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _AgentPicker(
                            controller: widget.controller,
                            compact: compactAgent,
                          ),
                          const _ComposerToolbarDivider(),
                          _ApprovalModePicker(
                            controller: widget.controller,
                            conversation: widget.conversation,
                            compact: compactApproval,
                            enabled: !approvalLocked,
                          ),
                        ],
                      ),
                    ),
                    const Spacer(),
                    ValueListenableBuilder<TextEditingValue>(
                      valueListenable: _text,
                      builder: (context, value, _) => _ComposerSendButton(
                        enabled: widget.controller.canSend || running,
                        running: running,
                        hasDraft:
                            value.text.trim().isNotEmpty ||
                            widget.controller.composerReferences.isNotEmpty,
                        onSend: _submit,
                        onStop: widget.controller.cancel,
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

RenderEditable? _findRenderEditable(RenderObject? root) {
  if (root is RenderEditable) return root;
  RenderEditable? result;
  root?.visitChildren((child) {
    result ??= _findRenderEditable(child);
  });
  return result;
}

class _ComposerReferenceToken {
  _ComposerReferenceToken({required this.reference, required this.offset});

  final ComposerReference reference;
  int offset;
}

class _ComposerTextEditingController extends TextEditingController {
  _ComposerTextEditingController({required this.onReferencesRemoved});

  static const _placeholder = '\uFFFC';

  final ValueChanged<List<ComposerReference>> onReferencesRemoved;
  final List<_ComposerReferenceToken> _tokens = [];
  bool _internalUpdate = false;

  List<_ComposerReferenceToken> get referenceTokens =>
      List.unmodifiable(_tokens);

  void syncReferences(List<ComposerReference> references) {
    final removed = [
      for (final token in _tokens)
        if (!references.contains(token.reference)) token,
    ]..sort((left, right) => right.offset.compareTo(left.offset));
    if (removed.isNotEmpty) {
      var nextText = text;
      var nextSelection = selection;
      for (final token in removed) {
        if (token.offset < nextText.length &&
            nextText[token.offset] == _placeholder) {
          nextText = nextText.replaceRange(token.offset, token.offset + 1, '');
          nextSelection = _selectionAfterRemoval(nextSelection, token.offset);
        }
        _tokens.remove(token);
        for (final remaining in _tokens) {
          if (remaining.offset > token.offset) remaining.offset--;
        }
      }
      _setInternalValue(
        value.copyWith(
          text: nextText,
          selection: nextSelection,
          composing: TextRange.empty,
        ),
      );
    }
    for (final reference in references) {
      if (_tokens.any((token) => identical(token.reference, reference))) {
        continue;
      }
      _insertReference(reference);
    }
  }

  void _insertReference(ComposerReference reference) {
    final selectedOffset = selection.isValid
        ? selection.extentOffset
        : text.length;
    final offset = selectedOffset.clamp(0, text.length);
    for (final token in _tokens) {
      if (token.offset >= offset) token.offset++;
    }
    _tokens.add(_ComposerReferenceToken(reference: reference, offset: offset));
    _tokens.sort((left, right) => left.offset.compareTo(right.offset));
    final nextText = text.replaceRange(offset, offset, _placeholder);
    _setInternalValue(
      TextEditingValue(
        text: nextText,
        selection: TextSelection.collapsed(offset: offset + 1),
      ),
    );
  }

  TextSelection _selectionAfterRemoval(
    TextSelection current,
    int removedOffset,
  ) {
    if (!current.isValid) return current;
    int shift(int value) => value > removedOffset ? value - 1 : value;
    return current.copyWith(
      baseOffset: shift(current.baseOffset),
      extentOffset: shift(current.extentOffset),
    );
  }

  @override
  set value(TextEditingValue newValue) {
    if (_internalUpdate) {
      super.value = newValue;
      return;
    }
    final previousText = text;
    final removedReferences = _reconcileExternalEdit(
      previousText,
      newValue.text,
    );
    super.value = newValue;
    if (removedReferences.isNotEmpty) {
      onReferencesRemoved(removedReferences);
    }
  }

  List<ComposerReference> _reconcileExternalEdit(
    String previousText,
    String nextText,
  ) {
    var prefix = 0;
    final shortest = min(previousText.length, nextText.length);
    while (prefix < shortest &&
        previousText.codeUnitAt(prefix) == nextText.codeUnitAt(prefix)) {
      prefix++;
    }
    var suffix = 0;
    while (suffix < previousText.length - prefix &&
        suffix < nextText.length - prefix &&
        previousText.codeUnitAt(previousText.length - suffix - 1) ==
            nextText.codeUnitAt(nextText.length - suffix - 1)) {
      suffix++;
    }
    final previousEnd = previousText.length - suffix;
    final nextEnd = nextText.length - suffix;
    final removed = [
      for (final token in _tokens)
        if (token.offset >= prefix && token.offset < previousEnd) token,
    ];
    _tokens.removeWhere(removed.contains);
    final shift = nextEnd - previousEnd;
    for (final token in _tokens) {
      if (token.offset >= previousEnd) token.offset += shift;
    }
    return [for (final token in removed) token.reference];
  }

  String get promptText {
    final ordered = [..._tokens]
      ..sort((left, right) => left.offset.compareTo(right.offset));
    final buffer = StringBuffer();
    var cursor = 0;
    for (final token in ordered) {
      if (token.offset < cursor || token.offset >= text.length) continue;
      buffer.write(text.substring(cursor, token.offset));
      buffer.write('\n\n${token.reference.promptText}\n\n');
      cursor = token.offset + 1;
    }
    buffer.write(text.substring(cursor));
    return buffer.toString();
  }

  void reset() {
    _tokens.clear();
    _setInternalValue(TextEditingValue.empty);
  }

  void _setInternalValue(TextEditingValue next) {
    _internalUpdate = true;
    try {
      value = next;
    } finally {
      _internalUpdate = false;
    }
  }

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    final tokensByOffset = {for (final token in _tokens) token.offset: token};
    final children = <InlineSpan>[];
    var cursor = 0;
    for (var offset = 0; offset < text.length; offset++) {
      final token = tokensByOffset[offset];
      if (token == null || text[offset] != _placeholder) continue;
      if (cursor < offset) {
        children.add(TextSpan(text: text.substring(cursor, offset)));
      }
      children.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: _ComposerInlineReferenceItem(reference: token.reference),
        ),
      );
      cursor = offset + 1;
    }
    if (cursor < text.length) {
      children.add(TextSpan(text: text.substring(cursor)));
    }
    return TextSpan(style: style, children: children);
  }
}

class _ComposerInlineReferenceItem extends StatelessWidget {
  const _ComposerInlineReferenceItem({required this.reference});

  final ComposerReference reference;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final normalized = reference.text.replaceAll(RegExp(r'\s+'), ' ').trim();
    final preview = normalized.length > 24
        ? '${normalized.substring(0, 24)}…'
        : normalized;
    final label = preview.isEmpty
        ? reference.fileName
        : '${reference.fileName} · $preview';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 1),
      child: Container(
        key: const ValueKey('composer-inline-reference'),
        height: 25,
        constraints: BoxConstraints(
          maxWidth: min(280, MediaQuery.sizeOf(context).width * 0.42),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: colors.primaryContainer.withValues(alpha: 0.42),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(color: colors.primary.withValues(alpha: 0.24)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              reference.isDirectory
                  ? CupertinoIcons.folder
                  : reference.text.isEmpty
                  ? CupertinoIcons.doc
                  : CupertinoIcons.quote_bubble,
              size: 11,
              color: colors.primary,
            ),
            const SizedBox(width: 5),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  fontSize: 11,
                  color: colors.onSurface,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ComposerAssetShelf extends StatelessWidget {
  const _ComposerAssetShelf({required this.assets, required this.onRemoved});

  final List<UploadedAttachment> assets;
  final ValueChanged<UploadedAttachment> onRemoved;

  @override
  Widget build(BuildContext context) {
    if (assets.isEmpty) return const SizedBox.shrink();
    final colors = Theme.of(context).colorScheme;
    return Padding(
      key: const ValueKey('composer-asset-shelf'),
      padding: const EdgeInsets.only(bottom: 12),
      child: SizedBox(
        height: 74,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: assets.length,
          separatorBuilder: (_, _) => const SizedBox(width: 8),
          itemBuilder: (context, index) {
            final asset = assets[index];
            final isImage = _isPreviewableImage(asset.path);
            return Stack(
              clipBehavior: Clip.none,
              children: [
                Container(
                  width: 74,
                  height: 74,
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHighest.withValues(
                      alpha: 0.38,
                    ),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(
                      color: colors.outlineVariant.withValues(alpha: 0.72),
                    ),
                  ),
                  child: isImage
                      ? Image.file(File(asset.path), fit: BoxFit.cover)
                      : Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              _assetIcon(asset),
                              size: 24,
                              color: colors.onSurfaceVariant,
                            ),
                            const SizedBox(height: 6),
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 6,
                              ),
                              child: Text(
                                asset.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.labelMedium
                                    ?.copyWith(
                                      color: colors.onSurfaceVariant,
                                      fontSize: 10,
                                    ),
                              ),
                            ),
                          ],
                        ),
                ),
                Positioned(
                  right: -7,
                  top: -7,
                  child: InkWell(
                    onTap: () => onRemoved(asset),
                    borderRadius: BorderRadius.circular(11),
                    child: Container(
                      width: 22,
                      height: 22,
                      decoration: BoxDecoration(
                        color: colors.surface,
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: colors.outlineVariant.withValues(alpha: 0.8),
                        ),
                      ),
                      child: Icon(
                        CupertinoIcons.xmark,
                        size: 11,
                        color: colors.onSurface,
                      ),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ComposerSkillShelf extends StatelessWidget {
  const _ComposerSkillShelf({required this.skills, required this.onRemoved});

  final List<String> skills;
  final ValueChanged<String> onRemoved;

  @override
  Widget build(BuildContext context) {
    if (skills.isEmpty) return const SizedBox.shrink();
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: SizedBox(
        height: 30,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: skills.length,
          separatorBuilder: (_, _) => const SizedBox(width: 7),
          itemBuilder: (context, index) {
            final skill = skills[index];
            return GlassCard(
              key: ValueKey('composer-selected-skill:$skill'),
              padding: const EdgeInsets.only(left: 9, right: 4),
              shape: const LiquidRoundedSuperellipse(borderRadius: 14),
              useOwnLayer: true,
              settings: LiquidGlassSettings(
                visibility: dark ? 0.78 : 0.82,
                glassColor: colors.primaryContainer.withValues(
                  alpha: dark ? 0.22 : 0.26,
                ),
                thickness: 7,
                blur: 3,
                chromaticAberration: 0,
                lightIntensity: 0.22,
                saturation: dark ? 1.02 : 1.06,
                glowIntensity: 0,
                standardOpacityMultiplier: dark ? 0.74 : 0.7,
                shadowElevation: 0.06,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    CupertinoIcons.sparkles,
                    size: 12,
                    color: colors.primary,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    skill,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontSize: 11.5,
                      color: colors.onSurface,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(width: 2),
                  InkWell(
                    key: ValueKey('composer-remove-skill:$skill'),
                    borderRadius: BorderRadius.circular(12),
                    onTap: () => onRemoved(skill),
                    child: Padding(
                      padding: const EdgeInsets.all(5),
                      child: Icon(
                        CupertinoIcons.xmark,
                        size: 10,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

bool _isPreviewableImage(String path) {
  final lower = path.toLowerCase();
  return lower.endsWith('.png') ||
      lower.endsWith('.jpg') ||
      lower.endsWith('.jpeg') ||
      lower.endsWith('.webp') ||
      lower.endsWith('.gif');
}

IconData _assetIcon(UploadedAttachment asset) {
  if (asset.isDirectory) return CupertinoIcons.folder;
  final lower = asset.name.toLowerCase();
  if (lower.endsWith('.mp4') || lower.endsWith('.mov')) {
    return CupertinoIcons.film;
  }
  if (lower.endsWith('.pdf')) return CupertinoIcons.doc_richtext;
  return CupertinoIcons.doc_text;
}

class _AgentPicker extends StatefulWidget {
  const _AgentPicker({required this.controller, this.compact = false});

  final WorkspaceController controller;
  final bool compact;

  @override
  State<_AgentPicker> createState() => _AgentPickerState();
}

class _AgentPickerState extends State<_AgentPicker> {
  final LayerLink _layerLink = LayerLink();
  final Object _tapRegionGroupId = Object();
  OverlayEntry? _overlayEntry;

  bool get _isOpen => _overlayEntry != null;

  @override
  void dispose() {
    _overlayEntry?.remove();
    super.dispose();
  }

  void _toggle() => _isOpen ? _close() : _open();

  void _open() {
    if (_isOpen) return;
    _overlayEntry = OverlayEntry(
      builder: (context) => Positioned(
        width: 220,
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: Alignment.topLeft,
          followerAnchor: Alignment.bottomLeft,
          offset: const Offset(0, -8),
          child: TapRegion(
            groupId: _tapRegionGroupId,
            child: _ComposerGlassMenu(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 286),
                child: ListView(
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  children: [
                    for (final agent in widget.controller.agents)
                      _ComposerMenuItem(
                        selected: agent.id == widget.controller.selectedAgentId,
                        icon: CupertinoIcons.person_crop_circle,
                        label: agent.name,
                        onTap: () {
                          _close();
                          widget.controller.selectAgent(agent.id);
                        },
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
    Overlay.of(context).insert(_overlayEntry!);
    setState(() {});
  }

  void _close() {
    final entry = _overlayEntry;
    if (entry == null) return;
    _overlayEntry = null;
    entry.remove();
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final selected = widget.controller.agents
        .where((value) => value.id == widget.controller.selectedAgentId)
        .firstOrNull;
    return TapRegion(
      groupId: _tapRegionGroupId,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _layerLink,
        child: Tooltip(
          message: context.l10n.text('workspace.chooseAgent'),
          child: InkWell(
            key: const ValueKey('agent-picker'),
            borderRadius: BorderRadius.circular(9),
            onTap: _toggle,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 140),
              curve: Curves.easeOutCubic,
              padding: EdgeInsets.symmetric(
                horizontal: widget.compact ? 8 : 10,
                vertical: 6,
              ),
              decoration: BoxDecoration(
                color: _isOpen
                    ? colors.primary.withValues(alpha: 0.12)
                    : Colors.transparent,
                borderRadius: BorderRadius.circular(9),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    CupertinoIcons.person_crop_circle,
                    size: 13,
                    color: colors.onSurfaceVariant,
                  ),
                  if (!widget.compact) ...[
                    const SizedBox(width: 5),
                    Text(
                      selected?.name ?? context.l10n.text('settings.agent'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: _isOpen ? 0.5 : 0,
                    duration: const Duration(milliseconds: 150),
                    curve: Curves.easeOutCubic,
                    child: Icon(
                      CupertinoIcons.chevron_down,
                      size: 11,
                      color: colors.onSurfaceVariant.withValues(alpha: 0.78),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerToolbarDivider extends StatelessWidget {
  const _ComposerToolbarDivider();

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      width: 1,
      height: 16,
      margin: const EdgeInsets.symmetric(horizontal: 1),
      color: colors.outlineVariant.withValues(alpha: 0.34),
    );
  }
}

class _ApprovalModePicker extends StatefulWidget {
  const _ApprovalModePicker({
    required this.controller,
    required this.conversation,
    required this.compact,
    required this.enabled,
  });

  final WorkspaceController controller;
  final Conversation conversation;
  final bool compact;
  final bool enabled;

  @override
  State<_ApprovalModePicker> createState() => _ApprovalModePickerState();
}

class _ApprovalModePickerState extends State<_ApprovalModePicker> {
  final LayerLink _layerLink = LayerLink();
  final Object _tapRegionGroupId = Object();
  OverlayEntry? _overlayEntry;

  bool get _isOpen => _overlayEntry != null;

  @override
  void dispose() {
    _overlayEntry?.remove();
    super.dispose();
  }

  void _toggle() => _isOpen ? _close() : _open();

  void _open() {
    if (_isOpen || !widget.enabled) return;
    _overlayEntry = OverlayEntry(
      builder: (context) => Positioned(
        width: 340,
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: Alignment.topLeft,
          followerAnchor: Alignment.bottomLeft,
          offset: const Offset(0, -8),
          child: TapRegion(
            groupId: _tapRegionGroupId,
            child: _ComposerGlassMenu(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final option in ApprovalMode.values)
                    _ComposerMenuItem(
                      key: ValueKey('approval-mode-${option.wireValue}'),
                      selected: option == widget.conversation.approvalMode,
                      icon: _approvalModeIcon(option),
                      label: _approvalModeLabel(option, context.l10n),
                      description: _approvalModeDescription(
                        option,
                        context.l10n,
                      ),
                      onTap: () {
                        _close();
                        widget.controller.setApprovalMode(option);
                      },
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    Overlay.of(context).insert(_overlayEntry!);
    setState(() {});
  }

  void _close() {
    final entry = _overlayEntry;
    if (entry == null) return;
    _overlayEntry = null;
    entry.remove();
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final mode = widget.conversation.approvalMode;
    return TapRegion(
      groupId: _tapRegionGroupId,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _layerLink,
        child: Semantics(
          button: true,
          enabled: widget.enabled,
          label: context.l10n.text('workspace.approvalMode', {
            'mode': _approvalModeLabel(mode, context.l10n),
          }),
          child: InkWell(
            key: const ValueKey('approval-mode-picker'),
            borderRadius: BorderRadius.circular(9),
            onTap: widget.enabled ? _toggle : null,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 140),
              curve: Curves.easeOutCubic,
              padding: EdgeInsets.symmetric(
                horizontal: widget.compact ? 8 : 10,
                vertical: 6,
              ),
              decoration: BoxDecoration(
                color: _isOpen
                    ? colors.primary.withValues(alpha: 0.12)
                    : Colors.transparent,
                borderRadius: BorderRadius.circular(9),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    _approvalModeIcon(mode),
                    size: 13,
                    color: widget.enabled
                        ? colors.onSurfaceVariant
                        : colors.onSurfaceVariant.withValues(alpha: 0.45),
                  ),
                  if (!widget.compact) ...[
                    const SizedBox(width: 5),
                    Text(
                      _approvalModeLabel(mode, context.l10n),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: widget.enabled
                            ? colors.onSurface
                            : colors.onSurfaceVariant.withValues(alpha: 0.45),
                      ),
                    ),
                  ],
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: _isOpen ? 0.5 : 0,
                    duration: const Duration(milliseconds: 150),
                    curve: Curves.easeOutCubic,
                    child: Icon(
                      CupertinoIcons.chevron_down,
                      size: 11,
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerGlassMenu extends StatelessWidget {
  const _ComposerGlassMenu({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Material(
      color: Colors.transparent,
      child: GlassCard(
        padding: const EdgeInsets.symmetric(vertical: 6),
        shape: const LiquidRoundedSuperellipse(borderRadius: 16),
        useOwnLayer: true,
        settings: LiquidGlassSettings(
          visibility: dark ? 0.9 : 0.86,
          glassColor: dark
              ? const Color(0xFF242528).withValues(alpha: 0.64)
              : Colors.white.withValues(alpha: 0.68),
          thickness: 11,
          blur: 3,
          chromaticAberration: 0,
          lightIntensity: 0.26,
          saturation: dark ? 1 : 1.06,
          glowIntensity: 0,
          standardOpacityMultiplier: dark ? 0.84 : 0.78,
          shadowElevation: dark ? 0.18 : 0.24,
        ),
        child: child,
      ),
    );
  }
}

class _ComposerMenuItem extends StatelessWidget {
  const _ComposerMenuItem({
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
    this.description,
    super.key,
  });

  final bool selected;
  final IconData icon;
  final String label;
  final String? description;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final hasDescription = description?.isNotEmpty == true;
    return InkWell(
      borderRadius: BorderRadius.circular(11),
      onTap: onTap,
      child: Container(
        constraints: BoxConstraints(minHeight: hasDescription ? 56 : 38),
        margin: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          color: selected
              ? colors.primary.withValues(alpha: 0.12)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(11),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              size: 14,
              color: selected ? colors.primary : colors.onSurfaceVariant,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontSize: 12.5,
                      color: colors.onSurface,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (hasDescription) ...[
                    const SizedBox(height: 2),
                    Text(
                      description!,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontSize: 11,
                        height: 1.25,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 8),
            AnimatedOpacity(
              opacity: selected ? 1 : 0,
              duration: const Duration(milliseconds: 120),
              child: Icon(
                CupertinoIcons.check_mark,
                size: 13,
                color: colors.primary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _approvalModeLabel(ApprovalMode mode, SageLocalizations l10n) =>
    switch (mode) {
      ApprovalMode.alwaysAsk => l10n.text('approval.alwaysAsk'),
      ApprovalMode.highRisk => l10n.text('approval.highRisk'),
      ApprovalMode.autoApprove => l10n.text('approval.autoApprove'),
    };

String _approvalModeDescription(ApprovalMode mode, SageLocalizations l10n) =>
    switch (mode) {
      ApprovalMode.alwaysAsk => l10n.text('approval.alwaysAskDescription'),
      ApprovalMode.highRisk => l10n.text('approval.highRiskDescription'),
      ApprovalMode.autoApprove => l10n.text('approval.autoApproveDescription'),
    };

IconData _approvalModeIcon(ApprovalMode mode) => switch (mode) {
  ApprovalMode.alwaysAsk => CupertinoIcons.hand_raised,
  ApprovalMode.highRisk => CupertinoIcons.checkmark_shield,
  ApprovalMode.autoApprove => CupertinoIcons.lock_open,
};

class _SkillPicker extends StatefulWidget {
  const _SkillPicker({required this.controller, required this.conversation});

  final WorkspaceController controller;
  final Conversation conversation;

  @override
  State<_SkillPicker> createState() => _SkillPickerState();
}

class _SkillPickerState extends State<_SkillPicker> {
  final LayerLink _layerLink = LayerLink();
  final Object _tapRegionGroupId = Object();
  OverlayEntry? _overlayEntry;

  bool get _isOpen => _overlayEntry != null;

  @override
  void dispose() {
    _overlayEntry?.remove();
    super.dispose();
  }

  void _toggle() => _isOpen ? _close() : _open();

  void _open() {
    if (_isOpen) return;
    _overlayEntry = OverlayEntry(
      builder: (context) => Positioned(
        width: 260,
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: Alignment.topLeft,
          followerAnchor: Alignment.bottomLeft,
          offset: const Offset(0, -8),
          child: TapRegion(
            groupId: _tapRegionGroupId,
            child: _ComposerGlassMenu(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 286),
                child: ListView(
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  children: [
                    _ComposerMenuItem(
                      key: const ValueKey('composer-open-file-option'),
                      selected: false,
                      icon: CupertinoIcons.folder_open,
                      label: context.l10n.text('workspace.openFile'),
                      onTap: () {
                        _close();
                        widget.controller.chooseAndUploadFile();
                      },
                    ),
                    _ComposerMenuItem(
                      key: const ValueKey('composer-plan-mode-option'),
                      selected: widget.conversation.planMode,
                      icon: CupertinoIcons.lightbulb,
                      label: context.l10n.text('workspace.planMode'),
                      description: context.l10n.text(
                        'workspace.planModeDescription',
                      ),
                      onTap: () {
                        _close();
                        widget.controller.setInvocationMode(
                          widget.conversation.planMode
                              ? InvocationMode.normal
                              : InvocationMode.plan,
                        );
                      },
                    ),
                    _ComposerMenuItem(
                      key: const ValueKey('composer-goal-mode-option'),
                      selected: widget.conversation.goalMode,
                      icon: CupertinoIcons.scope,
                      label: context.l10n.text('workspace.goalMode'),
                      description: context.l10n.text(
                        'workspace.goalModeDescription',
                      ),
                      onTap: () {
                        _close();
                        widget.controller.setInvocationMode(
                          widget.conversation.goalMode
                              ? InvocationMode.normal
                              : InvocationMode.goal,
                        );
                      },
                    ),
                    Divider(
                      height: 7,
                      thickness: 1,
                      indent: 14,
                      endIndent: 14,
                      color: Theme.of(
                        context,
                      ).colorScheme.outlineVariant.withValues(alpha: 0.4),
                    ),
                    if (widget.controller.skills.isEmpty)
                      Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 10,
                        ),
                        child: Text(context.l10n.text('workspace.noSkills')),
                      ),
                    for (final skill in widget.controller.skills)
                      _ComposerMenuItem(
                        key: ValueKey('composer-skill-option:${skill.name}'),
                        selected: widget.controller.preferredSkills.contains(
                          skill.name,
                        ),
                        icon: CupertinoIcons.sparkles,
                        label: skill.name,
                        onTap: () {
                          _close();
                          widget.controller.toggleSkill(skill.name);
                        },
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
    Overlay.of(context).insert(_overlayEntry!);
    setState(() {});
  }

  void _close() {
    final entry = _overlayEntry;
    if (entry == null) return;
    _overlayEntry = null;
    entry.remove();
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return TapRegion(
      groupId: _tapRegionGroupId,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _layerLink,
        child: Tooltip(
          message: context.l10n.text('workspace.addContent'),
          child: Semantics(
            key: const ValueKey('skill-picker'),
            button: true,
            child: InkWell(
              key: const ValueKey('composer-upload-button'),
              borderRadius: BorderRadius.circular(9),
              onTap: _toggle,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 140),
                curve: Curves.easeOutCubic,
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
                decoration: BoxDecoration(
                  color:
                      _isOpen ||
                          widget.conversation.invocationMode !=
                              InvocationMode.normal
                      ? colors.primary.withValues(alpha: 0.12)
                      : Colors.transparent,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  CupertinoIcons.add,
                  size: 20,
                  color:
                      _isOpen ||
                          widget.conversation.invocationMode !=
                              InvocationMode.normal
                      ? colors.primary
                      : colors.onSurfaceVariant,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerSendButton extends StatelessWidget {
  const _ComposerSendButton({
    required this.enabled,
    required this.running,
    required this.hasDraft,
    required this.onSend,
    required this.onStop,
  });

  final bool enabled;
  final bool running;
  final bool hasDraft;
  final VoidCallback onSend;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final shouldStop = running && !hasDraft;
    return Semantics(
      key: const ValueKey('send-button'),
      button: true,
      label: context.l10n.text(
        shouldStop
            ? 'common.cancel'
            : running
            ? 'workspace.sendSteer'
            : 'workspace.send',
      ),
      child: InkWell(
        key: const ValueKey('thread-send-button'),
        onTap: enabled ? (shouldStop ? onStop : onSend) : null,
        borderRadius: BorderRadius.circular(17),
        child: SizedBox(
          width: 34,
          height: 34,
          child: Center(
            child: Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                color: dark ? Colors.white : Colors.black,
                shape: BoxShape.circle,
              ),
              child: Icon(
                shouldStop ? CupertinoIcons.stop_fill : CupertinoIcons.arrow_up,
                size: shouldStop ? 13 : 16,
                color: dark ? Colors.black : Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _FileWorkspacePanelPlugin extends WorkspacePanelPluginBase {
  const _FileWorkspacePanelPlugin();

  @override
  String get id => 'sage.workspace.files';

  @override
  IconData get icon => CupertinoIcons.folder;

  @override
  bool get initiallyOpen => true;

  @override
  bool get closable => false;

  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => context.l10n.text('workspace.file');

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) =>
      _FilePanel(
        controller: panelContext.services.read<WorkspaceController>(),
        compact: panelContext.compact,
      );
}

class _FilePanel extends StatefulWidget {
  const _FilePanel({required this.controller, this.compact = false});

  final WorkspaceController controller;
  final bool compact;

  @override
  State<_FilePanel> createState() => _FilePanelState();
}

class _FilePanelState extends State<_FilePanel> {
  final TextEditingController _filter = TextEditingController();
  final Set<String> _expandedDirectories = {};
  bool _treeVisible = true;
  String? _previewPath;
  WorkspaceFilePreviewMode _previewMode = WorkspaceFilePreviewMode.rendered;

  WorkspaceController get controller => widget.controller;

  @override
  void dispose() {
    _filter.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant _FilePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    final selectedPath = controller.selectedFile?.path;
    if (selectedPath == null) return;
    final parts = selectedPath.split('/');
    var path = '';
    for (final part in parts.take(max(0, parts.length - 1))) {
      path = path.isEmpty ? part : '$path/$part';
      _expandedDirectories.add(path);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final selectedFile = controller.selectedFile;
    if (_previewPath != selectedFile?.path) {
      _previewPath = selectedFile?.path;
      _previewMode = WorkspaceFilePreviewMode.rendered;
    }
    return Padding(
      padding: EdgeInsets.only(top: widget.compact ? 8 : 0),
      child: DecoratedBox(
        decoration: BoxDecoration(color: colors.surface),
        child: Column(
          children: [
            _FileBrowserHeader(
              groupName: controller.selectedGroup.name,
              selectedPath: controller.selectedFile?.path,
              selectedNode: controller.selectedFile,
              previewMode: _previewMode,
              onPreviewModeChanged: (mode) =>
                  setState(() => _previewMode = mode),
              referenced: controller.isWorkspaceNodeReferenced(
                controller.selectedFile,
              ),
              treeVisible: _treeVisible,
              onToggleTree: () => setState(() => _treeVisible = !_treeVisible),
              onRefresh: controller.refreshFiles,
              onReference: () {
                final file = controller.selectedFile;
                if (file != null) controller.referenceWorkspaceNode(file);
              },
            ),
            const Divider(height: 1),
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: WorkspaceFilePreview(
                      key: ValueKey(controller.selectedFile?.path),
                      node: controller.selectedFile,
                      content: controller.selectedFileContent,
                      mode: _previewMode,
                      onReferenceSelection: (selection) {
                        final file = controller.selectedFile;
                        if (file != null) {
                          controller.referenceWorkspaceSelection(
                            file,
                            selection,
                          );
                        }
                      },
                    ),
                  ),
                  if (_treeVisible)
                    Align(
                      alignment: Alignment.centerRight,
                      child: FractionallySizedBox(
                        widthFactor: widget.compact ? 0.72 : 0.42,
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(
                            minWidth: 220,
                            maxWidth: 360,
                          ),
                          child: _FileTreeOverlay(
                            controller: controller,
                            filter: _filter,
                            expandedDirectories: _expandedDirectories,
                            onToggleDirectory: _toggleDirectory,
                            onFilterChanged: (_) => setState(() {}),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _toggleDirectory(String path) {
    setState(() {
      if (!_expandedDirectories.add(path)) {
        _expandedDirectories.remove(path);
      }
    });
  }
}

class _FileBrowserHeader extends StatelessWidget {
  const _FileBrowserHeader({
    required this.groupName,
    required this.selectedPath,
    required this.selectedNode,
    required this.previewMode,
    required this.onPreviewModeChanged,
    required this.referenced,
    required this.treeVisible,
    this.onToggleTree,
    required this.onRefresh,
    required this.onReference,
  });

  final String groupName;
  final String? selectedPath;
  final WorkspaceFileNode? selectedNode;
  final WorkspaceFilePreviewMode previewMode;
  final ValueChanged<WorkspaceFilePreviewMode> onPreviewModeChanged;
  final bool referenced;
  final bool treeVisible;
  final VoidCallback? onToggleTree;
  final VoidCallback onRefresh;
  final VoidCallback onReference;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final segments = [
      groupName,
      ...?selectedPath?.split('/').where((part) => part.isNotEmpty),
    ];
    return SizedBox(
      height: desktopPaneHeaderHeight,
      child: Row(
        children: [
          const SizedBox(width: 16),
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    for (var index = 0; index < segments.length; index++) ...[
                      if (index > 0)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 7),
                          child: Icon(
                            CupertinoIcons.chevron_right,
                            size: 12,
                            color: colors.onSurfaceVariant,
                          ),
                        ),
                      Text(
                        segments[index],
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontSize: 13,
                          fontWeight: index == segments.length - 1
                              ? FontWeight.w700
                              : FontWeight.w500,
                          color: index == segments.length - 1
                              ? colors.onSurface
                              : colors.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          if (selectedNode != null &&
              workspaceFileSupportsRenderedPreview(selectedNode!.name)) ...[
            SizedBox(
              key: const ValueKey('file-preview-mode'),
              width: 118,
              child: GlassSegmentedControl(
                height: 30,
                segments: [
                  GlassSegment(label: context.l10n.text('workspace.preview')),
                  GlassSegment(label: context.l10n.text('common.sourceCode')),
                ],
                selectedIndex: previewMode.index,
                onSegmentSelected: (index) => onPreviewModeChanged(
                  WorkspaceFilePreviewMode.values[index],
                ),
              ),
            ),
            const SizedBox(width: 6),
          ],
          if (selectedNode != null) ...[
            _HeaderIconButton(
              keyValue: referenced
                  ? 'file-header-referenced'
                  : 'file-header-reference',
              tooltip: context.l10n.text(
                referenced ? 'workspace.referenced' : 'workspace.reference',
              ),
              semanticsLabel: context.l10n.text(
                referenced
                    ? 'workspace.referencedFile'
                    : 'workspace.referenceFile',
              ),
              icon: CupertinoIcons.at,
              highlighted: referenced,
              onTap: referenced ? null : onReference,
            ),
            const SizedBox(width: 4),
          ],
          if (onToggleTree != null) ...[
            _HeaderIconButton(
              keyValue: 'file-tree-toggle',
              icon: treeVisible
                  ? CupertinoIcons.folder_fill
                  : CupertinoIcons.folder,
              highlighted: treeVisible,
              onTap: onToggleTree!,
            ),
            const SizedBox(width: 4),
          ],
          _HeaderIconButton(
            keyValue: 'canvas-refresh-button',
            icon: CupertinoIcons.arrow_clockwise,
            onTap: onRefresh,
          ),
          const SizedBox(width: 14),
        ],
      ),
    );
  }
}

class _FileTreeOverlay extends StatelessWidget {
  const _FileTreeOverlay({
    required this.controller,
    required this.filter,
    required this.expandedDirectories,
    required this.onToggleDirectory,
    required this.onFilterChanged,
  });

  final WorkspaceController controller;
  final TextEditingController filter;
  final Set<String> expandedDirectories;
  final ValueChanged<String> onToggleDirectory;
  final ValueChanged<String> onFilterChanged;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final query = filter.text.trim().toLowerCase();
    final flattened = <({WorkspaceFileNode node, int depth})>[];

    bool matches(WorkspaceFileNode node) {
      if (query.isEmpty || node.name.toLowerCase().contains(query)) return true;
      return node.children.any(matches);
    }

    void append(List<WorkspaceFileNode> nodes, int depth) {
      for (final node in nodes) {
        if (!matches(node)) continue;
        flattened.add((node: node, depth: depth));
        final expanded =
            query.isNotEmpty || expandedDirectories.contains(node.path);
        if (node.isDirectory && expanded) append(node.children, depth + 1);
      }
    }

    append(controller.files, 0);
    return DecoratedBox(
      key: const ValueKey('file-tree-overlay'),
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.97),
        border: Border(left: BorderSide(color: colors.outlineVariant)),
        boxShadow: [
          BoxShadow(
            color: colors.shadow.withValues(alpha: 0.14),
            blurRadius: 18,
            offset: const Offset(-6, 0),
          ),
        ],
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 6),
            child: SizedBox(
              height: 34,
              child: TextField(
                key: const ValueKey('file-tree-filter'),
                controller: filter,
                onChanged: onFilterChanged,
                style: const TextStyle(fontSize: 12),
                decoration: InputDecoration(
                  hintText: context.l10n.text('workspace.filterFiles'),
                  hintStyle: TextStyle(
                    fontSize: 12,
                    color: colors.onSurfaceVariant,
                  ),
                  prefixIcon: const Icon(CupertinoIcons.search, size: 15),
                  prefixIconConstraints: const BoxConstraints(
                    minWidth: 32,
                    minHeight: 30,
                  ),
                  isCollapsed: true,
                  contentPadding: const EdgeInsets.fromLTRB(0, 9, 9, 9),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(9),
                    borderSide: BorderSide(color: colors.outlineVariant),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(9),
                    borderSide: BorderSide(color: colors.outlineVariant),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(9),
                    borderSide: BorderSide(color: colors.primary),
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            child: controller.filesLoading
                ? const Center(child: CupertinoActivityIndicator())
                : flattened.isEmpty
                ? const Center(child: Icon(CupertinoIcons.folder_open))
                : ListView.builder(
                    key: const ValueKey('file-tree-list'),
                    padding: const EdgeInsets.fromLTRB(6, 2, 6, 10),
                    itemCount: flattened.length,
                    itemBuilder: (context, index) {
                      final value = flattened[index];
                      final node = value.node;
                      final selected =
                          controller.selectedFile?.path == node.path;
                      final expanded = expandedDirectories.contains(node.path);
                      final referenced = controller.isWorkspaceNodeReferenced(
                        node,
                      );
                      return _FileTreeRow(
                        node: node,
                        depth: value.depth,
                        selected: selected,
                        expanded: expanded,
                        referenced: referenced,
                        onTap: node.isDirectory
                            ? () => onToggleDirectory(node.path)
                            : () => controller.openFile(node),
                        onReference: () =>
                            controller.referenceWorkspaceNode(node),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _FileTreeRow extends StatefulWidget {
  const _FileTreeRow({
    required this.node,
    required this.depth,
    required this.selected,
    required this.expanded,
    required this.referenced,
    required this.onTap,
    required this.onReference,
  });

  final WorkspaceFileNode node;
  final int depth;
  final bool selected;
  final bool expanded;
  final bool referenced;
  final VoidCallback onTap;
  final VoidCallback onReference;

  @override
  State<_FileTreeRow> createState() => _FileTreeRowState();
}

class _FileTreeRowState extends State<_FileTreeRow> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final node = widget.node;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: InkWell(
        key: ValueKey('file-tree-row:${node.path}'),
        borderRadius: BorderRadius.circular(7),
        onTap: widget.onTap,
        child: Container(
          height: 29,
          padding: EdgeInsets.only(left: 7 + widget.depth * 14, right: 7),
          decoration: BoxDecoration(
            color: widget.selected
                ? colors.onSurface.withValues(alpha: 0.095)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(7),
          ),
          child: Row(
            children: [
              SizedBox(
                width: 13,
                child: node.isDirectory
                    ? Icon(
                        widget.expanded
                            ? CupertinoIcons.chevron_down
                            : CupertinoIcons.chevron_right,
                        size: 11,
                        color: colors.onSurfaceVariant,
                      )
                    : null,
              ),
              const SizedBox(width: 3),
              Icon(
                node.isDirectory
                    ? CupertinoIcons.folder
                    : _workspaceFileIcon(node.name),
                size: 15,
                color: node.isDirectory
                    ? colors.onSurfaceVariant
                    : _workspaceFileColor(node.name, colors),
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  node.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    fontSize: 12.5,
                    fontWeight: widget.selected
                        ? FontWeight.w600
                        : FontWeight.w400,
                  ),
                ),
              ),
              const SizedBox(width: 4),
              _TreeReferenceButton(
                node: node,
                referenced: widget.referenced,
                rowHovered: _hovered,
                onTap: widget.onReference,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TreeReferenceButton extends StatefulWidget {
  const _TreeReferenceButton({
    required this.node,
    required this.referenced,
    required this.rowHovered,
    required this.onTap,
  });

  final WorkspaceFileNode node;
  final bool referenced;
  final bool rowHovered;
  final VoidCallback onTap;

  @override
  State<_TreeReferenceButton> createState() => _TreeReferenceButtonState();
}

class _TreeReferenceButtonState extends State<_TreeReferenceButton> {
  bool _focused = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final visible = widget.rowHovered || _focused;
    final label = context.l10n.text(
      widget.referenced
          ? 'workspace.referencedNode'
          : 'workspace.referenceNode',
      {
        'kind': context.l10n.text(
          widget.node.isDirectory ? 'workspace.folder' : 'workspace.file',
        ),
      },
    );
    // Keep the action's width reserved so labels do not shift on hover. The
    // same action becomes visible on keyboard focus for non-pointer users.
    return AnimatedOpacity(
      key: ValueKey('file-tree-reference-visibility:${widget.node.path}'),
      opacity: visible ? 1 : 0,
      duration: const Duration(milliseconds: 140),
      child: IgnorePointer(
        ignoring: !visible,
        child: Tooltip(
          message: label,
          child: Semantics(
            button: true,
            enabled: !widget.referenced,
            label: label,
            child: InkWell(
              key: ValueKey('file-tree-reference:${widget.node.path}'),
              onFocusChange: (focused) => setState(() => _focused = focused),
              onTap: widget.referenced ? null : widget.onTap,
              borderRadius: BorderRadius.circular(7),
              child: Container(
                width: 22,
                height: 22,
                decoration: widget.referenced
                    ? BoxDecoration(
                        color: colors.onSurface.withValues(alpha: 0.09),
                        borderRadius: BorderRadius.circular(7),
                      )
                    : null,
                child: Icon(
                  CupertinoIcons.at,
                  size: 13,
                  color: colors.onSurfaceVariant.withValues(
                    alpha: widget.referenced ? 0.9 : 0.66,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

IconData _workspaceFileIcon(String name) {
  final lower = name.toLowerCase();
  if (lower.endsWith('.py')) {
    return CupertinoIcons.chevron_left_slash_chevron_right;
  }
  if (lower.endsWith('.dart')) {
    return CupertinoIcons.chevron_left_slash_chevron_right;
  }
  if (lower.endsWith('.json') ||
      lower.endsWith('.yaml') ||
      lower.endsWith('.yml')) {
    return CupertinoIcons.cube_box;
  }
  if (lower.endsWith('.db') || lower.endsWith('.sqlite')) {
    return CupertinoIcons.circle_grid_hex;
  }
  if (_isPreviewableImage(lower)) return CupertinoIcons.photo;
  return CupertinoIcons.doc;
}

Color _workspaceFileColor(String name, ColorScheme colors) {
  final lower = name.toLowerCase();
  if (lower.endsWith('.py')) return const Color(0xFF5AA9FF);
  if (lower.endsWith('.dart')) return const Color(0xFF55C2FF);
  if (lower.endsWith('.db') || lower.endsWith('.sqlite')) {
    return const Color(0xFFD05CE3);
  }
  if (_isPreviewableImage(lower)) return const Color(0xFF66C56C);
  return colors.onSurfaceVariant;
}

class _GlassSurface extends StatelessWidget {
  const _GlassSurface({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: EdgeInsets.zero,
      shape: const LiquidRoundedSuperellipse(borderRadius: 18),
      useOwnLayer: true,
      settings: _composerGlassSettings(context),
      child: child,
    );
  }
}

class _HeaderIconButton extends StatelessWidget {
  const _HeaderIconButton({
    required this.icon,
    required this.onTap,
    this.keyValue,
    this.tooltip,
    this.semanticsLabel,
    this.highlighted = false,
  });

  final IconData icon;
  final VoidCallback? onTap;
  final String? keyValue;
  final String? tooltip;
  final String? semanticsLabel;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final button = Semantics(
      button: true,
      enabled: onTap != null,
      label: semanticsLabel,
      child: InkWell(
        key: keyValue == null ? null : ValueKey<String>(keyValue!),
        borderRadius: BorderRadius.circular(highlighted ? 13 : 7),
        onTap: onTap,
        child: Container(
          width: highlighted ? 32 : 24,
          height: highlighted ? 32 : 24,
          decoration: highlighted
              ? BoxDecoration(
                  color: colors.onSurface.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(13),
                )
              : null,
          child: Icon(
            icon,
            size: highlighted ? 17 : 16,
            color: highlighted ? colors.onSurface : colors.onSurfaceVariant,
          ),
        ),
      ),
    );
    final message = tooltip;
    return message == null ? button : Tooltip(message: message, child: button);
  }
}

class _SplitResizeHandle extends StatelessWidget {
  const _SplitResizeHandle({super.key, required this.onDragUpdate});

  final GestureDragUpdateCallback onDragUpdate;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final dividerColor = dark
        ? const Color(0xFF3A3A3C)
        : const Color(0xFFD1D1D6);
    return MouseRegion(
      cursor: SystemMouseCursors.resizeLeftRight,
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onHorizontalDragUpdate: onDragUpdate,
        child: SizedBox(
          width: desktopSplitHandleWidth,
          child: Center(
            child: DecoratedBox(
              decoration: BoxDecoration(color: dividerColor),
              child: const SizedBox.expand(),
            ),
          ),
        ),
      ),
    );
  }
}

class _SplitResizeHitTarget extends StatelessWidget {
  const _SplitResizeHitTarget({required this.onDragUpdate});

  final GestureDragUpdateCallback onDragUpdate;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.resizeLeftRight,
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onHorizontalDragUpdate: onDragUpdate,
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _SidebarIconButton extends StatelessWidget {
  const _SidebarIconButton({
    required this.tooltip,
    required this.icon,
    required this.onTap,
    this.keyValue,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback onTap;
  final String? keyValue;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: InkWell(
          key: keyValue == null ? null : ValueKey<String>(keyValue!),
          borderRadius: BorderRadius.circular(6),
          onTap: onTap,
          child: SizedBox.square(
            dimension: 24,
            child: Icon(
              icon,
              size: 16,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ),
    );
  }
}

class _SidebarFooterAction extends StatelessWidget {
  const _SidebarFooterAction({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 2, 14, 8),
      child: InkWell(
        key: const ValueKey('settings-button'),
        borderRadius: BorderRadius.circular(9),
        onTap: onTap,
        child: SizedBox(
          height: 36,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Row(
              children: [
                Icon(icon, size: 16, color: colors.onSurfaceVariant),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
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
    );
  }
}

LiquidGlassSettings _composerGlassSettings(BuildContext context) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return LiquidGlassSettings(
    visibility: dark ? 0.94 : 0.96,
    glassColor: dark
        ? const Color(0xFF2F2F31).withValues(alpha: 0.9)
        : const Color(0xFFFFFFFF).withValues(alpha: 0.94),
    thickness: 4,
    blur: 3,
    chromaticAberration: 0,
    lightIntensity: 0.1,
    saturation: 1,
    glowIntensity: 0,
    standardOpacityMultiplier: dark ? 0.92 : 0.94,
    shadowElevation: 0.06,
  );
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.status});

  final RunStatus status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      RunStatus.running || RunStatus.starting => Colors.green,
      RunStatus.suspending || RunStatus.suspended => Colors.orange,
      RunStatus.failed => Colors.red,
      RunStatus.cancelled => Colors.grey,
      _ => Theme.of(context).colorScheme.outline,
    };
    return Container(
      width: 7,
      height: 7,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    );
  }
}

class _RunStatusChip extends StatelessWidget {
  const _RunStatusChip({required this.status});

  final RunStatus status;

  @override
  Widget build(BuildContext context) {
    return Text(
      _statusLabel(status, context.l10n),
      style: Theme.of(context).textTheme.labelMedium?.copyWith(
        fontSize: 11.5,
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
    );
  }
}

class _ErrorNotice extends StatelessWidget {
  const _ErrorNotice({required this.message, required this.onClose});

  final String message;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final localizedMessage = context.l10n.knownMessage(message);
    return Semantics(
      key: const ValueKey('workspace-error-notice'),
      liveRegion: true,
      label: localizedMessage,
      child: GlassCard(
        padding: EdgeInsets.zero,
        shape: const LiquidRoundedSuperellipse(borderRadius: 16),
        useOwnLayer: true,
        settings: _composerGlassSettings(context),
        child: Container(
          decoration: BoxDecoration(
            color: colors.errorContainer.withValues(alpha: 0.18),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: colors.error.withValues(alpha: 0.26)),
          ),
          padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
          child: Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: colors.errorContainer.withValues(alpha: 0.72),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  CupertinoIcons.exclamationmark,
                  color: colors.onErrorContainer,
                  size: 15,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  localizedMessage,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: colors.onSurface),
                ),
              ),
              IconButton(
                tooltip: context.l10n.text('common.close'),
                onPressed: onClose,
                icon: const Icon(CupertinoIcons.xmark, size: 15),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _riskLabel(
  String? category,
  String? sideEffectLevel,
  SageLocalizations l10n,
) => switch (category) {
  'destructive_filesystem' || 'filesystem_delete' => l10n.text('risk.files'),
  'external_side_effect' => l10n.text('risk.external'),
  'command_policy' => l10n.text('risk.command'),
  _ => switch (sideEffectLevel) {
    'none' => _approvalCardText('noSideEffect', l10n.languageCode),
    'read' => _approvalCardText('readOnly', l10n.languageCode),
    'write' ||
    'reversible' => _approvalCardText('writeOperation', l10n.languageCode),
    'irreversible' => _approvalCardText('highRisk', l10n.languageCode),
    _ => l10n.text('risk.generic'),
  },
};

String _approvalCardText(String key, String language) {
  final zh = language == 'zh';
  return switch (key) {
    'noSideEffect' => zh ? '无副作用' : 'No side effects',
    'readOnly' => zh ? '只读操作' : 'Read only',
    'writeOperation' => zh ? '写入操作' : 'Writes data',
    'highRisk' => zh ? '高风险操作' : 'High risk',
    _ => key,
  };
}

String _planApprovalTitle(String language) => switch (language) {
  'zh' => '审批计划',
  'pt' => 'Revisar plano',
  'es' => 'Revisar plan',
  'fr' => 'Examiner le plan',
  'de' => 'Plan prüfen',
  'ja' => '計画を確認',
  'ko' => '계획 검토',
  'ru' => 'Проверить план',
  _ => 'Review plan',
};

String? _riskReason(
  String? category,
  String? fallback,
  SageLocalizations l10n,
) => switch (category) {
  'destructive_filesystem' ||
  'filesystem_delete' => l10n.text('risk.filesReason'),
  'permission_change' => l10n.text('risk.permission'),
  'git_remote_write' => l10n.text('risk.gitRemote'),
  'git_worktree_destructive' => l10n.text('risk.gitWorktree'),
  'dependency_install' => l10n.text('risk.dependencies'),
  'process_control' => l10n.text('risk.process'),
  'untrusted_command' => l10n.text('risk.untrusted'),
  'shell_redirection' => l10n.text('risk.redirection'),
  'shell_parse' => l10n.text('risk.parse'),
  _ => fallback,
};

String _statusLabel(RunStatus status, SageLocalizations l10n) =>
    switch (status) {
      RunStatus.idle => l10n.text('status.idle'),
      RunStatus.starting => l10n.text('status.starting'),
      RunStatus.running => l10n.text('status.running'),
      RunStatus.suspending => l10n.text('status.suspending'),
      RunStatus.suspended => l10n.text('status.suspended'),
      RunStatus.completed => l10n.text('status.completed'),
      RunStatus.failed => l10n.text('status.failed'),
      RunStatus.cancelled => l10n.text('status.cancelled'),
    };

String _decisionLabel(String decision, SageLocalizations l10n) =>
    switch (decision) {
      'approve' => l10n.text('decision.approve'),
      'approve_once' => l10n.text('decision.approveOnce'),
      'approve_and_remember' => l10n.text('decision.approveAndRemember'),
      'allow' => l10n.text('decision.allow'),
      'deny' => l10n.text('decision.deny'),
      'cancel' => l10n.text('common.cancel'),
      'submit' => l10n.text('decision.submit'),
      'confirm_succeeded' => l10n.text('decision.confirmSucceeded'),
      'mark_failed' => l10n.text('decision.markFailed'),
      'continue' => _localizedRuntimeDecision('continue', l10n.languageCode),
      'change_direction' => _localizedRuntimeDecision(
        'change_direction',
        l10n.languageCode,
      ),
      'reconcile' => _localizedRuntimeDecision('reconcile', l10n.languageCode),
      'retry' => l10n.text('common.retry'),
      _ => decision,
    };

String _interactionDecisionLabel(
  String decision,
  String? toolName,
  SageLocalizations l10n,
) {
  if (toolName == 'goal_submit' &&
      {'approve', 'approve_once', 'approve_and_remember'}.contains(decision)) {
    return switch (l10n.languageCode) {
      'zh' => '批准计划',
      'pt' => 'Aprovar plano',
      'es' => 'Aprobar plan',
      'fr' => 'Approuver le plan',
      'de' => 'Plan genehmigen',
      'ja' => '計画を承認',
      'ko' => '계획 승인',
      'ru' => 'Утвердить план',
      _ => 'Approve plan',
    };
  }
  return _decisionLabel(decision, l10n);
}

String _localizedRuntimeDecision(String decision, String language) {
  const values = <String, Map<String, String>>{
    'continue': {
      'zh': '继续',
      'en': 'Continue',
      'pt': 'Continuar',
      'es': 'Continuar',
      'fr': 'Continuer',
      'de': 'Fortfahren',
      'ja': '続行',
      'ko': '계속',
      'ru': 'Продолжить',
    },
    'change_direction': {
      'zh': '改变方向',
      'en': 'Change direction',
      'pt': 'Mudar direção',
      'es': 'Cambiar de dirección',
      'fr': 'Changer de direction',
      'de': 'Richtung ändern',
      'ja': '方針を変更',
      'ko': '방향 변경',
      'ru': 'Изменить направление',
    },
    'reconcile': {
      'zh': '核对工具结果',
      'en': 'Check Tool result',
      'pt': 'Verificar resultado',
      'es': 'Comprobar resultado',
      'fr': 'Vérifier le résultat',
      'de': 'Ergebnis prüfen',
      'ja': 'ツール結果を確認',
      'ko': '도구 결과 확인',
      'ru': 'Проверить результат',
    },
  };
  return values[decision]?[language] ?? values[decision]?['en'] ?? decision;
}
