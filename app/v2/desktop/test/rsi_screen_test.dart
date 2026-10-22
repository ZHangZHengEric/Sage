import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'dart:io';
import 'package:flutter/services.dart';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';

class RsiApi extends V2ApiClient {
  int applications = 0;
  bool running = false;
  bool suiteBlocked = false;
  bool manualHistory = false;
  Map<String, Object?>? startOptions;
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async => {
    'current_fingerprint': 'a' * 64,
    'runs': [
      {
        'id': 'run-1',
        'goal': '提升工具使用准确性',
        'status': running ? 'running' : 'completed',
        'rounds': 3,
        'iteration': running ? 1 : 3,
        'created_at': '2026-10-12 10:00',
      },
    ],
    'versions': [
      if (manualHistory)
        {
          'id': 'unapplied-candidate',
          'source': 'rsi',
          'iteration': 2,
          'created_at': '2026-10-12 10:20',
        },
      {
        'id': 'version-1',
        'source': manualHistory ? 'settings' : 'rsi',
        'run_id': 'run-1',
        'iteration': 1,
        'created_at': '2026-10-12 10:10',
      },
    ],
  };
  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String runId, {
    int afterSequence = 0,
  }) async => {
    'id': runId,
    'status': suiteBlocked
        ? 'failed'
        : running
        ? 'running'
        : 'completed',
    if (suiteBlocked)
      'suite_review': {
        'approved': false,
        'rationale': 'Rubric conflicts with the authorized goal',
        'issues': [
          {
            'severity': 'blocking',
            'case_ids': ['final-negative'],
            'rationale': 'Negative quantity must not be ready',
            'suggested_fix': 'Align the rubric with the review policy',
          },
        ],
      },
    'iteration': running ? 1 : 3,
    'rounds': 3,
    'stage': 'round_completed',
    'events': afterSequence == 0
        ? [
            {'sequence': 1, 'event': 'round_completed', 'time': '10:10'},
          ]
        : [],
    'iterations': [
      {
        'iteration': 1,
        'reason': '可复用的验证步骤',
        'review': {'approved': true, 'rationale': '保留原始目标'},
        'evaluation': {'cases': []},
      },
    ],
  };
  @override
  Future<Map<String, Object?>> rsiVersion(
    String agentId,
    String versionId,
  ) async => {
    'id': versionId,
    'source': manualHistory ? 'settings' : 'rsi',
    'name': 'Sage',
    'config': {
      'description': '人工保存的配置',
      'systemContext': {'department': 'finance'},
      'agentMode': 'simple',
    },
    'iteration': 1,
    'created_at': '2026-10-12 10:10',
    'review': {'approved': true, 'rationale': '可复用方法，无背题'},
    'package': {
      'manifest': {
        'agents': {
          agentId: {
            'instructions': {'inline': '保持用户目标，验证工具结果。'},
            'tools': ['file_read'],
            'skills': ['verification'],
            'budgets': {'max_steps': 48},
          },
        },
      },
      'files': {'skills/verification/SKILL.md': '验证结果后再交付。'},
    },
  };
  @override
  Future<void> applyRsiVersion(
    String agentId,
    String versionId,
    String fingerprint,
  ) async {
    applications++;
  }

  @override
  Future<List<AgentSummary>> listAgents() async => [
    AgentSummary(
      id: 'agent',
      name: 'Sage',
      rsiStatus: running ? 'running' : null,
    ),
  ];
  @override
  Future<List<SkillSummary>> listSkills(String agentId) async => [];
  @override
  Future<AgentConfiguration> getAgentConfiguration(String agentId) async =>
      AgentConfiguration.fromJson({'id': agentId, 'name': 'Sage'});
  @override
  Future<List<ToolSummary>> listTools() async => [];
  @override
  Future<List<SkillSummary>> listSkillCatalog() async => [];
  @override
  Future<List<ModelProviderSummary>> listModelProviders() async => [];
  @override
  Future<List<McpConnectionSummary>> listMcpConnections() async => [];
  @override
  Future<List<ComponentSummary>> listComponents() async => [];
  @override
  Future<Map<String, Object?>> startRsi(
    String agentId,
    Map<String, Object?> body,
  ) async {
    startOptions = body;
    return {'id': 'new'};
  }
}

void main() {
  setUpAll(() async {
    if (Platform.environment['RSI_SCREENSHOT_DIR'] != null) {
      final loader = FontLoader('SageScreenshot')
        ..addFont(
          File(
            '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
          ).readAsBytes().then((b) => ByteData.sublistView(b)),
        );
      await loader.load();
      final icons = FontLoader('packages/cupertino_icons/CupertinoIcons')
        ..addFont(
          rootBundle.load('packages/cupertino_icons/assets/CupertinoIcons.ttf'),
        );
      await icons.load();
    }
  });
  for (final brightness in Brightness.values) {
    testWidgets(
      'RSI ${brightness.name}: explicit confirmation and version history',
      (tester) async {
        final api = RsiApi();
        final controller = WorkspaceController(api: api);
        tester.view.physicalSize = const Size(1440, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(
              brightness: brightness,
              fontFamily: Platform.environment['RSI_SCREENSHOT_DIR'] == null
                  ? null
                  : 'SageScreenshot',
              colorScheme: ColorScheme.fromSeed(
                seedColor: const Color(0xFF0A84FF),
                brightness: brightness,
                surface: brightness == Brightness.dark
                    ? Colors.black
                    : Colors.white,
              ),
            ),
            home: RepaintBoundary(
              key: const ValueKey('capture'),
              child: RsiScreen(
                controller: controller,
                agentId: 'agent',
                agentName: 'Sage',
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('所有版本'), findsNothing);
        expect(find.byType(GlassSegmentedControl), findsNothing);
        expect(find.textContaining('已完成'), findsWidgets);
        final screenshotDir = Platform.environment['RSI_SCREENSHOT_DIR'];
        if (screenshotDir != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('capture')),
          );
          await tester.runAsync(() async {
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$screenshotDir/rsi-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        await tester.ensureVisible(find.text('迭代 1'));
        await tester.tap(find.text('迭代 1'));
        await tester.pumpAndSettle();
        await Scrollable.ensureVisible(
          tester.element(find.byKey(const ValueKey('rsi-open-iteration-1'))),
          alignment: .5,
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('rsi-open-iteration-1')));
        await tester.pumpAndSettle();
        expect(find.text('对话矩阵'), findsNothing);
        expect(find.text('版本历史 · Sage'), findsOneWidget);
        await tester.ensureVisible(
          find.byKey(const ValueKey('rsi-apply-version')),
        );
        await tester.tap(find.byKey(const ValueKey('rsi-apply-version')));
        await tester.pumpAndSettle();
        expect(api.applications, 0);
        await tester.tap(find.text('取消'));
        await tester.pumpAndSettle();
        expect(api.applications, 0);
        await tester.tap(find.byKey(const ValueKey('rsi-apply-version')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('rsi-confirm-apply')));
        await tester.pumpAndSettle();
        expect(api.applications, 1);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
        controller.dispose();
        api.close();
      },
    );
  }
  testWidgets('RSI rounds and skill-only scope are sent to background API', (
    tester,
  ) async {
    final api = RsiApi();
    final controller = WorkspaceController(api: api);
    await tester.pumpWidget(
      MaterialApp(
        home: RsiScreen(
          controller: controller,
          agentId: 'agent',
          agentName: 'Sage',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('rsi-goal')),
      'Improve skill reuse',
    );
    expect(
      tester
          .widget<GlassTextField>(find.byKey(const ValueKey('rsi-rounds')))
          .controller
          ?.text,
      '8',
    );
    await tester.enterText(find.byKey(const ValueKey('rsi-rounds')), '7');
    await tester.tap(find.byKey(const ValueKey('rsi-part-instructions')));
    await tester.ensureVisible(find.byKey(const ValueKey('rsi-start')));
    await tester.tap(find.byKey(const ValueKey('rsi-start')));
    await tester.pumpAndSettle();
    expect(api.startOptions!['rounds'], 7);
    expect(api.startOptions!['validation_case_count'], 24);
    expect(api.startOptions!['max_concurrency'], 3);
    expect(api.startOptions!['optimization_scope'], ['skills']);
    expect(api.applications, 0);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    api.close();
  });
  testWidgets(
    'manual save history uses the settings frame and previews complete configuration',
    (tester) async {
      final api = RsiApi()..manualHistory = true;
      final controller = WorkspaceController(api: api);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: RsiScreen(
              controller: controller,
              agentId: 'agent',
              agentName: 'Sage',
              historyOnly: true,
              frameBuilder: (title, action, body) => ColoredBox(
                color: Colors.black,
                child: Column(
                  children: [
                    Text(title),
                    Expanded(child: body),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('rsi-start')), findsNothing);
      expect(find.text('版本历史 · Sage'), findsOneWidget);
      expect(find.byKey(const ValueKey('rsi-run-run-1')), findsNothing);
      expect(
        find.byKey(const ValueKey('rsi-version-unapplied-candidate')),
        findsOneWidget,
      );
      expect(find.byType(GlassSegmentedControl), findsNothing);
      await tester.tap(find.textContaining('配置保存 ·'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const ValueKey('rsi-saved-configuration')),
      );
      await tester.tap(find.text('保存的配置'));
      await tester.pumpAndSettle();
      expect(find.text('人工保存的配置'), findsOneWidget);
      expect(find.text('department: finance'), findsOneWidget);
      expect(api.applications, 0);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
      api.close();
    },
  );

  testWidgets('Active RSI fits a narrow window and disables another start', (
    tester,
  ) async {
    final api = RsiApi()..running = true;
    final controller = WorkspaceController(api: api);
    tester.view.physicalSize = const Size(375, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: RsiScreen(
          controller: controller,
          agentId: 'agent',
          agentName: 'Sage',
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(
      tester
          .widget<Semantics>(find.byKey(const ValueKey('rsi-start')))
          .properties
          .enabled,
      isFalse,
    );
    expect(find.textContaining('进化中'), findsWidgets);
    expect(find.byKey(const ValueKey('rsi-run-run-1')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('rsi-toggle-history')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byKey(const ValueKey('rsi-run-run-1')), findsOneWidget);
    expect(find.text('取消优化'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    api.close();
  });
  testWidgets('Blocked suite review shows concrete issues before activation', (
    tester,
  ) async {
    final api = RsiApi()..suiteBlocked = true;
    final controller = WorkspaceController(api: api);
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: RsiScreen(
          controller: controller,
          agentId: 'agent',
          agentName: 'Sage',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('rsi-suite-review')), findsOneWidget);
    expect(find.text('Negative quantity must not be ready'), findsOneWidget);
    expect(
      find.text('Align the rubric with the review policy'),
      findsOneWidget,
    );
    expect(api.applications, 0);
    await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('rsi-goal')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('rsi-suite-review')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.byKey(const ValueKey('rsi-suite-review')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    api.close();
  });
}
