import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'openui_pill.dart';
import 'openui_field_frame.dart';
import 'openui_charts.dart';
import 'openui_image.dart';

const openUiFieldComponents = {
  'Input',
  'Select',
  'Toggle',
  'NumberInput',
  'Slider',
  'DateInput',
  'CheckboxGroup',
  'RadioGroup',
};

/// Bounded arithmetic, never an expression interpreter or network action.
double? openUiCompute(
  String operation,
  List inputs,
  Map<String, Object?> values,
) {
  return _NumericEvaluation(values).compute(operation, inputs, 0);
}

double? openUiNumeric(Object? value, Map<String, Object?> values) =>
    _NumericEvaluation(values).resolve(value, 0);

class _NumericEvaluation {
  _NumericEvaluation(this.values);
  final Map<String, Object?> values;
  int remaining = 2048;
  final Set<String> active = {};

  double? resolve(Object? value, int depth) {
    if (--remaining < 0 || depth > 12) return null;
    if (value is num) return value.isFinite ? value.toDouble() : null;
    if (value is String) {
      if (!active.add(value)) return null;
      final result = resolve(values[value], depth + 1);
      active.remove(value);
      return result;
    }
    if (value is Map && value['props'] is Map) {
      final props = value['props'] as Map;
      if (value['component'] == 'Computed') {
        return compute(
          props['operation']?.toString() ?? '',
          props['inputs'] as List? ?? [],
          depth + 1,
        );
      }
      if (const {'NumberInput', 'Slider'}.contains(value['component'])) {
        return resolve(props['name'], depth + 1);
      }
    }
    return null;
  }

  double? selectionCount(Object? value, int depth) {
    if (--remaining < 0 || depth > 12) return null;
    if (value is String) {
      if (!active.add(value)) return null;
      final count = selectionCount(values[value], depth + 1);
      active.remove(value);
      return count;
    }
    if (value is Map &&
        value['component'] == 'CheckboxGroup' &&
        value['props'] is Map) {
      return selectionCount((value['props'] as Map)['name'], depth + 1);
    }
    if (value is List &&
        value.length <= 100 &&
        value.every((v) => v is String)) {
      return value.toSet().length.toDouble();
    }
    return null;
  }

  double? compute(String operation, List inputs, int depth) {
    if (depth > 12 || inputs.isEmpty || inputs.length > 16) return null;
    final args = <double>[];
    for (final input in inputs) {
      final value = operation == 'count'
          ? selectionCount(input, depth)
          : resolve(input, depth);
      if (value == null) return null;
      args.add(value);
    }
    if (args.isEmpty || args.length > 16) return null;
    double result;
    switch (operation) {
      case 'count':
      case 'sum':
        result = args.reduce((a, b) => a + b);
      case 'product':
        result = args.reduce((a, b) => a * b);
      case 'difference':
        if (args.length != 2) return null;
        result = args[0] - args[1];
      case 'divide':
        if (args.length != 2 || args[1] == 0) return null;
        result = args[0] / args[1];
      case 'ratioPercent':
        if (args.length != 2 || args[1] <= 0) return null;
        result = args[0] / args[1] * 100;
      case 'percent':
        if (args.length != 2) return null;
        result = args[0] * args[1] / 100;
      case 'compoundGrowth':
        if (args.length != 3 ||
            args[0] < 0 ||
            args[1] < -100 ||
            args[2] < 0 ||
            args[2] > 1000) {
          return null;
        }
        result = args[0] * math.pow(1 + args[1] / 100, args[2]).toDouble();
      case 'loanPayment':
        if (args.length != 3 ||
            args[0] < 0 ||
            args[1] < 0 ||
            args[2] <= 0 ||
            args[2] > 12000) {
          return null;
        }
        final rate = args[1] / 1200;
        result = rate == 0
            ? args[0] / args[2]
            : args[0] * rate / (1 - math.pow(1 + rate, -args[2]));
      default:
        return null;
    }
    return result.isFinite && result.abs() <= 1e15 ? result : null;
  }
}

String openUiNumberLabel(num value) {
  final parts = value.toStringAsPrecision(15).split('e');
  if (parts[0].contains('.')) {
    parts[0] = parts[0]
        .replaceFirst(RegExp(r'0+$'), '')
        .replaceFirst(RegExp(r'\.$'), '');
  }
  return parts.join('e');
}

Color openUiTone(ColorScheme colors, String? tone) => switch (tone) {
  'success' =>
    colors.brightness == Brightness.dark
        ? const Color(0xff7edab0)
        : const Color(0xff19734c),
  'warning' =>
    colors.brightness == Brightness.dark
        ? const Color(0xfff2c36d)
        : const Color(0xff865b00),
  'error' => colors.error,
  'info' => colors.primary,
  _ => colors.onSurfaceVariant,
};

class OpenUiExtras extends StatefulWidget {
  const OpenUiExtras({
    super.key,
    required this.node,
    required this.children,
    required this.values,
    required this.enabled,
    required this.ready,
    required this.onChanged,
    required this.settings,
  });
  final Map node;
  final List<Widget> children;
  final Map<String, Object?> values;
  final bool enabled, ready;
  final void Function(String, Object?) onChanged;
  final LiquidGlassSettings settings;
  @override
  State<OpenUiExtras> createState() => _OpenUiExtrasState();
}

class _OpenUiExtrasState extends State<OpenUiExtras> {
  int _tab = 0;
  final _number = TextEditingController();
  final _focus = FocusNode();
  @override
  void dispose() {
    _number.dispose();
    _focus.dispose();
    super.dispose();
  }

  Widget _card(Widget child) {
    final colors = Theme.of(context).colorScheme;
    return GlassCard(
      quality: widget.ready ? GlassQuality.standard : GlassQuality.minimal,
      useOwnLayer: true,
      settings: widget.settings,
      shape: const LiquidRoundedSuperellipse(borderRadius: 16),
      padding: EdgeInsets.zero,
      child: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          color: colors.surfaceContainerLow,
          border: Border.all(color: colors.outlineVariant),
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              colors.primary.withValues(alpha: .07),
              Colors.transparent,
              colors.tertiary.withValues(alpha: .05),
            ],
          ),
        ),
        child: Padding(padding: const EdgeInsets.all(12), child: child),
      ),
    );
  }

  Widget _group(String label, Widget child) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    spacing: 6,
    children: [
      if (label.isNotEmpty)
        Text(label, style: Theme.of(context).textTheme.labelLarge),
      child,
    ],
  );
  @override
  Widget build(BuildContext context) {
    final p = widget.node['props'] as Map;
    final colors = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final tone = openUiTone(colors, p['tone']?.toString());
    final label = p['label']?.toString() ?? '';
    final name = p['name']?.toString() ?? '';
    final value = widget.values[name] ?? p['value'];
    switch (widget.node['component']) {
      case 'Heading':
        return Text(
          p['content']?.toString() ?? '',
          style: switch (p['level']) {
            1 => text.titleLarge?.copyWith(
              fontSize: 20,
              fontWeight: FontWeight.w600,
            ),
            3 => text.titleSmall,
            _ => text.titleMedium?.copyWith(fontWeight: FontWeight.w600),
          },
        );
      case 'Badge':
        return Align(
          alignment: Alignment.centerLeft,
          child: OpenUiPill(
            label: label,
            selected: true,
            color: tone,
            settings: widget.settings,
          ),
        );
      case 'Metric':
        return _card(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 6,
            children: [
              Text(
                label,
                style: text.labelLarge?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
              SelectableText(
                p['value']?.toString() ?? '',
                style: text.titleLarge?.copyWith(
                  fontSize: 22,
                  fontWeight: FontWeight.w600,
                ),
              ),
              if ((p['change']?.toString() ?? '').isNotEmpty)
                Text(
                  p['change'].toString(),
                  style: text.labelLarge?.copyWith(color: tone),
                ),
            ],
          ),
        );
      case 'Computed':
        final result = openUiCompute(
          p['operation']?.toString() ?? '',
          p['inputs'] as List? ?? [],
          widget.values,
        );
        final precision = (p['precision'] as num? ?? 2).toInt().clamp(0, 6);
        return _card(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 6,
            children: [
              Text(
                label,
                style: text.labelLarge?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
              Semantics(
                liveRegion: true,
                child: Text(
                  result == null
                      ? '—'
                      : '${p['prefix'] ?? ''}${result.toStringAsFixed(precision)}${p['suffix'] ?? ''}',
                  key: ValueKey('openui-computed:$label'),
                  style: text.titleLarge?.copyWith(
                    fontSize: 22,
                    color: colors.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        );
      case 'Divider':
        return Divider(color: colors.outlineVariant, height: 1);
      case 'Alert':
        return _card(
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                switch (p['tone']) {
                  'error' => Icons.error_outline,
                  'warning' => Icons.warning_amber_rounded,
                  'success' => Icons.check_circle_outline,
                  _ => Icons.info_outline,
                },
                color: tone,
                size: 20,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  p['content']?.toString() ?? '',
                  style: text.bodyMedium?.copyWith(color: tone),
                ),
              ),
            ],
          ),
        );
      case 'Progress':
        final computed = openUiNumeric(p['value'], widget.values);
        if (computed == null) return _group(label, const Text('—'));
        final amount = computed.clamp(0, 100);
        return _group(
          label,
          Column(
            spacing: 6,
            children: [
              LinearProgressIndicator(
                value: amount / 100,
                minHeight: 8,
                borderRadius: BorderRadius.circular(8),
                color: tone,
                backgroundColor: colors.surfaceContainerHighest,
              ),
              Align(
                alignment: Alignment.centerRight,
                child: Text(
                  '${amount.toStringAsFixed(0)}%',
                  style: text.labelLarge,
                ),
              ),
            ],
          ),
        );
      case 'Image':
        return OpenUiImage(
          url: p['url']?.toString() ?? '',
          alt: p['alt']?.toString() ?? '',
          height: (p['height'] as num? ?? 240).toDouble().clamp(80, 600),
          ready: widget.ready,
        );
      case 'Tab':
      case 'Section':
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 10,
          children: widget.children,
        );
      case 'Tabs':
        if (widget.children.isEmpty) return const SizedBox.shrink();
        final nodes = (p['children'] as List? ?? []).whereType<Map>().toList();
        final selected = _tab.clamp(0, widget.children.length - 1);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 12,
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                spacing: 6,
                children: [
                  for (var i = 0; i < widget.children.length; i++)
                    OpenUiPill(
                      key: ValueKey('openui-tab:$i'),
                      label:
                          (nodes[i]['props'] as Map?)?['label']?.toString() ??
                          '',
                      selected: i == selected,
                      color: colors.primary,
                      onTap: () => setState(() => _tab = i),
                      settings: widget.settings,
                    ),
                ],
              ),
            ),
            widget.children[selected],
          ],
        );
      case 'Accordion':
        final nodes = (p['children'] as List? ?? []).whereType<Map>().toList();
        return Column(
          spacing: 10,
          children: [
            for (var i = 0; i < widget.children.length; i++)
              GlassCard(
                quality: widget.ready
                    ? GlassQuality.standard
                    : GlassQuality.minimal,
                useOwnLayer: true,
                settings: widget.settings,
                padding: EdgeInsets.zero,
                shape: const LiquidRoundedSuperellipse(borderRadius: 14),
                child: ExpansionTile(
                  key: ValueKey('openui-section:$i'),
                  shape: const Border(),
                  collapsedShape: const Border(),
                  title: Text(
                    (nodes[i]['props'] as Map?)?['title']?.toString() ?? '',
                  ),
                  childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  children: [widget.children[i]],
                ),
              ),
          ],
        );
      case 'NumberInput':
        if (!_focus.hasFocus) {
          final next = value?.toString() ?? '';
          if (_number.text != next) _number.text = next;
        }
        return _group(
          label,
          OpenUiFieldFrame(
            child: GlassTextField(
              quality: widget.ready
                  ? GlassQuality.standard
                  : GlassQuality.minimal,
              key: ValueKey('openui-field:$name'),
              controller: _number,
              focusNode: _focus,
              enabled: widget.enabled,
              height: 38,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              useOwnLayer: true,
              settings: widget.settings,
              textStyle: text.bodyMedium,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
                signed: true,
              ),
              onChanged: (s) => widget.onChanged(name, double.tryParse(s)),
            ),
          ),
        );
      case 'Slider':
        final min = (p['min'] as num? ?? 0).toDouble(),
            max = (p['max'] as num? ?? 100).toDouble();
        if (max <= min) return const SizedBox.shrink();
        final amount = (value is num ? value.toDouble() : min).clamp(min, max);
        final step = (p['step'] as num? ?? 1).toDouble();
        return _group(
          label,
          Column(
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: Text(openUiNumberLabel(amount), style: text.titleMedium),
              ),
              GlassSlider(
                quality: widget.ready
                    ? GlassQuality.standard
                    : GlassQuality.minimal,
                key: ValueKey('openui-field:$name'),
                value: amount,
                min: min,
                max: max,
                activeColor: colors.primary,
                inactiveColor: colors.surfaceContainerHighest,
                useOwnLayer: true,
                settings: widget.settings,
                onChanged: widget.enabled
                    ? (v) => widget.onChanged(
                        name,
                        (min + ((v - min) / step).round() * step).clamp(
                          min,
                          max,
                        ),
                      )
                    : null,
              ),
            ],
          ),
        );
      case 'DateInput':
        return _group(
          label,
          GlassButton.custom(
            quality: widget.ready
                ? GlassQuality.standard
                : GlassQuality.minimal,
            key: ValueKey('openui-field:$name'),
            label: value?.toString() ?? '',
            height: 36,
            width: 240,
            useOwnLayer: true,
            settings: widget.settings,
            shape: const LiquidRoundedRectangle(borderRadius: 12),
            enabled: widget.enabled,
            onTap: () async {
              final parsed = DateTime.tryParse(value?.toString() ?? '');
              final initial = parsed ?? DateTime.now();
              final picked = await showDatePicker(
                context: context,
                initialDate: initial,
                firstDate: DateTime(1),
                lastDate: DateTime(9999, 12, 31),
              );
              if (picked != null && mounted) {
                widget.onChanged(
                  name,
                  '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}',
                );
              }
            },
            child: Row(
              children: [
                const Icon(Icons.calendar_today_outlined, size: 18),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(value?.toString() ?? '', style: text.bodyMedium),
                ),
              ],
            ),
          ),
        );
      case 'CheckboxGroup':
      case 'RadioGroup':
        final multi = widget.node['component'] == 'CheckboxGroup';
        final options = (p['options'] as List? ?? []).whereType<String>();
        return _group(
          label,
          Wrap(
            spacing: 6,
            runSpacing: 8,
            children: [
              for (final option in options)
                OpenUiPill(
                  key: ValueKey('openui-option:$name:$option'),
                  label: option,
                  selected: multi
                      ? value is List && value.contains(option)
                      : value == option,
                  color: colors.primary,
                  onTap: widget.enabled
                      ? () {
                          if (multi) {
                            final next = value is List
                                ? List<String>.from(value)
                                : <String>[];
                            next.contains(option)
                                ? next.remove(option)
                                : next.add(option);
                            widget.onChanged(name, next);
                          } else {
                            widget.onChanged(name, option);
                          }
                        }
                      : null,
                  settings: widget.settings,
                ),
            ],
          ),
        );
      case 'Chart':
        final series = <Map<String, Object?>>[];
        for (final raw in (p['series'] as List? ?? []).whereType<Map>()) {
          final values = [
            for (final value in raw['values'] as List? ?? [])
              openUiNumeric(value, widget.values),
          ];
          if (values.any(
            (value) =>
                value == null ||
                !value.isFinite ||
                (p['type'] == 'pie' && value < 0),
          )) {
            return _group(p['title']?.toString() ?? '', const Text('—'));
          }
          series.add({'name': raw['name'], 'values': values});
        }
        return _card(OpenUiChart(props: {...p, 'series': series}));
      case 'Timeline':
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final item in (p['items'] as List? ?? []).whereType<Map>())
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.circle,
                      size: 10,
                      color: openUiTone(colors, item['tone']?.toString()),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        spacing: 4,
                        children: [
                          Text(
                            item['label']?.toString() ?? '',
                            style: text.titleSmall,
                          ),
                          Text(
                            item['value']?.toString() ?? '',
                            style: text.bodyMedium?.copyWith(
                              color: colors.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
          ],
        );
      case 'Diagram':
        return _card(OpenUiDiagram(props: p, settings: widget.settings));
      default:
        return const SizedBox.shrink();
    }
  }
}
