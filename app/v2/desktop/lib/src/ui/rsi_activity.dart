/// Human-readable work derived from real, unfinished calls in the audit stream.
String rsiActivityLabel(
  Object? stage, {
  Object? role,
  Object? activity,
  bool chinese = true,
}) {
  String t(String zh, String en) => chinese ? zh : en;
  if (stage == 'agent_call_started' || stage == 'agent_call_completed') {
    return switch (activity ?? role) {
      'diagnosis_summary' => t('汇总诊断', 'Summarizing findings'),
      'trial_comparison' => t('对比重复执行', 'Comparing repeated runs'),
      'tuning' => t('优化配置', 'Optimizing configuration'),
      'evaluation' => t('分析执行结果', 'Analyzing results'),
      'scoring' => t('评分与诊断', 'Scoring and diagnosis'),
      'suite_review' => t('检查题目', 'Reviewing questions'),
      'semantic_review' => t('检查改动', 'Reviewing changes'),
      'test_design' => t('准备题目', 'Preparing questions'),
      'test_dialogue' => t('继续测试对话', 'Continuing test dialogue'),
      _ => t('处理评测任务', 'Processing evaluation'),
    };
  }
  return switch (stage) {
    'queued' => t('排队中', 'Queued'),
    'resuming' => t('恢复实验', 'Resuming experiment'),
    'training_generation_started' => t(
      '准备训练题目',
      'Preparing training questions',
    ),
    'training_growth_deferred' => t('暂缓扩增训练题', 'Training expansion paused'),
    'test_generation_started' => t('准备题目', 'Preparing questions'),
    'suite_review_completed' => t('题目检查完成', 'Questions reviewed'),
    'training_cases_added' ||
    'suite_fixed' => t('准备执行对话', 'Preparing conversations'),
    'target_call_started' => t('执行对话', 'Running conversations'),
    'target_call_completed' => t('准备分析结果', 'Preparing result analysis'),
    'dialogue_execution_completed' ||
    'scoring_call_started' => t('计算评分', 'Calculating score'),
    'scoring_call_completed' ||
    'dialogue_execution_scored' => t('准备诊断结果', 'Preparing diagnosis'),
    'call_retry_scheduled' => t('重试当前调用', 'Retrying current call'),
    'case_call_failed' => t('保留结果，等待恢复', 'Results saved, awaiting recovery'),
    'scoring_call_failed' ||
    'infrastructure_retry' => t('等待恢复', 'Waiting to recover'),
    'evaluation_response_rejected' ||
    'agent_response_repair_requested' => t('修正评估记录', 'Repairing assessment'),
    'case_completed' => t('准备下一题', 'Preparing next question'),
    'evaluation_completed' ||
    'baseline_completed' => t('汇总评测结果', 'Summarizing evaluation'),
    'training_diagnosis_completed' => t(
      '准备优化配置',
      'Preparing configuration changes',
    ),
    'candidate_created' => t('检查候选版本', 'Checking candidate version'),
    'package_validation_failed' => t('修正配置', 'Repairing configuration'),
    'semantic_review_completed' => t('准备验证改动', 'Preparing change evaluation'),
    'stability_check_started' => t('稳定性复测中', 'Checking stability'),
    'stability_check_completed' => t('稳定性复测完成', 'Stability checked'),
    'human_test_pending' => t('测试集评测中', 'Evaluating test set'),
    'final_evaluation_started' ||
    'final_suite_sealed' => t('独立终测中', 'Independent final test'),
    'final_verification_completed' ||
    'final_evaluation_completed' => t('最终测试完成', 'Final tests completed'),
    'optimization_stopped' => t('结束迭代', 'Finishing iterations'),
    'round_completed' ||
    'training_challenge_completed' => t('准备下一轮', 'Preparing next round'),
    'result_completed' || 'operation_finished' => t('已完成', 'Completed'),
    _ => t('准备评测', 'Preparing evaluation'),
  };
}

String rsiRunningActivity(
  Map<String, Object?>? run,
  List<Map<String, Object?>> events, {
  required bool chinese,
}) {
  if (run?['stage'] == 'infrastructure_retry') {
    return rsiActivityLabel('infrastructure_retry', chinese: chinese);
  }
  final active = <String, Map<String, Object?>>{};
  var checkingStability = false;
  Map<String, Object?> data(Map<String, Object?> event) => event['data'] is Map
      ? (event['data'] as Map).cast<String, Object?>()
      : {};
  for (final event in events) {
    if (event['event'] == 'operation_started') {
      active.clear();
      checkingStability = false;
    }
    if (event['event'] == 'stability_check_started') checkingStability = true;
    if (event['event'] == 'stability_check_completed' ||
        event['event'] == 'round_completed') {
      checkingStability = false;
    }
    final value = data(event);
    if (event['event'] == 'case_call_failed') {
      active.removeWhere((_, started) {
        final origin = data(started);
        return origin['case_id'] == value['case_id'] &&
            origin['round'] == value['round'] &&
            origin['trial'] == value['trial'] &&
            origin['phase'] == value['phase'];
      });
    }
    final id = value['call_id']?.toString();
    if (id == null) continue;
    if (event['event'] == 'agent_call_started' ||
        event['event'] == 'target_call_started' ||
        event['event'] == 'scoring_call_started') {
      active[id] = event;
    } else if (event['event'] == 'agent_call_completed' ||
        event['event'] == 'target_call_completed' ||
        event['event'] == 'scoring_call_completed' ||
        event['event'] == 'scoring_call_failed' ||
        event['event'] == 'agent_call_failed' ||
        event['event'] == 'target_call_failed') {
      active.remove(id);
    }
  }
  final counts = <String, int>{};
  for (final event in active.values) {
    final value = data(event);
    // Older journals have no activity field. Case-less evaluation calls are
    // round-level diagnosis synthesis; case calls analyze individual executions.
    final activity =
        value['activity'] ??
        (value['role'] == 'evaluation' && value['case_id'] == null
            ? 'diagnosis_summary'
            : null);
    final label = rsiActivityLabel(
      event['event'],
      role: value['role'],
      activity: activity,
      chinese: chinese,
    );
    counts.update(label, (count) => count + 1, ifAbsent: () => 1);
  }
  if (counts.isNotEmpty) {
    final work = counts.entries
        .map((e) => e.value > 1 ? '${e.key} ${e.value}' : e.key)
        .join(' · ');
    return checkingStability
        ? '${chinese ? '稳定性复测' : 'Stability check'} · $work'
        : work;
  }
  final latest = events.lastOrNull;
  final value = latest == null ? <String, Object?>{} : data(latest);
  return rsiActivityLabel(
    run?['stage'] ?? latest?['event'],
    role: run?['role'] ?? value['role'],
    activity: run?['activity'] ?? value['activity'],
    chinese: chinese,
  );
}
