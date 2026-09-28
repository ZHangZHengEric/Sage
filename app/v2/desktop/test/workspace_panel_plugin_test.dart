import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:sage_desktop_v2/src/localization/app_localizations.dart';
import 'package:sage_desktop_v2/src/ui/workspace_panels/workspace_panel_plugin.dart';

void main() {
  test('workspace panel registry rejects duplicate plugin ids', () {
    expect(
      () => WorkspacePanelRegistry([
        const _TestPanelPlugin(id: 'files', label: 'Files'),
        const _TestPanelPlugin(id: 'files', label: 'Other files'),
      ]),
      throwsStateError,
    );
  });

  test('dock controller separates plugin types from open instances', () {
    const files = _TestPanelPlugin(
      id: 'files',
      label: 'Files',
      initiallyOpen: true,
      closable: false,
    );
    const terminal = _TestPanelPlugin(
      id: 'terminal',
      label: 'Terminal',
      singleton: false,
    );
    final controller = WorkspacePanelDockController();
    addTearDown(controller.dispose);
    controller.syncPlugins(const [files, terminal]);

    final firstTerminal = controller.open('terminal');
    final secondTerminal = controller.open('terminal');

    expect(controller.openInstances, hasLength(3));
    expect(firstTerminal?.pluginId, 'terminal');
    expect(secondTerminal?.pluginId, 'terminal');
    expect(firstTerminal?.instanceId, isNot(secondTerminal?.instanceId));
  });

  test('terminal display indices follow currently open instances', () {
    const files = _TestPanelPlugin(
      id: 'files',
      label: 'Files',
      initiallyOpen: true,
      closable: false,
    );
    const terminal = _TestPanelPlugin(
      id: 'terminal',
      label: 'Terminal',
      singleton: false,
    );
    final controller = WorkspacePanelDockController();
    addTearDown(controller.dispose);
    controller.syncPlugins(const [files, terminal]);

    final first = controller.open('terminal')!;
    final second = controller.open('terminal')!;
    expect(first.displayIndex, 1);
    expect(second.displayIndex, 2);

    controller.closeInstance(first.instanceId);
    final remaining = controller.openInstances.singleWhere(
      (instance) => instance.pluginId == 'terminal',
    );
    expect(remaining.instanceId, second.instanceId);
    expect(remaining.displayIndex, 1);

    final replacement = controller.open('terminal')!;
    expect(replacement.displayIndex, 2);
    expect(replacement.instanceId, isNot(first.instanceId));
  });

  test(
    'panel intents focus an existing instance unless a new one is asked for',
    () {
      const terminal = _TestPanelPlugin(
        id: 'terminal',
        label: 'Terminal',
        initiallyOpen: true,
        singleton: false,
      );
      final controller = WorkspacePanelDockController();
      addTearDown(controller.dispose);
      controller.syncPlugins(const [terminal]);

      final first = controller.openInstances.single;
      final focused = controller.dispatch(
        const WorkspacePanelIntent(pluginId: 'terminal'),
      );
      final second = controller.dispatch(
        const WorkspacePanelIntent(pluginId: 'terminal', newInstance: true),
      );

      expect(focused?.instanceId, first.instanceId);
      expect(second?.instanceId, isNot(first.instanceId));
      expect(controller.openInstances, hasLength(2));
      expect(controller.activeInstanceId, second?.instanceId);
    },
  );

  testWidgets('single available panel adds no dock chrome', (tester) async {
    final controller = WorkspacePanelDockController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      _PanelTestApp(
        controller: controller,
        plugins: const [
          _TestPanelPlugin(
            id: 'files',
            label: 'Files',
            initiallyOpen: true,
            closable: false,
          ),
        ],
      ),
    );
    await tester.pump();

    expect(find.byKey(const ValueKey('workspace-panel-tabs')), findsNothing);
    expect(find.text('files-count:0'), findsOneWidget);
  });

  testWidgets('tabs switch panel types and preserve panel state', (
    tester,
  ) async {
    final controller = WorkspacePanelDockController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      _PanelTestApp(
        controller: controller,
        plugins: const [
          _TestPanelPlugin(
            id: 'files',
            label: 'Files',
            initiallyOpen: true,
            closable: false,
          ),
          _TestPanelPlugin(
            id: 'terminal',
            label: 'Terminal',
            initiallyOpen: true,
          ),
        ],
      ),
    );
    await tester.pump();

    expect(find.byKey(const ValueKey('workspace-panel-tabs')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('increment:files')));
    await tester.pump();
    expect(find.text('files-count:1'), findsOneWidget);

    final terminalInstance = controller.openInstances.singleWhere(
      (instance) => instance.pluginId == 'terminal',
    );
    await tester.tap(
      find.byKey(
        ValueKey('workspace-panel-tab:${terminalInstance.instanceId}'),
      ),
    );
    await tester.pump();
    expect(find.text('terminal-count:0'), findsOneWidget);

    final filesInstance = controller.openInstances.singleWhere(
      (instance) => instance.pluginId == 'files',
    );
    await tester.tap(
      find.byKey(ValueKey('workspace-panel-tab:${filesInstance.instanceId}')),
    );
    await tester.pump();
    expect(find.text('files-count:1'), findsOneWidget);
  });

  testWidgets(
    'inactive panels are built lazily and retained after activation',
    (tester) async {
      final controller = WorkspacePanelDockController();
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        _PanelTestApp(
          controller: controller,
          plugins: const [
            _TestPanelPlugin(
              id: 'files',
              label: 'Files',
              initiallyOpen: true,
              closable: false,
            ),
            _TestPanelPlugin(
              id: 'terminal',
              label: 'Terminal',
              initiallyOpen: true,
            ),
          ],
        ),
      );
      await tester.pump();

      expect(find.text('files-count:0'), findsOneWidget);
      expect(find.text('terminal-count:0'), findsNothing);

      final terminal = controller.openInstances.singleWhere(
        (instance) => instance.pluginId == 'terminal',
      );
      controller.activateInstance(terminal.instanceId);
      await tester.pump();
      expect(find.text('terminal-count:0'), findsOneWidget);

      final files = controller.openInstances.singleWhere(
        (instance) => instance.pluginId == 'files',
      );
      controller.activateInstance(files.instanceId);
      await tester.pump();
      expect(
        find.text('terminal-count:0', skipOffstage: false),
        findsOneWidget,
      );
    },
  );

  testWidgets('a closed panel can be opened programmatically', (tester) async {
    final controller = WorkspacePanelDockController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      _PanelTestApp(
        controller: controller,
        compact: true,
        plugins: const [
          _TestPanelPlugin(
            id: 'files',
            label: 'Files',
            initiallyOpen: true,
            closable: false,
          ),
          _TestPanelPlugin(id: 'monitor', label: 'Monitor'),
        ],
      ),
    );
    await tester.pump();

    expect(
      find.byKey(const ValueKey('workspace-panel-open-menu')),
      findsOneWidget,
    );
    expect(controller.open('monitor'), isNotNull);
    await tester.pump();

    expect(find.text('monitor-count:0'), findsOneWidget);
    expect(find.text('monitor-compact:true'), findsOneWidget);
  });

  testWidgets('panel picker uses compact workspace menu styling', (
    tester,
  ) async {
    final controller = WorkspacePanelDockController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      _PanelTestApp(
        controller: controller,
        plugins: const [
          _TestPanelPlugin(
            id: 'files',
            label: 'Files',
            initiallyOpen: true,
            closable: false,
          ),
          _TestPanelPlugin(id: 'terminal', label: 'Terminal'),
        ],
      ),
    );
    await tester.pump();

    final button = tester.widget<PopupMenuButton<String>>(
      find.byKey(const ValueKey('workspace-panel-open-menu')),
    );
    expect(button.position, PopupMenuPosition.under);
    expect(button.elevation, 3);
    expect(button.surfaceTintColor, Colors.transparent);
    expect(button.menuPadding, const EdgeInsets.all(4));
    expect(button.constraints?.minWidth, 124);

    await tester.tap(find.byKey(const ValueKey('workspace-panel-open-menu')));
    await tester.pumpAndSettle();

    final item = tester.widget<PopupMenuItem<String>>(
      find.widgetWithText(PopupMenuItem<String>, 'Terminal'),
    );
    expect(item.height, 32);
    expect(item.padding, const EdgeInsets.symmetric(horizontal: 9));
  });
}

class _PanelTestApp extends StatelessWidget {
  const _PanelTestApp({
    required this.controller,
    required this.plugins,
    this.compact = false,
  });

  final WorkspacePanelDockController controller;
  final List<WorkspacePanelPlugin> plugins;
  final bool compact;

  @override
  Widget build(BuildContext context) => MaterialApp(
    locale: const Locale('en'),
    localizationsDelegates: const [
      SageLocalizations.delegate,
      ...GlobalMaterialLocalizations.delegates,
    ],
    supportedLocales: SageLocalizations.supportedLocales,
    home: Scaffold(
      body: SizedBox(
        width: 640,
        height: 480,
        child: WorkspacePanelDock(
          registry: WorkspacePanelRegistry(plugins),
          services: WorkspacePanelServices(const {}),
          controller: controller,
          compact: compact,
        ),
      ),
    ),
  );
}

class _TestPanelPlugin extends WorkspacePanelPluginBase {
  const _TestPanelPlugin({
    required this.id,
    required this.label,
    this.initiallyOpen = false,
    this.closable = true,
    this.singleton = true,
  });

  @override
  final String id;
  final String label;

  @override
  final bool initiallyOpen;

  @override
  final bool closable;

  @override
  final bool singleton;

  @override
  IconData get icon => CupertinoIcons.square_grid_2x2;

  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => label;

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) =>
      _StatefulPanel(pluginId: id, compact: panelContext.compact);
}

class _StatefulPanel extends StatefulWidget {
  const _StatefulPanel({required this.pluginId, required this.compact});

  final String pluginId;
  final bool compact;

  @override
  State<_StatefulPanel> createState() => _StatefulPanelState();
}

class _StatefulPanelState extends State<_StatefulPanel> {
  var count = 0;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text('${widget.pluginId}-count:$count'),
      Text('${widget.pluginId}-compact:${widget.compact}'),
      TextButton(
        key: ValueKey('increment:${widget.pluginId}'),
        onPressed: () => setState(() => count += 1),
        child: const Text('Increment'),
      ),
    ],
  );
}
