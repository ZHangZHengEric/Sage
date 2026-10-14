import 'dart:convert';
import 'dart:async';
import 'dart:io';
import 'dart:ui' show PointerDeviceKind;
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';
import 'package:sage_desktop_v2/src/ui/openui_extras.dart';
import 'package:sage_desktop_v2/src/ui/openui_image.dart';
import 'package:sage_desktop_v2/src/ui/openui_pill.dart';
import 'package:sage_desktop_v2/src/ui/openui_charts.dart';

void main() {
  final fixtures =
      (jsonDecode(File('test/fixtures/openui_gallery.json').readAsStringSync())
              as List)
          .cast<Map>();
  Map<String, Object?> surface(String name) => Map<String, Object?>.from(
    fixtures.firstWhere((f) => f['name'] == name)['surface'],
  );
  Widget host(
    Map<String, Object?> data, {
    Brightness brightness = Brightness.light,
    Future<void> Function(String, Map<String, Object?>)? submit,
    ValueChanged<Map<String, Object?>>? draft,
  }) => MaterialApp(
    theme: sageDesktopTheme(brightness),
    home: Scaffold(
      body: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: OpenUiSurface(
            surface: data,
            enabled: true,
            onSubmit: submit,
            onDraftChanged: draft,
          ),
        ),
      ),
    ),
  );
  test('bounded computations handle field references and invalid input', () {
    expect(openUiCompute('sum', [1, 2, 3], {}), 6);
    expect(openUiCompute('product', [2, 3], {}), 6);
    expect(openUiCompute('difference', [8, 3], {}), 5);
    expect(openUiCompute('divide', [10, 2], {}), 5);
    expect(openUiCompute('percent', [200, 15], {}), 30);
    expect(
      openUiCompute(
        'compoundGrowth',
        ['p', 'r', 'y'],
        {'p': 10000, 'r': 5, 'y': 10},
      ),
      closeTo(16288.946, 0.001),
    );
    expect(openUiCompute('loanPayment', [12000, 0, 12], {}), 1000);
    expect(
      openUiCompute('loanPayment', [100000, 6, 360], {}),
      closeTo(599.55, 0.01),
    );
    for (final inputs in [
      [1, 0],
      [1],
      [double.nan, 2],
      ['missing', 2],
    ]) {
      expect(openUiCompute('divide', inputs, {}), isNull);
    }
    expect(openUiCompute('compoundGrowth', [10000, 1000, 1000], {}), isNull);
    expect(openUiCompute('eval', [1], {}), isNull);
  });
  testWidgets('images wait for validation, decode, and discard old URL content', (
    tester,
  ) async {
    var reads = 0;
    final png = base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==',
    );
    final pending = Completer<Uint8List>();
    Future<Uint8List> loader(String url) {
      reads++;
      return url.endsWith('a.png') ? Future.value(png) : pending.future;
    }

    Widget image(String url, bool ready) => MaterialApp(
      home: Scaffold(
        body: OpenUiImage(
          url: url,
          alt: 'Preview',
          height: 180,
          ready: ready,
          loadBytes: loader,
        ),
      ),
    );
    await tester.pumpWidget(image('https://example.com/a.png', false));
    await tester.pumpAndSettle();
    expect(reads, 0);
    expect(find.byType(Image), findsNothing);
    await tester.pumpWidget(image('https://example.com/a.png', true));
    await tester.pumpAndSettle();
    expect(reads, 1);
    expect(find.byType(Image), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(image('https://example.com/b.png', true));
    await tester.pumpAndSettle();
    expect(reads, 2);
    expect(find.byType(Image), findsNothing);
    pending.completeError(const FormatException('Unavailable image'));
    await tester.pumpAndSettle();
    expect(find.text('Preview'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  test('images permit HTTPS public URL shapes only', () {
    for (final url in [
      'http://example.com/a.png',
      'https://127.0.0.1/a.png',
      'https://198.18.1.2/a.png',
      'file:///etc/passwd',
      'https://localhost/a',
      'https://host.local/a',
      'https://u:p@example.com/a',
      'https://example.com:8000/a',
    ]) {
      expect(openUiPublicImageUrl(Uri.parse(url)), isFalse);
    }
    expect(
      openUiPublicImageUrl(Uri.parse('https://example.com/a.png')),
      isTrue,
    );
  });
  for (final brightness in Brightness.values) {
    for (final width in [360.0, 480.0, 1000.0]) {
      testWidgets('expanded gallery ${brightness.name} at $width', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        for (final f in fixtures) {
          await tester.pumpWidget(
            host(
              Map<String, Object?>.from(f['surface']),
              brightness: brightness,
            ),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull, reason: f['name']);
        }
      });
    }
  }
  for (final brightness in Brightness.values) {
    testWidgets('expanded long labels at narrow width ${brightness.name}', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(360, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final long = List.filled(20, '很长的组件标签 Long label ').join();
      for (final original in fixtures) {
        final fixture = jsonDecode(jsonEncode(original)) as Map;
        void visit(Map node) {
          final props = node['props'] as Map;
          for (final key in ['label', 'title', 'content', 'alt', 'change']) {
            if (props[key] is String && (props[key] as String).isNotEmpty) {
              props[key] = long;
            }
          }
          if (props['children'] is List) {
            for (final child in (props['children'] as List).whereType<Map>()) {
              visit(child);
            }
          }
          if (props['series'] is List) {
            for (final series in (props['series'] as List).whereType<Map>()) {
              series['name'] = long;
            }
          }
          if (props['items'] is List) {
            for (final item in (props['items'] as List).whereType<Map>()) {
              item['label'] = long;
            }
          }
          if (props['nodes'] is List) {
            for (final item in (props['nodes'] as List).whereType<Map>()) {
              item['label'] = long;
            }
          }
        }

        visit(fixture['surface']['tree'] as Map);
        await tester.pumpWidget(
          host(
            Map<String, Object?>.from(fixture['surface']),
            brightness: brightness,
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull, reason: original['name']);
      }
    });
  }
  for (final brightness in Brightness.values) {
    testWidgets(
      'chained results and chart update together in ${brightness.name}',
      (tester) async {
        var submitted = 0;
        await tester.pumpWidget(
          host(
            surface('chained-calculator'),
            brightness: brightness,
            submit: (_, _) async {
              submitted++;
            },
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('¥6000.00'), findsOneWidget);
        expect(find.text('¥1500.00'), findsOneWidget);
        List chartValues() =>
            (tester
                            .widget<OpenUiChart>(find.byType(OpenUiChart))
                            .props['series']
                        as List)
                    .first['values']
                as List;
        expect(chartValues(), [3000, 3000]);
        final people = find.descendant(
          of: find.byKey(const ValueKey('openui-field:people')),
          matching: find.byType(EditableText),
        );
        await tester.enterText(people, '2');
        await tester.pumpAndSettle();
        expect(find.text('¥4500.00'), findsOneWidget);
        expect(find.text('¥2250.00'), findsOneWidget);
        expect(chartValues(), [3000, 1500]);
        expect(submitted, 0);
        expect(tester.takeException(), isNull);
      },
    );
  }
  test(
    'calculation dependencies stop at cycles, division by zero and oversized graphs',
    () {
      Map calc(String operation, List inputs) => {
        'component': 'Computed',
        'props': {'operation': operation, 'inputs': inputs},
      };
      expect(
        openUiCompute(
          'sum',
          ['a'],
          {
            'a': calc('sum', ['b']),
            'b': calc('sum', ['a']),
          },
        ),
        isNull,
      );
      expect(
        openUiCompute('sum', [
          calc('divide', [1, 0]),
        ], {}),
        isNull,
      );
      expect(
        openUiCompute('sum', [
          calc('product', [2, 3]),
          1,
        ], {}),
        7,
      );
      final graph = <String, Object?>{};
      for (var i = 0; i < 20; i++) {
        graph['n$i'] = calc('sum', List.filled(16, 'n${i + 1}'));
      }
      graph['n20'] = 1;
      expect(openUiNumeric('n0', graph), isNull);
    },
  );
  testWidgets(
    'numeric edits and slider drags update results locally without submitting',
    (tester) async {
      var submitted = 0;
      Map<String, Object?>? payload;
      await tester.pumpWidget(
        host(
          surface('calculator'),
          submit: (a, v) async {
            submitted++;
            payload = v;
          },
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('¥16288.95'), findsOneWidget);
      await tester.enterText(find.byType(EditableText), '20000');
      await tester.pumpAndSettle();
      expect(find.text('¥32577.89'), findsOneWidget);
      expect(
        (tester.widget<OpenUiChart>(find.byType(OpenUiChart)).props['series']
                as List)
            .first['values'],
        [20000],
      );
      expect(submitted, 0);
      await tester.drag(
        find.byKey(const ValueKey('openui-field:rate')),
        const Offset(80, 0),
      );
      await tester.pumpAndSettle();
      final sliders = tester
          .widgetList<GlassSlider>(find.byType(GlassSlider))
          .toList();
      expect(sliders.first.value, greaterThan(5));
      final expected = (20000 * math.pow(1 + sliders.first.value / 100, 10))
          .toStringAsFixed(2);
      expect(find.text('¥$expected'), findsOneWidget);
      expect(submitted, 0);
      await tester.ensureVisible(
        find.byKey(const ValueKey('openui-action:save')),
      );
      await tester.tap(find.byKey(const ValueKey('openui-action:save')));
      await tester.pumpAndSettle();
      expect(submitted, 1);
      expect(payload!['principal'], 20000);
      expect(payload!['rate'], sliders.first.value);
      expect(payload!.length, 3);
    },
  );
  testWidgets('tabs respond to keyboard activation', (tester) async {
    await tester.pumpWidget(host(surface('tabs')));
    await tester.pumpAndSettle();
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(find.text('准备'), findsOneWidget);
  });
  testWidgets('tabs and accordion reveal content in place', (tester) async {
    await tester.pumpWidget(host(surface('tabs')));
    await tester.pumpAndSettle();
    expect(find.text('方案'), findsOneWidget);
    expect(find.text('确认需求'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('openui-tab:1')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('准备'));
    await tester.pumpAndSettle();
    expect(find.text('确认需求'), findsOneWidget);
    await tester.tap(find.text('发布'));
    await tester.pumpAndSettle();
    expect(find.text('已完成'), findsOneWidget);
  });
  testWidgets('multi-choice, radio, and date submit typed values', (
    tester,
  ) async {
    Map<String, Object?>? payload;
    await tester.pumpWidget(
      host(
        surface('form'),
        submit: (a, v) async {
          payload = v;
        },
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('openui-option:interests:美食')),
    );
    await tester.tap(find.byKey(const ValueKey('openui-option:interests:美食')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('openui-option:pace:紧凑')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('openui-field:date')));
    await tester.tap(find.byKey(const ValueKey('openui-field:date')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('7'));
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('openui-action:plan')),
    );
    await tester.tap(find.byKey(const ValueKey('openui-action:plan')));
    await tester.pumpAndSettle();
    expect(payload!['interests'], ['艺术', '美食']);
    expect(payload!['pace'], '紧凑');
    expect(payload!['date'], '2026-11-07');
  });
  testWidgets('chart toggles and hover preserve a visible series', (
    tester,
  ) async {
    await tester.pumpWidget(host(surface('bar')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('openui-series:0')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('openui-series:1')));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<OpenUiPill>(find.byKey(const ValueKey('openui-series:1')))
          .selected,
      isTrue,
    );
    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: const Offset(150, 120));
    await gesture.moveTo(const Offset(200, 180));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await gesture.removePointer();
  });
}
