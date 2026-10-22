import 'dart:convert';
import 'dart:math' as math;
import 'rsi_diff.dart';
import 'rsi_score_history.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

Map<String, Object?> _map(Object? value) =>
    value is Map ? value.cast<String, Object?>() : {};
List<Map<String, Object?>> _rows(Object? value) => value is List
    ? value.whereType<Map>().map((e) => e.cast<String, Object?>()).toList()
    : [];

/// A projection of the audit journal. No progress or dialogue is simulated.
class RsiObservatory extends StatefulWidget {
  const RsiObservatory({
    required this.run,
    required this.events,
    required this.settings,
    required this.chinese,
    super.key,
  });
  final Map<String, Object?>? run;
  final List<Map<String, Object?>> events;
  final LiquidGlassSettings settings;
  final bool chinese;

  @override
  State<RsiObservatory> createState() => _RsiObservatoryState();
}

class _RsiObservatoryState extends State<RsiObservatory>
    with SingleTickerProviderStateMixin {
  late final AnimationController _motion = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 12),
  );
  String? _selectedPass;
  String tr(String zh, String en) => widget.chinese ? zh : en;
  bool get running =>
      const ['queued', 'running'].contains(widget.run?['status']);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _updateMotion();
  }

  @override
  void didUpdateWidget(covariant RsiObservatory oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.run?['id'] != widget.run?['id']) _selectedPass = null;
    _updateMotion();
  }

  void _updateMotion() {
    if (running &&
        !MediaQuery.disableAnimationsOf(context) &&
        TickerMode.valuesOf(context).enabled) {
      if (!_motion.isAnimating) _motion.repeat();
    } else {
      _motion.stop();
    }
  }

  @override
  void dispose() {
    _motion.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final accent = dark ? const Color(0xFF64E8DD) : const Color(0xFF006C68);
    final violet = dark ? const Color(0xFFB5A5FF) : const Color(0xFF6850BB);
    final projection = _Projection(widget.run, widget.events);
    final passes = projection.passes;
    final pass = passes.contains(_selectedPass)
        ? _selectedPass
        : passes.lastOrNull;
    final cases = projection.casesFor(pass);
    final graded = cases.where((c) => c.grade.isNotEmpty).length;
    final responding = running
        ? cases
              .where(
                (c) => const ['responding', 'evaluating'].contains(c.state),
              )
              .length
        : 0;
    final run = widget.run;
    final termination = _map(
      run?['termination'] ??
          _map(_map(run?['result'])['report'])['termination'],
    );
    final stabilityEvent = widget.events
        .where(
          (event) => const [
            'stability_check_started',
            'stability_check_completed',
          ].contains(event['event']),
        )
        .lastOrNull;
    final checkingStability =
        stabilityEvent?['event'] == 'stability_check_started';
    final checkingFinal = passes.lastOrNull?.startsWith('final_') == true;
    final status = switch (run?['status']) {
      'running' =>
        checkingStability
            ? tr('稳定性复测中', 'Checking stability')
            : checkingFinal
            ? tr('独立终测中', 'Independent final test')
            : tr('进化中', 'Evolving'),
      'queued' => tr('排队中', 'Queued'),
      'completed' =>
        run?['goal_verified'] == false && run?['validation_case_count'] != null
            ? tr('验证未达标', 'Validation target not reached')
            : run?['goal_verified'] == true &&
                  run?['validation_case_count'] != null
            ? tr('进化成功', 'Evolution verified')
            : projection.finalPassed == false
            ? tr('终测未达标', 'Final test failed')
            : projection.finalPassed == true
            ? tr('进化成功', 'Evolution verified')
            : tr('进化完成', 'Completed'),
      'failed' => tr('进化失败', 'Failed'),
      'cancelled' => tr('已取消', 'Cancelled'),
      'interrupted' => tr('已中断', 'Interrupted'),
      _ => tr('等待开始', 'Ready'),
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GlassCard(
          settings: widget.settings,
          child: Container(
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  accent.withValues(alpha: dark ? .12 : .07),
                  violet.withValues(alpha: .04),
                  Colors.transparent,
                ],
              ),
            ),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final core = SizedBox(
                  width: 132,
                  height: 132,
                  child: RepaintBoundary(
                    child: CustomPaint(
                      painter: _CorePainter(_motion, accent, violet),
                      child: Center(
                        child: Icon(
                          CupertinoIcons.sparkles,
                          size: 34,
                          color: accent,
                        ),
                      ),
                    ),
                  ),
                );
                final info = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      status,
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 16),
                    Wrap(
                      spacing: 24,
                      runSpacing: 14,
                      children: [
                        _metric(
                          projection.adaptive
                              ? tr('基线整体分', 'Baseline overall')
                              : tr('基线验证分', 'Baseline validation'),
                          (projection.adaptive
                                      ? projection.overallScores[0]
                                      : projection.scores[0])
                                  ?.toStringAsFixed(3) ??
                              '—',
                          violet,
                        ),
                        _metric(
                          projection.adaptive
                              ? tr('当前整体分', 'Current overall')
                              : tr('当前验证分', 'Current validation'),
                          (projection.adaptive
                                      ? projection.bestOverall
                                      : projection.bestScore)
                                  ?.toStringAsFixed(3) ??
                              '—',
                          accent,
                        ),
                        _metric(
                          tr('进化轮次', 'Round'),
                          '${run?['iteration'] ?? 0} / ${run?['rounds'] ?? '—'}',
                          accent,
                        ),
                        _metric(
                          tr('训练 / 验证', 'Training / Validation'),
                          '${projection.suite.where((c) => c['split'] == 'training').length} / ${projection.suite.where((c) => c['split'] == 'validation').length}',
                          accent,
                        ),
                        _metric(
                          tr('执行中', 'Active'),
                          '$responding / ${run?['max_concurrency'] ?? 1}',
                          violet,
                        ),
                        _metric(
                          tr('已评估', 'Evaluated'),
                          '$graded / ${cases.length}',
                          violet,
                        ),
                      ],
                    ),
                  ],
                );
                return constraints.maxWidth < 480
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Center(child: core),
                          info,
                        ],
                      )
                    : Row(
                        children: [
                          core,
                          const SizedBox(width: 24),
                          Expanded(child: info),
                        ],
                      );
              },
            ),
          ),
        ),
        if (_rows(widget.run?['test_observations']).isNotEmpty) ...[
          const SizedBox(height: 16),
          RsiScoreHistory(
            key: ValueKey('rsi-scores-${widget.run?["id"]}'),
            records: _rows(widget.run?['test_observations']),
            settings: widget.settings,
            chinese: widget.chinese,
          ),
        ],
        if (_rows(widget.run?['test_observations']).isEmpty &&
            projection.suite.isNotEmpty &&
            pass?.startsWith('final_') != true) ...[
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final round = projection.scopeRound(pass);
              final visible = projection.suite
                  .where(
                    (q) =>
                        (projection.introduced[q['id'].toString()] ?? 0) <=
                        round,
                  )
                  .toList();
              Widget matrix(String split) => _ScoreMatrix(
                split: split,
                questions: visible.where((q) => q['split'] == split).toList(),
                views: {for (final item in cases) item.id: item},
                settings: widget.settings,
                chinese: widget.chinese,
              );
              return constraints.maxWidth < 660
                  ? Column(
                      children: [
                        matrix('training'),
                        const SizedBox(height: 12),
                        matrix('validation'),
                      ],
                    )
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: matrix('training')),
                        const SizedBox(width: 12),
                        Expanded(child: matrix('validation')),
                      ],
                    );
            },
          ),
        ],
        const SizedBox(height: 18),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final step in [
              (
                '01',
                tr('准备问题', 'Prepare questions'),
                projection.suite.isNotEmpty,
              ),
              ('02', tr('展开对话', 'Conversations'), projection.calls.isNotEmpty),
              ('03', tr('评估打标', 'Evaluate & label'), projection.hasGrades),
              ('04', tr('迭代进化', 'Evolve'), projection.hasRounds),
            ])
              _badge(
                '${step.$1}  ${step.$2}',
                step.$3
                    ? accent
                    : Theme.of(context).colorScheme.onSurfaceVariant,
              ),
          ],
        ),
        if (termination.isNotEmpty || run?['exit_reason'] != null) ...[
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _badge(switch (termination['reason'] ?? run?['exit_reason']) {
                'target_reached' => tr('达标退出', 'Target reached'),
                'stagnation' => tr('连续无提升 · 停止迭代', 'Stopped · No improvement'),
                'round_limit' => tr('达到轮数上限', 'Round limit reached'),
                'time_limit' => tr('时间预算耗尽', 'Time budget exhausted'),
                'timeout' => tr('执行超时', 'Execution timed out'),
                _ => tr('执行异常', 'Execution error'),
              }, accent),
              if ((termination['stability_passes'] as num? ?? 0) >= 2)
                _badge(tr('稳定性复测通过', 'Stability verified'), violet),
            ],
          ),
        ],
        if (projection.scores.isNotEmpty) ...[
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final entry
                  in (projection.scores.entries.toList()
                    ..sort((a, b) => a.key.compareTo(b.key))))
                _badge(
                  '${entry.key == 0 ? tr('基线', 'Baseline') : '${tr('第', 'Round')} ${entry.key}${widget.chinese ? ' 轮' : ''}'}  ${projection.scoreLabel(entry.key, widget.chinese)}${projection.reused.contains(entry.key) ? tr(' · 复用评测', ' · Reused evaluation') : ''}${projection.accepted[entry.key] == false ? tr(' · 未采纳', ' · Rejected') : ''}',
                  projection.accepted[entry.key] == false
                      ? Theme.of(context).colorScheme.error
                      : accent,
                ),
              for (final entry in projection.stabilityScores.entries)
                _badge(
                  '${tr('复测', 'Stability')} ${entry.key}  ${entry.value.$1.toStringAsFixed(3)} · ${entry.value.$2 ? tr('通过', 'Passed') : tr('未通过', 'Failed')}',
                  entry.value.$2 ? accent : Theme.of(context).colorScheme.error,
                ),
              if (projection.finalScore != null)
                _badge(
                  '${tr('独立终测', 'Final test')}  ${projection.finalScore!.toStringAsFixed(3)} · ${projection.finalPassed == true ? tr('通过', 'Passed') : tr('未通过', 'Failed')}',
                  projection.finalPassed == true
                      ? accent
                      : Theme.of(context).colorScheme.error,
                ),
            ],
          ),
        ],
        const SizedBox(height: 14),
        RsiRoundChanges(
          run: run,
          events: widget.events,
          settings: widget.settings,
          chinese: widget.chinese,
        ),
        if (_toolEvolution(
          run,
          widget.events,
        ).values.any((tools) => tools.isNotEmpty)) ...[
          const SizedBox(height: 18),
          GlassCard(
            settings: widget.settings,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    tr('工具进化', 'Tool evolution'),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final entry in _toolEvolution(
                        run,
                        widget.events,
                      ).entries)
                        GlassButton.custom(
                          key: ValueKey('rsi-tools-${entry.key}'),
                          width: 190,
                          height: 36,
                          settings: widget.settings,
                          onTap: () => showDialog<void>(
                            context: context,
                            builder: (context) => Dialog(
                              child: ConstrainedBox(
                                constraints: const BoxConstraints(
                                  maxWidth: 600,
                                  maxHeight: 600,
                                ),
                                child: Padding(
                                  padding: const EdgeInsets.all(24),
                                  child: SingleChildScrollView(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Text(
                                          tr('工具进化', 'Tool evolution'),
                                          style: Theme.of(
                                            context,
                                          ).textTheme.titleLarge,
                                        ),
                                        for (final tool
                                            in entry.value.entries) ...[
                                          const SizedBox(height: 20),
                                          SelectableText(
                                            tool.key,
                                            style: Theme.of(
                                              context,
                                            ).textTheme.titleMedium,
                                          ),
                                          const SizedBox(height: 8),
                                          SelectableText(
                                            '${tool.value['description'] ?? ''}',
                                          ),
                                          const SizedBox(height: 8),
                                          SelectableText(
                                            '${tr('参数', 'Parameters')}: ${_map(_map(tool.value['input_schema'])['properties']).keys.join(', ')}',
                                          ),
                                        ],
                                        const SizedBox(height: 20),
                                        Align(
                                          alignment: Alignment.centerRight,
                                          child: TextButton(
                                            onPressed: () =>
                                                Navigator.pop(context),
                                            child: Text(tr('关闭', 'Close')),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                          child: Text(
                            '${entry.key == 0 ? tr('基线', 'Baseline') : 'R${entry.key}'} · ${entry.value.length} ${tr('业务工具', 'business tools')}${projection.accepted[entry.key] == false ? tr(' · 未采纳', ' · Rejected') : ''}',
                            style: TextStyle(
                              color: projection.accepted[entry.key] == false
                                  ? Theme.of(context).colorScheme.error
                                  : accent,
                              fontSize: 12,
                            ),
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 24),
        Row(
          children: [
            Expanded(
              child: Text(
                tr('对话矩阵', 'Conversation matrix'),
                style: Theme.of(
                  context,
                ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600),
              ),
            ),
            if (projection.suite.isNotEmpty ||
                projection.finalSuite.isNotEmpty ||
                projection.humanTestSuite.isNotEmpty) ...[
              Semantics(
                button: true,
                label: tr('查看题库', 'Question library'),
                child: GlassButton.custom(
                  key: const ValueKey('rsi-open-suite'),
                  width: 112,
                  height: 32,
                  settings: widget.settings,
                  onTap: () => showDialog<void>(
                    context: context,
                    builder: (context) => _SuiteLibrary(
                      cases: [
                        ...projection.suite,
                        ...projection.finalSuite,
                        ...projection.humanTestSuite,
                      ],
                      chinese: widget.chinese,
                      settings: widget.settings,
                    ),
                  ),
                  child: Text(tr('查看题库', 'Question library')),
                ),
              ),
              const SizedBox(width: 12),
            ],
            if (running) _badge(tr('实时', 'LIVE'), accent),
          ],
        ),
        const SizedBox(height: 14),
        if (passes.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final value in passes)
                  ChoiceChip(
                    label: Text(projection.passLabel(value, widget.chinese)),
                    selected: pass == value,
                    onSelected: (_) => setState(() => _selectedPass = value),
                  ),
              ],
            ),
          ),
        if (cases.isEmpty)
          GlassCard(
            settings: widget.settings,
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Row(
                children: [
                  Icon(CupertinoIcons.square_grid_2x2, color: accent),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Text(
                      run == null
                          ? tr('开始进化', 'Start evolution')
                          : running
                          ? tr('正在准备问题', 'Preparing questions')
                          : tr('暂无对话记录', 'No conversation records'),
                    ),
                  ),
                ],
              ),
            ),
          )
        else
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = math.max(1, (constraints.maxWidth / 290).floor());
              final width =
                  (constraints.maxWidth - (columns - 1) * 12) / columns;
              return Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  for (final (index, item) in cases.indexed)
                    SizedBox(
                      width: width,
                      child: _conversation(item, accent, violet, index + 1),
                    ),
                ],
              );
            },
          ),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _metric(String label, String value, Color color) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        value,
        style: TextStyle(
          fontSize: 23,
          fontWeight: FontWeight.w600,
          fontFeatures: const [FontFeature.tabularFigures()],
          color: color,
        ),
      ),
      const SizedBox(height: 4),
      Text(label, style: Theme.of(context).textTheme.labelMedium),
    ],
  );

  Widget _badge(String label, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .09),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: color.withValues(alpha: .24)),
    ),
    child: Text(
      label,
      style: TextStyle(
        color: color,
        fontSize: 11,
        fontWeight: FontWeight.w600,
        letterSpacing: .4,
      ),
    ),
  );

  Widget _conversation(_CaseView item, Color accent, Color violet, int number) {
    final terminal = !running;
    final label = switch (item.state) {
      'graded' =>
        item.grade['passed'] == true ? tr('通过', 'Passed') : tr('未通过', 'Failed'),
      'responding' =>
        terminal ? tr('未完成', 'Unfinished') : tr('对话中', 'Responding'),
      'evaluating' =>
        terminal ? tr('未评估', 'Ungraded') : tr('评估中', 'Evaluating'),
      _ => terminal ? tr('未执行', 'Not run') : tr('等待对话', 'Waiting'),
    };
    final color = item.state == 'graded'
        ? item.grade['passed'] == true
              ? accent
              : Theme.of(context).colorScheme.error
        : item.state == 'waiting'
        ? Theme.of(context).colorScheme.onSurfaceVariant
        : violet;
    return GlassCard(
      key: ValueKey('rsi-conversation-${item.id}'),
      settings: widget.settings,
      child: Container(
        height: 326,
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: color, width: 2)),
        ),
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(CupertinoIcons.chat_bubble_2, size: 16, color: color),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${tr('问题', 'Question')} ${number.toString().padLeft(2, '0')}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                AnimatedSwitcher(
                  duration: MediaQuery.disableAnimationsOf(context)
                      ? Duration.zero
                      : const Duration(milliseconds: 250),
                  child: KeyedSubtree(
                    key: ValueKey(label),
                    child: _badge(label, color),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Expanded(
              child: ListView(
                key: PageStorageKey(
                  'rsi-messages-${widget.run?['id']}-${item.id}-${_selectedPass ?? 'latest'}',
                ),
                children: [
                  _bubble(item.input, false, accent),
                  for (final turn in item.turns) ...[
                    if (turn['input'] != item.input)
                      _bubble(turn['input']?.toString() ?? '', false, accent),
                    if (turn['output'] != null)
                      _bubble(turn['output'].toString(), true, violet),
                  ],
                  if (item.grade['rationale'] != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(
                        item.grade['rationale'].toString(),
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(
                          context,
                        ).textTheme.bodySmall?.copyWith(color: color),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: Text(
                    item.grade['score'] != null
                        ? '${tr('评分', 'Score')} ${item.grade['score']}'
                        : '${tr('对话轮次', 'Turns')} ${item.turns.length}',
                    style: TextStyle(fontSize: 11, color: color),
                  ),
                ),
                IconButton(
                  tooltip: tr('展开对话', 'Expand conversation'),
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(
                    CupertinoIcons.arrow_up_left_arrow_down_right,
                    size: 15,
                  ),
                  onPressed: () => _openConversation(item),
                ),
              ],
            ),
            if (running &&
                const ['responding', 'evaluating'].contains(item.state))
              _ActivityLine(motion: _motion, color: color),
          ],
        ),
      ),
    );
  }

  Widget _bubble(String value, bool agent, Color color) => Container(
    margin: const EdgeInsets.only(bottom: 9),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: color.withValues(alpha: agent ? .1 : .05),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          agent ? 'Agent' : tr('问题', 'Question'),
          style: TextStyle(
            color: color,
            fontSize: 10,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 5),
        Text(
          value,
          maxLines: 5,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(height: 1.55),
        ),
      ],
    ),
  );

  void _openConversation(_CaseView item) {
    showDialog<void>(
      context: context,
      builder: (context) => Dialog(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680, maxHeight: 720),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        item.id,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    IconButton(
                      tooltip: tr('关闭', 'Close'),
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(CupertinoIcons.xmark),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SelectableText(item.input),
                        for (final turn in item.turns) ...[
                          const Divider(height: 28),
                          if (turn['input'] != item.input)
                            SelectableText(turn['input']?.toString() ?? ''),
                          const SizedBox(height: 10),
                          SelectableText(
                            turn['output']?.toString() ??
                                tr('等待回答', 'Awaiting response'),
                          ),
                        ],
                        if (item.rubric.isNotEmpty) ...[
                          const Divider(height: 28),
                          Text(tr('评测标准', 'Rubric')),
                          const SizedBox(height: 8),
                          SelectableText(item.rubric),
                        ],
                        if (item.grade.isNotEmpty) ...[
                          const Divider(height: 28),
                          Text('${tr('评分', 'Score')} ${item.grade['score']}'),
                          const SizedBox(height: 8),
                          SelectableText(
                            item.grade['rationale']?.toString() ?? '',
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ActivityLine extends StatelessWidget {
  const _ActivityLine({required this.motion, required this.color});
  final Animation<double> motion;
  final Color color;
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: motion,
    builder: (context, _) => SizedBox(
      height: 2,
      child: LayoutBuilder(
        builder: (context, constraints) => Align(
          alignment: Alignment(math.sin(motion.value * math.pi * 12), 0),
          child: Container(
            width: constraints.maxWidth * .28,
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ),
      ),
    ),
  );
}

class _CorePainter extends CustomPainter {
  _CorePainter(this.motion, this.accent, this.violet) : super(repaint: motion);
  final Animation<double> motion;
  final Color accent, violet;
  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.shortestSide * .43;
    canvas.drawCircle(
      center,
      radius,
      Paint()
        ..shader = RadialGradient(
          colors: [accent.withValues(alpha: .2), accent.withValues(alpha: 0)],
        ).createShader(Rect.fromCircle(center: center, radius: radius)),
    );
    for (var ring = 0; ring < 3; ring++) {
      canvas.save();
      canvas.translate(center.dx, center.dy);
      canvas.rotate(motion.value * math.pi * 2 * (ring == 1 ? -1 : 1) + ring);
      final r = radius - ring * 12;
      final paint = Paint()
        ..color = (ring == 1 ? violet : accent).withValues(alpha: .65)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1;
      canvas.drawArc(
        Rect.fromCenter(center: Offset.zero, width: r * 2, height: r * 1.4),
        .3,
        math.pi * 1.65,
        false,
        paint,
      );
      canvas.drawCircle(
        Offset(r, 0),
        3,
        Paint()..color = ring == 1 ? violet : accent,
      );
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(covariant _CorePainter oldDelegate) =>
      oldDelegate.accent != accent || oldDelegate.violet != violet;
}

Color _scoreDotColor(double? score, bool dark) {
  if (score == null) {
    return dark ? const Color(0xFF46515D) : const Color(0xFFD3D9DF);
  }
  final neutral = dark ? const Color(0xFFAAA38D) : const Color(0xFFD6CBB6);
  return score <= .5
      ? Color.lerp(
          dark ? const Color(0xFFDF4255) : const Color(0xFFAB1D36),
          neutral,
          score * 2,
        )!
      : Color.lerp(
          neutral,
          dark ? const Color(0xFF16BC83) : const Color(0xFF087746),
          (score - .5) * 2,
        )!;
}

class _ScoreMatrix extends StatelessWidget {
  const _ScoreMatrix({
    required this.split,
    required this.questions,
    required this.views,
    required this.settings,
    required this.chinese,
  });
  final String split;
  final List<Map<String, Object?>> questions;
  final Map<String, _CaseView> views;
  final LiquidGlassSettings settings;
  final bool chinese;
  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final title = split == 'training'
        ? (chinese ? '训练集' : 'Training set')
        : (chinese ? '验证集' : 'Validation set');
    double? score(String id) => (views[id]?.grade['score'] as num?)?.toDouble();
    final graded = questions
        .where((q) => score(q['id'].toString()) != null)
        .length;
    return GlassCard(
      key: ValueKey('rsi-score-matrix-$split'),
      settings: settings,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                title,
                style: Theme.of(
                  context,
                ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(width: 10),
              Text(
                '$graded / ${questions.length}',
                style: Theme.of(context).textTheme.labelSmall,
              ),
              const Spacer(),
              Text('0', style: Theme.of(context).textTheme.labelSmall),
              const SizedBox(width: 5),
              for (final value in [0.0, .25, .5, .75, 1.0])
                Container(
                  width: 7,
                  height: 7,
                  margin: const EdgeInsets.symmetric(horizontal: 1.5),
                  decoration: BoxDecoration(
                    color: _scoreDotColor(value, dark),
                    shape: BoxShape.circle,
                  ),
                ),
              const SizedBox(width: 5),
              Text('1', style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
          const SizedBox(height: 14),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 180),
            child: SingleChildScrollView(
              child: Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final (index, question) in questions.indexed)
                    Builder(
                      builder: (context) {
                        final id = question['id'].toString();
                        final value = score(id);
                        final state = views[id]?.state;
                        final active =
                            state == 'responding' || state == 'evaluating';
                        final status = value != null
                            ? value.toStringAsFixed(3)
                            : active
                            ? (chinese ? '评测中' : 'Evaluating')
                            : (chinese ? '未评估' : 'Not evaluated');
                        final label = '$title ${index + 1} · $status';
                        return Semantics(
                          label: '$label · ${question['input']}',
                          child: Tooltip(
                            message: label,
                            child: AnimatedContainer(
                              key: ValueKey('rsi-score-dot-$split-$id'),
                              duration: MediaQuery.disableAnimationsOf(context)
                                  ? Duration.zero
                                  : const Duration(milliseconds: 220),
                              width: 14,
                              height: 14,
                              decoration: BoxDecoration(
                                color: _scoreDotColor(value, dark),
                                shape: BoxShape.circle,
                                border: active
                                    ? Border.all(
                                        color: Theme.of(
                                          context,
                                        ).colorScheme.primary,
                                        width: 2,
                                      )
                                    : null,
                              ),
                            ),
                          ),
                        );
                      },
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CaseView {
  _CaseView(this.id, this.input, this.rubric);
  final String id;
  String input, rubric;
  String state = 'waiting';
  Map<String, Object?> grade = {};
  final List<Map<String, Object?>> turns = [];
}

class _Projection {
  _Projection(Map<String, Object?>? run, List<Map<String, Object?>> events)
    : adaptive = run?['validation_case_count'] != null {
    humanTestSuite.addAll(_rows(_map(run?['human_test_suite'])['cases']));
    for (final event in events) {
      final data = _map(event['data']);
      switch (event['event']) {
        case 'test_generation_batch_completed':
          suite.addAll(_rows(data['cases']));
        case 'training_cases_added':
          for (final item in _rows(data['cases'])) {
            introduced[item['id'].toString()] =
                (data['round'] as num?)?.toInt() ?? 0;
            if (!suite.any((c) => c['id'] == item['id'])) suite.add(item);
          }
        case 'training_challenge_completed':
          selectedScore = _mean(_map(data['evaluation']));
          selectedOverall = _overall(_map(data['evaluation']));
        case 'suite_fixed':
          suite.clear();
          suite.addAll(_rows(_map(data['suite'])['cases']));
        case 'final_suite_sealed':
          finalSuite.addAll(_rows(_map(data['suite'])['cases']));
        case 'final_baseline_completed':
          _finalCandidate = true;
        case 'stability_check_started':
          _stabilityConfirmation =
              ((data['attempt'] ?? data['confirmation']) as num?)?.toInt() ?? 1;
          stabilityScopeRounds[_stabilityConfirmation!] = introduced.values
              .fold<int>(
                (data['round'] as num?)?.toInt() ?? 0,
                (a, b) => math.max(a, b),
              );
        case 'stability_check_completed':
          _stabilityConfirmation = null;
          final measured = _mean(_map(data['evaluation']));
          final attempt = ((data['attempt'] ?? data['confirmation']) as num?)
              ?.toInt();
          if (measured != null) selectedScore = measured;
          selectedOverall =
              _overall(_map(data['evaluation'])) ?? selectedOverall;
          if (measured != null && attempt != null) {
            stabilityScores[attempt] = (measured, data['passed'] == true);
          }
        case 'target_call_started':
          final pass = _pass(data);
          _passes.add(pass);
          final view = _case(
            pass,
            data['case_id'].toString(),
            data['input']?.toString() ?? '',
          );
          view.state = 'responding';
          final turn = <String, Object?>{'input': data['input']};
          view.turns.add(turn);
          calls[data['call_id'].toString()] = (view, turn);
        case 'target_call_completed':
          final call = calls[data['call_id'].toString()];
          if (call != null) {
            call.$2['output'] = _map(data['observation'])['output'];
            call.$1.state = 'evaluating';
          }
        case 'case_completed':
          _result(_pass(data), _map(data['result']));
        case 'evaluation_completed':
          _score(
            (data['round'] as num?)?.toInt() ?? 0,
            _map(data['evaluation']),
          );
        case 'round_completed':
          hasRounds = true;
          final record = _map(data['record']);
          final index = (record['round'] as num?)?.toInt();
          if (index != null) {
            accepted[index] = record['accepted'] == true;
            if (record['accepted'] == true) {
              selectedScore = _mean(_map(record['evaluation']));
              selectedOverall = _overall(_map(record['evaluation']));
            }
            if (record['evaluation_reused'] == true) reused.add(index);
            _score(index, _map(record['evaluation']));
          }
        case 'final_verification_completed':
          final verification = _map(data['verification']);
          finalScore = _mean(_map(verification['candidate']));
          finalPassed = verification['passed'] == true;
      }
    }
    // Durable evaluation snapshots also work before the journal has caught up.
    final result = _map(run?['result']);
    final report = _map(result['report']);
    for (final item in _rows(_map(report['suite'])['cases'])) {
      if (!suite.any((c) => c['id'] == item['id'])) suite.add(item);
    }
    for (final addition in _rows(report['training_additions'])) {
      for (final item in _rows(addition['cases'])) {
        introduced[item['id'].toString()] =
            (addition['round'] as num?)?.toInt() ?? 0;
      }
    }
    final finalCheck = _map(report['final_verification']);
    if (finalSuite.isEmpty) {
      finalSuite.addAll(_rows(_map(finalCheck['suite'])['cases']));
    }
    final baseline = _map(report['baseline']);
    _score(0, baseline);
    selectedScore = _mean(_map(report['selected'])) ?? selectedScore;
    selectedOverall = _overall(_map(report['selected'])) ?? selectedOverall;
    finalScore = _mean(_map(finalCheck['candidate'])) ?? finalScore;
    if (finalCheck.isNotEmpty) finalPassed = finalCheck['passed'] == true;
    _snapshot('baseline:0', baseline);
    for (final iteration in [
      ..._rows(result['iterations']),
      ..._rows(run?['iterations']),
      ..._rows(report['rounds']),
    ]) {
      final index = iteration['iteration'] ?? iteration['round'];
      if (index == null) continue;
      if (index != 0) hasRounds = true;
      if (iteration['evaluation_reused'] == true && index is num) {
        reused.add(index.toInt());
      }
      if (index is num) {
        _score(index.toInt(), _map(iteration['evaluation']));
        if (iteration['accepted'] is bool) {
          accepted[index.toInt()] = iteration['accepted'] == true;
        }
      }
      if (iteration['evaluation_reused'] == true) continue;
      _snapshot(
        index == 0 ? 'baseline:0' : 'candidate:$index',
        _map(iteration['evaluation']),
      );
    }
    for (final check in _rows(report['stability_checks'])) {
      final attempt = (check['attempt'] as num?)?.toInt();
      if (attempt != null) {
        stabilityScopeRounds[attempt] =
            _rows(_map(check['evaluation'])['cases']).fold<int>(
              (check['round'] as num?)?.toInt() ?? 0,
              (latest, item) => math.max(
                latest,
                introduced[_map(item['case'])['id'].toString()] ?? 0,
              ),
            );
      }
      final measured = _mean(_map(check['evaluation']));
      if (measured != null && check['attempt'] is num) {
        stabilityScores[(check['attempt'] as num).toInt()] = (
          measured,
          check['passed'] == true,
        );
      }
      _snapshot(
        'stability_${check['attempt']}:${check['round']}',
        _map(check['evaluation']),
      );
    }
    _snapshot('final_baseline:0', _map(finalCheck['baseline']));
    _snapshot('final_candidate:0', _map(finalCheck['candidate']));
  }
  final bool adaptive;
  String scoreLabel(int index, bool zh) {
    final validation = scores[index]?.toStringAsFixed(3) ?? '—';
    if (!adaptive) return validation;
    return '${zh ? '整体' : 'Overall'} ${overallScores[index]?.toStringAsFixed(3) ?? '—'} · ${zh ? '验证' : 'Validation'} $validation · ${zh ? '训练' : 'Training'} ${trainingScores[index]?.toStringAsFixed(3) ?? '—'}';
  }

  final scores = <int, double>{};
  final trainingScores = <int, double>{};
  final overallScores = <int, double>{};
  final introduced = <String, int>{};
  final stabilityScopeRounds = <int, int>{};
  final stabilityScores = <int, (double, bool)>{};
  final accepted = <int, bool>{0: true};
  final reused = <int>{};
  double? selectedScore, finalScore;
  double? selectedOverall;
  bool? finalPassed;
  double? get bestScore {
    if (selectedScore != null) return selectedScore;
    var best = scores[0];
    for (final index in scores.keys.toList()..sort()) {
      if (accepted[index] == true) {
        best = scores[index];
      }
    }
    return best;
  }

  double? get bestOverall {
    if (selectedOverall != null) return selectedOverall;
    var score = overallScores[0];
    for (final index in overallScores.keys.toList()..sort()) {
      if (accepted[index] == true) score = overallScores[index];
    }
    return score;
  }

  double? _overall(Map<String, Object?> evaluation) {
    final cases = _rows(evaluation['cases']);
    final means = <double>[];
    for (final split in ['training', 'validation']) {
      final rows = cases
          .where((c) => _map(c['case'])['split'] == split)
          .toList();
      final scores = rows
          .map((c) => _map(c['grade'])['score'])
          .whereType<num>()
          .toList();
      if (rows.isEmpty || scores.length != rows.length) return null;
      means.add(
        scores.fold<double>(0, (sum, score) => sum + score) / scores.length,
      );
    }
    return (means[0] + means[1]) / 2;
  }

  double? _mean(Map<String, Object?> evaluation) {
    final allCases = _rows(evaluation['cases']);
    final validation = allCases
        .where((c) => _map(c['case'])['split'] == 'validation')
        .toList();
    final cases = adaptive && validation.isNotEmpty ? validation : allCases;
    final values = cases
        .map((c) => _map(c['grade'])['score'])
        .whereType<num>()
        .toList();
    if (cases.isEmpty || values.length != cases.length) return null;
    return values.fold<double>(0, (sum, score) => sum + score) / values.length;
  }

  void _score(int index, Map<String, Object?> evaluation) {
    final training = _rows(
      evaluation['cases'],
    ).where((c) => _map(c['case'])['split'] == 'training').toList();
    if (training.isNotEmpty) {
      trainingScores[index] =
          training.fold<double>(
            0,
            (sum, c) =>
                sum + ((_map(c['grade'])['score'] as num?)?.toDouble() ?? 0),
          ) /
          training.length;
    }
    final value = _mean(evaluation);
    if (value != null) scores[index] = value;
    final overall = _overall(evaluation);
    if (overall != null) overallScores[index] = overall;
  }

  final suite = <Map<String, Object?>>[];
  final finalSuite = <Map<String, Object?>>[];
  final humanTestSuite = <Map<String, Object?>>[];
  bool _finalCandidate = false;
  int? _stabilityConfirmation;
  final calls = <String, (_CaseView, Map<String, Object?>)>{};
  final _views = <String, Map<String, _CaseView>>{};
  final _passes = <String>{};
  bool hasRounds = false;
  bool get hasGrades =>
      _views.values.any((v) => v.values.any((c) => c.grade.isNotEmpty));
  List<String> get passes => _passes.toList();
  int scopeRound(String? pass) {
    final parts = pass?.split(':') ?? [];
    final round = int.tryParse(parts.elementAtOrNull(1) ?? '') ?? 0;
    if (parts.firstOrNull?.startsWith('stability_') == true) {
      final attempt = int.tryParse(parts.first.substring(10));
      return stabilityScopeRounds[attempt] ?? round;
    }
    return round;
  }

  String _pass(Map<String, Object?> data) {
    final round = data['round'] ?? 0;
    final phase = data['phase'] == 'final'
        ? (_finalCandidate ? 'final_candidate' : 'final_baseline')
        : data['phase'] == 'training_challenge'
        ? 'challenge'
        : _stabilityConfirmation != null
        ? 'stability_$_stabilityConfirmation'
        : round == 0
        ? 'baseline'
        : 'candidate';
    final trial = data['trial'];
    return '$phase:$round${trial is num && trial > 1 ? ':$trial' : ''}';
  }

  void _snapshot(String pass, Map<String, Object?> evaluation) {
    if (_passes.any((p) => p.startsWith('$pass:'))) return;
    for (final item in _rows(evaluation['cases'])) {
      _result(pass, item);
    }
  }

  String passLabel(String pass, bool zh) {
    final parts = pass.split(':');
    final phase = switch (parts.first) {
      'baseline' => zh ? '基线' : 'Baseline',
      'challenge' => '${zh ? '训练挑战' : 'Training challenge'} ${parts[1]}',
      'final_baseline' => zh ? '最终测试 · 基线' : 'Final · Baseline',
      'final_candidate' => zh ? '最终测试 · 候选' : 'Final · Candidate',
      final value when value.startsWith('stability_') =>
        '${zh ? '稳定性复测' : 'Stability check'} ${value.substring(10)}',
      _ => '${zh ? '第' : 'Round'} ${parts[1]}${zh ? ' 轮' : ''}',
    };
    return parts.length > 2
        ? '$phase · ${zh ? '测试' : 'Trial'} ${parts[2]}'
        : phase;
  }

  _CaseView _case(String pass, String id, String input) =>
      (_views[pass] ??= {})[id] ??= _CaseView(id, input, '');
  void _result(String pass, Map<String, Object?> result) {
    final test = _map(result['case']);
    if (test['id'] == null) return;
    _passes.add(pass);
    final view = _case(
      pass,
      test['id'].toString(),
      test['input']?.toString() ?? '',
    );
    view.rubric = test['rubric']?.toString() ?? '';
    view.grade = _map(result['grade']);
    view.state = 'graded';
    view.turns.clear();
    final dialogue = _rows(result['dialogue']);
    if (dialogue.isNotEmpty) {
      for (final turn in dialogue) {
        view.turns.add({
          'input': turn['input'],
          'output': _map(turn['observation'])['output'],
        });
      }
    } else {
      view.turns.add({
        'input': view.input,
        'output': _map(result['observation'])['output'],
      });
    }
  }

  List<_CaseView> casesFor(String? pass) {
    final views = _views[pass] ?? {};
    final result = <_CaseView>[];
    for (final item
        in (pass?.startsWith('final_') == true ? finalSuite : suite)) {
      final id = item['id'].toString();
      final round = scopeRound(pass);
      if (!views.containsKey(id) && (introduced[id] ?? 0) > round) continue;
      if (pass?.startsWith('challenge:') == true && !views.containsKey(id)) {
        continue;
      }
      final view =
          views[id] ??
          _CaseView(
            id,
            item['input']?.toString() ?? '',
            item['rubric']?.toString() ?? '',
          );
      if (view.rubric.isEmpty) view.rubric = item['rubric']?.toString() ?? '';
      result.add(view);
    }
    for (final view in views.values) {
      if (!result.any((v) => v.id == view.id)) result.add(view);
    }
    return result;
  }
}

class _SuiteLibrary extends StatefulWidget {
  const _SuiteLibrary({
    required this.cases,
    required this.chinese,
    required this.settings,
  });
  final List<Map<String, Object?>> cases;
  final bool chinese;
  final LiquidGlassSettings settings;
  @override
  State<_SuiteLibrary> createState() => _SuiteLibraryState();
}

class _SuiteLibraryState extends State<_SuiteLibrary> {
  final _search = TextEditingController();
  String _split = 'all';
  String tr(String zh, String en) => widget.chinese ? zh : en;
  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final query = _search.text.trim().toLowerCase();
    final cases = widget.cases
        .where(
          (c) =>
              (_split == 'all' || (c['split'] ?? 'training') == _split) &&
              ['id', 'input', 'rubric'].any(
                (key) =>
                    c[key]?.toString().toLowerCase().contains(query) == true,
              ),
        )
        .toList();
    return Dialog(
      backgroundColor: Colors.transparent,
      child: SizedBox(
        width: 920,
        height: MediaQuery.sizeOf(context).height * .82,
        child: GlassCard(
          settings: widget.settings,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${tr('测试题库', 'Question library')} · ${widget.cases.length}',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    IconButton(
                      tooltip: tr('关闭', 'Close'),
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(CupertinoIcons.xmark, size: 18),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                GlassTextField(
                  key: const ValueKey('rsi-suite-search'),
                  controller: _search,
                  settings: widget.settings,
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final split in {
                      'all': tr('全部', 'All'),
                      'training': tr('训练', 'Training'),
                      'validation': tr('验证', 'Validation'),
                      if (widget.cases.any((c) => c['split'] == 'test'))
                        'test': tr('测试', 'Test'),
                      if (widget.cases.any((c) => c['split'] == 'final'))
                        'final': tr('最终测试', 'Final tests'),
                    }.entries)
                      ChoiceChip(
                        label: Text(split.value),
                        selected: _split == split.key,
                        onSelected: (_) => setState(() => _split = split.key),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: cases.isEmpty
                      ? Center(
                          child: Text(tr('没有匹配的问题', 'No matching questions')),
                        )
                      : ListView.builder(
                          itemCount: cases.length,
                          itemBuilder: (context, index) {
                            final item = cases[index];
                            return ExpansionTile(
                              key: ValueKey('rsi-library-case-${item['id']}'),
                              leading: Text('${index + 1}'.padLeft(2, '0')),
                              title: Text(
                                item['input']?.toString() ?? '',
                                maxLines: 3,
                                overflow: TextOverflow.ellipsis,
                              ),
                              childrenPadding: const EdgeInsets.fromLTRB(
                                16,
                                0,
                                16,
                                20,
                              ),
                              expandedCrossAxisAlignment:
                                  CrossAxisAlignment.start,
                              children: [
                                SelectableText(item['input']?.toString() ?? ''),
                                if ((item['coverage_tags'] as List? ?? [])
                                    .isNotEmpty) ...[
                                  const SizedBox(height: 12),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 8,
                                    children: [
                                      for (final tag
                                          in item['coverage_tags'] as List)
                                        Chip(label: Text(tag.toString())),
                                    ],
                                  ),
                                ],
                                const SizedBox(height: 16),
                                Text(
                                  tr('评测标准', 'Rubric'),
                                  style: Theme.of(context).textTheme.titleSmall,
                                ),
                                const SizedBox(height: 8),
                                SelectableText(
                                  item['rubric']?.toString() ?? '',
                                ),
                              ],
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

Map<int, Map<String, Map<String, Object?>>> _toolEvolution(
  Map<String, Object?>? run,
  List<Map<String, Object?>> events,
) {
  final versions = <int, Map<String, Map<String, Object?>>>{0: {}};
  void add(int round, Object? package) {
    if (package is! Map) return;
    final tools = <String, Map<String, Object?>>{};
    for (final file in _map(package['files']).entries) {
      if (!file.key.startsWith('tools/rsi/') || !file.key.endsWith('.json')) {
        continue;
      }
      try {
        tools[file.key.split('/').last.replaceFirst('.json', '')] = _map(
          jsonDecode(file.value as String),
        );
      } on Object {
        /* Incomplete journal records are ignored until a full snapshot arrives. */
      }
    }
    versions[round] = tools;
  }

  for (final event in events) {
    final data = _map(event['data']);
    if (event['event'] == 'operation_started') add(0, data['package']);
    if (event['event'] == 'candidate_created') {
      add((data['round'] as num?)?.toInt() ?? 0, data['package']);
    }
  }
  for (final iteration in _rows([
    ..._rows(_map(run?['result'])['iterations']),
    ..._rows(run?['iterations']),
  ])) {
    final round = iteration['iteration'] ?? iteration['round'];
    if (round is num) {
      add(
        round.toInt(),
        iteration['package'] ?? iteration['candidate_package'],
      );
    }
  }
  return Map.fromEntries(
    versions.entries.toList()..sort((a, b) => a.key.compareTo(b.key)),
  );
}
