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
}
