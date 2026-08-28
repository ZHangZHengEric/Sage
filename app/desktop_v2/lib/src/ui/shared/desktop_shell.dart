import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

const double desktopCompactBreakpoint = 760;
const double desktopPaneHeaderHeight = 42;
const double desktopSplitHandleWidth = 2;

double desktopCompactRailHeight(double availableHeight) =>
    (availableHeight * 0.2).clamp(118.0, 176.0).toDouble();

class DesktopSidebarSurface extends StatelessWidget {
  const DesktopSidebarSurface({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final baseGradient = dark
        ? [
            const Color(0xFF183846).withValues(alpha: 0.52),
            const Color(0xFF071217).withValues(alpha: 0.36),
            const Color(0xFF173A43).withValues(alpha: 0.44),
          ]
        : [
            const Color(0xFFFFFFFF).withValues(alpha: 0.82),
            const Color(0xFFEAF6FB).withValues(alpha: 0.6),
            const Color(0xFFFFFFFF).withValues(alpha: 0.74),
          ];
    final sheenGradient = dark
        ? [
            Colors.white.withValues(alpha: 0.08),
            Colors.white.withValues(alpha: 0.015),
            const Color(0xFF5AC8FA).withValues(alpha: 0.05),
          ]
        : [
            Colors.white.withValues(alpha: 0.38),
            Colors.white.withValues(alpha: 0.07),
            const Color(0xFF5AC8FA).withValues(alpha: 0.1),
          ];
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: baseGradient,
          stops: const [0, 0.52, 1],
        ),
      ),
      child: Stack(
        children: [
          Positioned.fill(
            child: IgnorePointer(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: sheenGradient,
                    stops: const [0, 0.34, 1],
                  ),
                ),
              ),
            ),
          ),
          child,
        ],
      ),
    );
  }
}

LiquidGlassSettings desktopSidebarGlassSettings(BuildContext context) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return LiquidGlassSettings(
    visibility: dark ? 0.82 : 0.88,
    glassColor: dark
        ? const Color(0xFF2B2C2E).withValues(alpha: 0.82)
        : const Color(0xFFFFFFFF).withValues(alpha: 0.9),
    thickness: 4,
    blur: 3,
    chromaticAberration: 0,
    lightIntensity: 0.1,
    saturation: 1,
    glowIntensity: 0,
    standardOpacityMultiplier: dark ? 0.86 : 0.9,
    shadowElevation: 0.04,
  );
}
