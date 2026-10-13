import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

/// Glass selection pill with bounded text, keyboard access and full-label semantics.
class OpenUiPill extends StatelessWidget {
  const OpenUiPill({
    super.key,
    required this.label,
    this.selected = false,
    this.color,
    this.icon,
    this.onTap,
    this.settings,
  });
  final String label;
  final bool selected;
  final Color? color;
  final Widget? icon;
  final VoidCallback? onTap;
  final LiquidGlassSettings? settings;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final foreground = color ?? colors.onSurface;
    final style = Theme.of(
      context,
    ).textTheme.labelLarge?.copyWith(color: foreground);
    final painter = TextPainter(
      text: TextSpan(text: label, style: style),
      textDirection: Directionality.of(context),
      textScaler: MediaQuery.textScalerOf(context),
      maxLines: 1,
    )..layout();
    final labelWidth = painter.width;
    painter.dispose();
    return LayoutBuilder(
      builder: (context, constraints) {
        final available = constraints.hasBoundedWidth
            ? constraints.maxWidth
            : 280.0;
        final width = math.min(
          available,
          math.max(60, labelWidth + 32 + (icon == null ? 0 : 24)),
        );
        return Tooltip(
          message: label,
          child: FocusableActionDetector(
            enabled: onTap != null,
            shortcuts: const {
              SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
              SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
            },
            actions: {
              ActivateIntent: CallbackAction<ActivateIntent>(
                onInvoke: (_) {
                  onTap?.call();
                  return null;
                },
              ),
            },
            child: Semantics(
              label: label,
              button: onTap != null,
              selected: selected,
              enabled: onTap != null,
              child: GlassButton.custom(
                quality: GlassQuality.standard,
                label: label,
                enabled: onTap != null,
                width: width.toDouble(),
                height: 44,
                useOwnLayer: true,
                shape: const LiquidRoundedRectangle(borderRadius: 22),
                settings:
                    (settings ??
                            LiquidGlassSettings(glassColor: colors.surface))
                        .copyWith(
                          glassColor: selected
                              ? (color ?? colors.primary).withValues(alpha: .16)
                              : colors.surface,
                        ),
                onTap: onTap ?? () {},
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: Row(
                    children: [
                      if (icon != null) ...[icon!, const SizedBox(width: 8)],
                      Expanded(
                        child: Text(
                          label,
                          style: style,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
