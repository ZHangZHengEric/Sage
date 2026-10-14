import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'openui_extras.dart';
import 'openui_field_frame.dart';
import 'openui_deck.dart';

/// Native rendering of Sage's validated declarative OpenUI component library.
/// No source evaluation or action execution occurs in this widget.
class OpenUiSurface extends StatefulWidget {
  const OpenUiSurface({
    super.key,
    required this.surface,
    this.enabled = false,
    this.onSubmit,
    this.onDraftChanged,
    this.onExpand,
    this.onExport,
  });
  final Map<String, Object?> surface;
  final bool enabled;
  final Future<void> Function(String action, Map<String, Object?> values)?
  onSubmit;
  final ValueChanged<Map<String, Object?>>? onDraftChanged;
  final VoidCallback? onExpand;
  final Future<void> Function(bool dark)? onExport;
  @override
  State<OpenUiSurface> createState() => _OpenUiSurfaceState();
}

class _OpenUiSurfaceState extends State<OpenUiSurface> {
  final _controllers = <String, TextEditingController>{};
  final _values = <String, Object?>{};
  final _touched = <String>{};
  Map<String, Object?> _numericValues = {};
  bool _sending = false;
  String? _error;
  bool get _enabled =>
      widget.enabled &&
      !_sending &&
      (widget.surface['error']?.toString() ?? '').isEmpty;
  String _label(String en, String zh) =>
      Localizations.localeOf(context).languageCode == 'zh' ? zh : en;

  @override
  void initState() {
    super.initState();
    final draft = widget.surface['draft_values'];
    if (draft is Map) {
      _values.addAll(draft.cast<String, Object?>());
      _touched.addAll(draft.keys.map((key) => key.toString()));
    }
  }

  @override
  void didUpdateWidget(covariant OpenUiSurface oldWidget) {
    super.didUpdateWidget(oldWidget);
    final draft = widget.surface['draft_values'];
    if (draft is Map) {
      for (final entry in draft.entries) {
        _values[entry.key.toString()] = entry.value;
        _touched.add(entry.key.toString());
        final controller = _controllers[entry.key];
        if (controller != null && controller.text != entry.value) {
          controller.text = entry.value?.toString() ?? '';
        }
      }
    }
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void _changed(String name, Object? value) {
    if (!_enabled) return;
    _touched.add(name);
    _values[name] = value;
    widget.onDraftChanged?.call(Map.of(_values));
    setState(() => _error = null);
  }

  Future<void> _submit(String action) async {
    if (!_enabled || widget.onSubmit == null) return;
    String? validationError;
    void validate(Object? node) {
      if (node is! Map || node['props'] is! Map) return;
      final props = node['props'] as Map;
      final value = _values[props['name']];
      if (props['required'] == true &&
          ((value?.toString().trim() ?? '').isEmpty ||
              value is List && value.isEmpty)) {
        validationError = _label(
          '${props['label']} is required',
          '请填写${props['label']}',
        );
      }
      if (const {'NumberInput', 'Slider'}.contains(node['component']) &&
          (value is! num ||
              !value.isFinite ||
              value < (props['min'] as num? ?? 0) ||
              value > (props['max'] as num? ?? 1000000))) {
        validationError = _label(
          'Check ${props['label']}',
          '请检查${props['label']}',
        );
      }
      if (props['children'] is List) {
        for (final child in props['children'] as List) {
          validate(child);
        }
      }
    }

    validate(widget.surface['tree']);
    if (validationError != null) {
      setState(() => _error = validationError);
      return;
    }
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await widget.onSubmit!(action, Map.of(_values));
    } on Object {
      if (mounted) {
        setState(
          () => _error = _label(
            'Could not submit. Check the conversation before trying again.',
            '提交未完成，请先查看会话状态。',
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  GlassQuality get _quality => widget.surface['complete'] == false
      ? GlassQuality.minimal
      : GlassQuality.standard;

  LiquidGlassSettings _glass(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    return LiquidGlassSettings(
      visibility: dark ? 0.86 : 0.9,
      glassColor: theme.colorScheme.surface.withValues(
        alpha: dark ? 0.86 : 0.94,
      ),
      thickness: 4,
      blur: 3,
      chromaticAberration: 0,
      lightIntensity: 0.1,
      saturation: 1,
      glowIntensity: 0,
      standardOpacityMultiplier: dark ? 0.88 : 0.92,
    );
  }

  Widget _artCard({
    required Widget child,
    EdgeInsets padding = const EdgeInsets.all(12),
  }) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return GlassCard(
      quality: _quality,
      useOwnLayer: true,
      settings: _glass(context),
      padding: EdgeInsets.zero,
      shape: const LiquidRoundedSuperellipse(borderRadius: 20),
      child: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          color: colors.surfaceContainerLow,
          border: Border.all(color: colors.outlineVariant),
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              colors.primary.withValues(alpha: dark ? 0.12 : 0.09),
              Colors.transparent,
              colors.tertiary.withValues(alpha: dark ? 0.09 : 0.06),
            ],
            stops: const [0, 0.58, 1],
          ),
        ),
        child: Padding(padding: padding, child: child),
      ),
    );
  }

  Widget _node(Map node, [int depth = 0, String path = 'root']) {
    if (depth > 12) return const SizedBox.shrink();
    final rawProps = node['props'];
    if (rawProps is! Map) return const SizedBox.shrink();
    final props = rawProps;
    final colors = Theme.of(context).colorScheme;
    final children = props['children'] is List
        ? [
            for (final (index, child) in (props['children'] as List).indexed)
              if (child is Map) _node(child, depth + 1, '$path/$index'),
          ]
        : <Widget>[];
    final name = props['name']?.toString() ?? '';
    if (name.isNotEmpty && !_touched.contains(name)) {
      _values[name] = props['value'];
      final controller = _controllers[name];
      if (controller != null && controller.text != props['value']?.toString()) {
        controller.text = props['value']?.toString() ?? '';
      }
    }
    final label = props['label']?.toString() ?? '';
    switch (node['component']) {
      case 'Deck':
        return OpenUiDeck(
          node: node,
          ready:
              widget.surface['complete'] != false &&
              widget.surface['surface_id'] != null,
          onExport: widget.onExport,
        );
      case 'Stack':
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 12,
          children: children,
        );
      case 'Row':
        if (children.isEmpty) return const SizedBox.shrink();
        return LayoutBuilder(
          builder: (context, constraints) {
            final columns = (constraints.maxWidth / 200).floor().clamp(
              1,
              children.length,
            );
            final width = (constraints.maxWidth - 12 * (columns - 1)) / columns;
            return Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final child in children)
                  SizedBox(width: width, child: child),
              ],
            );
          },
        );
      case 'Card':
        return _artCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            spacing: 10,
            children: [
              if ((props['title']?.toString() ?? '').isNotEmpty)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 3,
                      height: 16,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(3),
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [colors.primary, colors.tertiary],
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        props['title'].toString(),
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(
                              color: colors.onSurface,
                              fontWeight: FontWeight.w600,
                              letterSpacing: -0.2,
                              fontSize: 14,
                            ),
                      ),
                    ),
                  ],
                ),
              ...children,
            ],
          ),
        );
      case 'Text':
        return SelectableText(
          props['content']?.toString() ?? '',
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: colors.onSurface),
        );
      case 'Table':
        final columns = (props['columns'] as List? ?? [])
            .map((value) => value?.toString() ?? '')
            .toList();
        if (columns.isEmpty) return const SizedBox.shrink();
        final rows = props['rows'] as List? ?? [];
        return GlassCard(
          quality: _quality,
          useOwnLayer: true,
          settings: _glass(context),
          padding: EdgeInsets.zero,
          shape: const LiquidRoundedSuperellipse(borderRadius: 14),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: LayoutBuilder(
              builder: (context, constraints) => SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: ConstrainedBox(
                  constraints: BoxConstraints(minWidth: constraints.maxWidth),
                  child: DataTable(
                    horizontalMargin: 12,
                    columnSpacing: 24,
                    headingRowHeight: 36,
                    dataRowMinHeight: 36,
                    dataRowMaxHeight: 48,
                    dividerThickness: 0.5,
                    headingTextStyle: Theme.of(context).textTheme.labelLarge
                        ?.copyWith(
                          color: colors.onSurfaceVariant,
                          fontWeight: FontWeight.w600,
                        ),
                    headingRowColor: WidgetStatePropertyAll(
                      colors.primary.withValues(alpha: 0.06),
                    ),
                    columns: [
                      for (final value in columns)
                        DataColumn(label: Text(value)),
                    ],
                    rows: [
                      for (var index = 0; index < rows.length; index++)
                        if (rows[index] is List &&
                            (rows[index] as List).length == columns.length)
                          DataRow(
                            color: WidgetStatePropertyAll(
                              index.isOdd
                                  ? colors.onSurface.withValues(alpha: 0.025)
                                  : Colors.transparent,
                            ),
                            cells: [
                              for (final cell in rows[index] as List)
                                DataCell(
                                  SelectableText(
                                    cell?.toString() ?? '',
                                    style: Theme.of(
                                      context,
                                    ).textTheme.bodyMedium,
                                  ),
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
      case 'Input':
        final controller = _controllers.putIfAbsent(
          name,
          () => TextEditingController(
            text: (_values[name] ?? props['value'] ?? '').toString(),
          ),
        );
        _values.putIfAbsent(name, () => controller.text);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 6,
          children: [
            Text(
              label,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: colors.onSurfaceVariant,
                fontWeight: FontWeight.w600,
              ),
            ),
            OpenUiFieldFrame(
              child: GlassTextField(
                quality: _quality,
                key: ValueKey('openui-field:$name'),
                controller: controller,
                enabled: _enabled,
                useOwnLayer: true,
                settings: _glass(context),
                maxLength: 8000,
                height: 38,
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
                textStyle: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.onSurface),
                onChanged: (value) => _changed(name, value),
              ),
            ),
          ],
        );
      case 'Select':
        final options = (props['options'] as List? ?? [])
            .whereType<String>()
            .toSet()
            .toList();
        if (options.isEmpty) return const SizedBox.shrink();
        final value = (_values[name] ?? props['value'] ?? '').toString();
        _values.putIfAbsent(name, () => value);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 6,
          children: [
            Text(
              label,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: colors.onSurfaceVariant,
                fontWeight: FontWeight.w600,
              ),
            ),
            GlassCard(
              quality: _quality,
              useOwnLayer: true,
              settings: _glass(context),
              shape: const LiquidRoundedSuperellipse(borderRadius: 12),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 0),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  key: ValueKey('openui-field:$name'),
                  isExpanded: true,
                  value: options.contains(value) ? value : null,
                  dropdownColor: colors.surface,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: colors.onSurface),
                  items: [
                    for (final option in options)
                      DropdownMenuItem(value: option, child: Text(option)),
                  ],
                  onChanged: _enabled
                      ? (next) => _changed(name, next ?? '')
                      : null,
                ),
              ),
            ),
          ],
        );
      case 'Toggle':
        final value = _values[name] ?? props['value'] ?? false;
        _values.putIfAbsent(name, () => value == true);
        return Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.onSurface),
              ),
            ),
            AbsorbPointer(
              absorbing: !_enabled,
              child: GlassSwitch(
                key: ValueKey('openui-field:$name'),
                value: value == true,
                activeColor: colors.primary,
                inactiveColor: colors.surfaceContainerHighest,
                onChanged: (next) => _changed(name, next),
                useOwnLayer: true,
                settings: _glass(context),
              ),
            ),
          ],
        );
      case 'Button':
        return Align(
          alignment: Alignment.centerLeft,
          child: GlassButton.custom(
            quality: _quality,
            key: ValueKey('openui-action:${props['action']}'),
            width: 160,
            style: GlassButtonStyle.filled,
            ambientBaseLight: 0,
            useOwnLayer: true,
            shape: const LiquidRoundedRectangle(borderRadius: 12),
            label: label,
            settings: _glass(context).copyWith(
              glassColor: colors.primary,
              visibility: 1,
              standardOpacityMultiplier: 1,
              lightIntensity: 0,
            ),
            height: 36,
            enabled: _enabled,
            onTap: () => _submit(props['action'].toString()),
            child: Text(
              label,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: colors.onPrimary,
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        );
      default:
        return OpenUiExtras(
          key: ValueKey(
            // Labels and titles are presentation, not unique identities. A
            // repeated Divider (or metric/title) must be a distinct sibling.
            '${node['component']}:$path:${node['id'] ?? name}',
          ),
          node: node,
          values: _numericValues,
          enabled: _enabled,
          ready: widget.surface['complete'] != false,
          onChanged: _changed,
          settings: _glass(context),
          children: children,
        );
    }
  }

  Set<String> _fieldNames(Map node) {
    final names = <String>{};
    final bindings = <String, Object?>{};
    void collectBinding(Map node) {
      if (node['id'] is String) bindings[node['id'] as String] = node;
      final props = node['props'];
      if (props is Map && props['inputs'] is List) {
        for (final input in (props['inputs'] as List).whereType<Map>()) {
          collectBinding(input);
        }
      }
    }

    void visit(Map node) {
      final props = node['props'];
      if (props is! Map) return;
      if (node['id'] is String) bindings[node['id'] as String] = node;
      if (props['inputs'] is List) {
        for (final input in (props['inputs'] as List).whereType<Map>()) {
          collectBinding(input);
        }
      }
      if (node['component'] == 'Progress' && props['value'] is Map) {
        collectBinding(props['value'] as Map);
      }
      if (props['series'] is List) {
        for (final series in (props['series'] as List).whereType<Map>()) {
          if (series['values'] is List) {
            for (final value in (series['values'] as List).whereType<Map>()) {
              collectBinding(value);
            }
          }
        }
      }
      if (openUiFieldComponents.contains(node['component']) &&
          props['name'] is String) {
        names.add(props['name'] as String);
        if (!_touched.contains(props['name']) && props.containsKey('value')) {
          _values[props['name'] as String] = props['value'];
        }
      }
      if (props['children'] is List) {
        for (final child in (props['children'] as List).whereType<Map>()) {
          visit(child);
        }
      }
    }

    visit(node);
    _numericValues = {...bindings, ..._values};
    return names;
  }

  bool _hasFields(Map node) {
    if (openUiFieldComponents.contains(node['component'])) {
      return true;
    }
    final props = node['props'];
    if (props is! Map || props['children'] is! List) return false;
    return (props['children'] as List).whereType<Map>().any(_hasFields);
  }

  Widget _content(Map tree) {
    final content = _node(tree);
    if (_hasFields(tree)) {
      return Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: content,
        ),
      );
    }
    return content;
  }

  @override
  Widget build(BuildContext context) {
    final tree = widget.surface['tree'];
    final failed = (widget.surface['error']?.toString() ?? '').isNotEmpty;
    if (tree is Map) {
      final fields = _fieldNames(tree);
      _values.removeWhere((name, _) => !fields.contains(name));
      _touched.removeWhere((name) => !fields.contains(name));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 8,
      children: [
        if (widget.onExpand != null && tree is Map)
          Align(
            alignment: Alignment.centerRight,
            child: GlassButton.custom(
              quality: _quality,
              key: const ValueKey('openui-open-in-sidebar'),
              height: 30,
              width: Localizations.localeOf(context).languageCode == 'zh'
                  ? 124
                  : 160,
              useOwnLayer: true,
              shape: const LiquidRoundedRectangle(borderRadius: 8),
              label: _label('Open in sidebar', '在侧栏打开'),
              settings: _glass(context),
              onTap: widget.onExpand!,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                spacing: 6,
                children: [
                  const Icon(CupertinoIcons.sidebar_right, size: 14),
                  Flexible(
                    child: Text(
                      _label('Open in sidebar', '在侧栏打开'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ),
                ],
              ),
            ),
          ),
        if (tree is Map)
          _content(tree)
        else
          GlassCard(
            quality: _quality,
            useOwnLayer: true,
            settings: _glass(context),
            padding: const EdgeInsets.all(16),
            child: failed
                ? Text(
                    _label('This interface could not be rendered.', '此界面未能生成。'),
                  )
                : const Align(
                    alignment: Alignment.centerLeft,
                    child: CupertinoActivityIndicator(),
                  ),
          ),
        if (failed && tree is Map)
          Text(
            _label(
              'Generated content failed validation · read-only preview',
              '生成内容未通过校验，仅供预览',
            ),
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        if (_error != null)
          Text(
            _error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
      ],
    );
  }
}

/// The source stays in message history, while openui fences become native UI.
class OpenUiMessagePart {
  const OpenUiMessagePart(this.markdown, {this.blockIndex});
  final String markdown;
  final int? blockIndex;
}

List<OpenUiMessagePart> splitOpenUiMessage(
  String text, {
  bool streaming = false,
}) {
  final parts = <OpenUiMessagePart>[];
  final plain = StringBuffer();
  int? fenceLength;
  bool uiFence = false;
  int index = 0;
  for (final line in text.split(RegExp(r'(?<=\n)'))) {
    final match = RegExp(r'^(`{3,})([^\r\n]*)[\r\n]*$').firstMatch(line);
    if (fenceLength == null) {
      if (match != null) {
        fenceLength = match[1]!.length;
        uiFence = match[2]!.trim() == 'openui';
        if (uiFence) {
          if (plain.isNotEmpty) {
            parts.add(OpenUiMessagePart(plain.toString()));
            plain.clear();
          }
          parts.add(OpenUiMessagePart('', blockIndex: index++));
          continue;
        }
      }
      // Hide an opening tag split across tokens until its language is known.
      if (streaming &&
          match == null &&
          RegExp(
            r'^`{1,3}(?:o(?:p(?:e(?:n(?:u(?:i)?)?)?)?)?)?$',
          ).hasMatch(line)) {
        continue;
      }
      plain.write(line);
    } else if (match != null &&
        match[1]!.length >= fenceLength &&
        match[2]!.trim().isEmpty) {
      if (!uiFence) plain.write(line);
      fenceLength = null;
      uiFence = false;
    } else if (!uiFence) {
      plain.write(line);
    }
  }
  if (plain.isNotEmpty) parts.add(OpenUiMessagePart(plain.toString()));
  return parts;
}
