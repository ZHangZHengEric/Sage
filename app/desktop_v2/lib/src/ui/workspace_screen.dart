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
import 'package:markdown/markdown.dart' as md;

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

part 'workspace/thread.dart';
part 'workspace/messages.dart';
part 'workspace/process.dart';
part 'workspace/message_content.dart';
part 'workspace/composer.dart';
part 'workspace/files.dart';
part 'workspace/chrome.dart';

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
