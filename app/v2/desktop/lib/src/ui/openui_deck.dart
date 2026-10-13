import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'openui_charts.dart';
import 'openui_slide_layout.dart';

/// A fixed canvas: resizing the window scales the page rather than reflowing it.
class OpenUiDeck extends StatefulWidget {
  const OpenUiDeck({
    super.key,
    required this.node,
    required this.ready,
    this.onExport,
    this.initialIndex = 0,
    this.workspace = false,
    this.previewMessage,
  });
  final int initialIndex;
  final bool workspace;
  final String? previewMessage;
  final Map node;
  final bool ready;
  final Future<void> Function(bool dark)? onExport;
  @override
  State<OpenUiDeck> createState() => _OpenUiDeckState();
}

class _OpenUiDeckState extends State<OpenUiDeck> {
  late int _index = widget.initialIndex;
  bool _exporting = false;
  String? _error;
  List<Map> get slides =>
      ((widget.node['props'] as Map?)?['children'] as List? ?? [])
          .whereType<Map>()
          .where((n) => n['component'] == 'Slide')
          .toList();
  String t(String en, String zh) =>
      Localizations.localeOf(context).languageCode == 'zh' ? zh : en;
  void move(int i) => setState(() => _index = i.clamp(0, slides.length - 1));
  Future<void> export() async {
    if (!widget.ready || widget.onExport == null || _exporting) return;
    setState(() {
      _exporting = true;
      _error = null;
    });
    try {
      await widget.onExport!(Theme.of(context).brightness == Brightness.dark);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Widget button(Widget child, VoidCallback? action, {double width = 96}) =>
      FocusableActionDetector(
        enabled: action != null,
        shortcuts: const {
          SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
          SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
        },
        actions: {
          ActivateIntent: CallbackAction<ActivateIntent>(
            onInvoke: (_) {
              action?.call();
              return null;
            },
          ),
        },
        child: Semantics(
          button: true,
          enabled: action != null,
          child: IgnorePointer(
            ignoring: action == null,
            child: Opacity(
              opacity: action == null ? .45 : 1,
              child: GlassButton.custom(
                quality: GlassQuality.standard,
                settings: LiquidGlassSettings(
                  glassColor: Theme.of(
                    context,
                  ).colorScheme.surfaceContainerHigh.withValues(alpha: .55),
                ),
                onTap: action ?? () {},
                width: width,
                height: 34,
                shape: const LiquidRoundedRectangle(borderRadius: 8),
                useOwnLayer: true,
                child: DefaultTextStyle(
                  style: Theme.of(context).textTheme.labelMedium!.copyWith(
                    color: Theme.of(context).colorScheme.onSurface,
                  ),
                  child: child,
                ),
              ),
            ),
          ),
        ),
      );
  void present() {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog.fullscreen(
        child: SafeArea(
          child: Column(
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: button(
                  const Icon(Icons.close),
                  () => Navigator.pop(dialogContext),
                  width: 48,
                ),
              ),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final width =
                        (constraints.maxHeight - 196).clamp(
                          100,
                          constraints.maxHeight,
                        ) *
                        16 /
                        9;
                    return Center(
                      child: SizedBox(
                        width: width.clamp(100, constraints.maxWidth),
                        child: SingleChildScrollView(
                          child: OpenUiDeck(
                            node: widget.node,
                            initialIndex: _index,
                            ready: widget.ready,
                            onExport: widget.onExport,
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget workspace(List<Map> list, int index) {
    final colors = Theme.of(context).colorScheme;
    return LayoutBuilder(
      builder: (context, constraints) {
        final railWidth = constraints.maxWidth < 500 ? 88.0 : 132.0;
        return Column(
          key: const ValueKey('openui-deck-workspace'),
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                border: Border(
                  bottom: BorderSide(color: colors.outlineVariant),
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '${(widget.node['props'] as Map?)?['title'] ?? ''}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                  ),
                  const SizedBox(width: 8),
                  button(
                    Text(t('Present', '演示')),
                    widget.ready ? present : null,
                    width: 64,
                  ),
                  if (widget.onExport != null) ...[
                    const SizedBox(width: 6),
                    button(
                      Text(
                        _exporting
                            ? t('Exporting…', '正在导出…')
                            : t('Export PPTX', '导出 PPTX'),
                      ),
                      widget.ready && !_exporting ? export : null,
                      width: 106,
                    ),
                  ],
                ],
              ),
            ),
            Expanded(
              child: Row(
                children: [
                  Container(
                    width: railWidth,
                    decoration: BoxDecoration(
                      border: Border(
                        right: BorderSide(color: colors.outlineVariant),
                      ),
                    ),
                    child: ListView.builder(
                      key: const ValueKey('openui-slide-thumbnails'),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 12,
                      ),
                      itemCount: list.length,
                      itemBuilder: (context, i) {
                        final title =
                            '${(list[i]['props'] as Map?)?['title'] ?? ''}';
                        final selected = i == index;
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: Tooltip(
                            message: '${i + 1} · $title',
                            child: Semantics(
                              selected: selected,
                              button: true,
                              label: '${i + 1}: $title',
                              child: Material(
                                color: Colors.transparent,
                                child: InkWell(
                                  key: ValueKey('openui-slide-thumbnail:$i'),
                                  borderRadius: BorderRadius.circular(6),
                                  onTap: () => move(i),
                                  child: Padding(
                                    padding: const EdgeInsets.all(3),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.stretch,
                                      children: [
                                        Container(
                                          padding: const EdgeInsets.all(2),
                                          decoration: BoxDecoration(
                                            border: Border.all(
                                              color: selected
                                                  ? colors.primary
                                                  : colors.outlineVariant,
                                              width: 2,
                                            ),
                                            borderRadius: BorderRadius.circular(
                                              5,
                                            ),
                                          ),
                                          child: AspectRatio(
                                            aspectRatio: 16 / 9,
                                            child: IgnorePointer(
                                              child: ExcludeSemantics(
                                                child: OpenUiSlideCanvas(
                                                  node: list[i],
                                                  index: i,
                                                ),
                                              ),
                                            ),
                                          ),
                                        ),
                                        const SizedBox(height: 5),
                                        Text(
                                          '${i + 1}  $title',
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            fontSize: 11,
                                            color: selected
                                                ? colors.primary
                                                : colors.onSurfaceVariant,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                  Expanded(
                    child: ColoredBox(
                      color: colors.surfaceContainerLow,
                      child: SizedBox.expand(
                        child: Padding(
                          padding: const EdgeInsets.all(20),
                          child: Center(
                            child: AspectRatio(
                              aspectRatio: 16 / 9,
                              child: DecoratedBox(
                                decoration: BoxDecoration(
                                  boxShadow: [
                                    BoxShadow(
                                      color: Colors.black.withValues(
                                        alpha: .16,
                                      ),
                                      blurRadius: 20,
                                      offset: const Offset(0, 5),
                                    ),
                                  ],
                                ),
                                child: OpenUiSlideCanvas(
                                  key: const ValueKey(
                                    'openui-workspace-canvas',
                                  ),
                                  node: list[index],
                                  index: index,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                border: Border(top: BorderSide(color: colors.outlineVariant)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _error ?? widget.previewMessage ?? '',
                      maxLines: 2,
                      style: TextStyle(fontSize: 11, color: colors.error),
                    ),
                  ),
                  button(
                    const Icon(Icons.chevron_left, size: 18),
                    index > 0 ? () => move(index - 1) : null,
                    width: 32,
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: Text(
                      '${index + 1} / ${list.length}',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                  button(
                    const Icon(Icons.chevron_right, size: 18),
                    index + 1 < list.length ? () => move(index + 1) : null,
                    width: 32,
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final list = slides;
    if (list.isEmpty) {
      return const SizedBox(
        height: 120,
        child: Center(child: CircularProgressIndicator()),
      );
    }
    final index = _index.clamp(0, list.length - 1);
    if (widget.workspace) {
      return CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.arrowLeft): () =>
              move(index - 1),
          const SingleActivator(LogicalKeyboardKey.arrowRight): () =>
              move(index + 1),
        },
        child: Focus(
          child: ColoredBox(
            color: Theme.of(context).colorScheme.surface,
            child: workspace(list, index),
          ),
        ),
      );
    }
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.arrowLeft): () =>
            move(index - 1),
        const SingleActivator(LogicalKeyboardKey.arrowRight): () =>
            move(index + 1),
      },
      child: Focus(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 12,
          children: [
            AspectRatio(
              aspectRatio: 16 / 9,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(20),
                child: OpenUiSlideCanvas(node: list[index], index: index),
              ),
            ),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                button(
                  const Icon(Icons.chevron_left),
                  index > 0 ? () => move(index - 1) : null,
                  width: 34,
                ),
                Text('${index + 1} / ${list.length}'),
                button(
                  const Icon(Icons.chevron_right),
                  index + 1 < list.length ? () => move(index + 1) : null,
                  width: 34,
                ),
                button(Text(t('Present', '演示')), widget.ready ? present : null),
                if (widget.onExport != null)
                  button(
                    Text(
                      _exporting
                          ? t('Exporting…', '正在导出…')
                          : t('Export PPTX', '导出 PPTX'),
                    ),
                    widget.ready && !_exporting ? export : null,
                    width: 116,
                  ),
              ],
            ),
            SizedBox(
              height: 36,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: list.length,
                separatorBuilder: (_, _) => const SizedBox(width: 6),
                itemBuilder: (context, i) {
                  final selected = i == index;
                  final colors = Theme.of(context).colorScheme;
                  final title = '${(list[i]['props'] as Map?)?['title'] ?? ''}';
                  return Tooltip(
                    message: title,
                    child: Semantics(
                      selected: selected,
                      label: '${i + 1}: $title',
                      child: SizedBox(
                        width: 144,
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(
                              color: selected
                                  ? colors.primary
                                  : colors.outlineVariant,
                            ),
                            color: selected
                                ? colors.primary.withValues(alpha: .10)
                                : Colors.transparent,
                          ),
                          child: button(
                            Row(
                              children: [
                                Text(
                                  '${i + 1}'.padLeft(2, '0'),
                                  style: TextStyle(
                                    fontSize: 11,
                                    color: selected
                                        ? colors.primary
                                        : colors.onSurfaceVariant,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    title,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontSize: 12,
                                      fontWeight: selected
                                          ? FontWeight.w600
                                          : FontWeight.w400,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            () => move(i),
                            width: 144,
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
            if (_error != null)
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
    );
  }
}

class OpenUiSlideCanvas extends StatelessWidget {
  const OpenUiSlideCanvas({super.key, required this.node, this.index = 0});
  final Map node;
  final int index;
  @override
  Widget build(BuildContext context) {
    final p = node['props'] as Map? ?? {};
    final layout = p['layout'] ?? 'content';
    final cover = layout == 'cover';
    final dark = Theme.of(context).brightness == Brightness.dark;
    final palette = openUiSlideLayout[dark ? 'dark' : 'light'] as Map;
    Color color(Object? hex) =>
        Color(int.parse('ff${hex ?? '557BEF'}', radix: 16));
    final fg = color(palette['foreground']);
    final accent = color(
      (openUiSlideLayout[dark ? 'darkAccents' : 'accents'] as Map)[p['accent']],
    );
    final children = (p['children'] as List? ?? [])
        .whereType<Map>()
        .take(
          layout == 'cover'
              ? 1
              : layout == 'split'
              ? 4
              : 2,
        )
        .toList();
    final columns = layout == 'split' && children.length > 1 ? 2 : 1;
    final rows = children.isEmpty ? 1 : (children.length / columns).ceil();
    double n(String key) => (openUiSlideLayout[key] as num).toDouble();
    final margin = n('margin');
    final gap = n('gap');
    final bodyWidth = n('width') - 2 * margin;
    final w = (bodyWidth - (columns - 1) * gap) / columns;
    final h = (n('bodyHeight') - (rows - 1) * gap) / rows;
    Widget text(String value, double size, {bool bold = false, Color? tint}) =>
        Text(
          value,
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
            fontSize: size,
            height: 1.2,
            fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
            color: tint ?? fg,
          ),
        );
    Widget block(Map child) {
      final b = child['props'] as Map? ?? {};
      switch (child['component']) {
        case 'Text':
          return FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: w - 48,
              child: text('${b['content'] ?? ''}', h > 240 ? 30 : 20),
            ),
          );
        case 'Metric':
          Widget line(
            String value,
            double size, {
            bool bold = false,
            Color? tint,
          }) => SizedBox(
            width: w - 48,
            height: size * 1.2,
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: text(value, size, bold: bold, tint: tint),
            ),
          );
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              line('${b['label'] ?? ''}', 24),
              const SizedBox(height: 12),
              line(
                '${b['value'] ?? ''}',
                h > 240 ? 56 : 40,
                bold: true,
                tint: accent,
              ),
              const SizedBox(height: 12),
              line('${b['change'] ?? ''}', 22),
            ],
          );
        case 'Chart':
          return FittedBox(
            fit: BoxFit.contain,
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: w - 48,
              height: (b['series'] as List? ?? []).length > 1 ? 480 : 360,
              child: Theme(
                data: Theme.of(context).copyWith(
                  colorScheme: Theme.of(
                    context,
                  ).colorScheme.copyWith(primary: accent),
                ),
                child: OpenUiChart(props: b),
              ),
            ),
          );
        case 'Table':
          final columns = (b['columns'] as List? ?? []);
          if (columns.isEmpty) return const SizedBox.shrink();
          return FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: w - 48,
              child: Table(
                defaultVerticalAlignment: TableCellVerticalAlignment.middle,
                border: TableBorder(
                  horizontalInside: BorderSide(
                    color: fg.withValues(alpha: .15),
                  ),
                ),
                children: [
                  for (final row in [
                    columns,
                    ...(b['rows'] as List? ?? []).whereType<List>(),
                  ])
                    TableRow(
                      children: [
                        for (var i = 0; i < columns.length; i++)
                          Padding(
                            padding: const EdgeInsets.symmetric(
                              vertical: 12,
                              horizontal: 6,
                            ),
                            child: text(
                              i < row.length ? '${row[i] ?? ''}' : '',
                              20,
                              bold: identical(row, columns),
                            ),
                          ),
                      ],
                    ),
                ],
              ),
            ),
          );
        default:
          return const SizedBox.shrink();
      }
    }

    return FittedBox(
      fit: BoxFit.contain,
      child: SizedBox(
        width: n('width'),
        height: n('height'),
        child: ColoredBox(
          color: color(palette['background']),
          child: Stack(
            children: [
              Positioned(
                left: 950,
                top: -260,
                width: 600,
                height: 600,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: accent.withValues(alpha: .07),
                  ),
                ),
              ),
              Positioned(
                left: margin,
                top: 32,
                width: 72,
                height: 6,
                child: ColoredBox(color: accent),
              ),
              Positioned(
                left: margin,
                top: cover ? n('coverTitleY') : n('titleY'),
                width: cover ? n('coverTextWidth') : bodyWidth,
                height: cover ? n('coverTitleHeight') : n('titleHeight'),
                child: text(
                  '${p['title'] ?? ''}',
                  cover
                      ? n(
                          '${p['title'] ?? ''}'.length >
                                  n('coverLongTitleThreshold')
                              ? 'coverLongTitleSize'
                              : 'coverTitleSize',
                        )
                      : 44,
                  bold: true,
                ),
              ),
              Positioned(
                left: 1152,
                top: 675,
                width: 64,
                height: 24,
                child: text('${index + 1}'.padLeft(2, '0'), 16, tint: accent),
              ),
              if (cover && children.isNotEmpty)
                Positioned(
                  left: margin,
                  top: n('coverBodyY'),
                  width: n('coverTextWidth'),
                  height: n('coverBodyHeight'),
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.topLeft,
                    child: SizedBox(
                      width: n('coverTextWidth'),
                      child: text(
                        '${(children.first['props'] as Map?)?['content'] ?? ''}',
                        n('coverBodySize'),
                        tint: fg.withValues(alpha: .78),
                      ),
                    ),
                  ),
                ),
              for (var i = 0; !cover && i < children.length; i++)
                Positioned(
                  left: margin + (i % columns) * (w + gap),
                  top: n('bodyY') + (i ~/ columns) * (h + gap),
                  width: w,
                  height: h,
                  child: GlassCard(
                    quality: GlassQuality.standard,
                    settings: LiquidGlassSettings(
                      glassColor: color(palette['tile']),
                    ),
                    padding: const EdgeInsets.all(24),
                    child: block(children[i]),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
