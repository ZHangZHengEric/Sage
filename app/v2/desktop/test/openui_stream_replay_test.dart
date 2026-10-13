import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';
import 'package:sage_desktop_v2/src/ui/openui_charts.dart';

Map<String, Object?> node(String type, Map<String, Object?> props) => {
  'component': type,
  'props': props,
};
Map<String, Object?> stack(List<Object?> children) =>
    node('Stack', {'children': children});
Widget host(
  Map<String, Object?> surface,
  Brightness brightness, {
  bool enabled = false,
  ValueChanged<Map<String, Object?>>? onDraft,
}) => MaterialApp(
  theme: sageDesktopTheme(brightness),
  home: Scaffold(
    body: SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: OpenUiSurface(
          key: const ValueKey('stable-surface'),
          surface: surface,
          enabled: enabled,
          onDraftChanged: onDraft,
          onSubmit: (_, _) async {},
        ),
      ),
    ),
  ),
);

void main() {
  const sequencesPath = 'test/fixtures/openui_gallery_replay.json';
  testWidgets('all official-parser gallery stream states render', (
    tester,
  ) async {
    final sequences =
        jsonDecode(File(sequencesPath).readAsStringSync()) as List;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    for (final sequence in sequences) {
      for (final brightness in Brightness.values) {
        for (final width in [360.0, 1000.0]) {
          tester.view.physicalSize = Size(width, 900);
          await tester.pumpWidget(const SizedBox.shrink());
          var index = 0;
          for (final frame in sequence['frames'] as List) {
            await tester.pumpWidget(
              host(Map<String, Object?>.from(frame), brightness),
            );
            expect(
              tester.takeException(),
              isNull,
              reason: '${sequence['name']} $brightness $width frame ${index++}',
            );
            expect(find.byType(ErrorWidget), findsNothing);
          }
        }
      }
    }
  });
  testWidgets(
    'real MiMo and GPT calculators update outputs and charts without tools',
    (tester) async {
      final fixtures =
          jsonDecode(
                File(
                  'test/fixtures/openui_live_calculators.json',
                ).readAsStringSync(),
              )
              as List;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      for (final f in fixtures) {
        final coffee = f['case'] == 'coffee';
        final mimo = f['model'] == 'mimo-v2.6-pro';
        final field = coffee
            ? (mimo ? 'cups' : 'daily_sales')
            : (mimo ? 'monthly_amount' : 'monthly_savings');
        final label = coffee ? '月利润' : (mimo ? '期末总额（元）' : '期末总额（不计利息）');
        for (final brightness in Brightness.values) {
          for (final width in [360.0, 1000.0]) {
            tester.view.physicalSize = Size(width, 900);
            await tester.pumpWidget(const SizedBox.shrink());
            await tester.pumpWidget(
              host(
                Map<String, Object?>.from(f['surface']),
                brightness,
                enabled: true,
              ),
            );
            double result() {
              final text = tester
                  .widget<Text>(find.byKey(ValueKey('openui-computed:$label')))
                  .data!;
              return double.parse(text.replaceAll(RegExp(r'[^0-9.\-]'), ''));
            }

            List<num> chartValues() => tester
                .widgetList<OpenUiChart>(find.byType(OpenUiChart))
                .expand(
                  (c) => (c.props['series'] as List).expand(
                    (s) => (s['values'] as List).cast<num>(),
                  ),
                )
                .toList();
            expect(
              result(),
              coffee ? 31000 : 56000,
              reason: '${f['model']} ${f['case']} initial',
            );
            expect(chartValues(), contains(coffee ? 31000 : 36000));
            final input = find.descendant(
              of: find.byKey(ValueKey('openui-field:$field')),
              matching: find.byType(EditableText),
            );
            await tester.ensureVisible(input);
            await tester.enterText(input, coffee ? '120' : '4000');
            await tester.pump();
            expect(result(), coffee ? 41200 : 68000);
            expect(chartValues(), contains(coffee ? 41200 : 48000));
            expect(
              tester.takeException(),
              isNull,
              reason: '${f['model']} ${f['case']} $brightness $width',
            );
          }
        }
      }
    },
  );
  testWidgets('invalid real model streams retain safe disabled previews', (
    tester,
  ) async {
    final sequences =
        jsonDecode(
              File(
                'test/fixtures/openui_rejected_streams.json',
              ).readAsStringSync(),
            )
            as List;
    for (final sequence in sequences) {
      for (final brightness in Brightness.values) {
        await tester.pumpWidget(const SizedBox.shrink());
        for (final frame in sequence['frames'] as List) {
          await tester.pumpWidget(
            host(
              Map<String, Object?>.from(frame),
              brightness,
              enabled: frame['complete'] == true,
            ),
          );
          expect(tester.takeException(), isNull, reason: '${sequence['name']}');
          expect(find.byType(ErrorWidget), findsNothing);
        }
        expect(
          find.text('Generated content failed validation · read-only preview'),
          findsOneWidget,
        );
        expect(
          tester
              .widgetList<GlassTextField>(find.byType(GlassTextField))
              .every((field) => !field.enabled),
          isTrue,
        );
      }
    }
  });
  final replay =
      jsonDecode(
            File('test/fixtures/openui_coffee_replay.json').readAsStringSync(),
          )
          as Map;
  final frames = (replay['frames'] as List)
      .map((v) => Map<String, Object?>.from(v))
      .toList();
  for (final brightness in Brightness.values) {
    testWidgets(
      'actual coffee stream every parser state, resize and edits $brightness',
      (tester) async {
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPhysicalSize);
        for (final width in [360.0, 760.0, 1200.0]) {
          tester.view.physicalSize = Size(width, 900);
          await tester.pumpWidget(const SizedBox.shrink());
          for (var i = 0; i < frames.length; i++) {
            await tester.pumpWidget(host(frames[i], brightness));
            expect(
              tester.takeException(),
              isNull,
              reason: '$width stream frame $i',
            );
            expect(find.byType(ErrorWidget), findsNothing);
          }
          Map<String, Object?>? draft;
          await tester.pumpWidget(
            host(
              frames.last,
              brightness,
              enabled: true,
              onDraft: (v) => draft = v,
            ),
          );
          final input = find.byKey(const ValueKey('openui-field:daily_cups'));
          await tester.enterText(
            find.descendant(of: input, matching: find.byType(EditableText)),
            '120',
          );
          await tester.pump();
          expect(draft?['daily_cups'], 120);
          // Theme/viewport and surface updates must preserve the user's draft.
          await tester.pumpWidget(
            host(
              frames.last,
              brightness == Brightness.dark
                  ? Brightness.light
                  : Brightness.dark,
              enabled: true,
            ),
          );
          expect(tester.widget<GlassTextField>(input).controller!.text, '120');
          expect(tester.takeException(), isNull);
        }
      },
    );
  }

  testWidgets(
    'duplicate presentation siblings are legal across containers and streamed titles',
    (tester) async {
      final leaves = [
        node('Divider', {}),
        node('Heading', {'text': 'Same', 'level': 2}),
        node('Badge', {'label': 'Same', 'tone': 'info'}),
        node('Metric', {
          'label': 'Same',
          'value': '100',
          'change': '',
          'tone': 'info',
        }),
        node('Progress', {'label': 'Same', 'value': 50, 'tone': 'info'}),
        node('Alert', {'content': 'Same', 'tone': 'info'}),
        node('Computed', {
          'label': 'Same',
          'operation': 'sum',
          'inputs': [1, 2],
          'precision': 0,
        }),
        node('Chart', {
          'title': 'Same',
          'type': 'bar',
          'labels': ['A'],
          'series': [
            {
              'name': 'S',
              'values': [3],
            },
          ],
        }),
        node('Tabs', {
          'children': [
            node('Tab', {
              'label': 'Same',
              'children': [
                node('Text', {'content': 'Body'}),
              ],
            }),
          ],
        }),
        node('Accordion', {
          'children': [
            node('Section', {
              'label': 'Same',
              'children': [
                node('Text', {'content': 'Body'}),
              ],
            }),
          ],
        }),
      ];
      for (final container in ['Stack', 'Row', 'Card', 'Tab', 'Section']) {
        for (final leaf in leaves) {
          await tester.pumpWidget(
            host({
              'tree': node(container, {
                'children': [leaf, leaf, leaf],
              }),
            }, Brightness.dark),
          );
          await tester.pump();
          expect(
            tester.takeException(),
            isNull,
            reason: '$container / ${leaf['component']}',
          );
        }
      }
    },
  );

  testWidgets(
    'chained calculation and chart update locally without submission',
    (tester) async {
      var submissions = 0;
      final fields = [
        node('NumberInput', {
          'name': 'cups',
          'label': 'Cups',
          'value': 100,
          'min': 0,
          'max': 2000,
          'step': 1,
        }),
        node('NumberInput', {
          'name': 'price',
          'label': 'Price',
          'value': 25,
          'min': 0,
          'max': 200,
          'step': 1,
        }),
        node('NumberInput', {
          'name': 'fixed',
          'label': 'Fixed',
          'value': 20000,
          'min': 0,
          'max': 200000,
          'step': 1,
        }),
      ];
      Map<String, Object?> compute(
        String id,
        String op,
        List<Object?> inputs,
      ) => {
        ...node('Computed', {
          'label': id,
          'operation': op,
          'inputs': inputs,
          'precision': 0,
        }),
        'id': id,
      };
      final tree = stack([
        ...fields,
        compute('income', 'product', ['cups', 'price', 30]),
        compute('variable', 'product', ['cups', 8, 30]),
        compute('cost', 'sum', ['variable', 'fixed']),
        compute('profit', 'difference', ['income', 'cost']),
        node('Chart', {
          'title': 'Profit',
          'type': 'bar',
          'labels': ['Profit'],
          'series': [
            {
              'name': 'Monthly',
              'values': ['profit'],
            },
          ],
        }),
      ]);
      await tester.pumpWidget(
        MaterialApp(
          theme: sageDesktopTheme(Brightness.light),
          home: Scaffold(
            body: SingleChildScrollView(
              child: OpenUiSurface(
                surface: {
                  'tree': tree,
                  'complete': true,
                  'surface_id': 'local',
                },
                enabled: true,
                onSubmit: (_, _) async {
                  submissions++;
                },
              ),
            ),
          ),
        ),
      );
      String value(String id) => tester
          .widget<Text>(find.byKey(ValueKey('openui-computed:$id')))
          .data!;
      expect(value('income'), '75000');
      expect(value('profit'), '31000');
      final input = find.descendant(
        of: find.byKey(const ValueKey('openui-field:cups')),
        matching: find.byType(EditableText),
      );
      for (final (cups, profit) in [
        ('120', '41200'),
        ('200', '82000'),
        ('0', '-20000'),
        ('', '—'),
        ('100', '31000'),
      ]) {
        await tester.enterText(input, cups);
        await tester.pump();
        expect(value('profit'), profit);
        expect(tester.takeException(), isNull);
      }
      expect(submissions, 0);
    },
  );
}
