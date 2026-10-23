import 'dart:async';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'dart:io';
import 'package:flutter/services.dart';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/api/v2_api.dart';
import 'package:sage_desktop_v2/src/models.dart';
import 'package:sage_desktop_v2/src/state/workspace_controller.dart';
import 'package:sage_desktop_v2/src/ui/rsi_screen.dart';

class RsiApi extends V2ApiClient {
  int applications = 0;
  bool running = false;
  bool interrupted = false;
  bool externalHost = false;
  int resumes = 0;
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
        'status': interrupted
            ? 'interrupted'
            : running
            ? 'running'
            : 'completed',
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
    'workspace_path': '/tmp/sage-rsi/$runId/workspace',
    'resumable': interrupted,
    'external_host': externalHost,
    'status': interrupted
        ? 'interrupted'
        : suiteBlocked
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
            'instructions': {'path': 'prompts/system.md'},
            'tools': ['file_read'],
            'skills': ['verification'],
            'budgets': {'max_steps': 48},
          },
        },
      },
      'files': {
        'prompts/system.md': '保持用户目标，验证工具结果。',
        'skills/verification/SKILL.md': '验证结果后再交付。',
      },
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
  Future<Map<String, Object?>> resumeRsi(String agentId, String runId) async {
    resumes++;
    interrupted = false;
    running = true;
    return {'id': runId, 'status': 'running'};
  }

  @override
  Future<Map<String, Object?>> startRsi(
    String agentId,
    Map<String, Object?> body,
  ) async {
    startOptions = body;
    return {'id': 'new'};
  }
}

class PendingCancelApi extends RsiApi {
  int cancellations = 0;
  final cancelled = Completer<void>();

  @override
  Future<void> cancelRsi(String agentId, String runId) async {
    cancellations++;
    await cancelled.future;
    running = false;
  }
}

class DelayedHistoryApi extends RsiApi {
  bool delay = false;
  final pending = <String, Completer<Map<String, Object?>>>{};
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async => {
    ...await super.rsiHistory(agentId),
    'runs': [
      for (final id in ['run-1', 'run-2', 'run-3'])
        {
          'id': id,
          'goal': id,
          'status': 'completed',
          'rounds': 3,
          'iteration': 3,
          'created_at': '2026-10-22 10:00',
        },
    ],
  };
  Future<Map<String, Object?>> detail(String id) => super.rsiRun('agent', id);
  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String runId, {
    int afterSequence = 0,
  }) {
    if (delay)
      return (pending[runId] ??= Completer<Map<String, Object?>>()).future;
    return super.rsiRun(agentId, runId, afterSequence: afterSequence);
  }
}

class GroupedVersionsApi extends RsiApi {
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) async => {
    'runs': [
      {'id': 'new-run', 'created_at': '2026-10-22 10:27'},
      {'id': 'old-run', 'created_at': '2026-10-22 09:33'},
    ],
    'versions': [
      {
        'id': 'new-baseline',
        'run_id': 'new-run',
        'source': 'rsi',
        'iteration': 0,
        'created_at': '2026-10-22 10:27',
      },
      {
        'id': 'old-iteration',
        'run_id': 'old-run',
        'source': 'rsi',
        'iteration': 1,
        'created_at': '2026-10-22 09:40',
      },
      {
        'id': 'old-baseline',
        'run_id': 'old-run',
        'source': 'rsi',
        'iteration': 0,
        'created_at': '2026-10-22 09:33',
      },
    ],
  };

  @override
  Future<Map<String, Object?>> rsiVersion(
    String agentId,
    String versionId,
  ) async {
    final version = await super.rsiVersion(agentId, versionId);
    final package = (version['package'] as Map).cast<String, Object?>();
    final manifest = (package['manifest'] as Map).cast<String, Object?>();
    final agents = (manifest['agents'] as Map).cast<String, Object?>();
    return {
      ...version,
      'package': {
        ...package,
        'manifest': {
          ...manifest,
          'entrypoint': {'agent': 'archived-agent'},
          'agents': {'archived-agent': agents[agentId]},
        },
      },
      'id': versionId,
      'iteration': versionId.endsWith('baseline') ? 0 : 1,
    };
  }
}

class DelayedVersionsApi extends GroupedVersionsApi {
  final history = Completer<Map<String, Object?>>();
  final pending = <String, Completer<Map<String, Object?>>>{};
  Future<Map<String, Object?>> historyData() => super.rsiHistory('agent');
  Future<Map<String, Object?>> detail(String id) =>
      super.rsiVersion('agent', id);
  @override
  Future<Map<String, Object?>> rsiHistory(String agentId) => history.future;
  @override
  Future<Map<String, Object?>> rsiVersion(String agentId, String versionId) =>
      (pending[versionId] ??= Completer<Map<String, Object?>>()).future;
}

class RunningConfigurationApi extends RsiApi {
  RunningConfigurationApi() {
    running = true;
  }
  @override
  Future<Map<String, Object?>> rsiRun(
    String agentId,
    String runId, {
    int afterSequence = 0,
  }) async => {
    ...await super.rsiRun(agentId, runId, afterSequence: afterSequence),
    'goal': '本次运行保存的目标',
    'rounds': 2,
    'initial_training_case_count': 14,
    'training_cases_per_round': 4,
    'max_system_prompt_chars': 20000,
    'max_skill_chars': 15000,
    'max_skill_count': 2,
    'validation_case_count': 12,
    'human_test_count': 6,
    'optimization_scope': ['skills', 'tools'],
  };
}

void main() {
  for (final brightness in Brightness.values) {
    testWidgets('open current optimization folder ${brightness.name}', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1600, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = RsiApi();
      final controller = WorkspaceController(api: api);
      final opened = <String>[];
      addTearDown(() {
        controller.dispose();
        api.close();
      });
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: RsiScreen(
            controller: controller,
            agentId: 'agent',
            agentName: 'Sage',
            onOpenFolder: (path) async {
              opened.add(path);
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('rsi-open-folder')));
      await tester.pumpAndSettle();
      expect(opened, ['/tmp/sage-rsi/run-1']);
      expect(tester.takeException(), isNull);
    });
  }
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
  testWidgets(
    'history selection loads immediately during an older poll and ignores stale results',
    (tester) async {
      final api = DelayedHistoryApi();
      final controller = WorkspaceController(api: api);
      addTearDown(() {
        controller.dispose();
        api.close();
      });
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
      await tester.tap(find.byKey(const ValueKey('rsi-toggle-history')));
      await tester.pumpAndSettle();
      api.delay = true;
      await tester.pump(const Duration(seconds: 2));
      expect(api.pending.containsKey('run-1'), isTrue);
      await tester.tap(find.byKey(const ValueKey('rsi-run-run-2')));
      await tester.pump();
      expect(find.byKey(const ValueKey('rsi-run-loading')), findsOneWidget);
      expect(api.pending.containsKey('run-2'), isTrue);
      await tester.tap(find.byKey(const ValueKey('rsi-run-run-3')));
      await tester.pump();
      expect(api.pending.containsKey('run-3'), isTrue);
      api.pending['run-2']!.complete({
        ...await api.detail('run-2'),
        'status': 'failed',
      });
      api.pending['run-1']!.complete({
        ...await api.detail('run-1'),
        'status': 'cancelled',
      });
      await tester.pump();
      expect(find.byKey(const ValueKey('rsi-run-loading')), findsOneWidget);
      expect(find.text('进化失败'), findsNothing);
      api.pending['run-3']!.complete(await api.detail('run-3'));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('rsi-run-loading')), findsNothing);
      expect(find.text('进化完成'), findsOneWidget);
      expect(
        tester
            .widget<ListTile>(find.byKey(const ValueKey('rsi-run-run-3')))
            .selected,
        isTrue,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
  testWidgets(
    'version history loads its list and latest detail, and ignores stale errors',
    (tester) async {
      final api = DelayedVersionsApi();
      final controller = WorkspaceController(api: api);
      addTearDown(() {
        controller.dispose();
        api.close();
      });
      await tester.pumpWidget(
        MaterialApp(
          home: RsiScreen(
            controller: controller,
            agentId: 'agent',
            agentName: 'Sage',
            historyOnly: true,
          ),
        ),
      );
      await tester.pump();
      expect(find.byKey(const ValueKey('rsi-history-loading')), findsOneWidget);
      expect(find.byKey(const ValueKey('rsi-version-loading')), findsOneWidget);
      api.history.complete(await api.historyData());
      await tester.pump();
      expect(api.pending.containsKey('new-baseline'), isTrue);
      expect(
        tester
            .widget<ListTile>(
              find.byKey(const ValueKey('rsi-version-new-baseline')),
            )
            .selected,
        isTrue,
      );
      expect(find.byKey(const ValueKey('rsi-version-loading')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('rsi-version-old-iteration')));
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('rsi-version-old-baseline')));
      await tester.pump();
      expect(
        tester
            .widget<ListTile>(
              find.byKey(const ValueKey('rsi-version-old-baseline')),
            )
            .selected,
        isTrue,
      );
      api.pending['old-iteration']!.completeError(
        StateError('stale version error'),
      );
      api.pending['new-baseline']!.complete(await api.detail('new-baseline'));
      await tester.pump();
      expect(find.textContaining('stale version error'), findsNothing);
      expect(find.byKey(const ValueKey('rsi-version-loading')), findsOneWidget);
      api.pending['old-baseline']!.complete(await api.detail('old-baseline'));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('rsi-version-loading')), findsNothing);
      expect(find.text('file_read'), findsOneWidget);
      expect(
        tester
            .widget<ListTile>(
              find.byKey(const ValueKey('rsi-version-old-baseline')),
            )
            .selected,
        isTrue,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
  for (final brightness in Brightness.values) {
    testWidgets(
      'Version history ${brightness.name} groups baselines and resolves snapshot identity',
      (tester) async {
        final api = GroupedVersionsApi();
        final controller = WorkspaceController(api: api);
        addTearDown(() {
          controller.dispose();
          api.close();
        });
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
            ),
            home: RepaintBoundary(
              key: const ValueKey('version-capture'),
              child: RsiScreen(
                controller: controller,
                agentId: 'agent',
                agentName: 'Sage',
                historyOnly: true,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('进化 · 10-22 10:27'), findsOneWidget);
        expect(find.text('进化 · 10-22 09:33'), findsOneWidget);
        expect(find.text('基线'), findsNWidgets(3));
        expect(find.text('迭代 0'), findsNothing);
        expect(
          tester
              .getTopLeft(
                find.byKey(const ValueKey('rsi-version-old-baseline')),
              )
              .dy,
          greaterThan(
            tester
                .getTopLeft(
                  find.byKey(const ValueKey('rsi-version-old-iteration')),
                )
                .dy,
          ),
        );
        await tester.tap(
          find.byKey(const ValueKey('rsi-version-new-baseline')),
        );
        await tester.pumpAndSettle();
        expect(find.text('file_read'), findsOneWidget);
        expect(find.text('48'), findsOneWidget);
        expect(find.text('保持用户目标，验证工具结果。'), findsOneWidget);
        expect(find.textContaining('null'), findsNothing);
        expect(find.byKey(const ValueKey('rsi-apply-version')), findsNothing);
        expect(api.applications, 0);
        final dir = Platform.environment['RSI_SCREENSHOT_DIR'];
        if (dir != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('version-capture')),
          );
          await tester.runAsync(() async {
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$dir/version-history-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
    testWidgets(
      'RSI ${brightness.name}: resume action continues an interrupted run',
      (tester) async {
        final api = RsiApi()..interrupted = true;
        final controller = WorkspaceController(api: api);
        tester.view.physicalSize = const Size(1600, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(controller.dispose);
        addTearDown(api.close);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: RsiScreen(
              controller: controller,
              agentId: 'agent',
              agentName: 'Sage',
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('rsi-resume')), findsOneWidget);
        await tester.tap(find.byKey(const ValueKey('rsi-resume')));
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        expect(api.resumes, 1);
        expect(find.byKey(const ValueKey('rsi-resume')), findsNothing);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
    testWidgets(
      'RSI ${brightness.name} shares glass settings inside a different parent layer',
      (tester) async {
        final api = RsiApi();
        final controller = WorkspaceController(api: api);
        final messages = <String>[];
        final previous = debugPrint;
        debugPrint = (String? message, {int? wrapWidth}) {
          if (message != null) messages.add(message);
        };
        addTearDown(() {
          debugPrint = previous;
          controller.dispose();
          api.close();
        });
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: GlassScaffold(
              settings: const LiquidGlassSettings(blur: 20),
              body: RsiScreen(
                controller: controller,
                agentId: 'agent',
                agentName: 'Sage',
                frameBuilder: (title, actions, body) => Column(
                  children: [
                    actions,
                    Expanded(child: body),
                  ],
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.pump(const Duration(seconds: 4));
        await tester.pumpAndSettle();
        expect(
          messages.where(
            (m) =>
                m.contains('provided without') ||
                m.contains('per-widget settings are ignored'),
          ),
          isEmpty,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
        debugPrint = previous;
      },
    );
    testWidgets('RSI ${brightness.name}: read-only version history', (
      tester,
    ) async {
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
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
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
      expect(find.byKey(const ValueKey('rsi-apply-version')), findsNothing);
      expect(find.byKey(const ValueKey('rsi-confirm-apply')), findsNothing);
      expect(find.text('保持用户目标，验证工具结果。'), findsOneWidget);
      expect(find.text('file_read'), findsOneWidget);
      expect(find.text('48'), findsOneWidget);
      expect(find.textContaining('null'), findsNothing);
      expect(api.applications, 0);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
      api.close();
    });
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
    await tester.enterText(
      find.byKey(const ValueKey('rsi-initial-training-count')),
      '3',
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-training-increment')),
      '2',
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-system-prompt-limit')),
      '8000',
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-skill-length-limit')),
      '3000',
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-skill-count-limit')),
      '4',
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-edit-repair-limit')),
      '2',
    );
    expect(
      tester
          .widget<GlassTextField>(
            find.byKey(const ValueKey('rsi-evaluation-repeats')),
          )
          .controller
          ?.text,
      '1',
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-evaluation-repeats')),
      '0',
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('rsi-part-instructions')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('rsi-part-instructions')));
    await tester.ensureVisible(find.byKey(const ValueKey('rsi-start')));
    await tester.tap(find.byKey(const ValueKey('rsi-start')));
    await tester.pumpAndSettle();
    expect(api.startOptions, isNull);
    await tester.ensureVisible(
      find.byKey(const ValueKey('rsi-evaluation-repeats')),
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-evaluation-repeats')),
      '3',
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('rsi-human-test-repeats')),
    );
    await tester.enterText(
      find.byKey(const ValueKey('rsi-human-test-repeats')),
      '2',
    );
    await tester.ensureVisible(find.byKey(const ValueKey('rsi-start')));
    await tester.tap(find.byKey(const ValueKey('rsi-start')));
    await tester.pumpAndSettle();
    expect(api.startOptions!['rounds'], 7);
    expect(api.startOptions!['max_system_prompt_chars'], 8000);
    expect(api.startOptions!['max_skill_chars'], 3000);
    expect(api.startOptions!['max_skill_count'], 4);
    expect(api.startOptions!['max_edit_repairs'], 2);
    expect(api.startOptions!['initial_training_case_count'], 3);
    expect(api.startOptions!['training_cases_per_round'], 2);
    expect(api.startOptions!['validation_case_count'], 24);
    expect(api.startOptions!['max_concurrency'], 3);
    expect(api.startOptions!['evaluation_repeats'], 3);
    expect(api.startOptions!['human_test_repeats'], 2);
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
      await tester.tap(find.byKey(const ValueKey('rsi-version-version-1')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const ValueKey('rsi-saved-configuration')),
      );
      expect(find.text('人工保存的配置'), findsOneWidget);
      expect(find.text('department: finance'), findsOneWidget);
      expect(api.applications, 0);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
      api.close();
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'active configuration uses readable frozen values ${brightness.name}',
      (tester) async {
        final api = RunningConfigurationApi();
        final controller = WorkspaceController(api: api);
        tester.view.physicalSize = const Size(1440, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: RsiScreen(
              controller: controller,
              agentId: 'agent',
              agentName: 'Sage',
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        await tester.tap(find.byKey(const ValueKey('rsi-toggle-setup')));
        await tester.pump(const Duration(milliseconds: 300));
        expect(
          find.byKey(const ValueKey('rsi-configuration-readonly')),
          findsOneWidget,
        );
        expect(find.byType(GlassTextField), findsNothing);
        expect(find.byType(GlassPicker), findsNothing);
        expect(
          tester
              .widget<SelectableText>(
                find.byKey(const ValueKey('rsi-readonly-rounds')),
              )
              .data,
          '2',
        );
        expect(
          tester
              .widget<SelectableText>(
                find.byKey(const ValueKey('rsi-readonly-goal')),
              )
              .data,
          '本次运行保存的目标',
        );
        expect(
          tester
              .widget<SelectableText>(
                find.byKey(
                  const ValueKey('rsi-readonly-initial_training_case_count'),
                ),
              )
              .data,
          '14',
        );
        for (final entry in {
          'validation_case_count': '12',
          'human_test_count': '6',
          'max_system_prompt_chars': '20000',
          'max_skill_chars': '15000',
          'max_skill_count': '2',
        }.entries) {
          expect(
            tester
                .widget<SelectableText>(
                  find.byKey(ValueKey('rsi-readonly-${entry.key}')),
                )
                .data,
            entry.value,
          );
        }
        expect(find.byKey(const ValueKey('rsi-import-scorer')), findsNothing);
        await tester.tap(find.byKey(const ValueKey('rsi-scorer-help')));
        await tester.pump(const Duration(milliseconds: 300));
        expect(find.text('如何编写评分器'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        controller.dispose();
        api.close();
      },
    );
  }
  for (final brightness in Brightness.values) {
    testWidgets(
      'primary action changes from cancel to start ${brightness.name}',
      (tester) async {
        final api = PendingCancelApi()..running = true;
        final controller = WorkspaceController(api: api);
        tester.view.physicalSize = const Size(1440, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: RsiScreen(
              controller: controller,
              agentId: 'agent',
              agentName: 'Sage',
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        final cancel = find.byKey(const ValueKey('rsi-cancel'));
        expect(cancel, findsOneWidget);
        expect(find.byKey(const ValueKey('rsi-start')), findsNothing);
        await tester.tap(cancel);
        await tester.pump();
        expect(find.text('处理中…'), findsOneWidget);
        expect(tester.widget<Semantics>(cancel).properties.enabled, isFalse);
        await tester.tap(cancel, warnIfMissed: false);
        expect(api.cancellations, 1);
        api.cancelled.complete();
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));
        expect(find.byKey(const ValueKey('rsi-cancel')), findsNothing);
        final start = find.byKey(const ValueKey('rsi-start'));
        expect(start, findsOneWidget);
        expect(tester.widget<Semantics>(start).properties.enabled, isTrue);
        expect(find.text('开始进化'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
        controller.dispose();
        api.close();
      },
    );
  }
  testWidgets(
    'Active RSI fits a narrow window and replaces start with cancel',
    (tester) async {
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
            .widget<Semantics>(find.byKey(const ValueKey('rsi-cancel')))
            .properties
            .enabled,
        isTrue,
      );
      expect(find.byKey(const ValueKey('rsi-start')), findsNothing);
      expect(find.text('开始进化'), findsNothing);
      expect(
        find.byKey(const ValueKey('rsi-current-activity')),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('rsi-run-run-1')), findsNothing);
      await tester.tap(find.byKey(const ValueKey('rsi-toggle-history')));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const ValueKey('rsi-run-run-1')), findsOneWidget);
      expect(find.text('取消优化'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
      api.close();
    },
  );
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
