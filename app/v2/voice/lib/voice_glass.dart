import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

class VoiceGlassButton extends StatelessWidget {
  const VoiceGlassButton({
    super.key,
    required this.onPressed,
    this.icon,
    this.label,
    this.tooltip,
    this.selected = false,
    this.primary = false,
    this.plain = false,
  });

  final VoidCallback? onPressed;
  final IconData? icon;
  final String? label;
  final String? tooltip;
  final bool selected;
  final bool primary;
  final bool plain;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    const radius = 10.0;
    final style = ButtonStyle(
      foregroundColor: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.disabled)) {
          return colors.onSurface.withValues(alpha: .38);
        }
        return primary
            ? colors.onPrimary
            : selected
            ? colors.primary
            : colors.onSurface;
      }),
      shape: const WidgetStatePropertyAll(
        RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(radius)),
        ),
      ),
      minimumSize: const WidgetStatePropertyAll(Size(34, 34)),
      padding: WidgetStatePropertyAll(
        EdgeInsets.symmetric(horizontal: label == null ? 8 : 12),
      ),
      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
    final button = TextButton(
      onPressed: onPressed,
      style: style,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) Icon(icon, size: 17),
          if (icon != null && label != null) const SizedBox(width: 8),
          if (label != null)
            Flexible(
              child: Text(label!, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
        ],
      ),
    );
    return Tooltip(
      message: tooltip ?? label ?? '',
      child: plain
          ? button
          : GlassContainer(
              shape: const LiquidRoundedRectangle(borderRadius: radius),
              useOwnLayer: true,
              settings: LiquidGlassSettings(
                glassColor: onPressed != null && primary
                    ? colors.primary
                    : selected
                    ? colors.secondaryContainer
                    : colors.surfaceContainer,
                blur: 2,
                thickness: 4,
                lightIntensity: 0,
                glowIntensity: 0,
                shadowElevation: 0,
                standardOpacityMultiplier: 1,
              ),
              child: button,
            ),
    );
  }
}
