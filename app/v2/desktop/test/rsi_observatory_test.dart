import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';
import 'package:sage_desktop_v2/src/ui/rsi_score_history.dart';
import 'package:sage_desktop_v2/src/ui/rsi_diff.dart';

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
  testWidgets(
    'native execution tools survive completed events and open in the dialogue',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: {'status': 'completed'},
                events: [
                  event('suite_fixed', {
                    'suite': {
                      'cases': [testCase(0)],
                    },
                  }),
                  event('case_completed', {
                    'round': 0,
                    'phase': 'baseline',
                    'result': {
                      ...result(0),
                      'observation': {
                        'output': 'Checking. Finished.',
                        'evidence': {
                          'execution_transcript': [
                            {
                              'id': 'run:1',
                              'kind': 'message',
                              'role': 'assistant',
                              'text': 'Checking.',
                            },
                            {
                              'id': 'run:2',
                              'kind': 'tool_call',
                              'role': 'tool',
                              'tool_name': 'file_read',
                              'call_id': 'run:call',
                              'text': 'index.html',
                            },
                            {
                              'id': 'run:3',
                              'kind': 'tool_result',
                              'role': 'tool',
                              'call_id': 'run:call',
                              'text': 'File contents',
                              'state': 'completed',
                            },
                            {
                              'id': 'run:4',
                              'kind': 'message',
                              'role': 'assistant',
                              'text': 'Finished.',
                            },
                          ],
                        },
                      },
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
      expect(find.text('Checking.'), findsOneWidget);
      expect(find.text('Finished.'), findsOneWidget);
      expect(find.text('Checking. Finished.'), findsNothing);
      final tool = find.widgetWithText(ExpansionTile, '完成');
      await tester.ensureVisible(tool);
      await tester.tap(tool);
      await tester.pumpAndSettle();
      expect(find.text('index.html'), findsOneWidget);
      expect(find.text('File contents'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'discovery subset score cannot replace the complete retained overall score',
    (tester) async {
      tester.view.physicalSize = const Size(1600, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, Object?> scored(int i, double score) => {
        ...result(i),
        'grade': {
          'score': score,
          'passed': score >= .6,
          'rationale': 'Recorded score',
        },
      };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: const {
                  'status': 'running',
                  'rounds': 2,
                  'evaluation_protocol': 'adaptive_validation',
                  'validation_case_count': 1,
                },
                events: [
                  event('suite_fixed', {
                    'suite': {
                      'cases': [testCase(0), testCase(3)],
                    },
                  }),
                  event('evaluation_completed', {
                    'round': 0,
                    'evaluation': {
                      'cases': [scored(0, .4), scored(3, .4)],
                    },
                  }),
                  event('training_cases_added', {
                    'round': 1,
                    'cases': [testCase(1)],
                  }),
                  event('training_challenge_completed', {
                    'round': 1,
                    'evaluation': {
                      'cases': [scored(1, .1)],
                    },
                    'retained_evaluation': {
                      'cases': [scored(0, .8), scored(1, .8), scored(3, .9)],
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
      await tester.pump(const Duration(milliseconds: 200));
      expect(find.text('0.850'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'current activity follows unfinished work in ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final events = <Map<String, Object?>>[
          event('target_call_started', call(0, round: 0)),
          event('agent_call_started', {
            'call_id': 'eval',
            'role': 'evaluation',
            'case_id': 'CASE-02',
          }),
        ];
        Future<void> render({String status = 'running'}) async {
          await tester.pumpWidget(
            MaterialApp(
              theme: ThemeData(brightness: brightness),
              home: Scaffold(
                body: SingleChildScrollView(
                  child: RsiObservatory(
                    run: {'id': 'activity', 'status': status},
                    events: List.of(events),
                    settings: const LiquidGlassSettings(),
                    chinese: true,
                  ),
                ),
              ),
            ),
          );
          await tester.pump(const Duration(milliseconds: 100));
        }

        String title() => tester
            .widget<Text>(find.byKey(const ValueKey('rsi-current-activity')))
            .data!;
        await render();
        expect(title(), '执行对话 · 分析执行结果');
        events.add(
          event('target_call_completed', {
            'call_id': call(0, round: 0)['call_id'],
          }),
        );
        await render();
        expect(title(), '分析执行结果');
        events.add(event('agent_call_completed', {'call_id': 'eval'}));
        events.add(
          event('agent_call_started', {
            'call_id': 'summary',
            'role': 'evaluation',
            'activity': 'diagnosis_summary',
          }),
        );
        await render();
        expect(title(), '汇总诊断');
        events.add(event('agent_call_completed', {'call_id': 'summary'}));
        events.add(
          event('agent_call_started', {'call_id': 'tuner', 'role': 'tuning'}),
        );
        await render();
        expect(title(), '优化配置');
        await render(status: 'completed');
        expect(title(), '进化完成');
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
  testWidgets(
    'opaque fixture routing is hidden until actual conversation evidence arrives',
    (tester) async {
      const routing = '{"fixture_id":"opaque-123"}';
      final events = <Map<String, Object?>>[
        event('suite_fixed', {
          'suite': {
            'cases': [
              {...testCase(0), 'input': routing},
            ],
          },
        }),
        event('target_call_started', {...call(0, round: 0), 'input': routing}),
      ];
      Future<void> render(String visibility) async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: {'status': 'running', 'input_visibility': visibility},
                  events: events,
                  settings: const LiquidGlassSettings(),
                  chinese: true,
                ),
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 300));
      }

      await render('opaque_fixture');
      expect(find.text(routing), findsNothing);
      await render('message');
      expect(find.text(routing), findsOneWidget);
      events.add(
        event('target_call_completed', {
          'call_id': call(0, round: 0)['call_id'],
          'observation': {
            'output': jsonEncode({
              'conversation': [
                {'role': 'user', 'content': 'Actual user request'},
                {'role': 'assistant', 'content': 'Actual assistant response'},
              ],
            }),
          },
        }),
      );
      await render('opaque_fixture');
      expect(find.text(routing), findsNothing);
      expect(find.text('Actual user request'), findsOneWidget);
      expect(find.text('Actual assistant response'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );
  for (final brightness in Brightness.values) {
    testWidgets(
      'score dots open execution and distinct evaluator feedback ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: {'id': 'dot-details', 'status': 'completed'},
                  events: [
                    event('suite_fixed', {
                      'suite': {
                        'cases': [testCase(0), testCase(1)],
                      },
                    }),
                    event('case_completed', {
                      'round': 1,
                      'phase': 'optimization',
                      'result': {
                        ...result(0),
                        'grade': {
                          'score': .25,
                          'passed': false,
                          'rationale': 'Host score rationale',
                        },
                        'model_grade': {
                          'score': .8,
                          'passed': true,
                          'rationale': 'Evaluator rationale',
                          'diagnosis': {
                            'summary': 'Evaluator summary',
                            'findings': [
                              {
                                'cause': 'Missing verification',
                                'recommendation': 'Verify the original receipt',
                              },
                            ],
                          },
                        },
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
        await tester.tap(
          find.byKey(const ValueKey('rsi-score-dot-training-CASE-01')),
        );
        await tester.pumpAndSettle();
        final dialog = find.byType(Dialog);
        expect(
          find.descendant(of: dialog, matching: find.text('第 1 轮 · CASE-01')),
          findsOneWidget,
        );
        expect(
          find.descendant(of: dialog, matching: find.text('评分 0.250')),
          findsOneWidget,
        );
        expect(
          find.descendant(of: dialog, matching: find.text('评分 0.800')),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: dialog,
            matching: find.text('Host score rationale'),
          ),
          findsNothing,
        );
        expect(
          find.descendant(of: dialog, matching: find.text('Evaluator summary')),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: dialog,
            matching: find.text('Verify the original receipt'),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: dialog,
            matching: find.text('已核对原始记录，发现两条重复项目。已标记并重新计算金额。'),
          ),
          findsOneWidget,
        );
        await tester.tap(find.byTooltip('关闭'));
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(const ValueKey('rsi-score-dot-training-CASE-02')),
        );
        await tester.pumpAndSettle();
        expect(
          find.descendant(
            of: find.byType(Dialog),
            matching: find.text('暂无评分记录'),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: find.byType(Dialog),
            matching: find.text('暂无 Eval Agent 评价或建议记录'),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: find.byType(Dialog),
            matching: find.text('评分 0.250'),
          ),
          findsNothing,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
  for (final brightness in Brightness.values) {
    testWidgets(
      'dialogue library displays and searches scenarios ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: const {'id': 'dialogue-library', 'status': 'completed'},
                  events: [
                    event('suite_fixed', {
                      'suite': {
                        'cases': [
                          {
                            'id': 'return-case',
                            'input': 'Hello.',
                            'mode': 'dialogue',
                            'split': 'training',
                            'user_context': 'Return the damaged camera.',
                            'rubric': 'Complete the return',
                          },
                          {
                            'id': 'exchange-case',
                            'input': 'Hello.',
                            'mode': 'dialogue',
                            'split': 'validation',
                            'user_context': jsonEncode({
                              'background': 'Patient customer',
                              'request': 'Exchange a blue keyboard.',
                            }),
                            'rubric': 'Complete the exchange',
                          },
                        ],
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
        final open = find.byKey(const ValueKey('rsi-open-suite'));
        await tester.ensureVisible(open);
        await tester.tap(open);
        await tester.pumpAndSettle();
        expect(find.text('Return the damaged camera.'), findsOneWidget);
        expect(
          find.text(
            'request: Exchange a blue keyboard.\nbackground: Patient customer',
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: find.byType(Dialog),
            matching: find.text('Hello.'),
          ),
          findsNothing,
        );
        await tester.enterText(
          find.byKey(const ValueKey('rsi-suite-search')),
          'blue keyboard',
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('rsi-library-case-return-case')),
          findsNothing,
        );
        final cell = find.byKey(
          const ValueKey('rsi-library-case-exchange-case'),
        );
        expect(cell, findsOneWidget);
        await tester.tap(cell);
        await tester.pumpAndSettle();
        expect(
          find.byWidgetPredicate(
            (w) =>
                w is SelectableText &&
                w.data ==
                    'request: Exchange a blue keyboard.\nbackground: Patient customer',
          ),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final brightness in Brightness.values) {
    testWidgets(
      'library table shows human questions and reference answers ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final longQuestion = List.filled(
          60,
          'Please verify the order and all return requirements.',
        ).join(' ');
        final longAnswer = List.filled(
          100,
          'Verify the purchase, original payment and each requested return.',
        ).join('\n');
        final suite = [
          for (var i = 0; i < 12; i++)
            {
              'id': 'tau-$i',
              'input': jsonEncode({'tau_task_id': '$i'}),
              'split': i < 11 ? 'training' : 'validation',
              'rubric': 'Use official reward',
            },
        ];
        await tester.pumpWidget(
          RepaintBoundary(
            key: const ValueKey('rsi-library-capture'),
            child: MaterialApp(
              theme: ThemeData(
                brightness: brightness,
                fontFamily: Platform.environment['RSI_SCREENSHOT_DIR'] == null
                    ? null
                    : 'SageScreenshot',
              ),
              home: Scaffold(
                body: SingleChildScrollView(
                  child: RsiObservatory(
                    run: {
                      'id': 'library',
                      'status': 'completed',
                      'human_case_details': {
                        'tau-1': {
                          'question': longQuestion,
                          'reference_answer': longAnswer,
                        },
                        'tau-0': {
                          'question':
                              'Exchange the keyboard for clicky switches.',
                          'reference_answer':
                              'Verify the order and exchange the keyboard.',
                        },
                      },
                    },
                    events: [
                      event('suite_fixed', {
                        'suite': {'cases': suite},
                      }),
                    ],
                    settings: const LiquidGlassSettings(),
                    chinese: true,
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.ensureVisible(
          find.byKey(const ValueKey('rsi-open-suite')),
        );
        await tester.tap(find.byKey(const ValueKey('rsi-open-suite')));
        await tester.pumpAndSettle();
        final dialog = find.byType(Dialog);
        expect(find.byType(DataTable), findsOneWidget);
        expect(
          find.text('Exchange the keyboard for clicky switches.'),
          findsOneWidget,
        );
        expect(
          find.text('Verify the order and exchange the keyboard.'),
          findsOneWidget,
        );
        expect(
          find.descendant(of: dialog, matching: find.text('已提供')),
          findsNWidgets(2),
        );
        expect(
          find.descendant(of: dialog, matching: find.text('未提供')),
          findsNWidgets(8),
        );
        expect(
          find.byKey(const ValueKey('rsi-library-case-tau-10')),
          findsNothing,
        );
        final longCell = find.byKey(const ValueKey('rsi-library-case-tau-1'));
        expect(tester.getSize(longCell).height, lessThan(90));
        expect(
          tester.widget<DataTable>(find.byType(DataTable)).dataRowMaxHeight,
          104,
        );
        await tester.tap(longCell);
        await tester.pumpAndSettle();
        expect(
          find.byWidgetPredicate(
            (w) => w is SelectableText && w.data == longQuestion,
          ),
          findsOneWidget,
        );
        expect(
          find.byWidgetPredicate(
            (w) => w is SelectableText && w.data == longAnswer,
          ),
          findsOneWidget,
        );
        await tester.tap(
          find.byKey(const ValueKey('rsi-library-detail-close')),
        );
        await tester.pumpAndSettle();

        final screenshotDir = Platform.environment['RSI_SCREENSHOT_DIR'];
        if (screenshotDir != null) {
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('rsi-library-capture')),
          );
          await tester.runAsync(() async {
            final pixels = await boundary.toImage();
            final bytes = await pixels.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$screenshotDir/library-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            pixels.dispose();
          });
        }
        await tester.tap(
          find.descendant(of: dialog, matching: find.byTooltip('下一页')),
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('rsi-library-case-tau-10')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('rsi-library-case-tau-0')),
          findsNothing,
        );
        await tester.enterText(
          find.byKey(const ValueKey('rsi-suite-search')),
          'Verify the order',
        );
        await tester.pumpAndSettle();
        expect(
          find.text('Exchange the keyboard for clicky switches.'),
          findsOneWidget,
        );
        expect(
          find.descendant(of: dialog, matching: find.text('1 / 1')),
          findsOneWidget,
        );
        tester.view.physicalSize = const Size(700, 900);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
  for (final brightness in Brightness.values) {
    for (final snapshot in [false, true]) {
      testWidgets(
        'repeated dots isolate each execution ${brightness.name} snapshot=$snapshot',
        (tester) async {
          tester.view.physicalSize = const Size(1500, 1200);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          Map<String, Object?> trial(int index) {
            final grade = <String, Object?>{
              'score': index == 1 ? 0.0 : 1.0,
              'passed': index == 2,
              'rationale':
                  'Repeated narrative $index with different formatting.',
              'diagnosis': {
                'summary': 'Summary $index',
                'findings': [
                  {
                    'cause': 'Cause $index',
                    'recommendation': 'Recommendation $index',
                  },
                ],
              },
            };
            return {
              'observation': {
                'state': 'completed',
                'output': 'Execution response $index',
              },
              'grade': grade,
              'model_grade': grade,
            };
          }

          final first = trial(1), second = trial(2);
          final aggregate = {
            'case': testCase(0),
            'grade': {'score': .5, 'passed': false},
            'trials': [first, second],
          };
          final run = <String, Object?>{
            'id': 'repetitions',
            'call_pool': {
              'calls': [
                {'input': questions[1], 'trial': 2, 'state': 'running'},
              ],
            },
            'status': snapshot ? 'completed' : 'running',
            'evaluation_repeats': 2,
            if (snapshot)
              'result': {
                'report': {
                  'suite': {
                    'cases': [testCase(0), testCase(1)],
                  },
                  'baseline': {
                    'cases': [aggregate],
                  },
                },
              },
          };
          await tester.pumpWidget(
            RepaintBoundary(
              key: const ValueKey('rsi-repeated-capture'),
              child: MaterialApp(
                theme: ThemeData(
                  brightness: brightness,
                  fontFamily: Platform.environment['RSI_SCREENSHOT_DIR'] == null
                      ? null
                      : 'SageScreenshot',
                ),
                home: MediaQuery(
                  data: const MediaQueryData(disableAnimations: true),
                  child: Scaffold(
                    body: SingleChildScrollView(
                      child: RsiObservatory(
                        run: run,
                        events: snapshot
                            ? []
                            : [
                                event('suite_fixed', {
                                  'suite': {
                                    'cases': [testCase(0), testCase(1)],
                                  },
                                }),
                                event('case_completed', {
                                  'round': 0,
                                  'trial': 1,
                                  'result': {'case': testCase(0), ...first},
                                }),
                                event('case_completed', {
                                  'round': 0,
                                  'trial': 2,
                                  'result': {'case': testCase(0), ...second},
                                }),
                                event('case_completed', {
                                  'round': 0,
                                  'trial': 1,
                                  'result': {'case': testCase(1), ...second},
                                }),
                                event('target_call_started', {
                                  ...call(1, round: 0),
                                  'trial': 2,
                                }),
                              ],
                        settings: const LiquidGlassSettings(),
                        chinese: true,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
          await tester.pumpAndSettle();
          final dot1 = find.byKey(
            const ValueKey('rsi-score-dot-training-CASE-01-trial-1'),
          );
          final dot2 = find.byKey(
            const ValueKey('rsi-score-dot-training-CASE-01-trial-2'),
          );
          expect(dot1, findsOneWidget);
          expect(dot2, findsOneWidget);
          expect(tester.getCenter(dot1).dx, tester.getCenter(dot2).dx);
          expect(
            tester.getCenter(dot2).dy,
            greaterThan(tester.getCenter(dot1).dy),
          );
          final color1 =
              (tester.widget<AnimatedContainer>(dot1).decoration
                      as BoxDecoration)
                  .color;
          final color2 =
              (tester.widget<AnimatedContainer>(dot2).decoration
                      as BoxDecoration)
                  .color;
          expect(color1, isNot(color2));
          if (!snapshot) {
            final active = tester.widget<AnimatedContainer>(
              find.byKey(
                const ValueKey('rsi-score-dot-training-CASE-02-trial-2'),
              ),
            );
            final finished = tester.widget<AnimatedContainer>(
              find.byKey(
                const ValueKey('rsi-score-dot-training-CASE-02-trial-1'),
              ),
            );
            expect((active.decoration as BoxDecoration).border, isNotNull);
            expect((finished.decoration as BoxDecoration).border, isNull);
          }
          final screenshotDir = Platform.environment['RSI_SCREENSHOT_DIR'];
          if (screenshotDir != null) {
            final boundary = tester.renderObject<RenderRepaintBoundary>(
              find.byKey(const ValueKey('rsi-repeated-capture')),
            );
            await tester.runAsync(() async {
              final pixels = await boundary.toImage();
              final bytes = await pixels.toByteData(
                format: ui.ImageByteFormat.png,
              );
              await File(
                '$screenshotDir/repeated-${brightness.name}-$snapshot.png',
              ).writeAsBytes(bytes!.buffer.asUint8List());
              pixels.dispose();
            });
          }
          for (final index in [1, 2]) {
            await tester.tap(index == 1 ? dot1 : dot2);
            await tester.pumpAndSettle();
            final dialog = find.byType(Dialog);
            expect(
              find.descendant(
                of: dialog,
                matching: find.text('基线轮 · CASE-01 · 第 $index 次执行'),
              ),
              findsOneWidget,
            );
            expect(
              find.descendant(
                of: dialog,
                matching: find.text('Execution response $index'),
              ),
              findsOneWidget,
            );
            expect(
              find.descendant(
                of: dialog,
                matching: find.text('Summary $index'),
              ),
              findsOneWidget,
            );
            expect(
              find.descendant(
                of: dialog,
                matching: find.text(index == 1 ? '评分 0.000' : '评分 1.000'),
              ),
              findsOneWidget,
            );
            expect(
              find.descendant(
                of: dialog,
                matching: find.text(
                  'Repeated narrative $index with different formatting.',
                ),
              ),
              findsNothing,
            );

            expect(
              find.descendant(
                of: dialog,
                matching: find.text('Recommendation $index'),
              ),
              findsOneWidget,
            );
            expect(
              find.descendant(
                of: dialog,
                matching: find.text(
                  'Summary $index. Cause $index. Recommendation $index.',
                ),
              ),
              findsNothing,
            );
            expect(
              find.descendant(
                of: dialog,
                matching: find.text('Execution response ${index == 1 ? 2 : 1}'),
              ),
              findsNothing,
            );
            expect(
              find.descendant(of: dialog, matching: find.text('评分 0.500')),
              findsNothing,
            );
            await tester.tap(find.byTooltip('关闭'));
            await tester.pumpAndSettle();
          }
          final card = find.byKey(const ValueKey('rsi-conversation-CASE-01'));
          expect(
            find.descendant(
              of: card,
              matching: find.text('Execution response 1'),
            ),
            findsOneWidget,
          );
          expect(
            find.descendant(of: card, matching: find.text('评分 0.0')),
            findsOneWidget,
          );
          final picker = find.byKey(
            const ValueKey('rsi-matrix-execution-picker'),
          );
          await tester.ensureVisible(picker);
          await tester.tap(picker);
          await tester.pumpAndSettle();
          await tester.tap(
            find.byKey(const ValueKey('rsi-matrix-execution-2')),
          );
          await tester.pumpAndSettle();
          expect(tester.widget<GlassPicker>(picker).value, '第 2 次执行');
          expect(
            find.descendant(
              of: card,
              matching: find.text('Execution response 2'),
            ),
            findsOneWidget,
          );
          expect(
            find.descendant(
              of: card,
              matching: find.text('Execution response 1'),
            ),
            findsNothing,
          );
          expect(
            find.descendant(of: card, matching: find.text('评分 1.0')),
            findsOneWidget,
          );
          final expand = find.descendant(
            of: card,
            matching: find.byTooltip('展开对话'),
          );
          await tester.ensureVisible(expand);
          await tester.tap(expand);
          await tester.pumpAndSettle();
          expect(
            find.descendant(
              of: find.byType(Dialog),
              matching: find.text('基线轮 · CASE-01 · 第 2 次执行'),
            ),
            findsOneWidget,
          );
          expect(
            find.descendant(
              of: find.byType(Dialog),
              matching: find.text('Execution response 1'),
            ),
            findsNothing,
          );
          await tester.tap(find.byTooltip('关闭'));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox());
        },
      );
    }
  }
  adaptiveTests();
  stabilityScopeTests();
  testWidgets(
    'matrix paginates each dataset and resets on dataset and run changes',
    (tester) async {
      final suite = [
        for (var i = 0; i < 35; i++)
          {
            'id': 'page-$i',
            'input': 'Question $i',
            'split': i < 31 ? 'training' : 'validation',
          },
      ];
      Widget screen(String id) => MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: RsiObservatory(
              run: {
                'id': id,
                'status': 'completed',
                'human_test_suite': {
                  'cases': [
                    {
                      'id': 'held-out',
                      'input': 'Held out test',
                      'split': 'test',
                    },
                  ],
                },
                'result': {
                  'report': {
                    'suite': {'cases': suite},
                    'baseline': {
                      'cases': [
                        for (final q in suite)
                          {
                            'case': q,
                            'grade': {'score': .8, 'passed': true},
                          },
                      ],
                    },
                  },
                },
              },
              events: const [],
              settings: const LiquidGlassSettings(blur: 0),
              chinese: true,
            ),
          ),
        ),
      );
      await tester.pumpWidget(screen('one'));
      await tester.pumpAndSettle();
      Finder cards() => find.byWidgetPredicate(
        (w) =>
            w.key is ValueKey<String> &&
            (w.key as ValueKey<String>).value.startsWith('rsi-conversation-'),
      );
      expect(cards(), findsNWidgets(12));
      expect(
        find.byKey(const ValueKey('rsi-conversation-page-12')),
        findsNothing,
      );
      await tester.ensureVisible(find.byKey(const ValueKey('rsi-matrix-next')));
      await tester.tap(find.byKey(const ValueKey('rsi-matrix-next')));
      await tester.pumpAndSettle();
      expect(cards(), findsNWidgets(12));
      expect(
        find.byKey(const ValueKey('rsi-conversation-page-12')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('rsi-conversation-page-0')),
        findsNothing,
      );
      await tester.tap(
        find.byKey(const ValueKey('rsi-matrix-split-validation')),
      );
      await tester.pumpAndSettle();
      expect(cards(), findsNWidgets(4));
      expect(
        find.byKey(const ValueKey('rsi-conversation-page-31')),
        findsOneWidget,
      );
      expect(
        tester
            .widget<IconButton>(
              find.byKey(const ValueKey('rsi-matrix-previous')),
            )
            .onPressed,
        isNull,
      );
      await tester.tap(find.byKey(const ValueKey('rsi-matrix-split-test')));
      await tester.pumpAndSettle();
      expect(cards(), findsOneWidget);
      expect(
        find.byKey(const ValueKey('rsi-conversation-held-out')),
        findsOneWidget,
      );
      await tester.pumpWidget(screen('two'));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('rsi-conversation-page-0')),
        findsOneWidget,
      );
      expect(cards(), findsNWidgets(12));
      expect(tester.takeException(), isNull);
    },
  );
  for (final live in [true, false]) {
    testWidgets(
      'score trend averages repeated trials from ${live ? 'events' : 'snapshots'}',
      (tester) async {
        Map<String, Object?> measured(int i, double low, double high) => {
          ...result(i),
          'grade': {'score': low, 'passed': false},
          'trials': [
            {
              'grade': {'score': low},
            },
            {
              'grade': {'score': high},
            },
          ],
        };
        Map<String, Object?> evaluation(double low, double high) => {
          'cases': [for (var i = 0; i < 6; i++) measured(i, low, high)],
        };
        final events = <Map<String, Object?>>[
          if (live) ...[
            event('suite_fixed', {
              'suite': {'cases': List.generate(6, testCase)},
            }),
            for (var round = 0; round < 2; round++)
              for (var trial = 1; trial <= 2; trial++)
                for (var i = 0; i < 6; i++)
                  event('case_completed', {
                    'round': round,
                    'trial': trial,
                    'result': {
                      ...result(i),
                      'grade': {
                        'score': trial == 2
                            ? .8
                            : round == 0
                            ? .2
                            : .6,
                        'passed': false,
                      },
                    },
                  }),
          ],
        ];
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: {
                    'status': 'completed',
                    'validation_case_count': 3,
                    'test_observations': [
                      {
                        'round': 0,
                        'scores': {
                          'training': .2,
                          'validation': .2,
                          'test': .9,
                        },
                      },
                    ],
                    'result': {
                      'report': {
                        'suite': {'cases': List.generate(6, testCase)},
                        'baseline': evaluation(.2, .8),
                        'rounds': [
                          {'round': 1, 'evaluation': evaluation(.6, .8)},
                        ],
                      },
                    },
                  },
                  events: events,
                  settings: const LiquidGlassSettings(blur: 0),
                  chinese: true,
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final records = tester
            .widget<RsiScoreTrend>(find.byType(RsiScoreTrend))
            .records;
        final baseline = records.first['scores'] as Map;
        final iteration = records.last['scores'] as Map;
        expect(baseline['training'], closeTo(.5, 1e-9));
        expect(baseline['validation'], closeTo(.5, 1e-9));
        expect(baseline['test'], .9);
        expect(iteration['training'], closeTo(.7, 1e-9));
        expect(iteration['validation'], closeTo(.7, 1e-9));
        expect(tester.takeException(), isNull);
      },
    );
  }
  for (final brightness in Brightness.values) {
    testWidgets(
      'human test dots isolate repeats and rounds ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: {
                    'status': 'completed',
                    'evaluation_repeats': 2,
                    'human_test_repeats': 3,
                    'human_test_suite': {
                      'cases': [
                        {
                          'id': 'TEST-1',
                          'input': '独立测试题',
                          'rubric': '准确',
                          'split': 'test',
                        },
                      ],
                    },
                    'test_observations': [
                      {
                        'round': 0,
                        'repeats': 3,
                        'status': 'completed',
                        'valid': true,
                        'cases': [
                          {
                            'id': 'TEST-1',
                            'trials': [
                              {
                                'trial': 1,
                                'status': 'completed',
                                'grade': {'score': 0, 'passed': false},
                              },
                              {
                                'trial': 2,
                                'status': 'completed',
                                'grade': {'score': 1, 'passed': true},
                              },
                              {'trial': 3, 'status': 'queued'},
                            ],
                          },
                        ],
                      },
                    ],
                    'result': {
                      'report': {
                        'suite': {'cases': List.generate(6, testCase)},
                        'baseline': {
                          'cases': [result(0)],
                        },
                        'rounds': [
                          {
                            'round': 1,
                            'evaluation': {
                              'cases': [result(0)],
                            },
                          },
                        ],
                      },
                    },
                  },
                  events: const [],
                  settings: const LiquidGlassSettings(blur: 0),
                  chinese: true,
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('测试集（test）'), findsOneWidget);
        await tester.ensureVisible(find.widgetWithText(ChoiceChip, '基线轮'));
        await tester.tap(find.widgetWithText(ChoiceChip, '基线轮'));
        await tester.pumpAndSettle();
        Finder dot(int n) =>
            find.byKey(ValueKey('rsi-score-dot-test-TEST-1-trial-$n'));
        Color? color(int n) =>
            (tester.widget<AnimatedContainer>(dot(n)).decoration
                    as BoxDecoration)
                .color;
        expect(color(1), isNot(color(2)));
        expect(color(2), isNot(color(3)));
        await tester.ensureVisible(dot(2));
        await tester.tap(dot(2));
        await tester.pumpAndSettle();
        expect(find.text('评分 1.000'), findsWidgets);
        await tester.tap(find.byTooltip('关闭'));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.widgetWithText(ChoiceChip, '第 1 轮'));
        await tester.tap(find.widgetWithText(ChoiceChip, '第 1 轮'));
        await tester.pumpAndSettle();
        expect(color(1), color(2));
        expect(color(2), color(3));
        expect(tester.takeException(), isNull);
      },
    );
  }
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
      Widget screen({bool reduceMotion = false, String status = 'running'}) =>
          MaterialApp(
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
                          run: {
                            'id': 'run-1',
                            'status': status,
                            'call_pool': {
                              'calls': [
                                {
                                  'input': questions[1],
                                  'trial': 1,
                                  'state': 'running',
                                },
                              ],
                            },
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
        findsNothing,
      );
      expect(find.text('通过'), findsOneWidget);
      expect(find.text('对话中'), findsOneWidget); // Metric and one active card.
      expect(find.text('等待对话'), findsOneWidget);
      expect(
        tester.widget<RsiScoreTrend>(find.byType(RsiScoreTrend)).records,
        isEmpty,
      );
      final trainingMatrix = find.byKey(
        const ValueKey('rsi-score-matrix-training'),
      );
      final validationMatrix = find.byKey(
        const ValueKey('rsi-score-matrix-validation'),
      );
      expect(
        tester
            .getBottomLeft(find.byKey(const ValueKey('rsi-pass-selector')))
            .dy,
        lessThan(tester.getTopLeft(trainingMatrix).dy),
      );
      for (final label in ['通过 1', '未通过 0', '执行中 1', '待执行 1', '平均分 0.920']) {
        expect(
          find.descendant(of: trainingMatrix, matching: find.text(label)),
          findsOneWidget,
        );
      }
      for (final label in ['通过 0', '未通过 0', '执行中 0', '待执行 3', '平均分 —']) {
        expect(
          find.descendant(of: validationMatrix, matching: find.text(label)),
          findsOneWidget,
        );
      }
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

      expect(find.text('等待对话'), findsOneWidget);
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
      await tester.pumpWidget(screen(status: 'failed'));
      await tester.pump(const Duration(milliseconds: 300));
      expect(
        find.descendant(of: trainingMatrix, matching: find.text('执行中 0')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: trainingMatrix, matching: find.text('未评估 2')),
        findsOneWidget,
      );
      final stoppedDot = tester.widget<AnimatedContainer>(
        find.byKey(const ValueKey('rsi-score-dot-training-CASE-02')),
      );
      expect((stoppedDot.decoration as BoxDecoration).border, isNull);
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
      tester.view.physicalSize = const Size(1100, 1200);
      await tester.pumpAndSettle();
      expect(
        tester.getTopLeft(find.byType(RsiScoreTrend)).dx,
        greaterThan(
          tester
              .getBottomRight(
                find.byKey(const ValueKey('rsi-current-activity')),
              )
              .dx,
        ),
      );
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
    await tester.ensureVisible(find.byKey(const ValueKey('rsi-open-suite')));
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
    expect(find.text('评测标准'), findsWidgets);
    await tester.tap(find.byKey(const ValueKey('rsi-library-detail-close')));
    await tester.pumpAndSettle();
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
      expect(find.text('基线  0.400'), findsNothing);
      expect(find.text('第 1 轮  0.970'), findsNothing);
      expect(find.text('第 2 轮  0.800 · 未采纳'), findsNothing);
      expect(find.text('独立终测  0.800 · 未通过'), findsNothing);
      expect(
        tester
            .widget<RsiRoundChanges>(find.byType(RsiRoundChanges))
            .selectedRound,
        0,
      );
      await tester.ensureVisible(find.text('基线轮'));
      await tester.tap(find.text('基线轮'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<RsiRoundChanges>(find.byType(RsiRoundChanges))
            .selectedRound,
        0,
      );
      expect(find.text('基线轮，无进化改动'), findsOneWidget);
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
      expect(find.text('第 2 轮  0.920 · 复用评测 · 未采纳'), findsNothing);
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
        expect(find.text('达标退出'), findsNothing);
        expect(find.text('稳定性复测通过'), findsNothing);
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
      expect(find.text('稳定性复测 · 执行对话'), findsOneWidget);
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
      'round tabs ${brightness.name} hide legacy challenge and include all candidate cases',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1400);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final extra = {
          'id': 'new',
          'input': 'New training question',
          'rubric': 'Accurate',
          'split': 'training',
        };
        final events = [
          event('suite_fixed', {
            'suite': {'cases': List.generate(6, testCase)},
          }),
          event('case_completed', {
            'round': 0,
            'phase': 'optimization',
            'trial': 1,
            'result': result(0),
          }),
          event('training_cases_added', {
            'round': 1,
            'cases': [extra],
          }),
          event('target_call_started', {
            'call_id': 'new-call',
            'case_id': 'new',
            'input': extra['input'],
            'round': 1,
            'trial': 1,
            'phase': 'training_challenge',
          }),
        ];
        Widget screen() => MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: const {
                  'status': 'running',
                  'rounds': 4,
                  'validation_case_count': 3,
                },
                events: List.of(events),
                settings: const LiquidGlassSettings(),
                chinese: true,
              ),
            ),
          ),
        );
        await tester.pumpWidget(screen());
        await tester.pump(const Duration(milliseconds: 300));
        expect(find.widgetWithText(ChoiceChip, '第 1 轮 · 新增题预评测'), findsNothing);
        expect(find.text('新增训练题'), findsNothing);
        expect(find.widgetWithText(ChoiceChip, '基线轮'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('rsi-score-dot-training-new')),
          findsNothing,
        );
        expect(
          find.byKey(const ValueKey('rsi-score-dot-training-CASE-01')),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('rsi-score-matrix-validation')),
          findsOneWidget,
        );
        expect(find.text('待执行 3'), findsOneWidget);
        events.add(event('target_call_started', call(0)));
        await tester.pumpWidget(screen());
        await tester.pump(const Duration(milliseconds: 300));
        expect(find.widgetWithText(ChoiceChip, '第 1 轮'), findsOneWidget);
        expect(
          tester
              .widget<RsiRoundChanges>(find.byType(RsiRoundChanges))
              .selectedRound,
          1,
        );
        await tester.tap(find.widgetWithText(ChoiceChip, '基线轮'));
        await tester.pump(const Duration(milliseconds: 300));
        expect(
          tester
              .widget<RsiRoundChanges>(find.byType(RsiRoundChanges))
              .selectedRound,
          0,
        );
        await tester.tap(find.widgetWithText(ChoiceChip, '第 1 轮'));
        await tester.pump(const Duration(milliseconds: 300));
        for (var i = 0; i < 6; i++) {
          final split = i < 3 ? 'training' : 'validation';
          expect(
            find.byKey(ValueKey('rsi-score-dot-$split-${testCase(i)['id']}')),
            findsOneWidget,
          );
        }
        expect(
          find.byKey(const ValueKey('rsi-score-dot-training-new')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
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
        expect(find.text('未达到收敛目标'), findsOneWidget);
        expect(find.text('0.450'), findsNWidgets(2));
        expect(find.text('4 / 3'), findsOneWidget);
        expect(find.text('基线  整体 0.450 · 验证 0.800 · 训练 0.100'), findsNothing);
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
        final trend = tester.widget<RsiScoreTrend>(find.byType(RsiScoreTrend));
        expect(trend.records, hasLength(1));
        final measured = trend.records.single['scores'] as Map;
        expect(measured['training'], closeTo(.1, .0001));
        expect(measured['validation'], closeTo(.8, .0001));
        expect(measured['test'], isNull);
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
