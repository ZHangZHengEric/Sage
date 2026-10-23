import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_activity.dart';

Map<String, Object?> event(String kind, String id, String caseId, {int round = 1}) => {
  'event': kind,
  'data': {'call_id': id, 'case_id': caseId, 'round': round, 'trial': 1, 'phase': 'optimization'},
};
void main() {
  test('failed call exits running counts while sibling continues', () {
    final events = [event('target_call_started', 'a', 'one'), event('target_call_started', 'b', 'two'), event('target_call_failed', 'a', 'one')];
    expect(rsiRunningActivity({'stage':'target_call_started'},events.take(2).toList(),chinese:true),contains('2'));
    final label = rsiRunningActivity({'stage':'call_retry_scheduled'}, events, chinese:true);
    expect(label, equals('执行对话'));
    expect(label, isNot(contains('执行对话 2')));
  });
  test('exhausted case closes only its own pending ids', () {
    final events = [event('target_call_started', 'a', 'one'), event('target_call_started', 'b', 'two'), event('case_call_failed', 'ignored', 'one')];
    expect(rsiRunningActivity({'stage':'case_call_failed'}, events, chinese:true), equals('执行对话'));
  });
  for (final brightness in Brightness.values) {
    testWidgets('retry status remains readable in ${brightness.name}', (tester) async {
      final label = rsiActivityLabel('call_retry_scheduled');
      await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness:brightness), home:Scaffold(body:Text(label))));
      expect(find.text('重试当前调用'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  test('English retry label and failed analysis remove old entry', () {
    expect(rsiActivityLabel('call_retry_scheduled',chinese:false),'Retrying current call');
    final events = [event('agent_call_started','a','one'),event('agent_call_failed','a','one')];
    expect(rsiRunningActivity({'stage':'call_retry_scheduled'},events,chinese:false),'Retrying current call');
  });
}
