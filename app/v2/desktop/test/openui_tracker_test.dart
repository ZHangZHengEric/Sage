import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/app.dart';
import 'package:sage_desktop_v2/src/ui/openui_surface.dart';
import 'package:sage_desktop_v2/src/ui/openui_extras.dart';

void main() {
  test(
    'selection counting is explicit and percentage semantics remain stable',
    () {
      expect(
        openUiCompute(
          'count',
          ['selected'],
          {
            'selected': ['A', 'B'],
          },
        ),
        2,
      );
      expect(
        openUiCompute(
          'sum',
          ['selected'],
          {
            'selected': ['A', 'B'],
          },
        ),
        isNull,
      );
      expect(openUiCompute('count', [3], {}), isNull);
      expect(openUiCompute('ratioPercent', [3, 12], {}), 25);
      expect(openUiCompute('ratioPercent', [0, 0], {}), isNull);
      expect(openUiCompute('percent', [200, 15], {}), 30);
      expect(openUiCompute('count', ['loop'], {'loop': 'loop'}), isNull);
    },
  );
  testWidgets('unaltered generated GPT tracker updates hidden-week counts locally', (tester) async {
    final surface = Map<String, Object?>.from(jsonDecode(File('test/fixtures/openui_generated_tracker.json').readAsStringSync()));
    await tester.pumpWidget(MaterialApp(theme: sageDesktopTheme(Brightness.light), home: Scaffold(body: SingleChildScrollView(child:
      OpenUiSurface(surface: surface, enabled: true, onSubmit: (_, _) async { fail('No submit'); }),
    ))));
    for (var week = 0; week < 4; week++) {
      final tab = find.byKey(ValueKey('openui-tab:$week'));
      await tester.ensureVisible(tab); await tester.tap(tab); await tester.pumpAndSettle();
      final title = find.text('训练安排 · 3次');
      await tester.ensureVisible(title); await tester.tap(title); await tester.pumpAndSettle();
      final checkbox = find.byWidgetPredicate((w) => w.key is ValueKey<String> && (w.key as ValueKey<String>).value.startsWith('openui-option:week${week+1}_done:')).first;
      await tester.ensureVisible(checkbox); await tester.tap(checkbox); await tester.pumpAndSettle();
      expect(tester.widget<Text>(find.byKey(const ValueKey('openui-computed:已完成（共12次）'))).data, '${week+1}次');
      expect(tester.widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator)).value, closeTo((week+1)/12, .00001));
      expect(tester.takeException(), isNull);
    }
  });
  final frames =
      (jsonDecode(
                File(
                  'test/fixtures/openui_running_tracker.json',
                ).readAsStringSync(),
              )
              as List)
          .cast<Map>();
  for (final brightness in Brightness.values) {
    testWidgets(
      'running tracker streams and checkbox counts drive progress $brightness',
      (tester) async {
        tester.view.physicalSize = const Size(720, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        Widget host(Map frame) => MaterialApp(
          theme: sageDesktopTheme(brightness),
          home: Scaffold(
            body: SingleChildScrollView(
              child: OpenUiSurface(
                surface: Map<String, Object?>.from(frame),
                enabled: frame['complete'] == true,
                onSubmit: (_, _) async {
                  fail('Tracking must never submit to the model');
                },
              ),
            ),
          ),
        );
        for (final frame in frames) {
          await tester.pumpWidget(host(frame));
          expect(tester.takeException(), isNull);
        }
        final options = <String, List<String>>{};
        void visit(Map n) {
          final p = n['props'] as Map;
          if (n['component'] == 'CheckboxGroup') {
            options[p['name']] = (p['options'] as List).cast<String>();
          }
          for (final c in p['children'] as List? ?? []) {
            visit(c as Map);
          }
        }

        visit(frames.last['tree']);
        var checked = 0;
        for (var week = 0; week < 4; week++) {
          final tab = find.byKey(ValueKey('openui-tab:$week'));
          await tester.ensureVisible(tab);
          await tester.tap(tab);
          await tester.pumpAndSettle();
          final accordion = find.text('完成打卡');
          await tester.ensureVisible(accordion);
          await tester.tap(accordion);
          await tester.pumpAndSettle();
          final name = 'week${week + 1}_done';
          for (final option in options[name]!) {
            final choice = find.byKey(ValueKey('openui-option:$name:$option'));
            await tester.ensureVisible(choice);
            await tester.tap(choice);
            await tester.pumpAndSettle();
            checked++;
            final count = tester
                .widget<Text>(
                  find.byKey(const ValueKey('openui-computed:总完成次数')),
                )
                .data!;
            expect(count, '共完成 $checked / 12 次');
            expect(
              tester
                  .widget<LinearProgressIndicator>(
                    find.byType(LinearProgressIndicator).first,
                  )
                  .value,
              closeTo(checked / 12, .00001),
            );
            expect(tester.takeException(), isNull);
          }
        }
        final tab = find.byKey(const ValueKey('openui-tab:0'));
        await tester.ensureVisible(tab);
        await tester.tap(tab);
        await tester.pumpAndSettle();
        // Reopen this tab's details after the tab body was replaced.
        final accordion = find.text('完成打卡');
        await tester.ensureVisible(accordion);
        await tester.tap(accordion);
        await tester.pumpAndSettle();
        final choice = find.byKey(
          ValueKey('openui-option:week1_done:${options['week1_done']!.first}'),
        );
        await tester.ensureVisible(choice);
        await tester.tap(choice);
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<Text>(find.byKey(const ValueKey('openui-computed:总完成次数')))
              .data,
          '共完成 11 / 12 次',
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
}
