import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';
import 'package:sage_desktop_v2/src/app.dart';

// Opt-in fixtures contain synthetic, real-model responses; no credentials.
void main() {
  const fixturesPath = String.fromEnvironment('OPENUI_FIXTURES');
  testWidgets(
    'real model surfaces render in both themes and desktop widths',
    (tester) async {
      const fontPath = String.fromEnvironment('OPENUI_FONT');
      if (fontPath.isNotEmpty) {
        final loader = FontLoader('LivePreview')
          ..addFont(
            Future.value(
              ByteData.sublistView(File(fontPath).readAsBytesSync()),
            ),
          );
        await tester.runAsync(loader.load);
      }
      final icons = FontLoader("MaterialIcons")
        ..addFont(rootBundle.load("fonts/MaterialIcons-Regular.otf"));
      await tester.runAsync(icons.load);
      const screenshotsPath = String.fromEnvironment("OPENUI_SCREENSHOTS");
      const screenshotModel = String.fromEnvironment(
        'OPENUI_SCREENSHOT_MODEL', defaultValue: 'gpt-6.1-sol');
      final fixtures =
          jsonDecode(File(fixturesPath).readAsStringSync()) as List;
      final boundary = GlobalKey();
      for (final fixture in fixtures) {
        for (final brightness in Brightness.values) {
          var theme = sageDesktopTheme(brightness);
          if (fontPath.isNotEmpty) {
            theme = theme.copyWith(
              textTheme: theme.textTheme.apply(fontFamily: 'LivePreview'),
            );
          }
          for (final width in [360.0, 480.0, 1000.0]) {
            tester.view.physicalSize = Size(width, 900);
            tester.view.devicePixelRatio = 1;
            await tester.pumpWidget(
              MaterialApp(
                theme: theme,
                home: Scaffold(
                  body: SingleChildScrollView(
                    child: RepaintBoundary(
                      key: boundary,
                      child: ColoredBox(
                        color: theme.colorScheme.surface,
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: OpenUiSurface(
                            key: ValueKey(
                              '${fixture['model']}-${fixture['case']}-$brightness-$width',
                            ),
                            surface: Map<String, Object?>.from(
                              fixture['surface'],
                            ),
                            enabled: true,
                            onSubmit: (_, _) async {},
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            );
            await tester.pumpAndSettle();
            expect(
              tester.takeException(),
              isNull,
              reason:
                  '${fixture['model']} ${fixture['case']} $brightness $width',
            );
            if (screenshotsPath.isNotEmpty &&
                width == 1000 &&
                fixture['model'] == screenshotModel) {
              final render =
                  boundary.currentContext!.findRenderObject()!
                      as RenderRepaintBoundary;
              await tester.runAsync(() async {
                final image = await render.toImage();
                final bytes = await image.toByteData(
                  format: ui.ImageByteFormat.png,
                );
                await File(
                  '$screenshotsPath/${fixture['case']}-${brightness.name}.png',
                ).writeAsBytes(bytes!.buffer.asUint8List());
                image.dispose();
              });
            }
          }
        }
      }
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    },
    skip: fixturesPath.isEmpty,
  );
}
