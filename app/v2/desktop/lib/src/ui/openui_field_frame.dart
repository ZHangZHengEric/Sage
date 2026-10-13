import 'package:flutter/material.dart';

/// Keeps native Glass inputs recognizable even on a flat or transparent backdrop.
class OpenUiFieldFrame extends StatefulWidget {
  const OpenUiFieldFrame({super.key, required this.child});
  final Widget child;

  @override
  State<OpenUiFieldFrame> createState() => _OpenUiFieldFrameState();
}

class _OpenUiFieldFrameState extends State<OpenUiFieldFrame> {
  bool _focused = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Focus(
      canRequestFocus: false,
      onFocusChange: (value) => setState(() => _focused = value),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        decoration: BoxDecoration(
          color: colors.surfaceContainerHigh.withValues(alpha: .55),
          borderRadius: BorderRadius.circular(10),
        ),
        foregroundDecoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: _focused ? colors.primary : colors.outlineVariant,
            width: _focused ? 1.5 : 1,
          ),
        ),
        child: widget.child,
      ),
    );
  }
}
