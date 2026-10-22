// Opt-in rendering of saved real benchmark evidence. No model calls or mock scores.
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_score_history.dart';

void main() {
  final evidence = Platform.environment['RSI_TAU_EVIDENCE'];
  final output = Platform.environment['RSI_TAU_CAPTURE'];
  setUpAll(() async {
    if (evidence != null && output != null) {
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
      'render real tau checkpoints ${brightness.name}',
      (tester) async {
        final records =
            (jsonDecode(
                      File(
                        '$evidence/human-test-checkpoints.json',
                      ).readAsStringSync(),
                    )
                    as List)
                .cast<Map>()
                .map((r) => r.cast<String, Object?>())
                .toList();
        expect(records, isNotEmpty);
        expect(
          records.every((r) => (r['package_hash'] as String).length == 64),
          isTrue,
        );
        tester.view.physicalSize = const Size(1600, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final dark = brightness == Brightness.dark;
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(
              brightness: brightness,
              fontFamily: 'SageScreenshot',
            ),
            home: Scaffold(
              body: RepaintBoundary(
                key: const ValueKey('capture'),
                child: ColoredBox(
                  color: dark
                      ? const Color(0xFF101820)
                      : const Color(0xFFF0F4F8),
                  child: Padding(
                    padding: const EdgeInsets.all(36),
                    child: Center(
                      child: RsiScoreHistory(
                        records: records,
                        settings: LiquidGlassSettings(
                          blur: 0,
                          glassColor: dark
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
        expect(tester.takeException(), isNull);
        final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byKey(const ValueKey('capture')),
        );
        await tester.runAsync(() async {
          final pixels = await boundary.toImage();
          final bytes = await pixels.toByteData(format: ui.ImageByteFormat.png);
          await Directory(output!).create(recursive: true);
          await File(
            '$output/tau-checkpoints-${brightness.name}.png',
          ).writeAsBytes(bytes!.buffer.asUint8List());
          pixels.dispose();
          // Capture the exact read snapshot alongside its pixels.
          await File(
            '$output/tau-checkpoints-${brightness.name}.json',
          ).writeAsString(jsonEncode(records));
        });
        // Replay saved checkpoints through the real round selector. This is a
        // checkpoint walkthrough, not a recording of live benchmark execution.
        for (var index = 0; index < records.length; index++) {
          final round = records[index]['round'];
          await tester.tap(find.byKey(ValueKey('rsi-score-round-$round')));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          expect(
            tester
                .widget<ChoiceChip>(
                  find.byKey(ValueKey('rsi-score-round-$round')),
                )
                .selected,
            isTrue,
          );
          await tester.runAsync(() async {
            final pixels = await boundary.toImage();
            final bytes = await pixels.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$output/tau-round-${brightness.name}-${index.toString().padLeft(3, '0')}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            pixels.dispose();
          });
        }
      },
      skip: evidence == null || output == null,
    );
  }
}
