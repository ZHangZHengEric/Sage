import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';

import 'rsi_screen_test.dart' show RsiApi;

class SaveApi extends RsiApi {
  bool ready = true;
  bool approved = true;
  final requests = <(String, String, String, String)>[];
  Completer<AgentConfiguration>? save;

  @override
  Future<Map<String, Object?>> rsiVersion(
    String agentId,
    String versionId,
  ) async => {
    ...await super.rsiVersion(agentId, versionId),
    'ready': ready,
    'review': {'approved': approved},
  };

  @override
  Future<AgentConfiguration> saveRsiVersionAsAgent(
    String agentId,
    String versionId,
    String name,
    String requestId,
  ) {
    requests.add((agentId, versionId, name, requestId));
    return save!.future;
  }

  @override
  Future<List<AgentSummary>> listAgents() async => [
    ...await super.listAgents(),
    if (requests.length > 1)
      const AgentSummary(id: 'saved-agent', name: 'Specialist'),
  ];
}

void main() {
  setUpAll(() async {
    if (Platform.environment['RSI_SAVE_SCREENSHOT_DIR'] == null) return;
    final loader = FontLoader('SaveScreenshot')
      ..addFont(
        Future.value(
          ByteData.sublistView(
            await File(
              '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ).readAsBytes(),
          ),
        ),
      );
    await loader.load();
  });
  for (final brightness in Brightness.values) {
    testWidgets(
      'save RSI candidate as independent Agent in ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = SaveApi();
        final controller = WorkspaceController(api: api);
        addTearDown(controller.dispose);
        addTearDown(api.close);
        await tester.pumpWidget(
          RepaintBoundary(
            key: const ValueKey('save-capture'),
            child: MaterialApp(
              theme: ThemeData(
                brightness: brightness,
                fontFamily:
                    Platform.environment['RSI_SAVE_SCREENSHOT_DIR'] == null
                    ? null
                    : 'SaveScreenshot',
              ),
              home: Scaffold(
                body: RsiScreen(
                  controller: controller,
                  agentId: 'agent',
                  agentName: 'Sage',
                  historyOnly: true,
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final button = find.byKey(const ValueKey('rsi-save-as-agent'));
        await tester.ensureVisible(button);
        await tester.tap(button);
        await tester.pumpAndSettle();
        final field = find.byKey(const ValueKey('rsi-new-agent-name'));
        final screenshotDir = Platform.environment['RSI_SAVE_SCREENSHOT_DIR'];
        if (screenshotDir != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('save-capture')),
          );
          await tester.runAsync(() async {
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$screenshotDir/save-agent-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        await tester.enterText(field, '  ');
        await tester.tap(find.byKey(const ValueKey('rsi-save-agent-confirm')));
        await tester.pumpAndSettle();
        expect(find.text('请输入名称'), findsOneWidget);
        expect(api.requests, isEmpty);
        await tester.enterText(field, 'Specialist');
        api.save = Completer<AgentConfiguration>();
        await tester.tap(find.byKey(const ValueKey('rsi-save-agent-confirm')));
        await tester.pump();
        await tester.tap(
          find.byKey(const ValueKey('rsi-save-agent-confirm')),
          warnIfMissed: false,
        );
        await tester.pump();
        expect(api.requests, hasLength(1));
        api.save!.completeError(StateError('Temporary save failure'));
        await tester.pumpAndSettle();
        expect(find.textContaining('Temporary save failure'), findsOneWidget);
        api.save = Completer<AgentConfiguration>();
        await tester.tap(find.byKey(const ValueKey('rsi-save-agent-confirm')));
        await tester.pump();
        expect(api.requests, hasLength(2));
        expect(api.requests[0], api.requests[1]);
        expect(api.requests.first.$1, 'agent');
        expect(api.requests.first.$2, 'version-1');
        api.save!.complete(
          AgentConfiguration.fromJson({
            'id': 'saved-agent',
            'name': 'Specialist',
          }),
        );
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('rsi-new-agent-name')), findsNothing);
        expect(find.text('已保存为 Specialist'), findsOneWidget);
        expect(
          controller.agents.map((agent) => agent.id),
          contains('saved-agent'),
        );
        expect(api.applications, 0);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }

  for (final rejected in [false, true]) {
    testWidgets(
      'cannot save ${rejected ? 'rejected' : 'unfinished'} candidate',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = SaveApi()
          ..ready = rejected
          ..approved = !rejected;
        final controller = WorkspaceController(api: api);
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: RsiScreen(
                controller: controller,
                agentId: 'agent',
                agentName: 'Sage',
                historyOnly: true,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final button = find.byKey(const ValueKey('rsi-save-as-agent'));
        await tester.ensureVisible(button);
        await tester.tap(button, warnIfMissed: false);
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('rsi-new-agent-name')), findsNothing);
        expect(api.requests, isEmpty);
        await tester.pumpWidget(const SizedBox.shrink());
        controller.dispose();
        api.close();
      },
    );
  }
}
