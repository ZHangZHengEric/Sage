import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../state/workspace_controller.dart';
import '../usage_models.dart';

class UsageOverviewSettings extends StatefulWidget {
  const UsageOverviewSettings({required this.controller, super.key});

  final WorkspaceController controller;

  @override
  State<UsageOverviewSettings> createState() => _UsageOverviewSettingsState();
}

class _UsageOverviewSettingsState extends State<UsageOverviewSettings> {
  int _days = 30;
  final ScrollController _scrollController = ScrollController();

  bool get _zh => Localizations.localeOf(context).languageCode == 'zh';
  String _text(String zh, String en) => _zh ? zh : en;

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _changeRange(int days) {
    if (_days == days) return;
    setState(() => _days = days);
    widget.controller.loadUsageOverview(days: days);
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.controller,
    builder: (context, _) {
      final overview = widget.controller.usageOverview;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1080),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _text('概览', 'Overview'),
                          key: const ValueKey('settings-content-title'),
                          style: Theme.of(context).textTheme.headlineSmall
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _text('本机运行数据统计', 'Local runtime usage'),
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(
                                color: Theme.of(
                                  context,
                                ).colorScheme.onSurfaceVariant,
                              ),
                        ),
                      ],
                    ),
                  ),
                  _RangeSelector(
                    selected: _days,
                    onSelected: _changeRange,
                    zh: _zh,
                  ),
                  const SizedBox(width: 4),
                  IconButton(
                    key: const ValueKey('usage-refresh'),
                    tooltip: _text('刷新', 'Refresh'),
                    onPressed: widget.controller.usageOverviewLoading
                        ? null
                        : () =>
                              widget.controller.loadUsageOverview(days: _days),
                    icon: widget.controller.usageOverviewLoading
                        ? const CupertinoActivityIndicator(radius: 8)
                        : const Icon(CupertinoIcons.refresh, size: 18),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          Expanded(child: _body(overview)),
        ],
      );
    },
  );

  Widget _body(UsageOverview? overview) {
    if (overview == null && widget.controller.usageOverviewLoading) {
      return const Center(child: CupertinoActivityIndicator());
    }
    if (overview == null) {
      return _UsageMessage(
        icon: CupertinoIcons.exclamationmark_triangle,
        title: _text('暂时无法读取统计数据', 'Usage data is unavailable'),
        detail: widget.controller.usageOverviewError ?? '',
        actionLabel: _text('重试', 'Retry'),
        onAction: () => widget.controller.loadUsageOverview(days: _days),
      );
    }

    final totals = overview.totals;
    return Scrollbar(
      controller: _scrollController,
      thickness: 5,
      radius: const Radius.circular(3),
      child: SingleChildScrollView(
        key: const ValueKey('usage-overview-scroll'),
        controller: _scrollController,
        padding: const EdgeInsets.only(right: 12, bottom: 16),
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1080),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _MetricStrip(
                  metrics: [
                    _Metric(
                      _text('总 Token', 'Total tokens'),
                      _compact(totals.totalTokens),
                      _text(
                        '非缓存 ${_compact(totals.nonCachedInputTokens)} · 缓存 ${_compact(totals.cachedInputTokens)} · 输出 ${_compact(totals.outputTokens)}',
                        'Uncached ${_compact(totals.nonCachedInputTokens)} · Cached ${_compact(totals.cachedInputTokens)} · Output ${_compact(totals.outputTokens)}',
                      ),
                    ),
                    _Metric(
                      _text('Prompt Cache 利用率', 'Prompt cache utilization'),
                      _percent(totals.promptCacheUtilization),
                      _text(
                        '缓存 ${_compact(totals.cachedInputTokens)} / 输入 ${_compact(totals.inputTokens)}',
                        'Cached ${_compact(totals.cachedInputTokens)} / Input ${_compact(totals.inputTokens)}',
                      ),
                    ),
                    _Metric(
                      'Turns',
                      _compact(totals.turns),
                      _text(
                        '${totals.modelRequests} 次模型请求 · ${totals.sessions} 个会话',
                        '${totals.modelRequests} model requests · ${totals.sessions} sessions',
                      ),
                    ),
                    _Metric(
                      _text('工具调用', 'Tool calls'),
                      _compact(totals.toolCalls),
                      _text(
                        '${overview.tools.length} 种工具',
                        '${overview.tools.length} tools used',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 34),
                _UsageSection(
                  title: _text('Token 趋势', 'Token trend'),
                  subtitle: _text(
                    '按天统计输入与输出 Token',
                    'Daily input and output tokens',
                  ),
                  trailing: _TokenLegend(zh: _zh),
                  child: SizedBox(
                    height: 210,
                    child:
                        overview.daily.every((value) => value.totalTokens == 0)
                        ? _EmptyChart(
                            label: _text(
                              '所选时间内暂无 Token 消耗',
                              'No token usage in this period',
                            ),
                          )
                        : _TokenBarChart(days: overview.daily),
                  ),
                ),
                const SizedBox(height: 20),
                const Divider(height: 1),
                const SizedBox(height: 24),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final stacked = constraints.maxWidth < 780;
                    final model = _BreakdownSection(
                      title: _text('模型消耗', 'Usage by model'),
                      emptyLabel: _text('暂无模型调用', 'No model requests'),
                      values: overview.models,
                      zh: _zh,
                    );
                    final agent = _BreakdownSection(
                      title: _text('Agent 消耗', 'Usage by agent'),
                      emptyLabel: _text('暂无 Agent 运行', 'No agent runs'),
                      values: overview.agents,
                      zh: _zh,
                    );
                    if (stacked) {
                      return Column(
                        children: [
                          model,
                          const SizedBox(height: 24),
                          const Divider(height: 1),
                          const SizedBox(height: 24),
                          agent,
                        ],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: model),
                        const SizedBox(width: 56),
                        Expanded(child: agent),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 24),
                const Divider(height: 1),
                const SizedBox(height: 24),
                _ToolDistributionSection(tools: overview.tools, zh: _zh),
                if (totals.reasoningTokens > 0) ...[
                  const SizedBox(height: 12),
                  Text(
                    _text(
                      '其中推理 Token ${_compact(totals.reasoningTokens)}；已包含在输出 Token 中。',
                      'Reasoning tokens: ${_compact(totals.reasoningTokens)}; already included in output tokens.',
                    ),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RangeSelector extends StatelessWidget {
  const _RangeSelector({
    required this.selected,
    required this.onSelected,
    required this.zh,
  });
  final int selected;
  final ValueChanged<int> onSelected;
  final bool zh;

  @override
  Widget build(BuildContext context) => SegmentedButton<int>(
    key: const ValueKey('usage-range-selector'),
    segments: [
      ButtonSegment(value: 7, label: Text(zh ? '7 天' : '7d')),
      ButtonSegment(value: 30, label: Text(zh ? '30 天' : '30d')),
      ButtonSegment(value: 90, label: Text(zh ? '90 天' : '90d')),
    ],
    selected: {selected},
    showSelectedIcon: false,
    style: const ButtonStyle(visualDensity: VisualDensity.compact),
    onSelectionChanged: (value) => onSelected(value.first),
  );
}

class _Metric {
  const _Metric(this.label, this.value, this.detail);
  final String label;
  final String value;
  final String detail;
}

class _MetricStrip extends StatelessWidget {
  const _MetricStrip({required this.metrics});
  final List<_Metric> metrics;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final compact = constraints.maxWidth < 620;
      final colors = Theme.of(context).colorScheme;
      return Container(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 8 : 12,
          vertical: 11,
        ),
        decoration: BoxDecoration(
          border: Border.all(
            color: colors.outlineVariant.withValues(alpha: .7),
          ),
          borderRadius: BorderRadius.circular(14),
        ),
        child: compact
            ? Column(
                children: [
                  Row(
                    children: [
                      Expanded(child: _MetricCell(metric: metrics[0])),
                      const SizedBox(
                        height: 54,
                        child: VerticalDivider(width: 1),
                      ),
                      Expanded(child: _MetricCell(metric: metrics[1])),
                    ],
                  ),
                  const Divider(height: 12),
                  Row(
                    children: [
                      Expanded(child: _MetricCell(metric: metrics[2])),
                      const SizedBox(
                        height: 54,
                        child: VerticalDivider(width: 1),
                      ),
                      Expanded(child: _MetricCell(metric: metrics[3])),
                    ],
                  ),
                ],
              )
            : Row(
                children: [
                  for (var index = 0; index < metrics.length; index++) ...[
                    Expanded(child: _MetricCell(metric: metrics[index])),
                    if (index != metrics.length - 1)
                      const SizedBox(
                        height: 54,
                        child: VerticalDivider(width: 1),
                      ),
                  ],
                ],
              ),
      );
    },
  );
}

class _MetricCell extends StatelessWidget {
  const _MetricCell({required this.metric});
  final _Metric metric;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      key: ValueKey('usage-metric:${metric.label}'),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            metric.value,
            maxLines: 1,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w600,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
          const SizedBox(height: 1),
          Text(
            metric.label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelMedium,
          ),
          const SizedBox(height: 2),
          Text(
            metric.detail,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: colors.onSurfaceVariant,
              fontWeight: FontWeight.w400,
            ),
          ),
        ],
      ),
    );
  }
}

class _UsageSection extends StatelessWidget {
  const _UsageSection({
    required this.title,
    required this.child,
    this.subtitle,
    this.trailing,
  });
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    Widget titleBlock() => Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(
            context,
          ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 2),
          Text(
            subtitle!,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.onSurfaceVariant),
          ),
        ],
      ],
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        LayoutBuilder(
          builder: (context, constraints) {
            if (constraints.maxWidth < 520 && trailing != null) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [titleBlock(), const SizedBox(height: 12), trailing!],
              );
            }
            return Row(
              children: [
                Expanded(child: titleBlock()),
                ?trailing,
              ],
            );
          },
        ),
        const SizedBox(height: 18),
        child,
      ],
    );
  }
}

class _TokenLegend extends StatelessWidget {
  const _TokenLegend({required this.zh});
  final bool zh;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      _LegendDot(
        color: Theme.of(context).colorScheme.primary,
        label: zh ? '非缓存输入' : 'Uncached input',
      ),
      const SizedBox(width: 12),
      _LegendDot(
        color: Theme.of(context).colorScheme.secondary,
        label: zh ? '缓存输入' : 'Cached input',
      ),
      const SizedBox(width: 12),
      _LegendDot(
        color: Theme.of(context).colorScheme.tertiary,
        label: zh ? '输出' : 'Output',
      ),
    ],
  );
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 7,
        height: 7,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 5),
      Text(label, style: Theme.of(context).textTheme.labelSmall),
    ],
  );
}

class _TokenBarChart extends StatelessWidget {
  const _TokenBarChart({required this.days});
  final List<UsageDay> days;

  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Token usage by day',
    image: true,
    child: CustomPaint(
      key: const ValueKey('usage-token-chart'),
      painter: _TokenBarPainter(
        days: days,
        inputColor: Theme.of(context).colorScheme.primary,
        cachedColor: Theme.of(context).colorScheme.secondary,
        outputColor: Theme.of(context).colorScheme.tertiary,
        gridColor: Theme.of(context).colorScheme.outlineVariant,
        labelColor: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
      size: Size.infinite,
    ),
  );
}

class _TokenBarPainter extends CustomPainter {
  const _TokenBarPainter({
    required this.days,
    required this.inputColor,
    required this.cachedColor,
    required this.outputColor,
    required this.gridColor,
    required this.labelColor,
  });
  final List<UsageDay> days;
  final Color inputColor;
  final Color cachedColor;
  final Color outputColor;
  final Color gridColor;
  final Color labelColor;

  @override
  void paint(Canvas canvas, Size size) {
    const bottom = 24.0;
    const top = 8.0;
    final chartHeight = math.max(1.0, size.height - bottom - top);
    final maximum = days.fold<int>(
      1,
      (value, day) => math.max(value, day.totalTokens),
    );
    final gridPaint = Paint()
      ..color = gridColor.withValues(alpha: .75)
      ..strokeWidth = 1;
    for (var index = 0; index <= 3; index++) {
      final y = top + chartHeight * index / 3;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }
    final slot = size.width / math.max(1, days.length);
    final barWidth = math.min(14.0, math.max(2.0, slot * .58));
    final inputPaint = Paint()..color = inputColor;
    final cachedPaint = Paint()..color = cachedColor;
    final outputPaint = Paint()..color = outputColor;
    for (var index = 0; index < days.length; index++) {
      final day = days[index];
      final inputHeight = chartHeight * day.nonCachedInputTokens / maximum;
      final cachedHeight = chartHeight * day.cachedInputTokens / maximum;
      final outputHeight = chartHeight * day.outputTokens / maximum;
      final left = slot * index + (slot - barWidth) / 2;
      final baseline = top + chartHeight;
      if (inputHeight > 0) {
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromLTWH(left, baseline - inputHeight, barWidth, inputHeight),
            const Radius.circular(2),
          ),
          inputPaint,
        );
      }
      if (cachedHeight > 0) {
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromLTWH(
              left,
              baseline - inputHeight - cachedHeight,
              barWidth,
              cachedHeight,
            ),
            const Radius.circular(2),
          ),
          cachedPaint,
        );
      }
      if (outputHeight > 0) {
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromLTWH(
              left,
              baseline - inputHeight - cachedHeight - outputHeight,
              barWidth,
              outputHeight,
            ),
            const Radius.circular(2),
          ),
          outputPaint,
        );
      }
    }
    final labelIndexes = <int>{0, days.length ~/ 2, days.length - 1};
    for (final index in labelIndexes) {
      if (index < 0 || index >= days.length) continue;
      final day = days[index].date;
      final painter = TextPainter(
        text: TextSpan(
          text: '${day.month}/${day.day}',
          style: TextStyle(color: labelColor, fontSize: 10),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final center = slot * index + slot / 2;
      painter.paint(
        canvas,
        Offset(
          (center - painter.width / 2).clamp(0, size.width - painter.width),
          size.height - 15,
        ),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _TokenBarPainter oldDelegate) =>
      oldDelegate.days != days ||
      oldDelegate.inputColor != inputColor ||
      oldDelegate.cachedColor != cachedColor ||
      oldDelegate.outputColor != outputColor;
}

class _EmptyChart extends StatelessWidget {
  const _EmptyChart({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) => Center(
    child: Text(
      label,
      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
    ),
  );
}

class _BreakdownSection extends StatelessWidget {
  const _BreakdownSection({
    required this.title,
    required this.emptyLabel,
    required this.values,
    required this.zh,
  });
  final String title;
  final String emptyLabel;
  final List<UsageBreakdown> values;
  final bool zh;

  @override
  Widget build(BuildContext context) {
    final shown = values.take(6).toList();
    final maximum = shown.fold<int>(
      1,
      (value, item) => math.max(value, item.totalTokens),
    );
    return _UsageSection(
      title: title,
      child: shown.isEmpty
          ? SizedBox(height: 100, child: _EmptyChart(label: emptyLabel))
          : Column(
              children: [
                for (var index = 0; index < shown.length; index++) ...[
                  _BreakdownRow(
                    value: shown[index],
                    ratio: shown[index].totalTokens / maximum,
                    detail: zh
                        ? '缓存利用率 ${_percent(shown[index].promptCacheUtilization)} · 非缓存 ${_compact(shown[index].nonCachedInputTokens)} · 缓存 ${_compact(shown[index].cachedInputTokens)} · 输出 ${_compact(shown[index].outputTokens)}'
                        : 'Cache ${_percent(shown[index].promptCacheUtilization)} · Uncached ${_compact(shown[index].nonCachedInputTokens)} · Cached ${_compact(shown[index].cachedInputTokens)} · Output ${_compact(shown[index].outputTokens)}',
                  ),
                  if (index != shown.length - 1) const SizedBox(height: 14),
                ],
              ],
            ),
    );
  }
}

class _BreakdownRow extends StatelessWidget {
  const _BreakdownRow({
    required this.value,
    required this.ratio,
    required this.detail,
  });
  final UsageBreakdown value;
  final double ratio;
  final String detail;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                value.name.isEmpty ? 'Unknown' : value.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              _compact(value.totalTokens),
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
        const SizedBox(height: 7),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(
            value: ratio,
            minHeight: 5,
            backgroundColor: colors.surfaceContainerHighest,
            color: colors.primary,
          ),
        ),
        const SizedBox(height: 5),
        Align(
          alignment: Alignment.centerLeft,
          child: Text(
            detail,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.onSurfaceVariant),
          ),
        ),
      ],
    );
  }
}

class _ToolDistributionSection extends StatelessWidget {
  const _ToolDistributionSection({required this.tools, required this.zh});
  final List<ToolUsage> tools;
  final bool zh;

  @override
  Widget build(BuildContext context) {
    final shown = tools.take(12).toList();
    final maximum = shown.fold<int>(
      1,
      (value, item) => math.max(value, item.count),
    );
    return _UsageSection(
      title: zh ? '工具调用分布' : 'Tool distribution',
      subtitle: zh ? '按发起调用次数统计' : 'Counted when a tool call is proposed',
      child: shown.isEmpty
          ? SizedBox(
              height: 90,
              child: _EmptyChart(label: zh ? '暂无工具调用' : 'No tool calls'),
            )
          : LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth < 680 ? 1 : 2;
                final width =
                    (constraints.maxWidth - (columns - 1) * 44) / columns;
                return Wrap(
                  spacing: 44,
                  runSpacing: 16,
                  children: [
                    for (final tool in shown)
                      SizedBox(
                        width: width,
                        child: _ToolRow(
                          tool: tool,
                          fraction: tool.count / maximum,
                        ),
                      ),
                  ],
                );
              },
            ),
    );
  }
}

class _ToolRow extends StatelessWidget {
  const _ToolRow({required this.tool, required this.fraction});
  final ToolUsage tool;
  final double fraction;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                tool.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
            const SizedBox(width: 12),
            Text(
              '${tool.count}',
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: colors.onSurfaceVariant,
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(2),
          child: LinearProgressIndicator(
            value: fraction,
            minHeight: 3,
            backgroundColor: colors.surfaceContainerHighest,
            color: colors.primary.withValues(alpha: .72),
          ),
        ),
      ],
    );
  }
}

class _UsageMessage extends StatelessWidget {
  const _UsageMessage({
    required this.icon,
    required this.title,
    required this.detail,
    required this.actionLabel,
    required this.onAction,
  });
  final IconData icon;
  final String title;
  final String detail;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          icon,
          size: 30,
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        const SizedBox(height: 12),
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        if (detail.isNotEmpty) ...[
          const SizedBox(height: 6),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: Text(
              detail,
              textAlign: TextAlign.center,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        ],
        const SizedBox(height: 16),
        FilledButton.tonal(onPressed: onAction, child: Text(actionLabel)),
      ],
    ),
  );
}

String _compact(int value) {
  if (value < 1000) return '$value';
  if (value < 1000000) return '${_trim(value / 1000)}K';
  if (value < 1000000000) return '${_trim(value / 1000000)}M';
  return '${_trim(value / 1000000000)}B';
}

String _percent(double value) => '${_trim(value * 100)}%';

String _trim(double value) {
  final digits = value >= 100
      ? 0
      : value >= 10
      ? 1
      : 2;
  return value
      .toStringAsFixed(digits)
      .replaceFirst(RegExp(r'\.0+$'), '')
      .replaceFirst(RegExp(r'(\.[0-9]*?)0+$'), r'$1');
}
