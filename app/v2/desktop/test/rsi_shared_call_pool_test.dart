import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_activity.dart';
import 'package:sage_desktop_v2/src/ui/rsi_observatory.dart';

void main() {
  test('round measurement barrier has an explicit activity', () {
    expect(
      rsiRunningActivity(
        {'stage': 'checkpoint_measurements_pending'},
        [],
        chinese: true,
      ),
      '等待本轮测试测量完成',
    );
  });

  testWidgets('active count includes human tests without optimizer calls', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1800, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: RsiObservatory(
              run: {
                'id': 'shared-pool',
                'status': 'running',
                'max_concurrency': 10,
                'stage': 'checkpoint_measurements_pending',
                'call_pool': {'active': 7, 'waiting': 12, 'limit': 10},
              },
              events: const [],
              settings: const LiquidGlassSettings(),
              chinese: true,
            ),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('7 / 10'), findsOneWidget);
    expect(find.text('等待本轮测试测量完成'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final brightness in Brightness.values) {
    testWidgets('queued receipts and visible tool activity $brightness', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1800, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiObservatory(
                run: {
                  'id': 'live',
                  'status': 'running',
                  'max_concurrency': 1,
                  'call_pool': {
                    'active': 1,
                    'waiting': 1,
                    'limit': 1,
                    'calls': [
                      {
                        'input': 'train',
                        'trial': 1,
                        'state': 'running',
                        'activity': [
                          {
                            'role': 'tool',
                            'text': 'read_lints',
                            'state': 'completed',
                          },
                          {'role': 'assistant', 'text': 'Checking styles.'},
                        ],
                      },
                      {
                        'input': 'other',
                        'trial': 1,
                        'state': 'queued',
                        'activity': [],
                      },
                    ],
                  },
                },
                events: [
                  {
                    'event': 'suite_fixed',
                    'data': {
                      'suite': {
                        'cases': [
                          {'id': 'a', 'input': 'train', 'split': 'training'},
                          {'id': 'b', 'input': 'other', 'split': 'training'},
                        ],
                      },
                    },
                  },
                  for (final entry in {'a': 'train', 'b': 'other'}.entries)
                    {
                      'event': 'target_call_started',
                      'data': {
                        'phase': 'baseline',
                        'round': 0,
                        'trial': 1,
                        'call_id': entry.key,
                        'case_id': entry.key,
                        'input': entry.value,
                      },
                    },
                ],
                settings: const LiquidGlassSettings(),
                chinese: true,
              ),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('执行中 1'), findsOneWidget);
      expect(find.text('待执行 1'), findsOneWidget);
      expect(find.text('排队中'), findsOneWidget);
      expect(find.textContaining('read_lints'), findsOneWidget);
      expect(find.text('Checking styles.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
