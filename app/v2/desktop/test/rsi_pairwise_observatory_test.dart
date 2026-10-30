import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';
import 'package:sage_desktop_v2/src/ui/rsi_score_history.dart';
import 'rsi_observatory_test.dart' show event, result, testCase;

void main() {
  for (final brightness in Brightness.values) {
    testWidgets(
      'final paired judgments replace capture placeholders $brightness',
      (tester) async {
        tester.view.physicalSize = const Size(1600, 1400);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        Map<String, Object?> paired(int i, String outcome) => {
          ...result(i),
          'grade': {
            'score': outcome == 'win'
                ? 1.0
                : outcome == 'tie'
                ? .5
                : 0.0,
            'passed': outcome != 'loss',
            'scorer_details': {
              'pairwise': {'outcome': outcome},
            },
          },
        };
        final completed = [
          paired(0, 'win'),
          paired(1, 'tie'),
          paired(2, 'loss'),
          paired(3, 'win'),
        ];
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiObservatory(
                  run: const {
                    'status': 'completed',
                    'iteration': 1,
                    'rounds': 1,
                    'builtin_scoring': {'mode': 'pairwise'},
                    'test_observations': [
                      {
                        'round': 1,
                        'valid': true,
                        'pairwise': {
                          'wins': 8,
                          'ties': 1,
                          'losses': 1,
                          'pairs': 10,
                          'complete': true,
                          'errors': 0,
                        },
                      },
                    ],
                  },
                  events: [
                    event('suite_fixed', {
                      'suite': {
                        'cases': [for (var i = 0; i < 4; i++) testCase(i)],
                      },
                    }),
                    for (var i = 0; i < 4; i++)
                      event('case_completed', {
                        'round': 1,
                        'trial': 1,
                        'result': {
                          ...result(i),
                          'grade': {
                            'score': .5,
                            'passed': true,
                            'scorer_details': {
                              'pairwise': {'pending': true},
                            },
                          },
                        },
                      }),
                    event('evaluation_completed', {
                      'round': 1,
                      'evaluation': {'cases': completed},
                    }),
                    event('round_completed', {
                      'record': {
                        'round': 1,
                        'accepted': true,
                        'evaluation': {'cases': completed},
                        'comparison': {
                          'splits': {
                            'validation': {'wins': 1, 'ties': 0, 'losses': 0},
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
        expect(find.byKey(const ValueKey('rsi-score-trend')), findsOneWidget);
        final trend = tester.widget<RsiScoreTrend>(find.byType(RsiScoreTrend));
        expect(trend.pairwise, isTrue);
        expect(find.text('验证集 · 候选 vs 当轮最佳'), findsOneWidget);
        expect(find.text('逐轮负率（越低越好）'), findsOneWidget);
        expect(find.textContaining('训练集 · 对当轮最佳'), findsOneWidget);
        expect(find.textContaining('测试集 · 对原始基线'), findsOneWidget);
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('rsi-pairwise-summary')),
            matching: find.byType(GlassCard),
          ),
          findsNothing,
        );
        expect(
          (trend.records.single['scores'] as Map)['training'],
          closeTo(1 / 3, .00001),
        );
        expect((trend.records.single['scores'] as Map)['validation'], 0.0);
        expect((trend.records.single['scores'] as Map)['test'], .1);
        final matrix = find.byKey(const ValueKey('rsi-score-matrix-training'));
        expect(
          find.descendant(of: matrix, matching: find.text('胜 1')),
          findsOneWidget,
        );
        expect(
          find.descendant(of: matrix, matching: find.text('平 1')),
          findsOneWidget,
        );
        expect(
          find.descendant(of: matrix, matching: find.text('负 1')),
          findsOneWidget,
        );
        expect(find.textContaining('比较得分'), findsNothing);
        expect(find.textContaining('不败'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
