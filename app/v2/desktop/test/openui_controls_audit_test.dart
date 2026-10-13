import 'dart:convert';
import 'dart:io';
import 'dart:ui' show PointerDeviceKind;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/ui/openui_charts.dart';
import 'package:sage_desktop_v2/src/ui/openui_extras.dart';
import 'package:sage_desktop_v2/src/ui/openui_image.dart';
import 'package:sage_desktop_v2/src/ui/openui_pill.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';

Widget host(
  Widget child, {
  Brightness brightness = Brightness.light,
  double scale = 1,
}) => MaterialApp(
  theme: sageDesktopTheme(brightness),
  builder: (context, child) => MediaQuery(
    data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
    child: child!,
  ),
  home: Scaffold(
    body: SingleChildScrollView(
      child: Padding(padding: const EdgeInsets.all(16), child: child),
    ),
  ),
);

Map chart(String type, {int count = 3, int seriesCount = 2}) => {
  'type': type,
  'title': 'Chart',
  'labels': List.generate(count, (i) => 'Category $i'),
  'series': List.generate(
    seriesCount,
    (i) => {
      'name': 'Series $i',
      'values': List.generate(count, (j) => 10 + i * 5 + j * 10),
    },
  ),
};

void main() {
  test(
    'bar geometry uses group centers for labels and hit regions at all widths',
    () {
      for (final width in [180.0, 360.0, 1000.0]) {
        for (final count in [1, 2, 3, 10, 100]) {
          final g = OpenUiChartGeometry(Size(width, 240), count, 'bar');
          final slot = (width - 54) / count;
          for (var j = 0; j < count; j++) {
            expect(g.categoryX(j), closeTo(42 + (j + .5) * slot, .00001));
            for (final series in [1, 2, 8]) {
              for (var k = 0; k < series; k++) {
                // Use the actual bar center, including a single-series chart.
                expect(g.hit(Offset(g.barCenter(j, k, series), 100)), j);
              }
            }
          }
          expect(g.hit(const Offset(10, 100)), isNull);
          expect(g.hit(Offset(g.categoryX(0), 230)), isNull);
        }
      }
    },
  );

  test(
    'ring hit testing excludes hole, outside, zero slices and zero totals',
    () {
      const g = OpenUiChartGeometry(Size(400, 240), 3, 'pie');
      expect(g.hit(g.center, pieValues: [1, 2, 3]), isNull);
      expect(g.hit(const Offset(0, 0), pieValues: [1, 2, 3]), isNull);
      expect(g.hit(g.center + Offset(0, -g.radius), pieValues: [0, 1, 1]), 1);
      expect(
        g.hit(g.center + Offset(g.radius, 0), pieValues: [0, 0, 0]),
        isNull,
      );
    },
  );

  for (final brightness in Brightness.values) {
    testWidgets(
      'chart hover, exit, legend and keyboard follow data in ${brightness.name}',
      (tester) async {
        await tester.pumpWidget(
          host(OpenUiChart(props: chart('bar')), brightness: brightness),
        );
        final plot = find.byKey(const ValueKey('openui-chart-plot'));
        final origin = tester.getTopLeft(plot);
        final g = OpenUiChartGeometry(tester.getSize(plot), 3, 'bar');
        final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
        await mouse.addPointer(location: Offset.zero);
        for (var j = 0; j < 3; j++) {
          for (var k = 0; k < 2; k++) {
            await mouse.moveTo(origin + Offset(g.barCenter(j, k, 2), 100));
            await tester.pump();
            expect(
              find.text(
                'Category $j · Series 0 ${10 + j * 10} · Series 1 ${15 + j * 10}',
              ),
              findsOneWidget,
            );
          }
        }
        await mouse.moveTo(const Offset(1, 1));
        await tester.pump();
        expect(find.textContaining(' · Series 0'), findsNothing);
        await tester.tapAt(origin + Offset(g.categoryX(0), 100));
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
        await tester.pump();
        expect(find.textContaining('Category 1 ·'), findsOneWidget);
        await tester.sendKeyEvent(LogicalKeyboardKey.end);
        await tester.pump();
        expect(find.textContaining('Category 2 ·'), findsOneWidget);
        await tester.sendKeyEvent(LogicalKeyboardKey.escape);
        await tester.pump();
        expect(find.textContaining(' · Series 0'), findsNothing);
        await tester.tap(find.byKey(const ValueKey('openui-series:0')));
        await mouse.moveTo(origin + Offset(g.barCenter(0, 0, 1), 100));
        await tester.pump();
        expect(find.text('Category 0 · Series 1 15'), findsOneWidget);
        await mouse.removePointer();
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'all 31 components at enlarged text and narrow width ${brightness.name}',
      (tester) async {
        tester.view.physicalSize = const Size(360, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final fixtures =
            jsonDecode(
                  File('test/fixtures/openui_gallery.json').readAsStringSync(),
                )
                as List;
        final seen = <String>{};
        void visit(Map node) {
          seen.add(node['component'] as String);
          for (final child
              in (node['props']['children'] as List? ?? []).whereType<Map>()) {
            visit(child);
          }
        }

        for (final fixture in fixtures) {
          final surface = Map<String, Object?>.from(fixture['surface']);
          visit(surface['tree'] as Map);
          await tester.pumpWidget(
            host(
              OpenUiSurface(
                key: ValueKey(fixture['name']),
                surface: surface,
                enabled: false,
              ),
              brightness: brightness,
              scale: 1.5,
            ),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull, reason: fixture['name']);
        }
        expect(seen.length, 31);
      },
    );
  }

  testWidgets(
    'incomplete charts, zero/negative data and chart replacement are safe',
    (tester) async {
      for (final type in ['line', 'bar', 'pie']) {
        for (final values in [
          <num>[0, 0, 0],
          <num>[-10, 0, 20],
          [null, 1, 2],
        ]) {
          await tester.pumpWidget(
            host(
              OpenUiChart(
                props: {
                  ...chart(type),
                  'series': [
                    {'name': 'Changing', 'values': values},
                  ],
                },
              ),
            ),
          );
          await tester.pump();
          expect(tester.takeException(), isNull);
        }
      }
      await tester.pumpWidget(host(OpenUiChart(props: chart('bar'))));
      await tester.tap(find.byKey(const ValueKey('openui-series:0')));
      await tester.pump();
      await tester.pumpWidget(
        host(OpenUiChart(props: chart('line', count: 1))),
      );
      expect(
        tester
            .widget<OpenUiPill>(find.byKey(const ValueKey('openui-series:0')))
            .selected,
        isTrue,
      );
      final plot = find.byKey(const ValueKey('openui-chart-plot'));
      await tester.tapAt(tester.getCenter(plot));
      await tester.pump();
      expect(find.textContaining('Category 0 ·'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('disabled form and stale callbacks cannot mutate draft state', (
    tester,
  ) async {
    final fixtures =
        jsonDecode(File('test/fixtures/openui_gallery.json').readAsStringSync())
            as List;
    final surface = Map<String, Object?>.from(
      fixtures.firstWhere((f) => f['name'] == 'form')['surface'],
    );
    var changes = 0;
    Future<void> pump(bool enabled) => tester.pumpWidget(
      host(
        OpenUiSurface(
          key: const ValueKey('form'),
          surface: surface,
          enabled: enabled,
          onDraftChanged: (_) {
            changes++;
          },
        ),
      ),
    );
    await pump(true);
    final staleCallback = tester
        .widget<GlassSwitch>(
          find.byKey(const ValueKey('openui-field:insurance')),
        )
        .onChanged;
    await pump(false);
    staleCallback(false);
    await tester.tap(find.byKey(const ValueKey('openui-option:interests:美食')));
    await tester.pump();
    expect(changes, 0);
    for (final button in tester.widgetList<GlassButton>(
      find.byType(GlassButton),
    )) {
      expect(button.enabled, isFalse);
    }
    expect(tester.takeException(), isNull);
  });

  testWidgets('minimum-height image fallback fits long alt text', (
    tester,
  ) async {
    await tester.pumpWidget(
      host(
        const SizedBox(
          width: 200,
          child: OpenUiImage(
            url: '',
            alt: 'A long descriptive alternative text spanning several lines',
            height: 80,
            ready: false,
          ),
        ),
        scale: 1.5,
      ),
    );
    expect(tester.takeException(), isNull);
  });

  const screenshotPath = String.fromEnvironment('OPENUI_AUDIT_SCREENSHOTS');
  testWidgets(
    'capture corrected grouped-bar hover in both themes',
    (tester) async {
      const fontPath = String.fromEnvironment('OPENUI_FONT');
      if (fontPath.isNotEmpty) {
        final loader = FontLoader('AuditFont')
          ..addFont(
            Future.value(
              ByteData.sublistView(File(fontPath).readAsBytesSync()),
            ),
          );
        await tester.runAsync(loader.load);
      }
      final icons = FontLoader('MaterialIcons')
        ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
      await tester.runAsync(icons.load);
      final data = {
        'title': 'Membership plans',
        'type': 'bar',
        'labels': ['Basic', 'Pro', 'Team'],
        'series': [
          {
            'name': 'Monthly price',
            'values': [0, 99, 299],
          },
          {
            'name': 'Per person',
            'values': [0, 19.8, 14.95],
          },
        ],
      };
      for (final brightness in Brightness.values) {
        final boundary = GlobalKey();
        var theme = sageDesktopTheme(brightness);
        if (fontPath.isNotEmpty) {
          theme = theme.copyWith(
            textTheme: theme.textTheme.apply(fontFamily: 'AuditFont'),
          );
        }
        await tester.pumpWidget(
          MaterialApp(
            theme: theme,
            home: Scaffold(
              body: RepaintBoundary(
                key: boundary,
                child: ColoredBox(
                  color: theme.colorScheme.surface,
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: OpenUiChart(props: data),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final plot = find.byKey(const ValueKey('openui-chart-plot'));
        final geometry = OpenUiChartGeometry(tester.getSize(plot), 3, 'bar');
        final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
        await mouse.addPointer(location: Offset.zero);
        await mouse.moveTo(
          tester.getTopLeft(plot) + Offset(geometry.barCenter(2, 0, 2), 100),
        );
        await tester.pumpAndSettle();
        expect(
          find.text('Team · Monthly price 299 · Per person 14.95'),
          findsOneWidget,
        );
        await tester.runAsync(() async {
          final image =
              await (boundary.currentContext!.findRenderObject()!
                      as RenderRepaintBoundary)
                  .toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File(
            '$screenshotPath/chart-${brightness.name}.png',
          ).writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
        await mouse.removePointer();
        expect(tester.takeException(), isNull);
      }
    },
    skip: screenshotPath.isEmpty,
  );

  test('fractional slider labels preserve the selected precision', () {
    expect(openUiNumberLabel(.001), '0.001');
    expect(openUiNumberLabel(2.5), '2.5');
    expect(openUiNumberLabel(12000), '12000');
    expect(openUiNumberLabel(999999999999.5), '999999999999.5');
    expect(openUiNumberLabel(.1 + .2), '0.3');
  });
}
