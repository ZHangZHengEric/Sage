import 'rsi_transcript.dart';
import 'rsi_activity.dart';
import 'rsi_conversation_stream.dart';
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
  String? _selectedSplit;
  int _selectedExecution = 1;
  int _page = 0;
  static const _pageSize = 12;
  _Projection? _cachedProjection;
  Map<String, Object?>? _projectedRun;
  int _projectedEvents = -1;
  Object? _lastProjectedEvent;
  List<RsiRoundDiff> _cachedDiffs = [];
  List<Map<String, Object?>> _cachedTrend = [];
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
    if (oldWidget.run?['id'] != widget.run?['id']) {
      _selectedPass = null;
      _selectedExecution = 1;
      _selectedSplit = null;
      _page = 0;
    }
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
    if (_cachedProjection == null ||
        !identical(_projectedRun, widget.run) ||
        _projectedEvents != widget.events.length ||
        !identical(_lastProjectedEvent, widget.events.lastOrNull)) {
      _cachedProjection = _Projection(widget.run, widget.events);
      _cachedDiffs = collectRsiRoundDiffs(widget.run, widget.events);
      _cachedTrend = _cachedProjection!.scoreTrend(
        _rows(widget.run?['test_observations']),
      );
      _projectedRun = widget.run;
      _projectedEvents = widget.events.length;
      _lastProjectedEvent = widget.events.lastOrNull;
    }
    final projection = _cachedProjection!;
    final passes = projection.passes;
    final pass = passes.contains(_selectedPass)
        ? _selectedPass
        : passes.lastOrNull;
    final cases = projection.casesFor(pass);
    final selectedCheckpoint = _rows(widget.run?['test_observations'])
        .where((record) => record['round'] == projection.scopeRound(pass))
        .lastOrNull;
    final split =
        _selectedSplit ??
        (pass?.startsWith('final_') == true ? 'test' : 'training');
    final questions = {
      for (final q in [
        ...projection.suite,
        ...projection.finalSuite,
        ...projection.humanTestSuite,
      ])
        q['id'].toString(): q,
    };
    final testCases = pass?.startsWith('final_') == true
        ? cases
        : [
            for (final question in projection.humanTestSuite)
              _CaseView(
                question['id'].toString(),
                question['input']?.toString() ?? '',
                question['rubric']?.toString() ?? '',
              ),
          ];
    if (pass?.startsWith('final_') != true) {
      final checkpoint = _rows(
        widget.run?['test_observations'],
      ).where((r) => r['round'] == projection.scopeRound(pass)).lastOrNull;
      if (checkpoint != null) {
        for (final row in _rows(checkpoint['cases'])) {
          final view = testCases.where((c) => c.id == row['id']).firstOrNull;
          if (view == null || checkpoint['valid'] == false) continue;
          if (row['score'] is num) {
            view.grade = {'score': row['score'], 'passed': row['passed']};
            view.state = 'graded';
          } else if (row['status'] == 'running') {
            view.state = 'responding';
          }
        }
      }
    }
    final datasets = <String, List<_CaseView>>{
      'training': pass?.startsWith('final_') == true
          ? []
          : cases
                .where(
                  (c) =>
                      (questions[c.id]?['split'] ?? 'training') == 'training',
                )
                .toList(),
      'validation': pass?.startsWith('final_') == true
          ? []
          : cases
                .where((c) => questions[c.id]?['split'] == 'validation')
                .toList(),
      'test': testCases,
    };
    final filteredCases = datasets[split]!;
    final matrixExecutions = filteredCases.fold<int>(
      split == 'test'
          ? 1
          : ((widget.run?['evaluation_repeats'] as num?)?.toInt() ?? 1),
      (count, item) =>
          math.max(count, item.trialViews.keys.fold<int>(0, math.max)),
    );
    final execution = _selectedExecution.clamp(1, matrixExecutions);
    final selectedCases = matrixExecutions > 1
        ? [for (final item in filteredCases) item.executionView(execution)]
        : filteredCases;
    final pageCount = math.max(1, (filteredCases.length / _pageSize).ceil());
    final page = _page.clamp(0, pageCount - 1);
    final pageCases = selectedCases
        .skip(page * _pageSize)
        .take(_pageSize)
        .toList();
    final graded = cases.where((c) => c.grade.isNotEmpty).length;
    final responding = running
        ? cases
              .where(
                (c) => const ['responding', 'evaluating'].contains(c.state),
              )
              .length
        : 0;
    final run = widget.run;
    final status = switch (run?['status']) {
      'running' => rsiRunningActivity(
        run,
        widget.events,
        chinese: widget.chinese,
      ),
      'queued' => tr('排队中', 'Queued'),
      'completed' =>
        run?['goal_verified'] == false && run?['validation_case_count'] != null
            ? tr('未达到收敛目标', 'Convergence target not reached')
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
        Container(
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
                    key: const ValueKey('rsi-current-activity'),
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
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
                  const SizedBox(height: 20),
                  Wrap(
                    spacing: 20,
                    runSpacing: 8,
                    children: [
                      for (final step in [
                        (
                          '01',
                          tr('准备问题', 'Prepare questions'),
                          projection.suite.isNotEmpty,
                        ),
                        (
                          '02',
                          tr('展开对话', 'Conversations'),
                          projection.calls.isNotEmpty,
                        ),
                        (
                          '03',
                          tr('评估打标', 'Evaluate & label'),
                          projection.hasGrades,
                        ),
                        ('04', tr('迭代进化', 'Evolve'), projection.hasRounds),
                      ])
                        Text(
                          '${step.$1}  ${step.$2}',
                          style: Theme.of(context).textTheme.labelSmall
                              ?.copyWith(
                                color: step.$3
                                    ? accent
                                    : Theme.of(
                                        context,
                                      ).colorScheme.onSurfaceVariant,
                                fontWeight: FontWeight.w500,
                              ),
                        ),
                    ],
                  ),
                ],
              );
              final overview = constraints.maxWidth < 480
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
              final trend = RsiScoreTrend(
                records: _cachedTrend,
                chinese: widget.chinese,
              );
              return constraints.maxWidth >= 820
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        Expanded(child: overview),
                        const SizedBox(width: 20),
                        SizedBox(
                          width: (constraints.maxWidth * .3).clamp(240, 330),
                          child: trend,
                        ),
                      ],
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [overview, const SizedBox(height: 24), trend],
                    );
            },
          ),
        ),
        if (passes.isNotEmpty)
          Padding(
            key: const ValueKey('rsi-pass-selector'),
            padding: const EdgeInsets.only(top: 20, bottom: 4),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final value in passes)
                  ChoiceChip(
                    showCheckmark: false,
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    backgroundColor: Colors.transparent,
                    selectedColor: accent.withValues(alpha: dark ? .14 : .08),
                    side: BorderSide(
                      color: pass == value
                          ? accent.withValues(alpha: .4)
                          : Theme.of(
                              context,
                            ).colorScheme.outlineVariant.withValues(alpha: .5),
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                    labelStyle: Theme.of(context).textTheme.labelMedium
                        ?.copyWith(
                          color: pass == value
                              ? accent
                              : Theme.of(context).colorScheme.onSurfaceVariant,
                          fontWeight: pass == value
                              ? FontWeight.w600
                              : FontWeight.w400,
                        ),
                    label: Text(projection.passLabel(value, widget.chinese)),
                    selected: pass == value,
                    onSelected: (_) => setState(() {
                      _selectedPass = value;
                      _selectedExecution = 1;
                      _selectedSplit = null;
                      _page = 0;
                    }),
                  ),
              ],
            ),
          ),
        if (selectedCheckpoint != null) ...[
          const SizedBox(height: 16),
          RsiScoreHistory(
            key: ValueKey('rsi-scores-${widget.run?["id"]}'),
            records: [selectedCheckpoint],
            round: projection.scopeRound(pass),
            settings: widget.settings,
            chinese: widget.chinese,
          ),
        ],
        if (selectedCheckpoint == null &&
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
              final sideBySide = constraints.maxWidth >= 660;
              final columns = math.max(
                1,
                (((constraints.maxWidth - 12) / 2 - 32 + 6) / 20).floor(),
              );
              final largestSet = math.max(
                visible.where((q) => q['split'] == 'training').length,
                visible.where((q) => q['split'] == 'validation').length,
              );
              final dotHeight = sideBySide
                  ? (math.max(1, (largestSet / columns).ceil()) * 20 - 6)
                        .clamp(14, 180)
                        .toDouble()
                  : null;
              Widget matrix(String split) => _ScoreMatrix(
                split: split,
                questions: visible.where((q) => q['split'] == split).toList(),
                views: {for (final item in cases) item.id: item},
                running: running,
                dotHeight: dotHeight,
                onOpen: _openConversation,
                repeatCount: cases.fold<int>(
                  (widget.run?['evaluation_repeats'] as num?)?.toInt() ?? 1,
                  (count, item) => math.max(
                    count,
                    item.trialViews.keys.fold<int>(0, math.max),
                  ),
                ),
                settings: widget.settings,
                chinese: widget.chinese,
              );
              return !sideBySide
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
        const SizedBox(height: 14),
        RsiRoundChanges(
          selectedRound: projection.scopeRound(pass),
          diffs: _cachedDiffs,
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
                  shape: const LiquidRoundedRectangle(borderRadius: 10),
                  settings: widget.settings,
                  onTap: () => showDialog<void>(
                    context: context,
                    builder: (context) => _SuiteLibrary(
                      executedInputs: {
                        for (final id in questions.keys)
                          if (projection.executedInput(id)
                              case final String value)
                            id: value,
                      },
                      cases: [
                        for (final question in {
                          for (final item in [
                            ...projection.suite,
                            ...projection.finalSuite,
                            ...projection.humanTestSuite,
                          ])
                            item['id']: item,
                        }.values)
                          {
                            ...question,
                            'human_display': _map(
                              _map(run?['human_case_details'])[question['id']],
                            ),
                          },
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
        Wrap(
          spacing: 16,
          runSpacing: 12,
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final entry in {
                  'training': tr('训练集', 'Training'),
                  'validation': tr('验证集', 'Validation'),
                  'test': tr('测试集', 'Test'),
                }.entries)
                  ChoiceChip(
                    key: ValueKey('rsi-matrix-split-${entry.key}'),
                    label: Text(
                      '${entry.value} ${datasets[entry.key]!.length}',
                    ),
                    selected: split == entry.key,
                    showCheckmark: false,
                    selectedColor: accent.withValues(alpha: .12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                    onSelected: (_) => setState(() {
                      _selectedSplit = entry.key;
                      _page = 0;
                    }),
                  ),
              ],
            ),
            if (matrixExecutions > 1)
              GlassPicker(
                key: const ValueKey('rsi-matrix-execution-picker'),
                value: tr('第 $execution 次执行', 'Execution $execution'),
                width: 156,
                height: 34,
                settings: widget.settings,
                textStyle: Theme.of(context).textTheme.bodyMedium,
                onTap: () =>
                    _chooseMatrixExecution(matrixExecutions, execution),
              ),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  key: const ValueKey('rsi-matrix-previous'),
                  tooltip: tr('上一页', 'Previous page'),
                  onPressed: page == 0
                      ? null
                      : () => setState(() => _page = page - 1),
                  icon: const Icon(CupertinoIcons.chevron_left, size: 16),
                ),
                Text(
                  '${page + 1} / $pageCount',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                IconButton(
                  key: const ValueKey('rsi-matrix-next'),
                  tooltip: tr('下一页', 'Next page'),
                  onPressed: page + 1 >= pageCount
                      ? null
                      : () => setState(() => _page = page + 1),
                  icon: const Icon(CupertinoIcons.chevron_right, size: 16),
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 14),
        if (filteredCases.isEmpty)
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
                          : tr(
                              '当前数据集暂无对话记录',
                              'No conversations in this dataset',
                            ),
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
                  for (final (index, item) in pageCases.indexed)
                    SizedBox(
                      width: width,
                      child: _conversation(
                        item,
                        accent,
                        violet,
                        page * _pageSize + index + 1,
                      ),
                    ),
                ],
              );
            },
          ),
        const SizedBox(height: 24),
      ],
    );
  }

  Future<void> _chooseMatrixExecution(int count, int selected) =>
      showDialog<void>(
        context: context,
        builder: (context) => Dialog(
          backgroundColor: Colors.transparent,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 320, maxHeight: 480),
            child: GlassCard(
              useOwnLayer: true,
              settings: widget.settings.copyWith(
                glassColor: Theme.of(context).colorScheme.surface,
                visibility: 1,
                standardOpacityMultiplier: 1,
                lightIntensity: 0,
                glowIntensity: 0,
                blur: 0,
              ),
              padding: const EdgeInsets.all(8),
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (var index = 1; index <= count; index++)
                    ListTile(
                      key: ValueKey('rsi-matrix-execution-$index'),
                      title: Text(tr('第 $index 次执行', 'Execution $index')),
                      selected: index == selected,
                      trailing: index == selected
                          ? const Icon(CupertinoIcons.checkmark, size: 16)
                          : null,
                      onTap: () {
                        setState(() {
                          _selectedExecution = index;
                          _page = 0;
                        });
                        Navigator.pop(context);
                      },
                    ),
                ],
              ),
            ),
          ),
        ),
      );

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
              child: RsiConversationStream(
                key: PageStorageKey(
                  'rsi-messages-${widget.run?['id']}-${item.id}-${_selectedPass ?? 'latest'}-${item.execution ?? 'aggregate'}',
                ),
                revision: Object.hash(
                  Object.hashAll(
                    item.turns.map(
                      (turn) => Object.hash(turn['input'], turn['output']),
                    ),
                  ),
                  item.grade['rationale'],
                ),
                children: [
                  ..._conversationMessages(item, accent, violet),
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

  List<Widget> _conversationMessages(
    _CaseView item,
    Color accent,
    Color violet, {
    bool expanded = false,
  }) {
    final messages = <({String role, String text})>[];
    final structured = item.turns.any(
      (turn) => rsiTranscript(
        turn['output']?.toString() ?? '',
      ).any((message) => message.role == 'user'),
    );
    if (!structured && widget.run?['input_visibility'] != 'opaque_fixture') {
      messages.add((role: 'user', text: item.input));
    }
    for (final turn in item.turns) {
      final output = turn['output']?.toString();
      final transcript = output == null
          ? <({String role, String text})>[]
          : rsiTranscript(output);
      if (transcript.isNotEmpty) {
        messages.addAll(transcript);
      } else {
        if (turn['input'] != item.input) {
          messages.add((role: 'user', text: turn['input']?.toString() ?? ''));
        }
        if (output != null) messages.add((role: 'assistant', text: output));
      }
    }
    return [
      for (final message in messages)
        _bubble(
          message.text,
          message.role != 'user',
          message.role == 'assistant' ? violet : accent,
          label: message.role == 'tool'
              ? tr('工具', 'Tool')
              : message.role == 'user'
              ? tr('用户', 'User')
              : 'Agent',
          expanded: expanded,
        ),
    ];
  }

  Widget _bubble(
    String value,
    bool agent,
    Color color, {
    String? label,
    bool expanded = false,
  }) => Container(
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
          label ?? (agent ? 'Agent' : tr('问题', 'Question')),
          style: TextStyle(
            color: color,
            fontSize: 10,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 5),
        if (expanded)
          SelectableText(
            value,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(height: 1.55),
          )
        else
          Text(
            value,
            maxLines: 5,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(height: 1.55),
          ),
      ],
    ),
  );

  List<Widget> _gradeDetails(
    String title,
    Map<String, Object?> grade, {
    bool evaluator = false,
    bool showRationale = true,
    bool showScore = true,
  }) {
    final diagnosis = evaluator
        ? _map(grade['diagnosis'])
        : <String, Object?>{};
    final rendered = <String>{};
    bool first(Object? value) {
      final normalized =
          value?.toString().trim().replaceAll(RegExp(r'\s+'), ' ') ?? '';
      return normalized.isNotEmpty && rendered.add(normalized);
    }

    return [
      Text(title, style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 10),
      if (grade.isEmpty)
        Text(
          evaluator
              ? tr(
                  '暂无 Eval Agent 评价或建议记录',
                  'No Eval Agent evaluation or recommendations recorded',
                )
              : tr('暂无评分记录', 'No grading record'),
        )
      else ...[
        if (showScore)
          Wrap(
            spacing: 16,
            runSpacing: 8,
            children: [
              Text(
                '${tr('评分', 'Score')} ${(grade['score'] as num?)?.toStringAsFixed(3) ?? '—'}',
              ),
              if (grade['passed'] is bool)
                Text(
                  grade['passed'] == true
                      ? tr('通过', 'Passed')
                      : tr('未通过', 'Failed'),
                ),
            ],
          ),
        if (showRationale &&
            (!evaluator || diagnosis.isEmpty) &&
            first(grade['rationale'])) ...[
          const SizedBox(height: 8),
          SelectableText(grade['rationale'].toString()),
        ],
        if (first(diagnosis['summary'])) ...[
          const SizedBox(height: 12),
          SelectableText(diagnosis['summary'].toString()),
        ],
        for (final finding in _rows(diagnosis['findings'])) ...[
          const SizedBox(height: 12),
          if (first(finding['cause']))
            SelectableText(finding['cause'].toString()),
          if (first(finding['recommendation'])) ...[
            const SizedBox(height: 6),
            Text(
              tr('建议', 'Recommendation'),
              style: Theme.of(context).textTheme.labelMedium,
            ),
            SelectableText(finding['recommendation'].toString()),
          ],
        ],
        if (evaluator)
          for (final entry in <String, Object?>{
            tr('优点', 'Strengths'): diagnosis['strengths'],
            tr('不确定项', 'Uncertainties'): diagnosis['uncertainties'],
            tr('评估覆盖范围', 'Evaluation coverage'): diagnosis['coverage'],
          }.entries)
            if (entry.value is String &&
                    (entry.value as String).trim().isNotEmpty ||
                entry.value is List && (entry.value as List).isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(entry.key, style: Theme.of(context).textTheme.labelMedium),
              const SizedBox(height: 6),
              SelectableText(
                entry.value is List
                    ? (entry.value as List).join('\n')
                    : entry.value.toString(),
              ),
            ],
        if (evaluator && diagnosis.isEmpty && grade['rationale'] == null)
          Text(tr('暂无评价或建议记录', 'No evaluation or recommendations recorded')),
      ],
    ];
  }

  Map<String, Object?> _evalGrade(
    Map<String, Object?> model,
    Map<String, Object?> grade,
  ) => model.isNotEmpty
      ? model
      : _map(grade['diagnosis']).isNotEmpty
      ? grade
      : {};

  List<Widget> _evaluationDetails(_CaseView item) {
    final evaluation = _evalGrade(item.modelGrade, item.grade);
    return [
      ..._gradeDetails(
        tr('实际评分', 'Actual grade'),
        item.grade,
        showRationale: evaluation.isEmpty,
      ),
      const Divider(height: 28),
      ..._gradeDetails(
        tr('Eval Agent 评价与建议', 'Eval Agent evaluation and recommendations'),
        evaluation,
        evaluator: true,
        showScore:
            evaluation['score'] != item.grade['score'] ||
            evaluation['passed'] != item.grade['passed'],
      ),
    ];
  }

  List<Widget> _executionDetails(_CaseView item) => [
    Text(
      tr('执行过程', 'Execution'),
      style: Theme.of(context).textTheme.titleMedium,
    ),
    const SizedBox(height: 10),
    if (item.observation['state'] != null)
      Text('${tr('执行状态', 'Execution state')} ${item.observation['state']}'),
    if (item.observation['elapsed_seconds'] is num)
      Text(
        '${tr('耗时', 'Elapsed')} ${(item.observation['elapsed_seconds'] as num).toStringAsFixed(2)} s',
      ),
    const SizedBox(height: 12),
    ..._conversationMessages(
      item,
      Theme.of(context).colorScheme.primary,
      Theme.of(context).colorScheme.secondary,
      expanded: true,
    ),
    if (!item.turns.any((t) => t['output']?.toString().isNotEmpty == true))
      Text(tr('暂无执行对话记录', 'No execution dialogue recorded')),
    const Divider(height: 28),
  ];

  void _openConversation(_CaseView item) {
    final projection = _cachedProjection;
    final passes = projection?.passes ?? <String>[];
    final pass = passes.contains(_selectedPass)
        ? _selectedPass
        : passes.lastOrNull;
    final prefix = pass == null
        ? item.id
        : '${projection!.passLabel(pass, widget.chinese)} · ${item.id}';
    final title = item.execution == null
        ? prefix
        : '$prefix · ${tr('第 ${item.execution} 次执行', 'Execution ${item.execution}')}';
    final repeated = item.execution == null && item.trialViews.length > 1;
    final executions = item.trialViews.entries.toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog(
        backgroundColor: Colors.transparent,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820, maxHeight: 780),
          child: GlassCard(
            settings: widget.settings.copyWith(
              glassColor: Theme.of(context).colorScheme.surface,
              visibility: 1,
              standardOpacityMultiplier: 1,
              lightIntensity: 0,
              glowIntensity: 0,
              blur: 0,
            ),
            useOwnLayer: true,
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        title,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    IconButton(
                      tooltip: tr('关闭', 'Close'),
                      onPressed: () => Navigator.pop(dialogContext),
                      icon: const Icon(CupertinoIcons.xmark),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (item.rubric.isNotEmpty) ...[
                          Text(
                            tr('评测标准', 'Rubric'),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 8),
                          SelectableText(item.rubric),
                          const Divider(height: 28),
                        ],
                        if (!repeated) ...[
                          ..._executionDetails(item),
                          ..._evaluationDetails(item),
                        ] else ...[
                          ..._gradeDetails(
                            tr('汇总评分', 'Aggregate grade'),
                            item.grade,
                            showRationale: false,
                          ),
                          for (final entry in executions)
                            ExpansionTile(
                              title: Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      tr(
                                        '第 ${entry.key} 次执行',
                                        'Execution ${entry.key}',
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 10),
                                  Text(
                                    (entry.value.grade['score'] as num?)
                                            ?.toStringAsFixed(3) ??
                                        '—',
                                  ),
                                ],
                              ),
                              children: [
                                Padding(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 12,
                                  ),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.stretch,
                                    children: [
                                      ..._executionDetails(entry.value),
                                      ..._evaluationDetails(entry.value),
                                    ],
                                  ),
                                ),
                              ],
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
    required this.running,
    this.dotHeight,
    this.repeatCount = 1,
    this.trialIndex,
    this.embedded = false,
    required this.settings,
    required this.chinese,
    required this.onOpen,
  });
  final String split;
  final List<Map<String, Object?>> questions;
  final Map<String, _CaseView> views;
  final bool running;
  final double? dotHeight;
  final int repeatCount;
  final int? trialIndex;
  final bool embedded;
  final LiquidGlassSettings settings;
  final bool chinese;
  final ValueChanged<_CaseView> onOpen;
  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final title = split == 'training'
        ? (chinese ? '训练集' : 'Training set')
        : (chinese ? '验证集' : 'Validation set');
    if (repeatCount > 1) {
      return GlassCard(
        key: ValueKey('rsi-score-matrix-$split'),
        settings: settings,
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: Theme.of(
                context,
              ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
            ),
            for (var trial = 1; trial <= repeatCount; trial++) ...[
              const SizedBox(height: 14),
              if (trial > 1) const Divider(height: 16),
              _ScoreMatrix(
                split: split,
                questions: questions,
                views: {
                  for (final q in questions)
                    q['id'].toString():
                        (views[q['id'].toString()] ??
                                _CaseView(
                                  q['id'].toString(),
                                  q['input']?.toString() ?? '',
                                  q['rubric']?.toString() ?? '',
                                ))
                            .executionView(trial),
                },
                running: running,
                dotHeight: dotHeight,
                settings: settings,
                chinese: chinese,
                onOpen: onOpen,
                trialIndex: trial,
                embedded: true,
              ),
            ],
          ],
        ),
      );
    }
    double? score(String id) => (views[id]?.grade['score'] as num?)?.toDouble();
    final graded = questions
        .where((q) => score(q['id'].toString()) != null)
        .length;
    final items = [for (final q in questions) views[q['id'].toString()]];
    final active = items
        .where(
          (item) =>
              running &&
              (item?.state == 'responding' || item?.state == 'evaluating'),
        )
        .length;
    final waiting = items
        .where(
          (item) => running
              ? item == null || item.state == 'waiting'
              : item?.grade['score'] == null,
        )
        .length;
    final passed = items.where((item) => item?.grade['passed'] == true).length;
    final failed = items.where((item) => item?.grade['passed'] == false).length;
    final scores = [
      for (final q in questions)
        if (score(q['id'].toString()) case final double value) value,
    ];
    final average = scores.isEmpty
        ? '—'
        : (scores.reduce((a, b) => a + b) / scores.length).toStringAsFixed(3);
    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              trialIndex == null
                  ? title
                  : (chinese ? '第 $trialIndex 次执行' : 'Execution $trialIndex'),
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
          constraints: BoxConstraints(
            minHeight: dotHeight ?? 0,
            maxHeight: 180,
          ),
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
                          running &&
                          (state == 'responding' || state == 'evaluating');
                      final status = value != null
                          ? value.toStringAsFixed(3)
                          : active
                          ? (chinese ? '评测中' : 'Evaluating')
                          : (chinese ? '未评估' : 'Not evaluated');
                      final label =
                          '$title ${index + 1}${trialIndex == null ? '' : ' · ${chinese ? '第 $trialIndex 次执行' : 'Execution $trialIndex'}'} · $status';
                      return Semantics(
                        button: true,
                        label: '$label · ${question['input']}',
                        child: MouseRegion(
                          cursor: SystemMouseCursors.click,
                          child: GestureDetector(
                            onTap: () => onOpen(
                              views[id] ??
                                  _CaseView(
                                    id,
                                    question['input']?.toString() ?? '',
                                    question['rubric']?.toString() ?? '',
                                  ),
                            ),
                            child: Tooltip(
                              message: label,
                              child: AnimatedContainer(
                                key: ValueKey(
                                  trialIndex == null
                                      ? 'rsi-score-dot-$split-$id'
                                      : 'rsi-score-dot-$split-$id-trial-$trialIndex',
                                ),
                                duration:
                                    MediaQuery.disableAnimationsOf(context)
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
                          ),
                        ),
                      );
                    },
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 18,
          runSpacing: 8,
          children: [
            for (final stat in [
              '${chinese ? '通过' : 'Passed'} $passed',
              '${chinese ? '未通过' : 'Failed'} $failed',
              '${chinese ? '执行中' : 'Active'} $active',
              '${running ? (chinese ? '待执行' : 'Pending') : (chinese ? '未评估' : 'Not evaluated')} $waiting',
              '${chinese ? '平均分' : 'Average'} $average',
            ])
              Text(
                stat,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
          ],
        ),
      ],
    );
    return embedded
        ? content
        : GlassCard(
            key: ValueKey('rsi-score-matrix-$split'),
            settings: settings,
            padding: const EdgeInsets.all(16),
            child: content,
          );
  }
}

class _CaseView {
  _CaseView(this.id, this.input, this.rubric);
  final String id;
  String input, rubric;
  String state = 'waiting';
  Map<String, Object?> grade = {};
  Map<String, Object?> modelGrade = {};
  Map<String, Object?> observation = {};
  List<Map<String, Object?>> trials = [];
  final trialResults = <int, Map<String, Object?>>{};
  final trialViews = <int, _CaseView>{};
  int? execution;
  _CaseView executionView(int index) {
    final view = trialViews.putIfAbsent(
      index,
      () => _CaseView(id, input, rubric)..execution = index,
    );
    if (view.rubric.isEmpty) view.rubric = rubric;
    return view;
  }

  List<double> trialScores = [];
  final trialGrades = <int, Map<String, Object?>>{};
  double? get meanScore {
    if (trialScores.isNotEmpty) {
      return trialScores.reduce((a, b) => a + b) / trialScores.length;
    }
    return (grade['score'] as num?)?.toDouble();
  }

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
          final trial = (data['trial'] as num?)?.toInt() ?? 1;
          final turn = <String, Object?>{
            'input': data['input'],
            'trial': trial,
          };
          view.turns.add(turn);
          final individual = view.executionView(trial);
          individual.state = 'responding';
          individual.turns.add(turn);
          calls[data['call_id'].toString()] = (view, turn);
        case 'target_call_completed':
          final call = calls[data['call_id'].toString()];
          if (call != null) {
            call.$1.observation = _map(data['observation']);
            call.$2['output'] = _map(data['observation'])['output'];
            call.$1.state = 'evaluating';
            final individual = call.$1.executionView(
              (call.$2['trial'] as int?) ?? 1,
            );
            individual.observation = _map(data['observation']);
            individual.state = 'evaluating';
          }
        case 'case_completed':
          _result(
            _pass(data),
            _map(data['result']),
            trial: (data['trial'] as num?)?.toInt(),
          );
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
  List<String> get passes =>
      _passes.where((p) => !p.startsWith('challenge:')).toList();
  List<Map<String, Object?>> scoreTrend(
    List<Map<String, Object?>> checkpoints,
  ) {
    final measured = <int, Map<String, Object?>>{};
    Map<String, Object?> row(int round) => measured.putIfAbsent(
      round,
      () => {'round': round, 'scores': <String, Object?>{}},
    );
    final repeated = <int, Map<String, List<double>>>{};
    // Average complete trials for display; optimizer acceptance may deliberately
    // use minimum scores instead. Incomplete splits never contribute a point.
    for (final pass in passes.where(
      (p) => p.startsWith('baseline:') || p.startsWith('candidate:'),
    )) {
      final cases = casesFor(pass);
      for (final split in ['training', 'validation']) {
        final cohort = cases
            .where(
              (c) => suite.any((q) => q['id'] == c.id && q['split'] == split),
            )
            .toList();
        final grades = cohort.map((c) => c.meanScore).whereType<num>().toList();
        if (cohort.isNotEmpty && cohort.length == grades.length) {
          final bySplit = repeated.putIfAbsent(scopeRound(pass), () => {});
          (bySplit[split] ??= []).add(
            grades.fold<double>(0, (sum, grade) => sum + grade) / grades.length,
          );
        }
      }
    }
    for (final round in repeated.entries) {
      for (final split in round.value.entries) {
        _map(row(round.key)['scores'])[split.key] =
            split.value.reduce((a, b) => a + b) / split.value.length;
      }
    }
    for (final checkpoint in checkpoints) {
      final round = (checkpoint['round'] as num?)?.toInt();
      if (round == null) continue;
      final target = row(round);
      for (final split in ['training', 'validation', 'test']) {
        final value = _map(checkpoint['scores'])[split];
        if (value is num &&
            !(split == 'test' && checkpoint['valid'] == false)) {
          // Checkpoint development scores can use the optimizer's minimum
          // aggregation; never overwrite a mean reconstructed from actual trials.
          _map(target['scores']).putIfAbsent(split, () => value);
        }
      }
    }
    final result = measured.values.toList()
      ..sort((a, b) => (a['round'] as num).compareTo(b['round'] as num));
    return result;
  }

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
    return '$phase:$round';
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
      'baseline' => zh ? '基线轮' : 'Baseline',
      'challenge' =>
        zh
            ? '第 ${parts[1]} 轮 · 新增题预评测'
            : 'Round ${parts[1]} · New-case pre-evaluation',
      'final_baseline' => zh ? '最终测试 · 基线' : 'Final · Baseline',
      'final_candidate' => zh ? '最终测试 · 候选' : 'Final · Candidate',
      final value when value.startsWith('stability_') =>
        '${zh ? '稳定性复测' : 'Stability check'} ${value.substring(10)}',
      _ => '${zh ? '第' : 'Round'} ${parts[1]}${zh ? ' 轮' : ''}',
    };
    return parts.length > 2
        ? '$phase · ${zh ? '复测' : 'Trial'} ${parts[2]}'
        : phase;
  }

  _CaseView _case(String pass, String id, String input) =>
      (_views[pass] ??= {})[id] ??= _CaseView(id, input, '');
  void _result(String pass, Map<String, Object?> result, {int? trial}) {
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
    view.modelGrade = _map(result['model_grade']);
    view.observation = _map(result['observation']);
    view.trials = _rows(result['trials']);
    for (final (index, record) in view.trials.indexed) {
      _fillExecution(view.executionView(index + 1), record);
    }
    if (trial != null) _fillExecution(view.executionView(trial), result);
    if (trial != null) view.trialResults[trial] = result;
    if (view.trials.isEmpty && view.trialResults.isNotEmpty) {
      final indexes = view.trialResults.keys.toList()..sort();
      view.trials = [for (final index in indexes) view.trialResults[index]!];
    }
    if (trial != null) view.trialGrades[trial] = view.grade;
    view.trialScores = _rows(result['trials'])
        .map((trial) => _map(trial['grade'])['score'])
        .whereType<num>()
        .map((score) => score.toDouble())
        .toList();
    if (view.trialScores.isEmpty && view.trialGrades.isNotEmpty) {
      view.trialScores = view.trialGrades.values
          .map((g) => g['score'])
          .whereType<num>()
          .map((v) => v.toDouble())
          .toList();
      view.grade = {
        ...view.grade,
        'score': view.meanScore,
        'passed': view.trialGrades.values.every((g) => g['passed'] == true),
      };
    }
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

  void _fillExecution(_CaseView view, Map<String, Object?> result) {
    view.grade = _map(result['grade']);
    view.modelGrade = _map(result['model_grade']);
    view.observation = _map(result['observation']);
    view.state = view.grade.isNotEmpty ? 'graded' : 'waiting';
    view.turns.clear();
    final dialogue = _rows(result['dialogue']);
    view.turns.addAll(
      dialogue.isNotEmpty
          ? [
              for (final turn in dialogue)
                {
                  'input': turn['input'],
                  'output': _map(turn['observation'])['output'],
                },
            ]
          : [
              {'input': view.input, 'output': view.observation['output']},
            ],
    );
  }

  String? executedInput(String id) {
    for (final views in _views.values) {
      for (final turn in views[id]?.turns ?? <Map<String, Object?>>[]) {
        final user = rsiTranscript(turn['output']?.toString() ?? '')
            .where(
              (message) =>
                  message.role == 'user' && message.text.trim().isNotEmpty,
            )
            .firstOrNull;
        if (user != null) return user.text;
      }
    }
    return null;
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
    required this.executedInputs,
    required this.cases,
    required this.chinese,
    required this.settings,
  });
  final List<Map<String, Object?>> cases;
  final Map<String, String> executedInputs;
  final bool chinese;
  final LiquidGlassSettings settings;
  @override
  State<_SuiteLibrary> createState() => _SuiteLibraryState();
}

class _SuiteLibraryState extends State<_SuiteLibrary> {
  final _search = TextEditingController();
  final _horizontal = ScrollController();
  final _vertical = ScrollController();
  String _split = 'all';
  int _page = 0;
  static const _pageSize = 10;
  String tr(String zh, String en) => widget.chinese ? zh : en;
  @override
  void dispose() {
    _search.dispose();
    _horizontal.dispose();
    _vertical.dispose();
    super.dispose();
  }

  Object? _decoded(Object? value) {
    if (value is! String) return value;
    try {
      return jsonDecode(value);
    } on FormatException {
      return value;
    }
  }

  String _readable(Object? value) {
    if (value == null) return '';
    if (value is List) {
      return value.map(_readable).where((s) => s.isNotEmpty).join('\n');
    }
    if (value is Map) {
      return value.entries
          .where((e) => e.value != null)
          .map((e) => '${_fieldName(e.key.toString())}: ${_readable(e.value)}')
          .join('\n');
    }
    return value.toString();
  }

  String _question(Map<String, Object?> item) {
    final human = _map(item['human_display'])['question'];
    if (human != null) return _readable(human);
    final input = item['input']?.toString() ?? '';
    final data = _decoded(input);
    if (data is! Map || !data.containsKey('tau_task_id')) return input;
    final scenario = _map(_decoded(item['reference_answer']))['user_scenario'];
    return item['display_input']?.toString() ??
        widget.executedInputs[item['id']] ??
        (scenario != null
            ? _readable(scenario)
            : tr('未保存题目正文', 'Question content was not saved'));
  }

  Object? _answer(Map<String, Object?> item) =>
      _map(item['human_display'])['reference_answer'] ??
      _decoded(item['reference_answer']);
  bool _hasAnswer(Map<String, Object?> item) =>
      _readable(_answer(item)).trim().isNotEmpty;

  String _fieldName(String key) => switch (key) {
    'instructions' => tr('任务要求', 'Instructions'),
    'task_instructions' => tr('任务说明', 'Task instructions'),
    'reason_for_call' => tr('用户诉求', 'User request'),
    'known_info' => tr('已知信息', 'Known information'),
    'unknown_info' => tr('未知信息', 'Unknown information'),
    'persona' => tr('用户背景', 'Persona'),
    'domain' => tr('业务领域', 'Domain'),
    'actions' => tr('预期操作', 'Expected actions'),
    'name' => tr('操作', 'Action'),
    'arguments' => tr('参数', 'Arguments'),
    'communicate_info' => tr('应告知用户的信息', 'Information to communicate'),
    'nl_assertions' => tr('判定要求', 'Assertions'),
    'user_scenario' => tr('题目场景', 'Scenario'),
    'evaluation_criteria' => tr('标准答案与判定条件', 'Reference and criteria'),
    _ => key,
  };

  String _splitName(Map<String, Object?> item) =>
      switch (item['split'] ?? 'training') {
        'validation' => tr('验证', 'Validation'),
        'test' => tr('测试', 'Test'),
        'final' => tr('最终测试', 'Final tests'),
        _ => tr('训练', 'Training'),
      };

  void _resetPage() {
    _page = 0;
    if (_vertical.hasClients) _vertical.jumpTo(0);
  }

  Future<void> _openQuestion(Map<String, Object?> item) => showDialog<void>(
    context: context,
    builder: (context) => Dialog(
      backgroundColor: Colors.transparent,
      child: SizedBox(
        width: 820,
        height: MediaQuery.sizeOf(context).height * .84,
        child: GlassCard(
          settings: widget.settings.copyWith(
            glassColor: Theme.of(context).colorScheme.surface,
            visibility: 1,
            standardOpacityMultiplier: 1,
            lightIntensity: 0,
            glowIntensity: 0,
            blur: 0,
          ),
          useOwnLayer: true,
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${item['id']} · ${_splitName(item)}',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    key: const ValueKey('rsi-library-detail-close'),
                    tooltip: tr('关闭', 'Close'),
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(CupertinoIcons.xmark, size: 18),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      for (final entry in <String, String>{
                        tr('题目内容', 'Question'): _question(item),
                        tr('标准答案', 'Reference answer'): _hasAnswer(item)
                            ? _readable(_answer(item))
                            : tr('未提供', 'Not provided'),
                        tr('评测标准', 'Rubric'): item['rubric']?.toString() ?? '—',
                      }.entries) ...[
                        Text(
                          entry.key,
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        const SizedBox(height: 8),
                        SelectableText(
                          entry.value,
                          style: Theme.of(
                            context,
                          ).textTheme.bodyMedium?.copyWith(height: 1.5),
                        ),
                        const SizedBox(height: 24),
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

  @override
  Widget build(BuildContext context) {
    final query = _search.text.trim().toLowerCase();
    final cases = widget.cases
        .where(
          (c) =>
              (_split == 'all' || (c['split'] ?? 'training') == _split) &&
              [
                c['id'],
                _question(c),
                c['rubric'],
                _readable(_answer(c)),
              ].any((v) => v?.toString().toLowerCase().contains(query) == true),
        )
        .toList();
    final pages = math.max(1, (cases.length / _pageSize).ceil());
    final page = _page.clamp(0, pages - 1);
    final shown = cases.skip(page * _pageSize).take(_pageSize).toList();
    Widget cell(
      String value,
      double width, {
      Key? key,
      bool question = false,
    }) => SizedBox(
      width: width,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Text(
              value,
              key: key,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(height: 1.4),
            ),
          ),
          if (question) ...[
            const SizedBox(width: 8),
            Icon(
              CupertinoIcons.chevron_right,
              size: 12,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ],
        ],
      ),
    );
    return Dialog(
      backgroundColor: Colors.transparent,
      child: SizedBox(
        width: 1160,
        height: MediaQuery.sizeOf(context).height * .84,
        child: GlassCard(
          useOwnLayer: true,
          settings: widget.settings.copyWith(
            glassColor: Theme.of(context).colorScheme.surface,
            visibility: 1,
            standardOpacityMultiplier: 1,
            lightIntensity: 0,
            glowIntensity: 0,
            blur: 0,
          ),
          padding: const EdgeInsets.all(24),
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
                onChanged: (_) => setState(_resetPage),
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
                      onSelected: (_) => setState(() {
                        _split = split.key;
                        _resetPage();
                      }),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Expanded(
                child: cases.isEmpty
                    ? Center(
                        child: Text(tr('没有匹配的问题', 'No matching questions')),
                      )
                    : LayoutBuilder(
                        builder: (context, constraints) {
                          final width = math.max(920.0, constraints.maxWidth);
                          final available = width - 360;
                          final widths = [
                            90.0,
                            70.0,
                            available * .4,
                            76.0,
                            available * .35,
                            available * .25,
                          ];
                          final labels = [
                            tr('题目 ID', 'Question ID'),
                            tr('数据集', 'Dataset'),
                            tr('题目内容', 'Question'),
                            tr('标准答案', 'Reference answer'),
                            tr('答案内容', 'Answer'),
                            tr('评测标准', 'Rubric'),
                          ];
                          return Scrollbar(
                            controller: _horizontal,
                            thumbVisibility: width > constraints.maxWidth,
                            notificationPredicate: (n) =>
                                n.metrics.axis == Axis.horizontal,
                            child: SingleChildScrollView(
                              controller: _horizontal,
                              scrollDirection: Axis.horizontal,
                              child: SizedBox(
                                width: width,
                                child: Scrollbar(
                                  controller: _vertical,
                                  thumbVisibility: true,
                                  child: SingleChildScrollView(
                                    controller: _vertical,
                                    child: DataTable(
                                      headingRowColor: WidgetStatePropertyAll(
                                        Theme.of(
                                          context,
                                        ).colorScheme.surfaceContainerHighest,
                                      ),
                                      dataRowMinHeight: 104,
                                      dataRowMaxHeight: 104,
                                      columnSpacing: 20,
                                      horizontalMargin: 12,
                                      columns: [
                                        for (var i = 0; i < labels.length; i++)
                                          DataColumn(
                                            label: SizedBox(
                                              width: widths[i],
                                              child: Text(
                                                labels[i],
                                                maxLines: 2,
                                                overflow: TextOverflow.ellipsis,
                                              ),
                                            ),
                                          ),
                                      ],
                                      rows: [
                                        for (final item in shown)
                                          DataRow(
                                            cells: [
                                              DataCell(
                                                cell(
                                                  item['id']?.toString() ?? '',
                                                  widths[0],
                                                ),
                                                onTap: () =>
                                                    _openQuestion(item),
                                              ),
                                              DataCell(
                                                cell(
                                                  _splitName(item),
                                                  widths[1],
                                                ),
                                                onTap: () =>
                                                    _openQuestion(item),
                                              ),
                                              DataCell(
                                                Tooltip(
                                                  message: tr(
                                                    '查看完整题目',
                                                    'View full question',
                                                  ),
                                                  child: cell(
                                                    _question(item),
                                                    widths[2],
                                                    key: ValueKey(
                                                      'rsi-library-case-${item['id']}',
                                                    ),
                                                    question: true,
                                                  ),
                                                ),
                                                onTap: () =>
                                                    _openQuestion(item),
                                              ),
                                              DataCell(
                                                cell(
                                                  _hasAnswer(item)
                                                      ? tr('已提供', 'Provided')
                                                      : tr(
                                                          '未提供',
                                                          'Not provided',
                                                        ),
                                                  widths[3],
                                                ),
                                                onTap: () =>
                                                    _openQuestion(item),
                                              ),
                                              DataCell(
                                                cell(
                                                  _hasAnswer(item)
                                                      ? _readable(_answer(item))
                                                      : '—',
                                                  widths[4],
                                                ),
                                                onTap: () =>
                                                    _openQuestion(item),
                                              ),
                                              DataCell(
                                                cell(
                                                  item['rubric']?.toString() ??
                                                      '—',
                                                  widths[5],
                                                ),
                                                onTap: () =>
                                                    _openQuestion(item),
                                              ),
                                            ],
                                          ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          );
                        },
                      ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Text('${cases.length} ${tr('题', 'questions')}'),
                  const SizedBox(width: 16),
                  IconButton(
                    tooltip: tr('上一页', 'Previous page'),
                    onPressed: page == 0
                        ? null
                        : () => setState(() {
                            _page = page - 1;
                            if (_vertical.hasClients) _vertical.jumpTo(0);
                          }),
                    icon: const Icon(CupertinoIcons.chevron_left),
                  ),
                  Text('${page + 1} / $pages'),
                  IconButton(
                    tooltip: tr('下一页', 'Next page'),
                    onPressed: page + 1 >= pages
                        ? null
                        : () => setState(() {
                            _page = page + 1;
                            if (_vertical.hasClients) _vertical.jumpTo(0);
                          }),
                    icon: const Icon(CupertinoIcons.chevron_right),
                  ),
                ],
              ),
            ],
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
