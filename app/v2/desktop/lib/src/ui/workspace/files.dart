part of '../workspace_screen.dart';

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
