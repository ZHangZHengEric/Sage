import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_token_usage.dart';

Map<String, Object?> usage() => {
  'coverage': 'provider_calls',
  'total': {
    'input_tokens': 1000,
    'cached_input_tokens': 250,
    'output_tokens': 50,
    'total_tokens': 1050,
    'cache_rate': .25,
    'reported_records': 2,
    'unreported_records': 0,
  },
  'stages': {
    'execution': {
      'input_tokens': 1000,
      'cached_input_tokens': 250,
      'output_tokens': 50,
      'total_tokens': 1050,
      'cache_rate': .25,
    },
    for (final stage in [
      'evaluation',
      'design',
      'tuning',
      'review',
      'dialogue',
    ])
      stage: {
        'input_tokens': 0,
        'cached_input_tokens': 0,
        'output_tokens': 0,
        'total_tokens': 0,
      },
  },
};

void main() {
  for (final brightness in Brightness.values) {
    for (final width in [360.0, 1100.0]) {
      testWidgets('live token summary and stage table fit $width $brightness', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: Scaffold(
              body: SingleChildScrollView(
                child: RsiTokenUsage(usage: usage(), chinese: true),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('输入 1.0K'), findsOneWidget);
        expect(find.text('缓存命中 250'), findsOneWidget);
        expect(find.text('输出 50'), findsOneWidget);
        expect(find.text('缓存率 25.0%'), findsOneWidget);
        expect(find.text('执行 1.1K'), findsOneWidget);
        await tester.tap(find.text('Token 用量'));
        await tester.pumpAndSettle();
        expect(find.byType(DataTable), findsOneWidget);
        expect(find.text('1.1K'), findsNWidgets(3));
        expect(find.text('1050'), findsNothing);
        expect(find.text('总计'), findsOneWidget);
        expect(find.textContaining('合计 = 输入 + 输出'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }
  testWidgets('large token values use B M K in the detail table', (
    tester,
  ) async {
    final data = usage();
    (data['total'] as Map).addAll(<String, num>{
      'input_tokens': 1264000000,
      'cached_input_tokens': 488772762,
      'output_tokens': 19007885,
      'total_tokens': 1283007885,
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: RsiTokenUsage(usage: data, chinese: true),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Token 用量'));
    await tester.pumpAndSettle();
    expect(find.text('1.26B'), findsOneWidget);
    expect(find.text('488.77M'), findsOneWidget);
    expect(find.text('19.01M'), findsOneWidget);
    expect(find.text('1264000000'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'missing and legacy usage are visible as incomplete rather than zero',
    (tester) async {
      final data = usage()..['coverage'] = 'partial_legacy';
      (data['total'] as Map)['unreported_records'] = 3;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiTokenUsage(usage: data, chinese: true),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('已知用量 · 记录不完整'), findsOneWidget);
      await tester.tap(find.text('Token 用量'));
      await tester.pumpAndSettle();
      expect(find.textContaining('3 条调用未回传用量'), findsOneWidget);
      expect(find.textContaining('历史实验按可用记录回补'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
