import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_pairwise_summary.dart';

Map<String, Object?> grade(String outcome) => {
  'scorer_details': {
    'pairwise': {'outcome': outcome},
  },
};

void main() {
  test('neutral placeholders and mixed repeats are never inferred as ties', () {
    for (final marker in ['reference', 'pending']) {
      final neutral = <String, Object?>{
        'score': .5,
        'scorer_details': {
          'pairwise': {marker: true},
        },
      };
      expect(rsiPairwiseCounts(neutral), {'wins': 0, 'ties': 0, 'losses': 0});
      expect(
        rsiPairwiseLabel(neutral, true),
        marker == 'reference' ? '基线' : '待比较',
      );
    }
    final mixed = <String, Object?>{
      'score': .5,
      'scorer_details': {
        'pairwise_summary': {'wins': 1, 'ties': 0, 'losses': 1},
      },
    };
    expect(rsiPairwiseLabel(mixed, true), '胜 1 / 平 0 / 负 1');
  });
  for (final brightness in [Brightness.light, Brightness.dark]) {
    testWidgets('paired outcomes and incomplete measurements $brightness', (
      tester,
    ) async {
      Future<void> show({int expected = 3, int errors = 0}) =>
          tester.pumpWidget(
            MaterialApp(
              theme: ThemeData(brightness: brightness),
              home: Scaffold(
                body: RsiPairwiseSummary(
                  grades: [grade('win'), grade('tie'), grade('loss')],
                  expectedPairs: expected,
                  errors: errors,
                  settings: const LiquidGlassSettings(),
                  chinese: false,
                ),
              ),
            ),
          );
      await show();
      expect(find.text('Win / Tie / Loss  1 / 1 / 1'), findsOneWidget);
      expect(find.text('Win rate  33.3%'), findsOneWidget);
      expect(find.textContaining('Preference score'), findsNothing);
      await show(expected: 4, errors: 1);
      expect(find.text('Win rate  —'), findsOneWidget);
      expect(find.textContaining('Preference score'), findsNothing);
      expect(find.text('Measurement errors  1'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
