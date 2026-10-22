import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_score_history.dart';

void main() {
  test('score scale zooms around measured values with equal linear ticks', () {
    final scale = RsiScoreScale.fromRecords([
      {
        'round': 0,
        'scores': {'training': .795, 'validation': .8},
      },
      {
        'round': 1,
        'scores': {'training': .805},
      },
      {
        'round': 2,
        'valid': false,
        'scores': {'test': .1},
      },
    ]);
    expect(scale.minimum, lessThan(.795));
    expect(scale.maximum, greaterThan(.805));
    expect(scale.maximum - scale.minimum, lessThan(.15));
    final ticks = scale.ticks;
    for (var i = 1; i < ticks.length; i++) {
      expect(ticks[i] - ticks[i - 1], closeTo(scale.step, 1e-9));
    }
    expect(
      scale.fraction(.805) - scale.fraction(.795),
      closeTo(2 * (scale.fraction(.8) - scale.fraction(.795)), 1e-9),
    );
    expect(scale.label(0), '0');
    expect(scale.label(.8), '0.8');
  });
  test('score scale handles a single point, both score limits and no data', () {
    for (final value in [0.0, .8, 1.0]) {
      final scale = RsiScoreScale.fromRecords([
        {
          'scores': {'training': value},
        },
      ]);
      expect(scale.minimum, inInclusiveRange(0, value));
      expect(scale.maximum, inInclusiveRange(value, 1));
      expect(scale.maximum, greaterThan(scale.minimum));
      expect(scale.fraction(value).isFinite, isTrue);
    }
    final full = RsiScoreScale.fromRecords([
      {
        'scores': {'training': 0, 'validation': 1},
      },
    ]);
    expect(full.minimum, 0);
    expect(full.maximum, 1);
    final empty = RsiScoreScale.fromRecords([]);
    expect(empty.minimum, 0);
    expect(empty.maximum, 1);
  });
  setUpAll(() async {
    if (Platform.environment['RSI_SCREENSHOT_DIR'] != null) {
      await (FontLoader('SageScreenshot')..addFont(
            File(
              '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ).readAsBytes().then(ByteData.sublistView),
          ))
          .load();
    }
  });
  for (final brightness in Brightness.values) {
    testWidgets(
      'compact trend ${brightness.name} keeps missing and invalid scores absent',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: const Scaffold(
              body: SizedBox(
                width: 330,
                child: RsiScoreTrend(
                  chinese: true,
                  records: [
                    {
                      'round': 0,
                      'scores': {'training': .4, 'validation': .3, 'test': .2},
                    },
                    {
                      'round': 1,
                      'scores': {'training': .6, 'validation': .5},
                    },
                    {
                      'round': 2,
                      'valid': false,
                      'scores': {'training': .8, 'validation': .7, 'test': .99},
                    },
                  ],
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('训练集 0.800'), findsOneWidget);
        expect(find.text('验证集 0.700'), findsOneWidget);
        expect(find.text('测试集 —'), findsOneWidget);
        expect(find.text('R0'), findsOneWidget);
        expect(find.text('R2'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(
          const MaterialApp(home: RsiScoreTrend(records: [], chinese: true)),
        );
        await tester.pumpAndSettle();
        expect(find.text('训练集 —'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
    testWidgets(
      'controlled round has no duplicate trend or selector ${brightness.name}',
      (tester) async {
        Future<void> render(int round) => tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: RsiScoreHistory(
                round: round,
                records: [
                  for (var i = 0; i < 2; i++)
                    {
                      'round': i,
                      'valid': true,
                      'scores': {
                        'training': .5,
                        'validation': .5,
                        'test': i.toDouble(),
                      },
                      'cases': [
                        {'id': 'case', 'score': i.toDouble()},
                      ],
                    },
                ],
                settings: const LiquidGlassSettings(blur: 0),
                chinese: true,
              ),
            ),
          ),
        );
        await render(0);
        await tester.pumpAndSettle();
        expect(find.text('测试 test  0.000'), findsOneWidget);
        expect(find.byType(ChoiceChip), findsNothing);
        expect(find.text('0.5'), findsNothing);
        await render(1);
        await tester.pumpAndSettle();
        expect(find.text('测试 test  1.000'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('rsi-history-dot-1-test-case')),
          findsOneWidget,
        );
        await render(2);
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('rsi-three-split-history')),
          findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
    testWidgets(
      'three splits ${brightness.name}: retained rounds, missing test and dot selection',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final records = <Map<String, Object?>>[
          for (var round = 0; round <= 5; round++)
            {
              'round': round,
              'valid': true,
              'status': round == 5 ? 'running' : 'completed',
              'scores': {
                'training': .35 + round * .1,
                'validation': .3 + round * .09,
                'test': round == 5 ? null : .25 + round * .1,
              },
              'development_cases': [
                for (final split in ['training', 'validation'])
                  for (var i = 0; i < 24; i++)
                    {
                      'id': '$split-$i',
                      'split': split,
                      'score': ((i + round * 4) % 25) / 24,
                    },
              ],
              'cases': [
                for (var i = 0; i < 24; i++)
                  {
                    'id': 'test-$i',
                    'score': round == 5 && i > 5
                        ? null
                        : ((i + round * 3) % 25) / 24,
                    'status': round == 5 && i > 5
                        ? (i < 9 ? 'running' : 'queued')
                        : 'completed',
                  },
              ],
            },
        ];
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
                key: const ValueKey('capture'),
                child: ColoredBox(
                  color: brightness == Brightness.dark
                      ? const Color(0xFF101820)
                      : const Color(0xFFF0F4F8),
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Center(
                      child: RsiScoreHistory(
                        records: records,
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
        expect(find.text('测试 test  —'), findsOneWidget);
        expect(find.text('测试 test  6 / 24'), findsOneWidget);
        final pending = tester.widget<AnimatedContainer>(
          find.byKey(const ValueKey('rsi-history-dot-5-test-test-23')),
        );
        final measured = tester.widget<AnimatedContainer>(
          find.byKey(const ValueKey('rsi-history-dot-5-test-test-0')),
        );
        expect(
          (pending.decoration as BoxDecoration).color,
          isNot((measured.decoration as BoxDecoration).color),
        );
        await tester.tap(find.byKey(const ValueKey('rsi-score-round-0')));
        await tester.pumpAndSettle();
        expect(find.text('测试 test  0.250'), findsOneWidget);
        expect(
          find.byKey(const ValueKey('rsi-history-dot-0-training-training-0')),
          findsOneWidget,
        );
        final dir = Platform.environment['RSI_SCREENSHOT_DIR'];
        if (dir != null) {
          await tester.tap(find.byKey(const ValueKey('rsi-score-round-4')));
          await tester.pumpAndSettle();
          final boundary = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(const ValueKey('capture')),
          );
          await tester.runAsync(() async {
            final image = await boundary.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await Directory(dir).create(recursive: true);
            await File(
              '$dir/three-splits-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        tester.view.physicalSize = const Size(375, 900);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      },
    );
  }
}
