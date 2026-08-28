import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import '../models.dart';
import '../localization/app_localizations.dart';
import '../state/workspace_controller.dart';
import 'file_preview.dart';
import 'settings_screen.dart';
import 'shared/desktop_shell.dart';
import 'tool_activity_presentation.dart';

const double _splitHandleHitWidth = 12;
const double _minRailFraction = 0.16;
const double _defaultRailFraction = 0.16;
const double _maxRailFraction = 0.28;
const double _minWorkspaceFraction = 0.34;
const double _defaultWorkspaceFraction = 0.44;
const double _maxWorkspaceFraction = 0.60;

class WorkspaceScreen extends StatefulWidget {
  const WorkspaceScreen({
    required this.controller,
    required this.themeMode,
    required this.onThemeModeChanged,
    required this.language,
    required this.onLanguageChanged,
    super.key,
  });

  final WorkspaceController controller;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final String language;
  final ValueChanged<String> onLanguageChanged;

  @override
  State<WorkspaceScreen> createState() => _WorkspaceScreenState();
}

class _WorkspaceScreenState extends State<WorkspaceScreen> {
  bool _railCollapsed = false;
  bool _workspaceCollapsed = false;
  bool _settingsOpen = false;
  double _railFraction = _defaultRailFraction;
  double _workspaceFraction = _defaultWorkspaceFraction;

  void _resizeRail(double delta, double width) {
    setState(() {
      _railFraction = (_railFraction + delta / width)
          .clamp(_minRailFraction, _maxRailFraction)
          .toDouble();
    });
  }

  void _resizeWorkspace(double delta, double width) {
    setState(() {
      _workspaceFraction = (_workspaceFraction - delta / width)
          .clamp(_minWorkspaceFraction, _maxWorkspaceFraction)
          .toDouble();
    });
  }

  @override
  Widget build(BuildContext context) {
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
                        onClose: () => setState(() => _settingsOpen = false),
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
  }

  Widget _buildWorkspaceShell() {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < desktopCompactBreakpoint) {
          final railHeight = _railCollapsed
              ? 0.0
              : desktopCompactRailHeight(constraints.maxHeight);
          final workspaceHeight = _workspaceCollapsed
              ? 0.0
              : (constraints.maxHeight * 0.42).clamp(240.0, 430.0).toDouble();
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
                    child: _FilePanel(
                      controller: widget.controller,
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
        final minWorkspaceWidth = constraints.maxWidth * _minWorkspaceFraction;
        final maxWorkspaceWidth = min(
          constraints.maxWidth * _maxWorkspaceFraction,
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
                      child: _FilePanel(controller: widget.controller),
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

  bool _isExpanded(WorkspaceGroup group) =>
      group.id == widget.controller.selectedGroupId &&
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
                    ),
                    if (_isExpanded(group))
                      for (final conversation in group.conversations)
                        _ConversationTile(
                          conversation: conversation,
                          selected:
                              conversation.id ==
                              widget.controller.selectedConversationId,
                          onTap: () => widget.controller.selectConversation(
                            conversation.id,
                          ),
                          onArchive: () => widget.controller
                              .archiveConversation(group.id, conversation.id),
                          onDelete: () => _deleteConversation(
                            context,
                            group.id,
                            conversation,
                          ),
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
                      _ConversationTile(
                        conversation: conversation,
                        selected:
                            widget.controller.selectedGroupId ==
                                WorkspaceController.agentWorkspaceId &&
                            conversation.id ==
                                widget.controller.selectedConversationId,
                        indented: false,
                        onTap: () => widget.controller
                            .selectAgentWorkspaceConversation(conversation.id),
                        onArchive: () => widget.controller.archiveConversation(
                          WorkspaceController.agentWorkspaceId,
                          conversation.id,
                        ),
                        onDelete: () => _deleteConversation(
                          context,
                          WorkspaceController.agentWorkspaceId,
                          conversation,
                        ),
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
  });

  final WorkspaceGroup group;
  final bool selected;
  final bool expanded;
  final VoidCallback onTap;
  final VoidCallback onToggleExpanded;
  final VoidCallback onNewConversation;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
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
    this.indented = true,
  });

  final Conversation conversation;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback onArchive;
  final VoidCallback onDelete;
  final bool indented;

  @override
  State<_ConversationTile> createState() => _ConversationTileState();
}

class _ConversationTileState extends State<_ConversationTile> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final manageable =
        widget.conversation.status != RunStatus.starting &&
        widget.conversation.status != RunStatus.running &&
        widget.conversation.status != RunStatus.suspending &&
        widget.conversation.status != RunStatus.suspended;
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
            padding: const EdgeInsets.only(left: 12, right: 8),
            decoration: BoxDecoration(
              color: widget.selected
                  ? colors.onSurface.withValues(alpha: 0.095)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                if (widget.indented) const SizedBox(width: 16),
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
    final conversation = controller.selectedConversation;
    if (conversation == null) return const SizedBox.shrink();
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
            Expanded(child: _MessageList(conversation: conversation)),
            if (conversation.pendingInteraction case final interaction?)
              _InteractionCard(
                interaction: interaction,
                onReply: controller.replyInteraction,
              ),
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
  const _MessageList({required this.conversation});

  final Conversation conversation;

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
    return '$messageSignature:$processSignature';
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
      children.add(_MessageBubble(key: ValueKey(message.id), message: message));
      for (final panel in conversation.processPanels.where(
        (value) =>
            value.anchorMessageId == message.id && _shouldShowPanel(value),
      )) {
        attachedPanelIds.add(panel.id);
        children.add(const SizedBox(height: 14));
        children.add(
          _ProcessPanel(
            key: ValueKey(panel.id),
            panel: panel,
            messages: _processMessagesFor(panel),
          ),
        );
      }
      children.add(const SizedBox(height: 26));
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
        ),
      );
      children.add(const SizedBox(height: 26));
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
        _processMessagesFor(panel).isNotEmpty;
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
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message, super.key});

  final ChatMessage message;

  Future<void> _copy() => Clipboard.setData(ClipboardData(text: message.text));

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
              child: Container(
                constraints: BoxConstraints(maxWidth: user ? 608 : 760),
                padding: user
                    ? const EdgeInsets.symmetric(horizontal: 15, vertical: 12)
                    : EdgeInsets.zero,
                decoration: BoxDecoration(
                  color: user
                      ? colors.surfaceContainerHighest.withValues(alpha: 0.48)
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
                _ThreadCopyButton(onTap: _copy),
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
  const _ProcessPanel({required this.panel, required this.messages, super.key});

  final RuntimeProcessPanel panel;
  final List<ChatMessage> messages;

  @override
  State<_ProcessPanel> createState() => _ProcessPanelState();
}

class _ProcessPanelState extends State<_ProcessPanel> {
  bool _expanded = true;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _syncTimer();
  }

  @override
  void didUpdateWidget(covariant _ProcessPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
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
              _ProcessStreamLog(items: items),
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
  const _ProcessStreamLog({required this.items});

  final List<_ProcessStreamItem> items;

  @override
  Widget build(BuildContext context) {
    final entries = _processStreamEntries(items);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var index = 0; index < entries.length; index++) ...[
          entries[index].build(context),
          if (index != entries.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

List<_ProcessStreamEntry> _processStreamEntries(
  List<_ProcessStreamItem> items,
) {
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
      pendingActivities.add(item.activity);
      continue;
    }
    flushActivities();
    entries.add(_ProcessMessageEntry((item as _ProcessMessageItem).message));
  }
  flushActivities();
  return entries;
}

sealed class _ProcessStreamEntry {
  Widget build(BuildContext context);
}

class _SingleProcessActivityEntry extends _ProcessStreamEntry {
  _SingleProcessActivityEntry(this.activity);

  final RuntimeActivity activity;

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
    final arguments = toolArgumentPreview(
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
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text.rich(
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
                      if (arguments.isNotEmpty)
                        TextSpan(
                          text: '  $arguments',
                          style: _processTextStyle(context)?.copyWith(
                            color: detailColor,
                            fontWeight: FontWeight.w400,
                          ),
                        ),
                    ],
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (result.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    result,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: _processTextStyle(context)?.copyWith(
                      fontSize: 11.5,
                      color: detailColor,
                      fontWeight: FontWeight.w400,
                    ),
                  ),
                ],
              ],
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
      _ => CupertinoIcons.square_stack_3d_up,
    };

String _activityCategory(RuntimeActivity activity) {
  final name = activity.label.toLowerCase();
  if (name.contains('search') ||
      name.contains('find') ||
      name.contains('grep') ||
      name.contains('fetch') ||
      name.contains('browser')) {
    return 'search';
  }
  if (name.contains('read') || name.contains('list') || name.contains('glob')) {
    return 'read';
  }
  if (name.contains('write') ||
      name.contains('update') ||
      name.contains('patch') ||
      name.contains('edit')) {
    return 'write';
  }
  if (name.contains('shell') ||
      name.contains('exec') ||
      name.contains('command') ||
      name.contains('test')) {
    return 'shell';
  }
  if (name.contains('agent') ||
      name.contains('spawn') ||
      name.contains('delegate')) {
    return 'agent';
  }
  return 'other';
}

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

class _ThreadCopyButton extends StatelessWidget {
  const _ThreadCopyButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Tooltip(
      message: context.l10n.text('common.copy'),
      child: InkWell(
        borderRadius: BorderRadius.circular(9),
        onTap: onTap,
        child: SizedBox(
          width: 24,
          height: 24,
          child: Icon(
            CupertinoIcons.doc_on_doc,
            size: 12.5,
            color: colors.onSurfaceVariant.withValues(alpha: 0.76),
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
  final Future<void> Function(String decision, {String text}) onReply;

  @override
  State<_InteractionCard> createState() => _InteractionCardState();
}

class _InteractionCardState extends State<_InteractionCard> {
  final _answer = TextEditingController();
  bool _submitting = false;

  Future<void> _reply(String decision) async {
    if (_submitting) return;
    setState(() => _submitting = true);
    try {
      await widget.onReply(decision, text: _answer.text);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  List<String> _visibleDecisions(bool approval) {
    final decisions = widget.interaction.allowedDecisions;
    if (!approval || !decisions.contains('deny')) return decisions;
    return decisions.where((value) => value != 'cancel').toList();
  }

  String? _argumentSummary(Map<String, Object?> payload) {
    final rawArguments = payload['arguments'];
    if (rawArguments is! Map || rawArguments.isEmpty) return null;
    final arguments = rawArguments.cast<Object?, Object?>();
    final command = arguments['command']?.toString().trim();
    if (command != null && command.isNotEmpty) return command;
    try {
      return const JsonEncoder.withIndent('  ').convert(arguments);
    } on JsonUnsupportedObjectError {
      return arguments.toString();
    }
  }

  @override
  void dispose() {
    _answer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final payload = widget.interaction.payload;
    final approval = widget.interaction.type == 'approval';
    final prompt =
        payload['prompt']?.toString() ??
        payload['reason']?.toString() ??
        (approval
            ? context.l10n.text('workspace.requestApproval')
            : widget.interaction.type);
    final toolName = payload['tool_name']?.toString();
    final language = toolPresentationLanguage(context);
    final argumentSummary = approval ? _argumentSummary(payload) : null;
    final riskReason = payload['risk_reason']?.toString();
    final riskCategory = payload['risk_category']?.toString();
    final displayedRiskReason = _riskReason(
      riskCategory,
      riskReason,
      context.l10n,
    );
    final decisions = _visibleDecisions(approval);
    final colors = Theme.of(context).colorScheme;
    final title = approval && toolName != null
        ? localizedToolName(toolName, language)
        : prompt;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 580),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(0, 4, 0, 8),
          child: _GlassSurface(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 15, 16, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 32,
                        height: 32,
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
                            color: colors.errorContainer.withValues(
                              alpha: 0.55,
                            ),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            _riskLabel(riskCategory, context.l10n),
                            style: Theme.of(context).textTheme.labelSmall
                                ?.copyWith(
                                  color: colors.onErrorContainer,
                                  fontWeight: FontWeight.w600,
                                ),
                          ),
                        ),
                    ],
                  ),
                  if (argumentSummary != null) ...[
                    const SizedBox(height: 12),
                    Container(
                      key: const ValueKey('interaction-command'),
                      width: double.infinity,
                      constraints: const BoxConstraints(maxHeight: 132),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
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
                      child: SingleChildScrollView(
                        child: SelectableText(
                          argumentSummary,
                          style: TextStyle(
                            color: colors.onSurface,
                            fontFamily: 'monospace',
                            fontSize: 12.5,
                            height: 1.45,
                          ),
                        ),
                      ),
                    ),
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
                  if (widget.interaction.type == 'user_input') ...[
                    const SizedBox(height: 10),
                    TextField(
                      key: const ValueKey('interaction-input'),
                      controller: _answer,
                      autofocus: true,
                      onSubmitted: (_) => _reply(decisions.first),
                    ),
                  ],
                  const SizedBox(height: 14),
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
                            child: Text(_decisionLabel(decision, context.l10n)),
                          )
                        else
                          GlassButton.custom(
                            key: ValueKey('interaction-submit-$decision'),
                            width: decision == 'approve_once' ? 108 : 92,
                            height: 36,
                            label: _decisionLabel(decision, context.l10n),
                            enabled: !_submitting,
                            onTap: () => _reply(decision),
                            shape: const LiquidRoundedRectangle(
                              borderRadius: 10,
                            ),
                            settings: _composerGlassSettings(context),
                            child: _submitting
                                ? const CupertinoActivityIndicator(radius: 7)
                                : Text(
                                    _decisionLabel(decision, context.l10n),
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
  final _text = TextEditingController();
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_syncComposerInsertions);
    _syncComposerInsertions();
  }

  @override
  void didUpdateWidget(covariant _Composer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_syncComposerInsertions);
      widget.controller.addListener(_syncComposerInsertions);
    }
    _syncComposerInsertions();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_syncComposerInsertions);
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _syncComposerInsertions() {
    var inserted = false;
    while (true) {
      final insertion = widget.controller.takeComposerInsertion(
        widget.conversation.id,
      );
      if (insertion == null) break;
      final current = _text.text.trimRight();
      final next = current.isEmpty ? insertion : '$current\n\n$insertion';
      _text.value = TextEditingValue(
        text: next,
        selection: TextSelection.collapsed(offset: next.length),
      );
      inserted = true;
    }
    if (inserted) _focus.requestFocus();
  }

  void _submit() {
    final value = _text.text;
    if (value.trim().isEmpty) return;
    _text.clear();
    widget.controller.send(value);
    _focus.requestFocus();
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
                      running ? 'workspace.inputSteer' : 'workspace.inputAgent',
                    ),
                    hintStyle: Theme.of(context).textTheme.bodyLarge?.copyWith(
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
                    _SkillPicker(controller: widget.controller),
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
                        hasDraft: value.text.trim().isNotEmpty,
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

class _ComposerAssetShelf extends StatelessWidget {
  const _ComposerAssetShelf({required this.assets, required this.onRemoved});

  final List<UploadedAttachment> assets;
  final ValueChanged<UploadedAttachment> onRemoved;

  @override
  Widget build(BuildContext context) {
    if (assets.isEmpty) return const SizedBox.shrink();
    final colors = Theme.of(context).colorScheme;
    return Padding(
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
  const _SkillPicker({required this.controller});

  final WorkspaceController controller;

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
                  color: _isOpen
                      ? colors.primary.withValues(alpha: 0.12)
                      : Colors.transparent,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  CupertinoIcons.add,
                  size: 20,
                  color: _isOpen ? colors.primary : colors.onSurfaceVariant,
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
              onRemoveProject: controller.selectedGroup.project == null
                  ? null
                  : controller.removeSelectedProject,
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
    this.onRemoveProject,
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
  final VoidCallback? onRemoveProject;

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
          if (onRemoveProject != null) ...[
            const SizedBox(width: 4),
            _HeaderIconButton(
              keyValue: 'workspace-remove-project',
              icon: CupertinoIcons.folder_badge_minus,
              onTap: onRemoveProject!,
            ),
          ],
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
                      return InkWell(
                        key: ValueKey('file-tree-row:${node.path}'),
                        borderRadius: BorderRadius.circular(7),
                        onTap: node.isDirectory
                            ? () => onToggleDirectory(node.path)
                            : () => controller.openFile(node),
                        child: Container(
                          height: 29,
                          padding: EdgeInsets.only(
                            left: 7 + value.depth * 14,
                            right: 7,
                          ),
                          decoration: BoxDecoration(
                            color: selected
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
                                        expanded
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
                                  style: Theme.of(context).textTheme.bodyMedium
                                      ?.copyWith(
                                        fontSize: 12.5,
                                        fontWeight: selected
                                            ? FontWeight.w600
                                            : FontWeight.w400,
                                      ),
                                ),
                              ),
                              const SizedBox(width: 4),
                              _TreeReferenceButton(
                                node: node,
                                referenced: referenced,
                                onTap: () =>
                                    controller.referenceWorkspaceNode(node),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _TreeReferenceButton extends StatelessWidget {
  const _TreeReferenceButton({
    required this.node,
    required this.referenced,
    required this.onTap,
  });

  final WorkspaceFileNode node;
  final bool referenced;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final label = context.l10n.text(
      referenced ? 'workspace.referencedNode' : 'workspace.referenceNode',
      {
        'kind': context.l10n.text(
          node.isDirectory ? 'workspace.folder' : 'workspace.file',
        ),
      },
    );
    return Tooltip(
      message: label,
      child: Semantics(
        button: true,
        enabled: !referenced,
        label: label,
        child: InkWell(
          key: ValueKey('file-tree-reference:${node.path}'),
          onTap: referenced ? null : onTap,
          borderRadius: BorderRadius.circular(7),
          child: Container(
            width: 22,
            height: 22,
            decoration: referenced
                ? BoxDecoration(
                    color: colors.onSurface.withValues(alpha: 0.09),
                    borderRadius: BorderRadius.circular(7),
                  )
                : null,
            child: Icon(
              CupertinoIcons.at,
              size: 13,
              color: colors.onSurfaceVariant.withValues(
                alpha: referenced ? 0.9 : 0.66,
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

String _riskLabel(String? category, SageLocalizations l10n) =>
    switch (category) {
      'destructive_filesystem' ||
      'filesystem_delete' => l10n.text('risk.files'),
      'external_side_effect' => l10n.text('risk.external'),
      'command_policy' => l10n.text('risk.command'),
      _ => l10n.text('risk.generic'),
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
      'allow' => l10n.text('decision.allow'),
      'deny' => l10n.text('decision.deny'),
      'cancel' => l10n.text('common.cancel'),
      'submit' => l10n.text('decision.submit'),
      'confirm_succeeded' => l10n.text('decision.confirmSucceeded'),
      'mark_failed' => l10n.text('decision.markFailed'),
      _ => decision,
    };
