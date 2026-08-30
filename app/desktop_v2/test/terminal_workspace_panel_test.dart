import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/localization/app_localizations.dart';
import 'package:sage_desktop_v2/src/services/terminal_service.dart';
import 'package:sage_desktop_v2/src/ui/workspace_panels/terminal/terminal_workspace_panel_plugin.dart';
import 'package:sage_desktop_v2/src/ui/workspace_panels/workspace_panel_plugin.dart';

void main() {
  testWidgets('terminal panel connects input, resize, exit, and disposal', (
    tester,
  ) async {
    final api = _FakeTerminalApi();
    final controller = WorkspacePanelDockController();
    addTearDown(api.dispose);
    addTearDown(controller.dispose);

    await tester.pumpWidget(_TerminalTestApp(api: api, controller: controller));
    await tester.pump();
    await tester.pump();

    expect(api.createCalls, 1);
    expect(api.lastAgentId, 'agent-1');
    expect(api.lastWorkspaceId, 'project-1');
    expect(find.byType(TerminalView), findsOneWidget);

    final view = tester.widget<TerminalView>(find.byType(TerminalView));
    view.terminal.onOutput?.call('pwd\r');
    await tester.pump();
    expect(api.writes, ['pwd\r']);

    view.terminal.onResize?.call(132, 42, 1000, 600);
    await tester.pump(const Duration(milliseconds: 130));
    expect(api.resizes, [(132, 42)]);

    api.events.add({
      'type': 'terminal.output',
      'session_id': 'terminal-1',
      'sequence': 1,
      'data': base64Encode(utf8.encode('ready\r\n')),
    });
    api.events.add({
      'type': 'terminal.exited',
      'session_id': 'terminal-1',
      'sequence': 2,
      'exit_code': 0,
    });
    await tester.pump();
    expect(find.text('Completed'), findsOneWidget);

    controller.closeInstance(controller.openInstances.single.instanceId);
    await tester.pump();
    expect(api.closed, ['terminal-1']);
  });
}

class _TerminalTestApp extends StatelessWidget {
  const _TerminalTestApp({required this.api, required this.controller});

  final _FakeTerminalApi api;
  final WorkspacePanelDockController controller;

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
        width: 720,
        height: 520,
        child: WorkspacePanelDock(
          registry: WorkspacePanelRegistry(const [
            TerminalWorkspacePanelPlugin(),
          ]),
          services: WorkspacePanelServices({
            TerminalService: TerminalService(api),
            WorkspacePanelSelection: const WorkspacePanelSelection(
              agentId: 'agent-1',
              workspaceId: 'project-1',
              workspaceName: 'Project One',
            ),
          }),
          controller: controller,
        ),
      ),
    ),
  );
}

class _FakeTerminalApi extends V2ApiClient {
  _FakeTerminalApi() : super(baseUri: Uri.parse('http://127.0.0.1:1'));

  final events = StreamController<Map<String, Object?>>.broadcast(sync: true);
  final writes = <String>[];
  final resizes = <(int, int)>[];
  final closed = <String>[];
  var createCalls = 0;
  String? lastAgentId;
  String? lastWorkspaceId;

  @override
  Future<Map<String, Object?>> createTerminal({
    required String agentId,
    String workspaceId = '',
    int columns = 100,
    int rows = 30,
  }) async {
    createCalls += 1;
    lastAgentId = agentId;
    lastWorkspaceId = workspaceId;
    return {
      'session_id': 'terminal-1',
      'pid': 42,
      'cwd': '/workspace/project-one',
      'shell': '/bin/zsh',
      'columns': columns,
      'rows': rows,
      'sequence': 0,
      'running': true,
    };
  }

  @override
  Stream<Map<String, Object?>> terminalEvents(
    String sessionId, {
    int afterSequence = 0,
  }) => events.stream;

  @override
  Future<void> writeTerminal(String sessionId, String data) async {
    writes.add(data);
  }

  @override
  Future<void> resizeTerminal(
    String sessionId, {
    required int columns,
    required int rows,
  }) async {
    resizes.add((columns, rows));
  }

  @override
  Future<void> closeTerminal(String sessionId) async {
    closed.add(sessionId);
  }

  Future<void> dispose() async {
    await events.close();
    close();
  }
}
