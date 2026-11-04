import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';
import 'package:sage_desktop_v2/src/ui/rsi_round_comparison.dart';
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
                    'recommended_hash': 'recommended',
                    'retained_hash': 'recommended',
                    'result': {
                      'iterations': [
                        {
                          'iteration': 1,
                          'recommended': true,
                          'evaluation': {'package_hash': 'recommended'},
                        },
                      ],
                    },
                    'builtin_scoring': {'mode': 'pairwise'},
                    'test_observations': [
                      {
                        'round': 1,
                        'package_hash': 'recommended',
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
                      {
                        'round': 2,
                        'valid': true,
                        'status': 'error',
                        'repeats': 2,
                        'cases': [
                          {'id': 'one'},
                          {'id': 'two'},
                        ],
                        'pairwise': {
                          'wins': 2,
                          'ties': 1,
                          'losses': 0,
                          'pairs': 3,
                          'complete': false,
                          'errors': 1,
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
        expect(find.byKey(const ValueKey('rsi-score-trend')), findsNothing);
        final comparison = tester.widget<RsiRoundComparisons>(
          find.byType(RsiRoundComparisons),
        );
        expect(comparison.rounds.single.opponent, 0);
        expect(comparison.rounds.single.accepted, isTrue);
        expect(comparison.finalTest?.version, 1);
        expect(comparison.finalTest?.results['wins'], 8);
        expect(find.text('验证集 · 第 1 轮候选 vs 基线版本'), findsOneWidget);
        expect(find.text('逐轮采纳 · 验证集'), findsOneWidget);
        final bar = find.byKey(const ValueKey('rsi-comparison-stack-1'));
        expect(tester.widget<Flex>(bar).direction, Axis.vertical);
        expect(tester.getSize(bar).height, 76);
        final roundTooltip = tester.widget<Tooltip>(
          find.byKey(const ValueKey('rsi-comparison-round-1')),
        );
        expect(roundTooltip.message, contains('第 1 轮 vs 原始基线'));
        expect(roundTooltip.message, contains('1 胜'));
        expect(find.text('最终 Test'), findsOneWidget);
        expect(find.text('逐轮 Test · 对原始基线'), findsOneWidget);
        final checkpointBar = find.byKey(
          const ValueKey('rsi-test-checkpoint-slot-1'),
        );
        expect(tester.getCenter(checkpointBar).dx, tester.getCenter(bar).dx);
        expect(
          find.byKey(const ValueKey('rsi-test-checkpoint-trend')),
          findsOneWidget,
        );
        final partialTooltip = tester.widget<Tooltip>(
          find.byKey(const ValueKey('rsi-test-checkpoint-2')),
        );
        expect(partialTooltip.message, contains('R2 检查点'));
        expect(partialTooltip.message, contains('3/4'));
        final testBar = find.byKey(const ValueKey('rsi-final-test-stack'));
        expect(tester.widget<Flex>(testBar).direction, Axis.vertical);
        expect(tester.getTopLeft(testBar).dy, tester.getTopLeft(bar).dy);
        final testTooltip = tester.widget<Tooltip>(
          find.byKey(const ValueKey('rsi-final-test-column')),
        );
        expect(testTooltip.message, contains('第 1 轮 vs 原始基线'));
        expect(testTooltip.message, contains('8 胜 · 1 平 · 1 负'));
        expect(find.text('建议采纳第 1 轮'), findsOneWidget);
        expect(
          tester.widget(find.byKey(const ValueKey('rsi-recommended-round'))),
          isA<TextButton>(),
        );
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('rsi-overview')),
            matching: find.byKey(const ValueKey('rsi-token-usage')),
          ),
          findsOneWidget,
        );
        expect(find.text('候选胜率'), findsNothing);
        expect(find.text('胜率'), findsNothing);
        expect(comparison.tests.last.expected, 4);
        final history = find.byKey(
          const ValueKey('rsi-test-comparison-history'),
        );
        await tester.ensureVisible(history);
        await tester.tap(history);
        await tester.pumpAndSettle();
        expect(find.textContaining('2 胜 · 1 平 · 0 负  ·  3/4'), findsOneWidget);
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
