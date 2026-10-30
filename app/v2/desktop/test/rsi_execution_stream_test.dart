import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_desktop_v2/src/ui/rsi_execution_stream.dart';

void main() {
  test('cumulative evidence keeps text and pairs tools without duplicates', () {
    final snapshot = [
      {
        'id': 'run:1',
        'kind': 'message',
        'role': 'assistant',
        'text': 'Checking',
      },
      {
        'id': 'run:2',
        'kind': 'tool_call',
        'role': 'tool',
        'call_id': 'run:call',
        'tool_name': 'file_read',
        'text': '{"path":"index.html"}',
      },
      {
        'id': 'run:3',
        'kind': 'tool_result',
        'role': 'tool',
        'call_id': 'run:call',
        'text': 'Missing file',
        'error': 'Read failed',
        'state': 'failed',
      },
      {
        'id': 'run:4',
        'kind': 'message',
        'role': 'assistant',
        'text': 'Finished',
      },
    ];
    final entries = rsiExecutionEntries([
      {
        'evidence': {'execution_transcript': snapshot},
      },
      {
        'evidence': {'execution_transcript': snapshot},
      },
      {'input': 'Follow up', 'output': 'Legacy answer'},
    ]);
    expect(entries.map((e) => e['text']), [
      'Checking',
      '{"path":"index.html"}',
      'Finished',
      'Follow up',
      'Legacy answer',
    ]);
    expect(entries[1]['state'], 'failed');
    expect(entries[1]['result'], 'Missing file\nRead failed');
    expect(
      rsiExecutionEntries([
        {'output': 'old answer'},
      ]),
      isEmpty,
    );
  });

  for (final brightness in Brightness.values) {
    testWidgets('tool details expand in $brightness', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(brightness: brightness),
          home: Scaffold(
            body: RsiExecutionTool(
              name: 'file_read',
              arguments: 'index.html',
              result: 'Missing file',
              state: 'failed',
              chinese: true,
              settings: const LiquidGlassSettings(),
            ),
          ),
        ),
      );
      expect(find.text('失败'), findsOneWidget);
      expect(find.text('Missing file'), findsNothing);
      await tester.tap(find.byType(ExpansionTile));
      await tester.pumpAndSettle();
      expect(find.text('index.html'), findsOneWidget);
      expect(find.text('Missing file'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
