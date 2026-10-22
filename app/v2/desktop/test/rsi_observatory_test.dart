import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';

const questions = [
  '检查报销单中的重复项目，并解释判断依据。',
  '用户补充了一张新的发票，继续核对报销金额。',
  '执行工具失败时，如何验证结果并恢复任务？',
  '为跨时区会议安排时间，并检查参与者冲突。',
  '从多个来源提取数据，核对结论的一致性。',
  '用户修改了目标，重新规划并完成交付。',
];
Map<String, Object?> event(String name, Map<String, Object?> data) => {
  'event': name,
  'data': data,
};
Map<String, Object?> testCase(int i) => {
  'id': 'CASE-${(i + 1).toString().padLeft(2, '0')}',
  'input': questions[i],
  'split': i < 3 ? 'training' : 'validation',
  'rubric': '核实信息，保持用户目标，使用证据支持结论。',
};
Map<String, Object?> call(
  int i, {
  int round = 1,
  String phase = 'optimization',
}) => {
  'call_id': 'call-$i-$round-$phase',
  'case_id': testCase(i)['id'],
  'input': questions[i],
  'round': round,
  'phase': phase,
  'trial': 1,
};
Map<String, Object?> result(int i) => {
  'case': testCase(i),
  'observation': {'output': '已核对原始记录，发现两条重复项目。已标记并重新计算金额。'},
  'grade': {
    'score': .92,
    'passed': true,
    'rationale': '证据完整，判断准确，保留了可复用的核验步骤。',
  },
};

void main() {
  adaptiveTests();
  stabilityScopeTests();
  setUpAll(() async {
    if (Platform.environment['RSI_SCREENSHOT_DIR'] != null) {
      await (FontLoader('SageScreenshot')..addFont(
            File(
              '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ).readAsBytes().then(ByteData.sublistView),
          ))
          .load();
      await (FontLoader('packages/cupertino_icons/CupertinoIcons')..addFont(
            rootBundle.load(
              'packages/cupertino_icons/assets/CupertinoIcons.ttf',
            ),
          ))
          .load();
    }
  });
  for (final brightness in Brightness.values) {
    testWidgets('matrix ${brightness.name} follows independent call states', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1440, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final events = [
        event('suite_fixed', {
          'suite': {'cases': List.generate(6, testCase)},
        }),
        event('target_call_started', call(0)),
        event('target_call_completed', {
          'call_id': call(0)['call_id'],
          'observation': result(0)['observation'],
        }),
        event('case_completed', {
          'round': 1,
          'phase': 'optimization',
          'result': result(0),
        }),
        event('target_call_started', call(1)),
      ];
      Widget screen({bool reduceMotion = false}) => MaterialApp(
        theme: ThemeData(
          brightness: brightness,
          fontFamily: Platform.environment['RSI_SCREENSHOT_DIR'] == null
              ? null
              : 'SageScreenshot',
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF007E78),
            brightness: brightness,
          ),
        ),
        home: MediaQuery(
          data: MediaQueryData(disableAnimations: reduceMotion),
          child: Scaffold(
            body: RepaintBoundary(
              key: const ValueKey('capture'),
              child: ColoredBox(
                color: brightness == Brightness.dark
                    ? const Color(0xFF0A1119)
                    : const Color(0xFFF0F4F8),
                child: Padding(
                  padding: const EdgeInsets.all(28),
                  child: SingleChildScrollView(
                    child: RsiObservatory(
                      run: const {
                        'id': 'run-1',
                        'status': 'running',
                        'rounds': 3,
                        'iteration': 1,
                      },
                      events: List.of(events),
                      chinese: true,
                      settings: LiquidGlassSettings(
                        blur: 0,
                        glassColor: brightness == Brightness.dark
                            ? const Color(0xFF172329)
                            : Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpWidget(screen());
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pump(const Duration(milliseconds: 300));
      expect(
        find.byKey(const ValueKey('rsi-conversation-CASE-01')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('rsi-conversation-CASE-06')),
        findsOneWidget,
      );
      expect(find.text('通过'), findsOneWidget);
      expect(find.text('对话中'), findsOneWidget); // Metric and one active card.
      expect(find.text('等待对话'), findsNWidgets(4));
      final first = tester.getTopLeft(
        find.byKey(const ValueKey('rsi-conversation-CASE-01')),
      );
      final second = tester.getTopLeft(
        find.byKey(const ValueKey('rsi-conversation-CASE-02')),
      );
      expect(first.dy, second.dy);
      expect(second.dx, greaterThan(first.dx));
      events.add(
        event('target_call_completed', {
          'call_id': call(1)['call_id'],
          'observation': {'output': '正在检查新发票与原始记录的对应关系。'},
        }),
      );
      await tester.pumpWidget(screen());
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('评估中'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('rsi-score-matrix-training')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('rsi-score-matrix-validation')),
        findsOneWidget,
      );
      final measuredDot = tester.widget<AnimatedContainer>(
        find.byKey(const ValueKey('rsi-score-dot-training-CASE-01')),
      );
      final pendingDot = tester.widget<AnimatedContainer>(
        find.byKey(const ValueKey('rsi-score-dot-training-CASE-03')),
      );
      expect(
        (measuredDot.decoration as BoxDecoration).color,
        isNot((pendingDot.decoration as BoxDecoration).color),
      );

      expect(find.text('等待对话'), findsNWidgets(4));
      final dir = Platform.environment['RSI_SCREENSHOT_DIR'];
      if (dir != null) {
        final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byKey(const ValueKey('capture')),
        );
        await tester.runAsync(() async {
          final image = await boundary.toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File(
            '$dir/matrix-${brightness.name}.png',
          ).writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }
      events.add(
        event('case_completed', {
          'round': 1,
          'phase': 'optimization',
          'result': result(1),
        }),
      );
      events.add(event('target_call_started', call(0, round: 2)));
      await tester.pumpWidget(screen());
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('通过'), findsNothing); // New round has its own outcomes.
      await tester.tap(find.text('第 1 轮'));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('通过'), findsNWidgets(2));
      await tester.pumpWidget(screen(reduceMotion: true));
      await tester
          .pumpAndSettle(); // Active run must settle with reduced motion.
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }
  testWidgets('final tests use their own suite and baseline/candidate lanes', (
    tester,
  ) async {
    final events = [
      event('suite_fixed', {
        'suite': {
          'cases': [testCase(0)],
        },
      }),
      event('final_suite_sealed', {
        'suite': {
          'cases': [testCase(1)],
        },
      }),
      event('target_call_started', call(1, round: 0, phase: 'final')),
      event('case_completed', {
        'round': 0,
        'phase': 'final',
        'result': result(1),
      }),
      event('final_baseline_completed', {}),
      event('target_call_started', call(1, round: 0, phase: 'final')),
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: RsiObservatory(
              run: const {'id': 'run', 'status': 'failed'},
              events: events,
              settings: const LiquidGlassSettings(),
              chinese: true,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('rsi-conversation-CASE-01')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('rsi-conversation-CASE-02')),
      findsOneWidget,
    );
    expect(find.text('未完成'), findsOneWidget);
    expect(find.text('通过'), findsNothing);
    await tester.tap(find.text('最终测试 · 基线'));
    await tester.pumpAndSettle();
    expect(find.text('通过'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('rsi-open-suite')));
    await tester.pumpAndSettle();
    expect(find.text('测试题库 · 2'), findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('rsi-suite-search')),
      'CASE-02',
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('rsi-library-case-CASE-02')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('rsi-library-case-CASE-01')),
      findsNothing,
    );
    await tester.tap(find.byKey(const ValueKey('rsi-library-case-CASE-02')));
    await tester.pumpAndSettle();
    expect(find.text('评测标准'), findsOneWidget);
    await tester.tap(find.text('验证'));
    await tester.pumpAndSettle();
    expect(find.text('没有匹配的问题'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'score trajectory uses measured rounds and honors final rollback',
    (tester) async {
      Map<String, Object?> evaluation(double score) => {
        'cases': [
          {
            'case': testCase(0),
            'grade': {'score': score, 'passed': score > .9},
            'observation': {'output': '真实评测回答'},
          },
        ],
      };
      final baseline = evaluation(.4);
      final candidate = evaluation(.97);
      final rejected = evaluation(.8);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: {
                  'id': 'measured',
                  'status': 'completed',
                  'result': {
                    'report': {
                      'baseline': baseline,
                      'selected': baseline,
                      'final_verification': {
                        'candidate': rejected,
                        'passed': false,
                      },
                    },
                  },
                },
                events: [
                  event('evaluation_completed', {
                    'round': 0,
                    'evaluation': baseline,
                  }),
                  event('round_completed', {
                    'record': {
                      'round': 1,
                      'accepted': true,
                      'evaluation': candidate,
                    },
                  }),
                  event('round_completed', {
                    'record': {
                      'round': 2,
                      'accepted': false,
                      'evaluation': rejected,
                    },
                  }),
                ],
                settings: const LiquidGlassSettings(),
                chinese: true,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('基线  0.400'), findsOneWidget);
      expect(find.text('第 1 轮  0.970'), findsOneWidget);
      expect(find.text('第 2 轮  0.800 · 未采纳'), findsOneWidget);
      expect(find.text('独立终测  0.800 · 未通过'), findsOneWidget);
      expect(
        find.text('0.400'),
        findsNWidgets(2),
      ); // Baseline and restored current best.
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('generated tools show actual versioned growth and rejection', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: RsiObservatory(
              run: const {'status': 'completed'},
              events: [
                event('operation_started', {
                  'package': {'files': <String, Object?>{}},
                }),
                event('candidate_created', {
                  'round': 1,
                  'package': {
                    'files': {
                      'tools/rsi/rsi_support_policy.json': jsonEncode({
                        'description': '核对签收日期与退货期限',
                        'input_schema': {
                          'type': 'object',
                          'properties': {
                            'days': {'type': 'integer'},
                          },
                        },
                        'expression': {'var': 'days'},
                      }),
                    },
                  },
                }),
                event('round_completed', {
                  'record': {'round': 1, 'accepted': false},
                }),
              ],
              settings: const LiquidGlassSettings(),
              chinese: true,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('工具进化'), findsOneWidget);
    expect(find.text('基线 · 0 业务工具'), findsOneWidget);
    expect(find.text('R1 · 1 业务工具 · 未采纳'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('rsi-tools-1')));
    await tester.tap(find.byKey(const ValueKey('rsi-tools-1')));
    await tester.pumpAndSettle();
    expect(find.text('rsi_support_policy'), findsOneWidget);
    expect(find.text('核对签收日期与退货期限'), findsOneWidget);
    expect(find.text('参数: days'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'durable report restores tools and labels reused evaluations without new conversations',
    (tester) async {
      final evaluation = {
        'cases': [result(0), result(1)],
      };
      final package = {
        'files': {
          'tools/rsi/rsi_policy.json': jsonEncode({
            'description': '售后条件判断',
            'input_schema': {'type': 'object', 'properties': {}},
          }),
        },
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: {
                  'status': 'completed',
                  'iterations': [
                    {'iteration': 1, 'accepted': true},
                    {
                      'iteration': 2,
                      'accepted': false,
                      'evaluation_reused': true,
                    },
                  ],
                  'result': {
                    'report': {
                      'suite': {
                        'cases': [testCase(0), testCase(1)],
                      },
                      'baseline': evaluation,
                    },
                    'iterations': [
                      {'iteration': 0, 'evaluation': evaluation},
                      {
                        'iteration': 1,
                        'evaluation': evaluation,
                        'package': package,
                      },
                      {
                        'iteration': 2,
                        'evaluation': evaluation,
                        'package': package,
                        'evaluation_reused': true,
                      },
                    ],
                  },
                },
                events: const [],
                settings: const LiquidGlassSettings(),
                chinese: true,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('第 2 轮  0.920 · 复用评测 · 未采纳'), findsOneWidget);
      expect(find.text('R1 · 1 业务工具'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, '第 2 轮'), findsNothing);
      expect(find.widgetWithText(ChoiceChip, '第 1 轮'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  for (final brightness in Brightness.values) {
    testWidgets(
      'termination states in ${brightness.name} do not claim final success',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: {
                    'status': 'completed',
                    'termination': {
                      'reason': 'target_reached',
                      'stability_passes': 2,
                    },
                    'result': {
                      'report': {
                        'final_verification': {
                          'passed': false,
                          'candidate': {
                            'cases': [result(0)],
                          },
                        },
                      },
                    },
                  },
                  events: const [],
                  settings: const LiquidGlassSettings(),
                  chinese: true,
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('达标退出'), findsOneWidget);
        expect(find.text('稳定性复测通过'), findsOneWidget);
        expect(find.text('终测未达标'), findsOneWidget);
        expect(find.text('进化成功'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'fresh stability pass does not reuse candidate conversation grades',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: {'status': 'running', 'iteration': 1, 'rounds': 8},
                events: [
                  event('suite_fixed', {
                    'suite': {
                      'cases': [testCase(0), testCase(1)],
                    },
                  }),
                  event('case_completed', {
                    'round': 1,
                    'phase': 'optimization',
                    'result': result(0),
                  }),
                  event('case_completed', {
                    'round': 1,
                    'phase': 'optimization',
                    'result': result(1),
                  }),
                  event('stability_check_started', {
                    'round': 1,
                    'confirmation': 1,
                  }),
                  event('target_call_started', call(0)),
                ],
                settings: const LiquidGlassSettings(),
                chinese: true,
              ),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 200));
      expect(find.widgetWithText(ChoiceChip, '稳定性复测 1'), findsOneWidget);
      expect(find.text('稳定性复测中'), findsOneWidget);
      expect(find.text('0 / 2'), findsNWidgets(2));
      expect(find.text('评分 0.92'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}

void adaptiveTests() {
  for (final brightness in Brightness.values) {
    testWidgets(
      'adaptive ${brightness.name} shows validation scores and growing training without final exam',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final extra = {
          'id': 'new-challenge',
          'input': '新增的训练挑战',
          'rubric': '准确判断',
          'split': 'training',
        };
        final evaluation = {
          'cases': [
            for (var i = 0; i < 6; i++)
              {
                ...result(i),
                'grade': {'score': i < 3 ? .1 : .8, 'passed': false},
              },
          ],
        };
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(
              brightness: brightness,
              fontFamily: Platform.environment['RSI_SCREENSHOT_DIR'] == null
                  ? null
                  : 'SageScreenshot',
            ),
            home: Scaffold(
              body: RepaintBoundary(
                key: const ValueKey('adaptive-capture'),
                child: ColoredBox(
                  color: brightness == Brightness.dark
                      ? const Color(0xFF101820)
                      : const Color(0xFFF0F4F8),
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: SingleChildScrollView(
                      child: RsiObservatory(
                        run: {
                          'status': 'completed',
                          'validation_case_count': 3,
                          'human_test_suite': {
                            'cases': [
                              {
                                'id': 'human-test-only',
                                'input': '只供人查看的测试问题',
                                'rubric': '独立评测',
                                'split': 'test',
                              },
                            ],
                          },
                          'goal_verified': false,
                          'result': {
                            'report': {
                              'suite': {
                                'cases': [...List.generate(6, testCase), extra],
                              },
                              'training_additions': [
                                {
                                  'round': 2,
                                  'cases': [extra],
                                },
                              ],
                              'baseline': evaluation,
                              'selected': evaluation,
                            },
                          },
                        },
                        events: const [],
                        settings: LiquidGlassSettings(
                          blur: 0,
                          glassColor: brightness == Brightness.dark
                              ? const Color(0xFF172329)
                              : Colors.white,
                        ),
                        chinese: true,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('只供人查看的测试问题'), findsNothing);
        expect(
          find.byKey(const ValueKey('rsi-conversation-human-test-only')),
          findsNothing,
        );
        expect(find.text('验证未达标'), findsOneWidget);
        expect(find.text('0.450'), findsNWidgets(2));
        expect(find.text('4 / 3'), findsOneWidget);
        expect(find.text('基线  整体 0.450 · 验证 0.800 · 训练 0.100'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('rsi-conversation-new-challenge')),
          findsNothing,
        );
        expect(
          find.byKey(const ValueKey('rsi-score-dot-training-CASE-01')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('rsi-score-dot-validation-CASE-04')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('rsi-score-dot-training-new-challenge')),
          findsNothing,
        );
        final red = tester.widget<AnimatedContainer>(
          find.byKey(const ValueKey('rsi-score-dot-training-CASE-01')),
        );
        final green = tester.widget<AnimatedContainer>(
          find.byKey(const ValueKey('rsi-score-dot-validation-CASE-04')),
        );
        final redColor = (red.decoration as BoxDecoration).color!;
        final greenColor = (green.decoration as BoxDecoration).color!;
        expect(redColor.r, greaterThan(redColor.g));
        expect(greenColor.g, greaterThan(greenColor.r));
        final dir = Platform.environment['RSI_SCREENSHOT_DIR'];
        if (dir != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('adaptive-capture')),
          );
          await tester.runAsync(() async {
            final pixels = await boundary.toImage();
            final bytes = await pixels.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$dir/adaptive-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            pixels.dispose();
          });
        }
        final library = find.byKey(const ValueKey('rsi-open-suite'));
        await tester.ensureVisible(library);
        await tester.tap(library);
        await tester.pumpAndSettle();
        expect(find.widgetWithText(ChoiceChip, '训练'), findsOneWidget);
        expect(find.widgetWithText(ChoiceChip, '验证'), findsOneWidget);
        expect(find.widgetWithText(ChoiceChip, '最终测试'), findsNothing);
        await tester.tap(find.widgetWithText(ChoiceChip, '测试'));
        await tester.pumpAndSettle();
        expect(find.text('只供人查看的测试问题'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }
}

void stabilityScopeTests() {
  testWidgets(
    'stability dots include the complete challenge cohort before new calls start',
    (tester) async {
      tester.view.physicalSize = const Size(1600, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final extra = {
        'id': 'challenge-new',
        'input': 'New training challenge',
        'rubric': 'Accurate',
        'split': 'training',
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: const {
                  'status': 'running',
                  'validation_case_count': 1,
                  'iteration': 2,
                  'rounds': 4,
                },
                events: [
                  event('suite_fixed', {
                    'suite': {
                      'cases': [testCase(0), testCase(3)],
                    },
                  }),
                  event('training_cases_added', {
                    'round': 2,
                    'cases': [extra],
                  }),
                  event('stability_check_started', {'round': 1, 'attempt': 1}),
                  event('target_call_started', call(0, round: 1)),
                ],
                settings: const LiquidGlassSettings(),
                chinese: true,
              ),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.widgetWithText(ChoiceChip, '稳定性复测 1'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('rsi-score-dot-training-challenge-new')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('rsi-conversation-challenge-new')),
        findsOneWidget,
      );
      expect(find.text('0 / 3'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
