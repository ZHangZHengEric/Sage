import 'dart:collection';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../localization/app_localizations.dart';

/// Layout preferences declared by a workspace panel plugin.
///
/// The dock owns the actual layout. Plugins only describe the space in which
/// they work well, so adding a new panel does not add another layout branch to
/// the application shell.
@immutable
class WorkspacePanelSizing {
  const WorkspacePanelSizing({
    this.minWidthFraction = 0.34,
    this.preferredWidthFraction = 0.44,
    this.maxWidthFraction = 0.60,
    this.compactHeightFraction = 0.42,
    this.minCompactHeight = 240,
    this.maxCompactHeight = 430,
  }) : assert(minWidthFraction > 0),
       assert(minWidthFraction <= preferredWidthFraction),
       assert(preferredWidthFraction <= maxWidthFraction),
       assert(maxWidthFraction <= 1),
       assert(compactHeightFraction > 0),
       assert(compactHeightFraction <= 1),
       assert(minCompactHeight > 0),
       assert(minCompactHeight <= maxCompactHeight);

  final double minWidthFraction;
  final double preferredWidthFraction;
  final double maxWidthFraction;
  final double compactHeightFraction;
  final double minCompactHeight;
  final double maxCompactHeight;
}

/// Narrow, typed access to host-owned services.
///
/// A panel asks only for the services it needs. This keeps panel plugins from
/// depending on [WorkspaceScreen] while allowing existing features to migrate
/// incrementally from the current application controller.
@immutable
class WorkspacePanelServices {
  WorkspacePanelServices(Map<Type, Object> services)
    : _services = Map.unmodifiable(services);

  final Map<Type, Object> _services;

  T read<T extends Object>() {
    final value = _services[T];
    if (value is T) return value;
    throw StateError('Workspace panel service $T is not registered.');
  }

  T? maybeRead<T extends Object>() {
    final value = _services[T];
    return value is T ? value : null;
  }
}

@immutable
class WorkspacePanelSelection {
  const WorkspacePanelSelection({
    required this.agentId,
    required this.workspaceId,
    required this.workspaceName,
  });

  final String agentId;
  final String workspaceId;
  final String workspaceName;
}

/// Context supplied by the dock to every open panel instance.
@immutable
class WorkspacePanelContext {
  const WorkspacePanelContext({
    required this.services,
    required this.instanceId,
    required this.compact,
    required this.active,
  });

  final WorkspacePanelServices services;
  final String instanceId;
  final bool compact;
  final bool active;
}

/// A registered type of right-side workspace panel.
///
/// Plugin definitions are separate from open instances. A singleton plugin
/// such as the file workspace has one tab, while a future terminal plugin may
/// opt into multiple instances without changing the dock contract.
abstract interface class WorkspacePanelPlugin {
  String get id;
  IconData get icon;
  WorkspacePanelSizing get sizing;
  bool get initiallyOpen;
  bool get closable;
  bool get singleton;

  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  });

  bool supports(WorkspacePanelServices services);

  Widget build(BuildContext context, WorkspacePanelContext panelContext);
}

/// Convenience base class with conservative defaults for native panels.
abstract class WorkspacePanelPluginBase implements WorkspacePanelPlugin {
  const WorkspacePanelPluginBase();

  @override
  WorkspacePanelSizing get sizing => const WorkspacePanelSizing();

  @override
  bool get initiallyOpen => false;

  @override
  bool get closable => true;

  @override
  bool get singleton => true;

  @override
  bool supports(WorkspacePanelServices services) => true;
}

/// Ordered registry of all panel types known to the desktop client.
class WorkspacePanelRegistry {
  WorkspacePanelRegistry([Iterable<WorkspacePanelPlugin> plugins = const []]) {
    for (final plugin in plugins) {
      register(plugin);
    }
  }

  final LinkedHashMap<String, WorkspacePanelPlugin> _plugins = LinkedHashMap();

  List<WorkspacePanelPlugin> get plugins => List.unmodifiable(_plugins.values);

  WorkspacePanelPlugin? operator [](String id) => _plugins[id];

  void register(WorkspacePanelPlugin plugin) {
    final id = plugin.id.trim();
    if (id.isEmpty) {
      throw ArgumentError.value(plugin.id, 'plugin.id', 'must not be empty');
    }
    if (_plugins.containsKey(id)) {
      throw StateError('Workspace panel plugin "$id" is already registered.');
    }
    _plugins[id] = plugin;
  }
}

@immutable
class WorkspacePanelInstance {
  const WorkspacePanelInstance({
    required this.instanceId,
    required this.pluginId,
    required this.displayIndex,
  });

  final String instanceId;
  final String pluginId;
  final int displayIndex;

  WorkspacePanelInstance copyWith({int? displayIndex}) =>
      WorkspacePanelInstance(
        instanceId: instanceId,
        pluginId: pluginId,
        displayIndex: displayIndex ?? this.displayIndex,
      );
}

/// A UI-independent request to reveal or create a panel.
///
/// Runtime and tool adapters dispatch intents instead of importing panel
/// widgets. [payload] is reserved for plugin-specific navigation such as a file
/// path or process id.
@immutable
class WorkspacePanelIntent {
  const WorkspacePanelIntent({
    required this.pluginId,
    this.newInstance = false,
    this.activate = true,
    this.payload = const {},
  });

  final String pluginId;
  final bool newInstance;
  final bool activate;
  final Map<String, Object?> payload;
}

/// Mutable dock state and the programmatic API used by tool/event adapters.
///
/// For example, a terminal tool can call [open] when its first process starts,
/// without the chat controller knowing how the terminal panel is rendered.
class WorkspacePanelDockController extends ChangeNotifier {
  final List<WorkspacePanelInstance> _openInstances = [];
  Map<String, WorkspacePanelPlugin> _availablePlugins = const {};
  final Set<String> _knownPluginIds = {};
  final Map<String, int> _nextPluginInstanceSequence = {};
  String? _activeInstanceId;

  List<WorkspacePanelInstance> get openInstances =>
      List.unmodifiable(_openInstances);

  String? get activeInstanceId => _activeInstanceId;

  String? get activePluginId {
    final active = _instance(_activeInstanceId);
    return active?.pluginId;
  }

  WorkspacePanelPlugin? get activePlugin => _availablePlugins[activePluginId];

  void syncPlugins(Iterable<WorkspacePanelPlugin> plugins) {
    final available = <String, WorkspacePanelPlugin>{
      for (final plugin in plugins) plugin.id: plugin,
    };
    var changed = false;

    final removed = _openInstances
        .where((instance) => !available.containsKey(instance.pluginId))
        .toList();
    if (removed.isNotEmpty) {
      _openInstances.removeWhere(
        (instance) => !available.containsKey(instance.pluginId),
      );
      changed = true;
    }

    for (final plugin in available.values) {
      if (_knownPluginIds.add(plugin.id) && plugin.initiallyOpen) {
        _openInstances.add(
          WorkspacePanelInstance(
            instanceId: _newInstanceId(plugin.id),
            pluginId: plugin.id,
            displayIndex: _nextDisplayIndex(plugin.id),
          ),
        );
        changed = true;
      }
    }
    _availablePlugins = Map.unmodifiable(available);

    if (_openInstances.isEmpty && available.isNotEmpty) {
      final first = available.values.first;
      _openInstances.add(
        WorkspacePanelInstance(
          instanceId: _newInstanceId(first.id),
          pluginId: first.id,
          displayIndex: _nextDisplayIndex(first.id),
        ),
      );
      changed = true;
    }
    if (_instance(_activeInstanceId) == null && _openInstances.isNotEmpty) {
      _activeInstanceId = _openInstances.first.instanceId;
      changed = true;
    }
    if (changed) notifyListeners();
  }

  WorkspacePanelInstance? open(String pluginId, {bool activate = true}) {
    final plugin = _availablePlugins[pluginId];
    if (plugin == null) return null;
    if (plugin.singleton) {
      for (final instance in _openInstances) {
        if (instance.pluginId != pluginId) continue;
        if (activate) activateInstance(instance.instanceId);
        return instance;
      }
    }
    final instance = WorkspacePanelInstance(
      instanceId: _newInstanceId(pluginId),
      pluginId: pluginId,
      displayIndex: _nextDisplayIndex(pluginId),
    );
    _openInstances.add(instance);
    if (activate) _activeInstanceId = instance.instanceId;
    notifyListeners();
    return instance;
  }

  WorkspacePanelInstance? dispatch(WorkspacePanelIntent intent) {
    if (!intent.newInstance) {
      for (final instance in _openInstances) {
        if (instance.pluginId != intent.pluginId) continue;
        if (intent.activate) activateInstance(instance.instanceId);
        return instance;
      }
    }
    return open(intent.pluginId, activate: intent.activate);
  }

  void activateInstance(String instanceId) {
    if (_activeInstanceId == instanceId || _instance(instanceId) == null) {
      return;
    }
    _activeInstanceId = instanceId;
    notifyListeners();
  }

  void closeInstance(String instanceId) {
    final instance = _instance(instanceId);
    final plugin = instance == null
        ? null
        : _availablePlugins[instance.pluginId];
    if (instance == null || plugin == null || !plugin.closable) return;
    final index = _openInstances.indexOf(instance);
    _openInstances.remove(instance);
    _reindexPluginInstances(instance.pluginId);
    if (_activeInstanceId == instanceId) {
      if (_openInstances.isEmpty) {
        _activeInstanceId = null;
      } else {
        _activeInstanceId =
            _openInstances[index.clamp(0, _openInstances.length - 1)]
                .instanceId;
      }
    }
    notifyListeners();
  }

  WorkspacePanelInstance? _instance(String? instanceId) {
    if (instanceId == null) return null;
    for (final instance in _openInstances) {
      if (instance.instanceId == instanceId) return instance;
    }
    return null;
  }

  String _newInstanceId(String pluginId) {
    final sequence = (_nextPluginInstanceSequence[pluginId] ?? 0) + 1;
    _nextPluginInstanceSequence[pluginId] = sequence;
    return '$pluginId:$sequence';
  }

  int _nextDisplayIndex(String pluginId) =>
      _openInstances.where((instance) => instance.pluginId == pluginId).length +
      1;

  void _reindexPluginInstances(String pluginId) {
    var displayIndex = 0;
    for (var index = 0; index < _openInstances.length; index += 1) {
      final instance = _openInstances[index];
      if (instance.pluginId != pluginId) continue;
      displayIndex += 1;
      if (instance.displayIndex == displayIndex) continue;
      _openInstances[index] = instance.copyWith(displayIndex: displayIndex);
    }
  }
}

/// Generic right-side host. It adds no chrome while only one plugin is
/// available, so migrating the existing file workspace is visually neutral.
class WorkspacePanelDock extends StatefulWidget {
  const WorkspacePanelDock({
    required this.registry,
    required this.services,
    required this.controller,
    this.compact = false,
    super.key,
  });

  final WorkspacePanelRegistry registry;
  final WorkspacePanelServices services;
  final WorkspacePanelDockController controller;
  final bool compact;

  @override
  State<WorkspacePanelDock> createState() => _WorkspacePanelDockState();
}

class _WorkspacePanelDockState extends State<WorkspacePanelDock> {
  bool _syncScheduled = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onControllerChanged);
    _schedulePluginSync();
  }

  @override
  void didUpdateWidget(covariant WorkspacePanelDock oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_onControllerChanged);
      widget.controller.addListener(_onControllerChanged);
    }
    _schedulePluginSync();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    super.dispose();
  }

  void _schedulePluginSync() {
    if (_syncScheduled) return;
    _syncScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _syncScheduled = false;
      if (!mounted) return;
      widget.controller.syncPlugins(
        widget.registry.plugins.where(
          (plugin) => plugin.supports(widget.services),
        ),
      );
    });
  }

  void _onControllerChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final available = widget.registry.plugins
        .where((plugin) => plugin.supports(widget.services))
        .toList();
    final open = widget.controller.openInstances
        .where((instance) => widget.registry[instance.pluginId] != null)
        .toList();
    if (open.isEmpty) return const SizedBox.shrink();

    final closedPlugins = [
      for (final plugin in available)
        if (!plugin.singleton ||
            !open.any((instance) => instance.pluginId == plugin.id))
          plugin,
    ];
    final showTabs = open.length > 1 || closedPlugins.isNotEmpty;
    final activeInstanceId = widget.controller.activeInstanceId;
    final activeIndex = open.indexWhere(
      (instance) => instance.instanceId == activeInstanceId,
    );
    final selectedIndex = activeIndex < 0 ? 0 : activeIndex;

    final content = IndexedStack(
      key: const ValueKey('workspace-panel-stack'),
      index: selectedIndex,
      children: [
        for (var index = 0; index < open.length; index++)
          _WorkspacePanelInstanceHost(
            key: ValueKey(open[index].instanceId),
            plugin: widget.registry[open[index].pluginId]!,
            services: widget.services,
            instance: open[index],
            compact: widget.compact,
            active: index == selectedIndex,
          ),
      ],
    );
    if (!showTabs) return content;

    return Column(
      children: [
        _WorkspacePanelTabs(
          open: open,
          closedPlugins: closedPlugins,
          registry: widget.registry,
          services: widget.services,
          activeInstanceId: open[selectedIndex].instanceId,
          onActivate: widget.controller.activateInstance,
          onClose: widget.controller.closeInstance,
          onOpen: widget.controller.open,
        ),
        Expanded(child: content),
      ],
    );
  }
}

class _WorkspacePanelInstanceHost extends StatefulWidget {
  const _WorkspacePanelInstanceHost({
    required this.plugin,
    required this.services,
    required this.instance,
    required this.compact,
    required this.active,
    super.key,
  });

  final WorkspacePanelPlugin plugin;
  final WorkspacePanelServices services;
  final WorkspacePanelInstance instance;
  final bool compact;
  final bool active;

  @override
  State<_WorkspacePanelInstanceHost> createState() =>
      _WorkspacePanelInstanceHostState();
}

class _WorkspacePanelInstanceHostState
    extends State<_WorkspacePanelInstanceHost> {
  late bool _hasActivated = widget.active;

  @override
  void didUpdateWidget(covariant _WorkspacePanelInstanceHost oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active) _hasActivated = true;
  }

  @override
  Widget build(BuildContext context) {
    if (!_hasActivated) {
      return const SizedBox.expand(
        key: ValueKey('workspace-panel-lazy-placeholder'),
      );
    }
    return TickerMode(
      enabled: widget.active,
      child: widget.plugin.build(
        context,
        WorkspacePanelContext(
          services: widget.services,
          instanceId: widget.instance.instanceId,
          compact: widget.compact,
          active: widget.active,
        ),
      ),
    );
  }
}

class _WorkspacePanelTabs extends StatelessWidget {
  const _WorkspacePanelTabs({
    required this.open,
    required this.closedPlugins,
    required this.registry,
    required this.services,
    required this.activeInstanceId,
    required this.onActivate,
    required this.onClose,
    required this.onOpen,
  });

  final List<WorkspacePanelInstance> open;
  final List<WorkspacePanelPlugin> closedPlugins;
  final WorkspacePanelRegistry registry;
  final WorkspacePanelServices services;
  final String activeInstanceId;
  final ValueChanged<String> onActivate;
  final ValueChanged<String> onClose;
  final WorkspacePanelInstance? Function(String pluginId) onOpen;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.outlineVariant)),
      ),
      child: SizedBox(
        key: const ValueKey('workspace-panel-tabs'),
        height: 38,
        child: Row(
          children: [
            Expanded(
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.only(left: 8),
                itemCount: open.length,
                separatorBuilder: (_, _) => const SizedBox(width: 2),
                itemBuilder: (context, index) {
                  final instance = open[index];
                  final plugin = registry[instance.pluginId]!;
                  return _WorkspacePanelTab(
                    instance: instance,
                    plugin: plugin,
                    services: services,
                    active: instance.instanceId == activeInstanceId,
                    onActivate: () => onActivate(instance.instanceId),
                    onClose: plugin.closable
                        ? () => onClose(instance.instanceId)
                        : null,
                  );
                },
              ),
            ),
            if (closedPlugins.isNotEmpty)
              PopupMenuButton<String>(
                key: const ValueKey('workspace-panel-open-menu'),
                tooltip: context.l10n.text('common.add'),
                position: PopupMenuPosition.under,
                offset: const Offset(0, 2),
                color: colors.surface.withValues(alpha: 0.98),
                surfaceTintColor: Colors.transparent,
                shadowColor: Colors.black.withValues(alpha: 0.16),
                elevation: 3,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                  side: BorderSide(
                    color: colors.outlineVariant.withValues(alpha: 0.8),
                  ),
                ),
                constraints: const BoxConstraints(minWidth: 124, maxWidth: 220),
                menuPadding: const EdgeInsets.all(4),
                icon: const Icon(CupertinoIcons.plus, size: 17),
                onSelected: onOpen,
                itemBuilder: (context) => [
                  for (final plugin in closedPlugins)
                    PopupMenuItem(
                      value: plugin.id,
                      height: 32,
                      padding: const EdgeInsets.symmetric(horizontal: 9),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            plugin.icon,
                            size: 14,
                            color: colors.onSurfaceVariant,
                          ),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              plugin.title(context, services),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.labelMedium
                                  ?.copyWith(
                                    color: colors.onSurface,
                                    fontWeight: FontWeight.w600,
                                  ),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            const SizedBox(width: 4),
          ],
        ),
      ),
    );
  }
}

class _WorkspacePanelTab extends StatelessWidget {
  const _WorkspacePanelTab({
    required this.instance,
    required this.plugin,
    required this.services,
    required this.active,
    required this.onActivate,
    this.onClose,
  });

  final WorkspacePanelInstance instance;
  final WorkspacePanelPlugin plugin;
  final WorkspacePanelServices services;
  final bool active;
  final VoidCallback onActivate;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return InkWell(
      key: ValueKey('workspace-panel-tab:${instance.instanceId}'),
      onTap: onActivate,
      borderRadius: BorderRadius.circular(7),
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: EdgeInsets.only(left: 9, right: onClose == null ? 10 : 4),
        decoration: BoxDecoration(
          color: active
              ? colors.onSurface.withValues(alpha: 0.09)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(7),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              plugin.icon,
              size: 14,
              color: active ? colors.onSurface : colors.onSurfaceVariant,
            ),
            const SizedBox(width: 6),
            Text(
              plugin.title(context, services, instance: instance),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                color: active ? colors.onSurface : colors.onSurfaceVariant,
              ),
            ),
            if (onClose != null) ...[
              const SizedBox(width: 3),
              IconButton(
                key: ValueKey('workspace-panel-close:${instance.instanceId}'),
                tooltip: context.l10n.text('common.close'),
                onPressed: onClose,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints.tightFor(
                  width: 24,
                  height: 24,
                ),
                icon: const Icon(CupertinoIcons.xmark, size: 11),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
