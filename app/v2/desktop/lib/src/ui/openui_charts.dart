import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'openui_pill.dart';

/// Shared geometry for paint, axis labels and pointer hit testing.
class OpenUiChartGeometry {
  const OpenUiChartGeometry(this.size, this.count, this.type);
  final Size size;
  final int count;
  final String type;
  Rect get plot => Rect.fromLTWH(
    42,
    8,
    math.max(0, size.width - 54),
    math.max(0, size.height - 36),
  );
  double categoryX(int index) =>
      plot.left +
      (type == 'bar'
          ? plot.width * (index + .5) / count
          : count == 1
          ? plot.width / 2
          : plot.width * index / (count - 1));
  double barWidth(int seriesCount) => plot.width / count * .7 / seriesCount;
  double barPaintWidth(int seriesCount) {
    final width = barWidth(seriesCount);
    return width - math.min(2, width * .15);
  }

  double barLeft(int index, int seriesIndex, int seriesCount) =>
      plot.left +
      plot.width / count * (index + .15) +
      seriesIndex * barWidth(seriesCount);
  double barCenter(int index, int seriesIndex, int seriesCount) =>
      barLeft(index, seriesIndex, seriesCount) + barPaintWidth(seriesCount) / 2;
  Offset get center => Offset(size.width / 2, size.height / 2);
  double get radius => math.max(0, math.min(size.width, size.height) / 2 - 20);
  int? hit(Offset point, {List<num> pieValues = const []}) {
    if (count < 1) return null;
    if (type == 'pie') {
      final distance = (point - center).distance;
      final total = pieValues.fold<double>(0, (sum, value) => sum + value);
      if (radius <= 0 ||
          distance < math.max(0, radius - 16) ||
          distance > radius + 16 ||
          total <= 0) {
        return null;
      }
      final angle =
          (math.atan2(point.dy - center.dy, point.dx - center.dx) +
              math.pi / 2) %
          (2 * math.pi);
      var end = 0.0;
      for (var i = 0; i < pieValues.length; i++) {
        end += pieValues[i] / total * 2 * math.pi;
        if (pieValues[i] > 0 && angle < end) return i;
      }
      return null;
    }
    if (plot.width <= 0 || !plot.contains(point)) return null;
    final fraction = (point.dx - plot.left) / plot.width;
    return (type == 'bar'
            ? (fraction * count).floor()
            : (fraction * (count - 1)).round())
        .clamp(0, count - 1);
  }
}

class OpenUiChart extends StatefulWidget {
  const OpenUiChart({super.key, required this.props});
  final Map props;
  @override
  State<OpenUiChart> createState() => _OpenUiChartState();
}

class _OpenUiChartState extends State<OpenUiChart> {
  final _hidden = <int>{};
  int? _selected;
  final _focus = FocusNode();
  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant OpenUiChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.props['type'] != widget.props['type'] ||
        '${oldWidget.props['labels']}' != '${widget.props['labels']}' ||
        '${(oldWidget.props['series'] as List? ?? []).map((s) => s['name'])}' !=
            '${(widget.props['series'] as List? ?? []).map((s) => s['name'])}') {
      _selected = null;
      _hidden.clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.props;
    final labels = (p['labels'] as List? ?? [])
        .map((v) => v.toString())
        .toList();
    final series = (p['series'] as List? ?? [])
        .whereType<Map>()
        .where(
          (s) =>
              s['values'] is List &&
              (s['values'] as List).length == labels.length &&
              (s['values'] as List).every(
                (v) => v is num && v.isFinite && (p['type'] != 'pie' || v >= 0),
              ),
        )
        .toList();
    if (labels.isEmpty || series.isEmpty) return const SizedBox.shrink();
    _hidden.removeWhere((index) => index >= series.length);
    if (_hidden.length == series.length) _hidden.remove(0);
    final c = Theme.of(context).colorScheme;
    final palette = [
      c.primary,
      c.tertiary,
      const Color(0xff40b79a),
      const Color(0xffddad54),
      const Color(0xffbe83c6),
      const Color(0xff629ebd),
      const Color(0xffdf8380),
      const Color(0xff9aa757),
    ];
    final selected = _selected != null && _selected! < labels.length
        ? _selected
        : null;
    final type = p['type']?.toString() ?? 'line';
    final visible = [
      for (var i = 0; i < series.length; i++)
        if (!_hidden.contains(i)) i,
    ];
    final semantics = [
      for (final i in visible)
        '${series[i]['name']}: ${[for (var j = 0; j < labels.length; j++) '${labels[j]} ${(series[i]['values'] as List)[j]}'].join(', ')}',
    ].join('; ');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 14,
      children: [
        if ((p['title']?.toString() ?? '').isNotEmpty)
          Text(
            p['title'].toString(),
            style: Theme.of(context).textTheme.titleMedium,
          ),
        Semantics(
          label: semantics,
          child: LayoutBuilder(
            builder: (context, constraints) {
              final geometry = OpenUiChartGeometry(
                Size(constraints.maxWidth, 240),
                labels.length,
                type,
              );
              void select(int? index) {
                if (index != _selected) setState(() => _selected = index);
              }

              void choose(Offset offset) => select(
                geometry.hit(
                  offset,
                  pieValues: type == 'pie'
                      ? (series.first['values'] as List).cast<num>()
                      : const [],
                ),
              );

              return Focus(
                focusNode: _focus,
                onKeyEvent: (_, event) {
                  if (event is! KeyDownEvent && event is! KeyRepeatEvent) {
                    return KeyEventResult.ignored;
                  }
                  final key = event.logicalKey;
                  if (key == LogicalKeyboardKey.escape) {
                    select(null);
                  } else if (key == LogicalKeyboardKey.arrowRight) {
                    select(
                      (_selected == null ? 0 : _selected! + 1).clamp(
                        0,
                        labels.length - 1,
                      ),
                    );
                  } else if (key == LogicalKeyboardKey.arrowLeft) {
                    select(
                      (_selected == null ? labels.length - 1 : _selected! - 1)
                          .clamp(0, labels.length - 1),
                    );
                  } else if (key == LogicalKeyboardKey.home) {
                    select(0);
                  } else if (key == LogicalKeyboardKey.end) {
                    select(labels.length - 1);
                  } else {
                    return KeyEventResult.ignored;
                  }
                  return KeyEventResult.handled;
                },
                child: MouseRegion(
                  onExit: (_) => select(null),
                  onHover: (e) => choose(e.localPosition),
                  child: GestureDetector(
                    onTapDown: (e) {
                      _focus.requestFocus();
                      choose(e.localPosition);
                    },
                    child: SizedBox(
                      height: 240,
                      width: double.infinity,
                      child: CustomPaint(
                        key: const ValueKey('openui-chart-plot'),
                        painter: _ChartPainter(
                          labels: labels,
                          series: series,
                          visible: visible,
                          palette: palette,
                          foreground: c.onSurfaceVariant,
                          textStyle:
                              Theme.of(context).textTheme.labelSmall ??
                              const TextStyle(),
                          grid: c.outlineVariant,
                          type: type,
                          selected: selected,
                        ),
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (type == 'pie')
              for (var i = 0; i < labels.length; i++)
                OpenUiPill(
                  label: '${labels[i]} ${(series.first['values'] as List)[i]}',
                  selected: selected == i,
                  icon: Icon(
                    Icons.circle,
                    size: 9,
                    color: palette[i % palette.length],
                  ),
                  onTap: () => setState(() => _selected = i),
                )
            else
              for (var i = 0; i < series.length; i++)
                OpenUiPill(
                  key: ValueKey('openui-series:$i'),
                  label: series[i]['name']?.toString() ?? '',
                  selected: !_hidden.contains(i),
                  icon: Icon(
                    Icons.circle,
                    size: 9,
                    color: palette[i % palette.length],
                  ),
                  onTap: () => setState(() {
                    if (_hidden.contains(i)) {
                      _hidden.remove(i);
                    } else if (visible.length > 1) {
                      _hidden.add(i);
                    }
                  }),
                ),
          ],
        ),
        if (selected != null && type != 'pie')
          Text(
            '${labels[selected]} · ${[for (final i in visible) '${series[i]['name']} ${(series[i]['values'] as List)[selected]}'].join(' · ')}',
            style: Theme.of(context).textTheme.labelLarge,
          ),
      ],
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter({
    required this.labels,
    required this.series,
    required this.visible,
    required this.palette,
    required this.foreground,
    required this.textStyle,
    required this.grid,
    required this.type,
    required this.selected,
  });
  final List<String> labels;
  final List<Map> series;
  final List<int> visible;
  final List<Color> palette;
  final Color foreground, grid;
  final TextStyle textStyle;
  final String type;
  final int? selected;
  void _text(
    Canvas canvas,
    String value,
    Offset offset, {
    bool center = false,
  }) {
    final t = TextPainter(
      text: TextSpan(
        text: value,
        style: textStyle.copyWith(color: foreground, fontSize: 10),
      ),
      textDirection: TextDirection.ltr,
      maxLines: 1,
      ellipsis: '…',
    )..layout(maxWidth: 70);
    t.paint(canvas, offset - Offset(center ? t.width / 2 : 0, 0));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final geometry = OpenUiChartGeometry(size, labels.length, type);
    if (type == 'pie') {
      final values = (series.first['values'] as List).cast<num>();
      final total = values.fold<double>(0, (s, v) => s + v);
      final rect = Rect.fromCircle(
        center: geometry.center,
        radius: geometry.radius,
      );
      var start = -math.pi / 2;
      for (var i = 0; i < values.length; i++) {
        final sweep = total == 0 ? 0.0 : values[i] / total * 2 * math.pi;
        canvas.drawArc(
          rect,
          start,
          sweep,
          false,
          Paint()
            ..color = palette[i % palette.length].withValues(
              alpha: selected == null || selected == i ? 1 : .3,
            )
            ..style = PaintingStyle.stroke
            ..strokeWidth = 32,
        );
        start += sweep;
      }
      _text(
        canvas,
        total.toStringAsFixed(0),
        Offset(size.width / 2, size.height / 2 - 5),
        center: true,
      );
      return;
    }
    final all = [
      for (final i in visible) ...(series[i]['values'] as List).cast<num>(),
    ];
    var min = math.min(0, all.reduce(math.min)).toDouble(),
        max = math.max(0, all.reduce(math.max)).toDouble();
    if (min == max) max = min + 1;
    final plot = geometry.plot;
    double x(int j) => geometry.categoryX(j);
    double y(num v) => plot.bottom - (v - min) / (max - min) * plot.height;
    for (var j = 0; j <= 4; j++) {
      final yy = plot.top + plot.height * j / 4;
      canvas.drawLine(
        Offset(plot.left, yy),
        Offset(plot.right, yy),
        Paint()
          ..color = grid.withValues(alpha: .5)
          ..strokeWidth = .5,
      );
      _text(
        canvas,
        (max - (max - min) * j / 4).toStringAsPrecision(3),
        Offset(0, yy - 5),
      );
    }
    for (var j = 0; j < labels.length; j++) {
      if (j == 0 ||
          j == labels.length - 1 ||
          j % math.max(1, (labels.length / 5).ceil()) == 0) {
        _text(canvas, labels[j], Offset(x(j), plot.bottom + 10), center: true);
      }
    }
    canvas.save();
    canvas.clipRect(plot.inflate(3));
    for (var k = 0; k < visible.length; k++) {
      final i = visible[k],
          values = (series[i]['values'] as List).cast<num>(),
          color = palette[i % palette.length];
      if (type == 'bar') {
        final width = geometry.barPaintWidth(visible.length);
        for (var j = 0; j < values.length; j++) {
          final left = geometry.barLeft(j, k, visible.length);
          canvas.drawRRect(
            RRect.fromRectAndRadius(
              Rect.fromLTRB(
                left,
                math.min(y(0), y(values[j])),
                left + width,
                math.max(y(0), y(values[j])),
              ),
              const Radius.circular(3),
            ),
            Paint()..color = color,
          );
        }
      } else {
        final path = Path();
        for (var j = 0; j < values.length; j++) {
          j == 0
              ? path.moveTo(x(j), y(values[j]))
              : path.lineTo(x(j), y(values[j]));
        }
        final fill = Path.from(path)
          ..lineTo(x(values.length - 1), y(0))
          ..lineTo(x(0), y(0))
          ..close();
        canvas.drawPath(
          fill,
          Paint()
            ..shader = LinearGradient(
              colors: [
                color.withValues(alpha: .15),
                color.withValues(alpha: 0),
              ],
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
            ).createShader(plot),
        );
        canvas.drawPath(
          path,
          Paint()
            ..color = color
            ..strokeWidth = 2.5
            ..style = PaintingStyle.stroke,
        );
        if (values.length == 1) {
          canvas.drawCircle(
            Offset(x(0), y(values[0])),
            4,
            Paint()..color = color,
          );
        }
      }
      if (selected != null && selected! < values.length) {
        canvas.drawCircle(
          Offset(
            type == 'bar'
                ? geometry.barCenter(selected!, k, visible.length)
                : x(selected!),
            y(values[selected!]),
          ),
          4,
          Paint()..color = color,
        );
      }
    }
    if (selected != null) {
      canvas.drawLine(
        Offset(x(selected!), plot.top),
        Offset(x(selected!), plot.bottom),
        Paint()
          ..color = foreground.withValues(alpha: .3)
          ..strokeWidth = 1,
      );
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _ChartPainter old) => true;
}

class OpenUiDiagram extends StatelessWidget {
  const OpenUiDiagram({super.key, required this.props, required this.settings});
  final Map props;
  final LiquidGlassSettings settings;
  @override
  Widget build(BuildContext context) {
    final nodes = (props['nodes'] as List? ?? []).whereType<Map>().toList(),
        edges = (props['edges'] as List? ?? []).whereType<List>().toList();
    final colors = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 14,
      children: [
        if ((props['title']?.toString() ?? '').isNotEmpty)
          Text(
            props['title'].toString(),
            style: Theme.of(context).textTheme.titleMedium,
          ),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth < 440 ? 1 : 2;
            final width = (constraints.maxWidth - 24 * (columns - 1)) / columns;
            final height = ((nodes.length / columns).ceil()) * 100.0;
            final positions = {
              for (var i = 0; i < nodes.length; i++)
                nodes[i]['id']: Offset(
                  (i % columns) * (width + 24) + width / 2,
                  (i ~/ columns) * 100 + 30,
                ),
            };
            return SizedBox(
              height: height,
              child: Stack(
                children: [
                  Positioned.fill(
                    child: CustomPaint(
                      key: const ValueKey('openui-chart-plot'),
                      painter: _DiagramPainter(
                        positions: positions,
                        halfWidth: width / 2,
                        edges: edges,
                        color: colors.primary,
                      ),
                    ),
                  ),
                  for (var i = 0; i < nodes.length; i++)
                    Positioned(
                      left: (i % columns) * (width + 24),
                      top: (i ~/ columns) * 100,
                      width: width,
                      height: 60,
                      child: GlassCard(
                        quality: GlassQuality.standard,
                        useOwnLayer: true,
                        settings: settings,
                        padding: const EdgeInsets.all(10),
                        shape: const LiquidRoundedSuperellipse(
                          borderRadius: 12,
                        ),
                        child: Center(
                          child: Text(
                            nodes[i]['label']?.toString() ?? '',
                            textAlign: TextAlign.center,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            );
          },
        ),
      ],
    );
  }
}

class _DiagramPainter extends CustomPainter {
  _DiagramPainter({
    required this.positions,
    required this.edges,
    required this.color,
    required this.halfWidth,
  });
  final double halfWidth;
  final Map<dynamic, Offset> positions;
  final List<List> edges;
  final Color color;
  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      if (edge.length != 2) continue;
      final a = positions[edge[0]], b = positions[edge[1]];
      if (a == null || b == null || a == b) continue;
      final horizontal = a.dy == b.dy;
      final sign = horizontal
          ? (b.dx > a.dx ? 1.0 : -1.0)
          : (b.dy > a.dy ? 1.0 : -1.0);
      final offset = horizontal ? Offset(halfWidth, 0) : const Offset(0, 30);
      final start = a + offset * sign, end = b - offset * sign;
      final direction = (end - start) / (end - start).distance;
      canvas.drawLine(
        start,
        end,
        Paint()
          ..color = color.withValues(alpha: .5)
          ..strokeWidth = 1.5,
      );
      final side = Offset(-direction.dy, direction.dx);
      canvas.drawPath(
        Path()
          ..moveTo(end.dx, end.dy)
          ..lineTo(
            (end - direction * 8 + side * 4).dx,
            (end - direction * 8 + side * 4).dy,
          )
          ..lineTo(
            (end - direction * 8 - side * 4).dx,
            (end - direction * 8 - side * 4).dy,
          )
          ..close(),
        Paint()..color = color,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _DiagramPainter old) => true;
}
