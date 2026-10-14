import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/ui/openui_deck.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';

void main() {
  final fixtures =
      jsonDecode(File('test/fixtures/openui_gallery.json').readAsStringSync())
          as List;
  final deck =
      fixtures.firstWhere((f) => f['name'] == 'slides')['surface']['tree']
          as Map;
  Widget host({
    Brightness brightness = Brightness.light,
    Map? node,
    bool ready = true,
    Future<void> Function(bool)? export,
  }) => MaterialApp(
    theme: sageDesktopTheme(brightness),
    home: Scaffold(
      body: SingleChildScrollView(
        child: OpenUiDeck(node: node ?? deck, ready: ready, onExport: export),
      ),
    ),
  );
  for (final brightness in Brightness.values) {
    for (final width in [360.0, 768.0, 1280.0]) {
      testWidgets('all slides and fullscreen ${brightness.name} $width', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(host(brightness: brightness));
        await tester.pumpAndSettle();
        expect(find.text('1 / 3'), findsOneWidget);
        for (var i = 1; i < 3; i++) {
          await tester.tap(find.byIcon(Icons.chevron_right));
          await tester.pumpAndSettle();
          expect(find.text('${i + 1} / 3'), findsOneWidget);
          expect(tester.takeException(), isNull);
        }
        await tester.tap(find.text('Present'));
        await tester.pumpAndSettle();
        expect(find.byType(Dialog), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.tap(find.byIcon(Icons.close));
        await tester.pumpAndSettle();
      });
    }
  }
  testWidgets(
    'partial updates preserve selection and export waits for completion',
    (tester) async {
      var exports = 0;
      final partial = jsonDecode(jsonEncode(deck)) as Map;
      partial['props']['children'] = [partial['props']['children'][0]];
      partial['props']['children'][0]['props']['children'][0]['props']['content'] =
          'Stream';
      await tester.pumpWidget(
        host(
          node: partial,
          ready: false,
          export: (_) async {
            exports++;
          },
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Stream'), findsOneWidget);
      await tester.tap(find.text('Export PPTX'), warnIfMissed: false);
      expect(exports, 0);
      await tester.pumpWidget(
        host(
          export: (_) async {
            exports++;
          },
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('1 / 3'), findsOneWidget);
      await tester.tap(find.byIcon(Icons.chevron_right));
      await tester.pumpAndSettle();
      await tester.pumpWidget(
        host(
          node: jsonDecode(jsonEncode(deck)),
          export: (_) async {
            exports++;
          },
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('2 / 3'), findsOneWidget);
      await tester.tap(find.text('Export PPTX'));
      await tester.pumpAndSettle();
      expect(exports, 1);
    },
  );
  testWidgets(
    'invalid deck preview can still open in sidebar without enabling export',
    (tester) async {
      var expanded = 0;
      var exported = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: OpenUiSurface(
                surface: {
                  'tree': deck,
                  'complete': false,
                  'error': 'Unsupported slide block',
                },
                enabled: false,
                onExpand: () => expanded++,
                onExport: (_) async {
                  exported++;
                },
                onSubmit: (_, _) async {},
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('openui-open-in-sidebar')));
      await tester.tap(find.text('Export PPTX'), warnIfMissed: false);
      expect(expanded, 1);
      expect(exported, 0);
    },
  );
  for (final brightness in Brightness.values) {
    for (final width in [360.0, 640.0, 1100.0]) {
      testWidgets('workspace thumbnails and canvas ${brightness.name} $width', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        var theme = sageDesktopTheme(brightness);
        const output = String.fromEnvironment('OPENUI_WORKSPACE_SCREENSHOTS');
        if (output.isNotEmpty) {
          final font = FontLoader('SlidePreview')
            ..addFont(
              Future.value(
                ByteData.sublistView(
                  File(
                    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
                  ).readAsBytesSync(),
                ),
              ),
            );
          await tester.runAsync(font.load);
          final icons = FontLoader('MaterialIcons')
            ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
          await tester.runAsync(icons.load);
          theme = theme.copyWith(
            textTheme: theme.textTheme.apply(fontFamily: 'SlidePreview'),
          );
        }
        final boundary = GlobalKey();
        var exports = 0;
        await tester.pumpWidget(
          MaterialApp(
            theme: theme,
            home: Scaffold(
              body: RepaintBoundary(
                key: boundary,
                child: OpenUiDeck(
                  node: deck,
                  ready: true,
                  workspace: true,
                  onExport: (_) async {
                    exports++;
                  },
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('openui-slide-thumbnails')),
          findsOneWidget,
        );
        expect(find.text('1 / 3'), findsOneWidget);
        if (output.isNotEmpty && width == 640) {
          final render =
              boundary.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary;
          await tester.runAsync(() async {
            final image = await render.toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '$output/workspace-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        await tester.tap(
          find.byKey(const ValueKey('openui-slide-thumbnail:2')),
        );
        await tester.pumpAndSettle();
        expect(find.text('3 / 3'), findsOneWidget);
        final canvas = tester.widget<OpenUiSlideCanvas>(
          find.byKey(const ValueKey('openui-workspace-canvas')),
        );
        expect(canvas.index, 2);
        await tester.tap(find.byIcon(Icons.chevron_left));
        await tester.pumpAndSettle();
        expect(find.text('2 / 3'), findsOneWidget);
        await tester.tap(find.text('Export PPTX'));
        await tester.pumpAndSettle();
        expect(exports, 1);
        expect(tester.takeException(), isNull);
      });
    }
  }
  const livePath = String.fromEnvironment('OPENUI_FIXTURES');
  testWidgets(
    'live-model slide pages in both themes and three widths',
    (tester) async {
      final font = FontLoader('SlidePreview')
        ..addFont(
          Future.value(
            ByteData.sublistView(
              File(
                '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
              ).readAsBytesSync(),
            ),
          ),
        );
      await tester.runAsync(font.load);
      final icons = FontLoader('MaterialIcons')
        ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
      await tester.runAsync(icons.load);
      final live = jsonDecode(File(livePath).readAsStringSync()) as List;
      const output = String.fromEnvironment('OPENUI_SCREENSHOTS');
      for (final fixture in live) {
        final pages = fixture['surface']['tree']['props']['children'] as List;
        for (final brightness in Brightness.values) {
          final base = sageDesktopTheme(brightness);
          final theme = base.copyWith(
            textTheme: base.textTheme.apply(fontFamily: 'SlidePreview'),
          );
          for (final width in [360.0, 768.0, 1280.0]) {
            tester.view.physicalSize = Size(width, 900);
            tester.view.devicePixelRatio = 1;
            for (var i = 0; i < pages.length; i++) {
              final boundary = GlobalKey();
              await tester.pumpWidget(
                MaterialApp(
                  theme: theme,
                  home: Scaffold(
                    body: Center(
                      child: RepaintBoundary(
                        key: boundary,
                        child: AspectRatio(
                          aspectRatio: 16 / 9,
                          child: OpenUiSlideCanvas(node: pages[i], index: i),
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
                    '${fixture['model']} slide $i ${brightness.name} $width',
              );
              if (output.isNotEmpty &&
                  fixture['model'] == 'gpt-6.1-sol' &&
                  width == 1280) {
                final render =
                    boundary.currentContext!.findRenderObject()!
                        as RenderRepaintBoundary;
                await tester.runAsync(() async {
                  final image = await render.toImage();
                  final bytes = await image.toByteData(
                    format: ui.ImageByteFormat.png,
                  );
                  await File(
                    '$output/slide-${i + 1}-${brightness.name}.png',
                  ).writeAsBytes(bytes!.buffer.asUint8List());
                  image.dispose();
                });
              }
            }
          }
        }
      }
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    },
    skip: livePath.isEmpty,
  );
}
