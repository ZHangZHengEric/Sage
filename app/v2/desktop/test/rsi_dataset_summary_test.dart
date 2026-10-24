import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_dataset_summary.dart';

void main() {
  testWidgets(
    'import report separates fixed validation, advisory warnings and scorer self-test',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RsiDatasetSummary(
                chinese: true,
                report: {
                  'name': 'Generic benchmark',
                  'case_count': 6,
                  'split_counts': {'training': 2, 'validation': 3, 'test': 1},
                  'mode_counts': {'single_turn': 2, 'dialogue': 4},
                  'dialogue': {'count': 4, 'min_turns': 5, 'max_turns': 10},
                  'checks': [
                    {'name': 'unique_case_ids', 'status': 'passed'},
                    {'name': 'environment_binding', 'status': 'not_checked'},
                  ],
                  'warnings': [
                    {
                      'message': 'A fact may be missing',
                      'case_ids': ['dev-2'],
                    },
                  ],
                },
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('数据集校验与总结'), findsOneWidget);
      expect(find.text('训练集'), findsOneWidget);
      expect(find.text('验证集'), findsOneWidget);
      expect(find.text('测试集'), findsOneWidget);
      expect(find.text('单轮 / 多轮  2 / 4'), findsOneWidget);
      expect(find.text('ID 唯一'), findsOneWidget);
      expect(find.text('环境绑定 · 待检查'), findsOneWidget);
      expect(find.textContaining('评分器需单独自测'), findsOneWidget);
      expect(find.textContaining('待人工检查（非确定性错误）'), findsOneWidget);
      expect(find.textContaining('dev-2'), findsOneWidget);
      await tester.ensureVisible(find.text('覆盖标签与预审策略'));
      await tester.tap(find.text('覆盖标签与预审策略'));
      await tester.pumpAndSettle();
      expect(find.textContaining('固定规则校验，不调用预审模型'), findsOneWidget);
      expect(find.textContaining('导入集按原题、原评分器评测'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  for (final brightness in Brightness.values) {
    for (final width in [360.0, 1100.0]) {
      testWidgets('dataset overview fits $width in $brightness', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: const Scaffold(
              body: SingleChildScrollView(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: RsiDatasetSummary(
                    chinese: true,
                    report: {
                      'name': 'Generic retail · standard RSI dataset',
                      'case_count': 114,
                      'split_counts': {
                        'training': 62,
                        'validation': 12,
                        'test': 40,
                      },
                      'mode_counts': {'single_turn': 0, 'dialogue': 114},
                      'dialogue': {
                        'count': 114,
                        'min_turns': 20,
                        'max_turns': 20,
                      },
                      'reference_count': 114,
                      'environment': {
                        'mcp_servers': ['AnEnvironmentWithALongName'],
                        'tool_count': 16,
                      },
                      'checks': [
                        {'name': 'protocol', 'status': 'passed'},
                        {'name': 'required_fields', 'status': 'passed'},
                        {'name': 'unique_case_ids', 'status': 'passed'},
                        {'name': 'splits', 'status': 'passed'},
                        {'name': 'environment_binding', 'status': 'passed'},
                      ],
                    },
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('114'), findsOneWidget);
        expect(find.text('62'), findsOneWidget);
        expect(find.text('12'), findsOneWidget);
        expect(find.text('40'), findsOneWidget);
        expect(find.text('校验通过'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }
}
