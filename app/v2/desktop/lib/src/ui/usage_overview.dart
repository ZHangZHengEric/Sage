import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import '../localization/app_localizations.dart';
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
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final title = Column(
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
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  );
                  final range = _RangeSelector(
                    selected: _days,
                    onSelected: _changeRange,
                    zh: _zh,
                  );
                  final refresh = IconButton(
                    key: const ValueKey('usage-refresh'),
                    tooltip: _text('刷新', 'Refresh'),
                    onPressed: widget.controller.usageOverviewLoading
                        ? null
                        : () =>
                              widget.controller.loadUsageOverview(days: _days),
                    icon: widget.controller.usageOverviewLoading
                        ? const CupertinoActivityIndicator(radius: 8)
                        : const Icon(CupertinoIcons.refresh, size: 18),
                  );
                  if (constraints.maxWidth < 620) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(child: title),
                            refresh,
                          ],
                        ),
                        const SizedBox(height: 12),
                        range,
                      ],
                    );
                  }
                  return Row(
                    children: [
                      Expanded(child: title),
                      range,
                      const SizedBox(width: 4),
                      refresh,
                    ],
                  );
                },
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
                if (overview.dataQuality.partial) ...[
                  _UsagePartialNotice(quality: overview.dataQuality),
                  const SizedBox(height: 14),
                ],
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
                      _modelRequestDetail(totals),
                    ),
                    _Metric(
                      _text('工具调用', 'Tool calls'),
                      _compact(totals.toolCalls),
                      _text(
                        '${overview.tools.length} 种工具',
                        '${overview.tools.length} tools used',
                      ),
                    ),
                    _Metric(
                      'TTFT P50',
                      _duration(totals.firstTokenLatencyP50Ms),
                      _percentileDetail(
                        _duration(totals.firstTokenLatencyP95Ms),
                        totals.firstTokenLatencySamples,
                      ),
                    ),
                    _Metric(
                      'Token/s P50',
                      _rate(totals.outputTokensPerSecondP50),
                      _percentileDetail(
                        _rate(totals.outputTokensPerSecondP95),
                        totals.outputTokensPerSecondSamples,
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
                        : _TokenBarChart(days: overview.daily, zh: _zh),
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

  String _modelRequestDetail(UsageTotals totals) {
    final key = totals.failedModelRequests == 0
        ? 'usage.requestSummary'
        : 'usage.requestSummaryWithFailures';
    return context.l10n.text(key, {
      'requests': totals.modelRequests,
      'failed': totals.failedModelRequests,
      'sessions': totals.sessions,
    });
  }

  String _percentileDetail(String p95, int samples) =>
      'P95 $p95 · n=${_compact(samples)}';
}

class _UsagePartialNotice extends StatelessWidget {
  const _UsagePartialNotice({required this.quality});

  final UsageDataQuality quality;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final message = context.l10n.text('usage.partialData', {
      'count': quality.skippedSessions,
    });
    return Semantics(
      container: true,
      liveRegion: true,
      label: message,
      child: GlassCard(
        key: const ValueKey('usage-partial-data-notice'),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        shape: const LiquidRoundedSuperellipse(borderRadius: 12),
        useOwnLayer: true,
        settings: _usageGlass(context),
        child: Row(
          children: [
            Icon(
              CupertinoIcons.exclamationmark_triangle,
              size: 17,
              color: colors.tertiary,
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                message,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colors.onSurface,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ],
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
  const _Metric(this.label, this.value, [this.detail]);
  final String label;
  final String value;
  final String? detail;
}

class _MetricStrip extends StatelessWidget {
  const _MetricStrip({required this.metrics});
  final List<_Metric> metrics;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final columnCount = constraints.maxWidth < 620
          ? 2
          : constraints.maxWidth < 920
          ? 3
          : metrics.length;
      final rows = <Widget>[];
      for (var start = 0; start < metrics.length; start += columnCount) {
        final end = math.min(start + columnCount, metrics.length);
        rows.add(
          IntrinsicHeight(
            child: Row(
              children: [
                for (
                  var index = start;
                  index < start + columnCount;
                  index++
                ) ...[
                  Expanded(
                    child: index < end
                        ? _MetricCell(metric: metrics[index])
                        : const SizedBox.shrink(),
                  ),
                  if (index != start + columnCount - 1)
                    const VerticalDivider(width: 1),
                ],
              ],
            ),
          ),
        );
        if (end < metrics.length) rows.add(const Divider(height: 12));
      }
      return GlassCard(
        key: const ValueKey('usage-metric-strip'),
        padding: EdgeInsets.symmetric(
          horizontal: constraints.maxWidth < 620 ? 8 : 12,
          vertical: 11,
        ),
        shape: const LiquidRoundedSuperellipse(borderRadius: 14),
        useOwnLayer: true,
        settings: _usageGlass(context),
        child: Column(children: rows),
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
          if (metric.detail case final detail?) ...[
            const SizedBox(height: 2),
            Text(
              detail,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: colors.onSurfaceVariant,
                fontWeight: FontWeight.w400,
              ),
            ),
          ],
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
  Widget build(BuildContext context) => Wrap(
    spacing: 12,
    runSpacing: 6,
    children: [
      _LegendDot(
        color: Theme.of(context).colorScheme.primary,
        label: zh ? '非缓存输入' : 'Uncached input',
      ),
      _LegendDot(
        color: Theme.of(context).colorScheme.secondary,
        label: zh ? '缓存输入' : 'Cached input',
      ),
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

class _TokenBarChart extends StatefulWidget {
  const _TokenBarChart({required this.days, required this.zh});
  final List<UsageDay> days;
  final bool zh;

  @override
  State<_TokenBarChart> createState() => _TokenBarChartState();
}

class _TokenBarChartState extends State<_TokenBarChart> {
  int? _hoveredIndex;

  @override
  void didUpdateWidget(covariant _TokenBarChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_hoveredIndex != null && _hoveredIndex! >= widget.days.length) {
      _hoveredIndex = null;
    }
  }

  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Token usage by day',
    image: true,
    child: LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        final geometry = _TokenChartGeometry(size, widget.days.length);
        final colors = Theme.of(context).colorScheme;
        return MouseRegion(
          cursor: SystemMouseCursors.precise,
          onHover: (event) {
            final index = geometry.indexAt(event.localPosition);
            if (index != _hoveredIndex) {
              setState(() => _hoveredIndex = index);
            }
          },
          onExit: (_) {
            if (_hoveredIndex != null) setState(() => _hoveredIndex = null);
          },
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              Positioned.fill(
                child: CustomPaint(
                  key: const ValueKey('usage-token-chart'),
                  painter: _TokenBarPainter(
                    days: widget.days,
                    hoveredIndex: _hoveredIndex,
                    inputColor: colors.primary,
                    cachedColor: colors.secondary,
                    outputColor: colors.tertiary,
                    gridColor: colors.outlineVariant,
                    labelColor: colors.onSurfaceVariant,
                  ),
                ),
              ),
              if (_hoveredIndex case final index?)
                _TokenChartTooltip(
                  day: widget.days[index],
                  index: index,
                  geometry: geometry,
                  zh: widget.zh,
                ),
            ],
          ),
        );
      },
    ),
  );
}

class _TokenChartGeometry {
  const _TokenChartGeometry(this.size, this.dayCount);

  static const axisWidth = 52.0;
  static const rightPadding = 8.0;
  static const topPadding = 26.0;
  static const bottomPadding = 24.0;

  final Size size;
  final int dayCount;

  Rect get plot => Rect.fromLTRB(
    axisWidth,
    topPadding,
    math.max(axisWidth + 1, size.width - rightPadding),
    math.max(topPadding + 1, size.height - bottomPadding),
  );

  double get slotWidth => plot.width / math.max(1, dayCount);

  int? indexAt(Offset position) {
    final bounds = Rect.fromLTRB(plot.left, 0, plot.right, size.height);
    if (dayCount == 0 || !bounds.contains(position)) return null;
    return ((position.dx - plot.left) / slotWidth).floor().clamp(
      0,
      dayCount - 1,
    );
  }

  double centerFor(int index) => plot.left + slotWidth * (index + .5);
}

class _TokenChartTooltip extends StatelessWidget {
  const _TokenChartTooltip({
    required this.day,
    required this.index,
    required this.geometry,
    required this.zh,
  });

  final UsageDay day;
  final int index;
  final _TokenChartGeometry geometry;
  final bool zh;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final width = math.min(220.0, math.max(1.0, geometry.size.width - 8));
    final center = geometry.centerFor(index);
    final preferredLeft = center < geometry.size.width / 2
        ? center + 12
        : center - width - 12;
    final left = preferredLeft.clamp(4.0, geometry.size.width - width - 4);
    return Positioned(
      key: const ValueKey('usage-token-tooltip'),
      left: left,
      top: 4,
      width: width,
      child: Material(
        color: colors.surfaceContainerHighest,
        elevation: 8,
        shadowColor: Colors.black.withValues(alpha: .24),
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            border: Border.all(color: colors.outlineVariant),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${day.date.year}/${day.date.month}/${day.date.day}',
                style: Theme.of(
                  context,
                ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 7),
              _TokenTooltipRow(
                color: colors.primary,
                label: zh ? '非缓存输入' : 'Uncached input',
                value: day.nonCachedInputTokens,
              ),
              _TokenTooltipRow(
                color: colors.secondary,
                label: zh ? '缓存输入' : 'Cached input',
                value: day.cachedInputTokens,
              ),
              _TokenTooltipRow(
                color: colors.tertiary,
                label: zh ? '输出' : 'Output',
                value: day.outputTokens,
              ),
              const Divider(height: 13),
              _TokenTooltipRow(
                label: zh ? '合计' : 'Total',
                value: day.totalTokens,
                strong: true,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TokenTooltipRow extends StatelessWidget {
  const _TokenTooltipRow({
    required this.label,
    required this.value,
    this.color,
    this.strong = false,
  });

  final Color? color;
  final String label;
  final int value;
  final bool strong;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 1.5),
    child: Row(
      children: [
        if (color != null) ...[
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
        ],
        Expanded(
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              fontWeight: strong ? FontWeight.w700 : FontWeight.w400,
            ),
          ),
        ),
        Text(
          _integerText(value),
          key: ValueKey('usage-token-tooltip:$label'),
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
            fontWeight: strong ? FontWeight.w700 : FontWeight.w500,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    ),
  );
}

class _TokenBarPainter extends CustomPainter {
  const _TokenBarPainter({
    required this.days,
    required this.hoveredIndex,
    required this.inputColor,
    required this.cachedColor,
    required this.outputColor,
    required this.gridColor,
    required this.labelColor,
  });
  final List<UsageDay> days;
  final int? hoveredIndex;
  final Color inputColor;
  final Color cachedColor;
  final Color outputColor;
  final Color gridColor;
  final Color labelColor;

  @override
  void paint(Canvas canvas, Size size) {
    final geometry = _TokenChartGeometry(size, days.length);
    final plot = geometry.plot;
    final maximum = _tokenAxisMaximum(days);
    final gridPaint = Paint()
      ..color = gridColor.withValues(alpha: .75)
      ..strokeWidth = 1;
    for (var index = 0; index <= 4; index++) {
      final ratio = index / 4;
      final y = plot.bottom - plot.height * ratio;
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), gridPaint);
      final value = (maximum * ratio).round();
      final labelPainter = TextPainter(
        text: TextSpan(
          text: _compact(value),
          style: TextStyle(color: labelColor, fontSize: 10),
        ),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: _TokenChartGeometry.axisWidth - 10);
      labelPainter.paint(
        canvas,
        Offset(
          plot.left - labelPainter.width - 8,
          (y - labelPainter.height / 2).clamp(
            0,
            size.height - labelPainter.height,
          ),
        ),
      );
    }
    final slot = geometry.slotWidth;
    final barWidth = math.min(14.0, math.max(2.0, slot * .58));
    final inputPaint = Paint()..color = inputColor;
    final cachedPaint = Paint()..color = cachedColor;
    final outputPaint = Paint()..color = outputColor;
    if (hoveredIndex case final index?) {
      canvas.drawRect(
        Rect.fromLTWH(plot.left + slot * index, plot.top, slot, plot.height),
        Paint()..color = labelColor.withValues(alpha: .07),
      );
    }
    var lastValueLabelRight = double.negativeInfinity;
    for (var index = 0; index < days.length; index++) {
      final day = days[index];
      final inputHeight = plot.height * day.nonCachedInputTokens / maximum;
      final cachedHeight = plot.height * day.cachedInputTokens / maximum;
      final outputHeight = plot.height * day.outputTokens / maximum;
      final left = plot.left + slot * index + (slot - barWidth) / 2;
      final baseline = plot.bottom;
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
      if (day.totalTokens > 0) {
        final totalHeight = inputHeight + cachedHeight + outputHeight;
        final valuePainter = TextPainter(
          text: TextSpan(
            text: _compact(day.totalTokens),
            style: TextStyle(
              color: labelColor,
              fontSize: 9,
              fontWeight: FontWeight.w600,
            ),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        final valueLeft = geometry.centerFor(index) - valuePainter.width / 2;
        if (valueLeft >= lastValueLabelRight + 4) {
          valuePainter.paint(
            canvas,
            Offset(
              valueLeft.clamp(plot.left, plot.right - valuePainter.width),
              (baseline - totalHeight - valuePainter.height - 3).clamp(
                0,
                plot.bottom - valuePainter.height,
              ),
            ),
          );
          lastValueLabelRight = valueLeft + valuePainter.width;
        }
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
      final center = geometry.centerFor(index);
      painter.paint(
        canvas,
        Offset(
          (center - painter.width / 2).clamp(
            plot.left,
            plot.right - painter.width,
          ),
          size.height - 15,
        ),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _TokenBarPainter oldDelegate) =>
      oldDelegate.days != days ||
      oldDelegate.hoveredIndex != hoveredIndex ||
      oldDelegate.inputColor != inputColor ||
      oldDelegate.cachedColor != cachedColor ||
      oldDelegate.outputColor != outputColor ||
      oldDelegate.gridColor != gridColor ||
      oldDelegate.labelColor != labelColor;
}

double _tokenAxisMaximum(List<UsageDay> days) {
  final maximum = days.fold<int>(
    1,
    (value, day) => math.max(value, day.totalTokens),
  );
  final roughStep = maximum / 4;
  final magnitude = math.pow(10, (math.log(roughStep) / math.ln10).floor());
  final normalized = roughStep / magnitude;
  final niceNormalized = normalized <= 1
      ? 1
      : normalized <= 2
      ? 2
      : normalized <= 2.5
      ? 2.5
      : normalized <= 5
      ? 5
      : 10;
  return niceNormalized * magnitude * 4;
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

String _duration(double? milliseconds) {
  if (milliseconds == null) return '—';
  if (milliseconds < 1000) return '${milliseconds.round()} ms';
  final seconds = milliseconds / 1000;
  return '${seconds < 10 ? seconds.toStringAsFixed(2) : seconds.toStringAsFixed(1)} s';
}

String _rate(double? tokensPerSecond) {
  if (tokensPerSecond == null) return '—';
  return '${_trim(tokensPerSecond)} token/s';
}

LiquidGlassSettings _usageGlass(BuildContext context) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return LiquidGlassSettings(
    visibility: dark ? 0.86 : 0.9,
    glassColor: dark
        ? const Color(0xFF2B2C2E).withValues(alpha: 0.84)
        : Colors.white.withValues(alpha: 0.92),
    thickness: 4,
    blur: 3,
    chromaticAberration: 0,
    lightIntensity: 0.1,
    saturation: 1,
    glowIntensity: 0,
    standardOpacityMultiplier: dark ? 0.88 : 0.92,
    shadowElevation: 0.04,
  );
}

String _integerText(int value) {
  final negative = value < 0;
  final digits = value.abs().toString();
  final buffer = StringBuffer();
  if (negative) buffer.write('-');
  for (var index = 0; index < digits.length; index++) {
    if (index > 0 && (digits.length - index) % 3 == 0) buffer.write(',');
    buffer.write(digits[index]);
  }
  return buffer.toString();
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
