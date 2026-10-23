import 'package:flutter_test/flutter_test.dart';
import 'package:sage_desktop_v2/src/ui/rsi_activity.dart';

Map<String, Object?> event(
  String name,
  String id, {
  String? role,
  String? activity,
  String? caseId,
}) => {
  'event': name,
  'data': {
    'call_id': id,
    if (role != null) 'role': role,
    if (activity != null) 'activity': activity,
    if (caseId != null) 'case_id': caseId,
  },
};

void main() {
  test('scoring and assessment repair stages are explicit', () {
    expect(rsiActivityLabel('dialogue_execution_completed'), '计算评分');
    expect(
      rsiActivityLabel(
        'agent_call_started',
        role: 'evaluation',
        activity: 'scoring',
      ),
      '评分与诊断',
    );
    expect(rsiActivityLabel('dialogue_execution_scored'), '准备诊断结果');
    expect(rsiActivityLabel('evaluation_response_rejected'), '修正评估记录');
    expect(rsiActivityLabel('scoring_call_failed'), '等待恢复');
    expect(
      rsiRunningActivity(
        {'stage': 'infrastructure_retry'},
        [event('target_call_started', 'interrupted')],
        chinese: true,
      ),
      '等待恢复',
    );
    final events = [
      event('scoring_call_started', 'score-1'),
      event('scoring_call_started', 'score-2'),
    ];
    expect(rsiRunningActivity(null, events, chinese: true), '计算评分 2');
    events.add(event('scoring_call_completed', 'score-1'));
    expect(
      rsiRunningActivity(null, events, chinese: false),
      'Calculating score',
    );
    events.add(event('scoring_call_failed', 'score-2'));
    expect(rsiRunningActivity(null, events, chinese: true), '等待恢复');
  });
  test(
    'unfinished calls retain concurrent work after another call completes',
    () {
      final events = [
        event('target_call_started', 'target-1'),
        event(
          'agent_call_started',
          'eval-1',
          role: 'evaluation',
          caseId: 'case-1',
        ),
        event(
          'agent_call_started',
          'eval-2',
          role: 'evaluation',
          caseId: 'case-2',
        ),
      ];
      expect(
        rsiRunningActivity(null, events, chinese: true),
        '执行对话 · 分析执行结果 2',
      );
      events.add(event('target_call_completed', 'target-1'));
      expect(rsiRunningActivity(null, events, chinese: true), '分析执行结果 2');
      events.add(event('agent_call_completed', 'eval-2'));
      expect(rsiRunningActivity(null, events, chinese: true), '分析执行结果');
      events.add(event('agent_call_completed', 'eval-1'));
      events.add({
        'event': 'evaluation_completed',
        'data': <String, Object?>{},
      });
      expect(rsiRunningActivity(null, events, chinese: true), '汇总评测结果');
    },
  );

  test(
    'round summary, comparison, tuning and review are distinct without role jargon',
    () {
      for (final entry in {
        'diagnosis_summary': '汇总诊断',
        'trial_comparison': '对比重复执行',
        'tuning': '优化配置',
        'semantic_review': '检查改动',
      }.entries) {
        final label = rsiRunningActivity(null, [
          event(
            'agent_call_started',
            'call',
            role: 'evaluation',
            activity: entry.key,
          ),
        ], chinese: true);
        expect(label, entry.value);
        expect(label.toLowerCase(), isNot(contains('agent')));
      }
      expect(
        rsiRunningActivity(null, [
          event('agent_call_started', 'old', role: 'evaluation'),
        ], chinese: true),
        '汇总诊断',
      );
      expect(
        rsiActivityLabel('agent_call_started', role: 'tuning', chinese: false),
        'Optimizing configuration',
      );
    },
  );

  test('compact run without events uses persisted phase', () {
    expect(
      rsiRunningActivity(
        {
          'stage': 'agent_call_started',
          'role': 'evaluation',
          'activity': 'diagnosis_summary',
        },
        [],
        chinese: true,
      ),
      '汇总诊断',
    );
    expect(
      rsiRunningActivity({'stage': 'human_test_pending'}, [], chinese: true),
      '测试集评测中',
    );
    expect(
      rsiRunningActivity(
        {'stage': 'stability_check_started'},
        [],
        chinese: true,
      ),
      '稳定性复测中',
    );
  });

  test(
    'resumed operation does not retain interrupted calls from the previous attempt',
    () {
      final events = [
        event('target_call_started', 'old-unfinished'),
        event(
          'agent_call_started',
          'old-evaluation',
          role: 'evaluation',
          caseId: 'old-case',
        ),
        {'event': 'operation_started', 'data': <String, Object?>{}},
        event(
          'agent_call_started',
          'new-evaluation',
          role: 'evaluation',
          caseId: 'case',
        ),
      ];
      expect(rsiRunningActivity(null, events, chinese: true), '分析执行结果');
    },
  );
}
