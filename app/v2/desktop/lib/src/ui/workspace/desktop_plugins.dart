part of '../workspace_screen.dart';

const _desktopPluginIconSize = 72.0;
const _desktopPluginIconRadius = 17.0;

class _DesktopPluginRail extends StatelessWidget {
  const _DesktopPluginRail({
    required this.controller,
    required this.onOpen,
    required this.onOpenCollection,
    required this.collectionSelected,
    this.compact = false,
  });

  final WorkspaceController controller;
  final ValueChanged<String> onOpen;
  final VoidCallback onOpenCollection;
  final bool collectionSelected;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final plugins = controller.desktopPlugins;
    return ListenableBuilder(
      listenable: plugins,
      builder: (context, _) {
        final title = pluginText(context, 'Desktop Plugins', '桌面插件');
        final colors = Theme.of(context).colorScheme;
        Widget entry(
          String label,
          IconData icon,
          VoidCallback? onTap, {
          Key? key,
          bool? selected,
        }) => GlassButton.custom(
          key: key,
          width: compact ? 34 : double.infinity,
          height: 34,
          shape: const LiquidRoundedRectangle(borderRadius: 8),
          settings: desktopSidebarGlassSettings(context),
          style: GlassButtonStyle.transparent,
          label: label,
          onTap: onTap ?? () {},
          enabled: onTap != null,
          child: Semantics(
            selected: selected,
            child: Row(
              mainAxisAlignment: compact
                  ? MainAxisAlignment.center
                  : MainAxisAlignment.start,
              children: [
                if (!compact) const SizedBox(width: 9),
                Icon(
                  icon,
                  size: 16,
                  color: selected == true
                      ? colors.primary
                      : onTap == null
                      ? colors.outline
                      : colors.onSurfaceVariant,
                ),
                if (!compact) ...[
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      label,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: onTap == null
                            ? colors.outline
                            : colors.onSurface,
                        fontWeight: selected == true
                            ? FontWeight.w700
                            : FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        );
        final pinned = plugins.pinned;
        final height = MediaQuery.sizeOf(context).height;
        // Leave room for the sidebar header, actions, and history.
        final maxPinnedHeight = min(
          min(170.0, height * 0.22),
          max(0.0, height - 240),
        );
        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            entry(
              title,
              CupertinoIcons.square_grid_2x2,
              onOpenCollection,
              key: const ValueKey('desktop-plugins'),
              selected: collectionSelected,
            ),
            if (!compact && pinned.isNotEmpty && maxPinnedHeight > 0)
              ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: maxPinnedHeight,
                ),
                child: ListView(
                  primary: false,
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  physics: const ClampingScrollPhysics(),
                  children: [
                    for (final plugin in pinned)
                      GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onSecondaryTapUp: (details) => unawaited(
                          _showPinnedMenu(
                            context,
                            plugins,
                            plugin,
                            details.globalPosition,
                          ),
                        ),
                        child: entry(
                          plugin.title,
                          pluginIcon(plugin),
                          plugin.enabled ? () => onOpen(plugin.id) : null,
                          key: ValueKey('desktop-plugin-pin:${plugin.id}'),
                        ),
                      ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }

  Future<void> _showPinnedMenu(
    BuildContext context,
    DesktopPlugins plugins,
    DesktopPlugin plugin,
    Offset pointer,
  ) async {
    final unpin = await _showDesktopPluginMenu<bool>(
      context,
      pointer,
      width: 124,
      items: [
        PopupMenuItem<bool>(
          key: ValueKey('desktop-plugin-unpin:${plugin.id}'),
          value: true,
          height: 28,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          child: _pluginMenuLabel(
            context,
            pluginText(context, 'Unpin', '取消固定'),
            CupertinoIcons.pin_slash,
          ),
        ),
      ],
    );
    if (unpin != true || !context.mounted) return;
    try {
      await plugins.manage(plugin, 'unpin');
    } on Object catch (error) {
      if (context.mounted) {
        DesktopNoticeHost.show(
          context,
          message: error.toString(),
          isError: true,
        );
      }
    }
  }
}

Future<T?> _showDesktopPluginMenu<T>(
  BuildContext context,
  Offset pointer, {
  required double width,
  required List<PopupMenuEntry<T>> items,
}) {
  final overlay =
      Navigator.of(context).overlay!.context.findRenderObject()! as RenderBox;
  final anchor = overlay.globalToLocal(pointer);
  return showDialog<T>(
    context: context,
    useRootNavigator: false,
    useSafeArea: false,
    barrierColor: Colors.transparent,
    builder: (context) => CustomSingleChildLayout(
      delegate: _DesktopPluginMenuLayout(anchor, width),
      child: GlassCard(
        key: const ValueKey('desktop-plugin-context-menu'),
        shape: const LiquidRoundedRectangle(borderRadius: 8),
        settings: _composerGlassSettings(context),
        useOwnLayer: true,
        padding: const EdgeInsets.all(3),
        child: Material(
          type: MaterialType.transparency,
          child: Semantics(
            role: SemanticsRole.menu,
            container: true,
            explicitChildNodes: true,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: items),
            ),
          ),
        ),
      ),
    ),
  );
}

class _DesktopPluginMenuLayout extends SingleChildLayoutDelegate {
  const _DesktopPluginMenuLayout(this.anchor, this.width);

  final Offset anchor;
  final double width;

  @override
  BoxConstraints getConstraintsForChild(BoxConstraints constraints) {
    final size = constraints.biggest;
    final point = _anchorIn(size);
    final horizontal = max(point.dx, size.width - point.dx);
    final vertical = max(point.dy, size.height - point.dy);
    return BoxConstraints.tightFor(
      width: min(width, horizontal),
    ).copyWith(maxHeight: vertical);
  }

  @override
  Offset getPositionForChild(Size size, Size childSize) {
    final point = _anchorIn(size);
    final opensRight = size.width - point.dx >= childSize.width;
    final opensDown = size.height - point.dy >= childSize.height;
    return Offset(
      opensRight ? point.dx : point.dx - childSize.width,
      opensDown ? point.dy : point.dy - childSize.height,
    );
  }

  Offset _anchorIn(Size size) => Offset(
    anchor.dx.clamp(0.0, size.width),
    anchor.dy.clamp(0.0, size.height),
  );

  @override
  bool shouldRelayout(_DesktopPluginMenuLayout oldDelegate) =>
      anchor != oldDelegate.anchor || width != oldDelegate.width;
}

Widget _pluginMenuLabel(
  BuildContext context,
  String label,
  IconData icon, {
  bool destructive = false,
}) {
  final colors = Theme.of(context).colorScheme;
  return Row(
    children: [
      Icon(
        icon,
        size: 13,
        color: destructive ? colors.error : colors.onSurfaceVariant,
      ),
      const SizedBox(width: 7),
      Flexible(
        child: Text(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: destructive ? colors.error : colors.onSurface,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
    ],
  );
}

class _DesktopPluginCollectionPanel extends WorkspacePanelPluginBase {
  const _DesktopPluginCollectionPanel(this.controller, this.onOpen);

  static const panelId = 'sage.workspace.desktop-plugins';
  final WorkspaceController controller;
  final ValueChanged<String> onOpen;

  @override
  String get id => panelId;

  @override
  IconData get icon => CupertinoIcons.square_grid_2x2;

  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => pluginText(context, 'Desktop Plugins', '桌面插件');

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) =>
      _DesktopPluginCollection(
        controller: controller,
        onOpen: onOpen,
        active: panelContext.active,
      );
}

class _DesktopPluginCollection extends StatefulWidget {
  const _DesktopPluginCollection({
    required this.controller,
    required this.onOpen,
    required this.active,
  });
  final WorkspaceController controller;
  final ValueChanged<String> onOpen;
  final bool active;

  @override
  State<_DesktopPluginCollection> createState() =>
      _DesktopPluginCollectionState();
}

class _DesktopPluginCollectionState extends State<_DesktopPluginCollection> {
  static const _tileWidth = 112.0;
  static const _tileHeight = 108.0;
  bool _uploading = false;
  WorkspaceController get controller => widget.controller;

  @override
  Widget build(BuildContext context) {
    // Remove the launcher's menu portals before the Dock suspends its tickers.
    if (!widget.active) return const SizedBox.expand();
    final plugins = controller.desktopPlugins;
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return DecoratedBox(
      key: const ValueKey('desktop-plugin-collection'),
      decoration: BoxDecoration(
        color: colors.surface,
        gradient: RadialGradient(
          center: const Alignment(0, -0.65),
          radius: 1.05,
          colors: [
            Color.alphaBlend(
              colors.primary.withValues(alpha: dark ? 0.15 : 0.08),
              colors.surface,
            ),
            colors.surface,
          ],
        ),
      ),
      child: SizedBox.expand(
        child: ListenableBuilder(
          listenable: plugins,
          builder: (context, _) {
            final pinned = plugins.pinned;
            final all = [
              ...pinned,
              ...plugins.installed.where((item) => item.pin == null),
            ];
            return SingleChildScrollView(
              key: const PageStorageKey('desktop-plugin-launcher-scroll'),
              padding: const EdgeInsets.fromLTRB(12, 38, 12, 32),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 880),
                  child: Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 16,
                    runSpacing: 20,
                    children: [
                      for (final plugin in all)
                        _launcherIcon(
                          context,
                          plugins,
                          plugin,
                          pinned.indexOf(plugin),
                          pinned.length,
                        ),
                      _uploadTile(context),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _uploadTile(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final label = pluginText(context, 'Upload Plugin', '上传插件');
    return GlassButton.custom(
      key: const ValueKey('desktop-plugin-upload'),
      width: _tileWidth,
      height: _tileHeight,
      style: GlassButtonStyle.transparent,
      shape: const LiquidRoundedRectangle(borderRadius: 16),
      label: label,
      enabled: !_uploading,
      onTap: _upload,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: _desktopPluginIconSize,
            height: _desktopPluginIconSize,
            decoration: BoxDecoration(
              color: colors.onSurface.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(_desktopPluginIconRadius),
              border: Border.all(color: colors.outlineVariant),
            ),
            alignment: Alignment.center,
            child: _uploading
                ? const CupertinoActivityIndicator()
                : Icon(
                    CupertinoIcons.add,
                    size: 30,
                    color: colors.onSurfaceVariant,
                  ),
          ),
          const SizedBox(height: 8),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: colors.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _launcherIcon(
    BuildContext context,
    DesktopPlugins plugins,
    DesktopPlugin plugin,
    int position,
    int pinnedCount,
  ) {
    final colors = Theme.of(context).colorScheme;
    return Builder(
      builder: (tileContext) => CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.f10, shift: true): () =>
              _showLauncherMenu(tileContext, plugin, position, pinnedCount),
          const SingleActivator(LogicalKeyboardKey.contextMenu): () =>
              _showLauncherMenu(tileContext, plugin, position, pinnedCount),
        },
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onSecondaryTapUp: (details) => _showLauncherMenu(
            tileContext,
            plugin,
            position,
            pinnedCount,
            pointer: details.globalPosition,
          ),
          onLongPressStart: (details) => _showLauncherMenu(
            tileContext,
            plugin,
            position,
            pinnedCount,
            pointer: details.globalPosition,
          ),
          child: GlassButton.custom(
            key: ValueKey('desktop-plugin:${plugin.id}'),
            label: plugin.title,
            width: _tileWidth,
            height: _tileHeight,
            style: GlassButtonStyle.transparent,
            enabled: plugin.enabled,
            shape: const LiquidRoundedRectangle(borderRadius: 16),
            onTap: () => widget.onOpen(plugin.id),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Opacity(
                    opacity: plugin.enabled ? 1 : 0.55,
                    child: _DesktopPluginLogo(
                      key: ValueKey('${plugin.id}:${plugin.digest}'),
                      plugin: plugin,
                      plugins: plugins,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    plugin.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: plugin.enabled
                          ? colors.onSurface
                          : colors.onSurfaceVariant,
                      fontWeight: FontWeight.w600,
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

  Future<void> _showLauncherMenu(
    BuildContext context,
    DesktopPlugin plugin,
    int position,
    int pinnedCount, {
    Offset? pointer,
  }) async {
    final tile = context.findRenderObject()! as RenderBox;
    final anchor = pointer ?? tile.localToGlobal(Offset(0, tile.size.height));
    final action = await _showDesktopPluginMenu<String>(
      context,
      anchor,
      width: 154,
      items: [
        if (plugin.enabled)
          _item(
            context,
            plugin,
            'open',
            'Open',
            '打开',
            CupertinoIcons.arrow_up_right,
          ),
        if (position < 0)
          _item(context, plugin, 'pin', 'Pin', '固定', CupertinoIcons.pin)
        else
          _item(
            context,
            plugin,
            'unpin',
            'Unpin',
            '取消固定',
            CupertinoIcons.pin_slash,
          ),
        if (position > 0)
          _item(
            context,
            plugin,
            'up',
            'Move up',
            '上移',
            CupertinoIcons.arrow_up,
          ),
        if (position >= 0 && position + 1 < pinnedCount)
          _item(
            context,
            plugin,
            'down',
            'Move down',
            '下移',
            CupertinoIcons.arrow_down,
          ),
        if (plugin.enabled)
          _item(
            context,
            plugin,
            'disable',
            'Disable',
            '停用',
            CupertinoIcons.pause_circle,
          )
        else
          _item(
            context,
            plugin,
            'enable',
            'Enable',
            '启用',
            CupertinoIcons.play_circle,
          ),
        _item(
          context,
          plugin,
          'revoke',
          'Revoke permissions',
          '撤销权限',
          CupertinoIcons.lock,
        ),
        _item(
          context,
          plugin,
          'uninstall',
          'Uninstall',
          '卸载',
          CupertinoIcons.trash,
        ),
      ],
    );
    if (action != null && context.mounted) {
      await _manage(context, plugin, action);
    }
  }

  PopupMenuItem<String> _item(
    BuildContext context,
    DesktopPlugin plugin,
    String id,
    String en,
    String zh,
    IconData icon,
  ) => PopupMenuItem(
    key: ValueKey('desktop-plugin-menu:${plugin.id}:$id'),
    value: id,
    height: 28,
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    child: _pluginMenuLabel(
      context,
      pluginText(context, en, zh),
      icon,
      destructive: id == 'uninstall',
    ),
  );

  Future<void> _manage(
    BuildContext context,
    DesktopPlugin plugin,
    String action,
  ) async {
    try {
      if (action == 'open') {
        widget.onOpen(plugin.id);
        return;
      }
      if (action == 'uninstall') {
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(plugin.title),
            content: Text(
              pluginText(
                context,
                'Uninstall this plugin and delete its data?',
                '卸载插件并删除其数据？',
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(context.l10n.text('common.cancel')),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(pluginText(context, 'Uninstall', '卸载')),
              ),
            ],
          ),
        );
        if (confirmed != true) return;
      }
      await controller.desktopPlugins.manage(plugin, action);
    } on Object catch (error) {
      if (context.mounted) {
        DesktopNoticeHost.show(
          context,
          message: error.toString(),
          isError: true,
        );
      }
    }
  }

  Future<void> _upload() async {
    if (_uploading) return;
    setState(() => _uploading = true);
    try {
      final file = await openFile(
        acceptedTypeGroups: const [
          XTypeGroup(label: 'ZIP', extensions: ['zip']),
        ],
      );
      if (file == null || !mounted) return;
      final plugins = controller.desktopPlugins;
      await plugins.api.uploadDesktopPlugin(file, plugins.clientId);
    } on Object catch (error) {
      if (mounted) {
        DesktopNoticeHost.show(
          context,
          message: error.toString(),
          isError: true,
        );
      }
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }
}

class _DesktopPluginLogo extends StatefulWidget {
  const _DesktopPluginLogo({
    required this.plugin,
    required this.plugins,
    super.key,
  });

  final DesktopPlugin plugin;
  final DesktopPlugins plugins;

  @override
  State<_DesktopPluginLogo> createState() => _DesktopPluginLogoState();
}

class _DesktopPluginLogoState extends State<_DesktopPluginLogo> {
  late final _logo = widget.plugin.data['logo'] is String
      ? widget.plugins.api.desktopPluginLogo(
          widget.plugin.id,
          widget.plugin.digest,
        )
      : null;

  @override
  Widget build(BuildContext context) {
    final title = widget.plugin.title.trim();
    final hue = widget.plugin.id.codeUnits.fold(
      0,
      (hue, unit) => (hue * 31 + unit) % 360,
    );
    final base = HSLColor.fromAHSL(1, hue.toDouble(), 0.52, 0.39);
    final fallback = DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            base.withLightness(0.45).toColor(),
            base.withLightness(0.29).toColor(),
          ],
        ),
      ),
      child: Center(
        child: Text(
          title.isEmpty ? '?' : title.characters.first.toUpperCase(),
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: Colors.white,
            fontSize: 29,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
    return SizedBox.square(
      dimension: _desktopPluginIconSize,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(_desktopPluginIconRadius),
        child: FutureBuilder(
          future: _logo,
          builder: (context, snapshot) {
            final bytes = snapshot.data;
            return bytes == null
                ? fallback
                : Image.memory(
                    bytes,
                    fit: BoxFit.cover,
                    cacheWidth: 216,
                    errorBuilder: (context, error, stackTrace) => fallback,
                  );
          },
        ),
      ),
    );
  }
}
