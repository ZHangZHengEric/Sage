import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import '../../localization/app_localizations.dart';

/// One application-wide location for transient feedback and controller errors.
class DesktopNoticeHost extends StatefulWidget {
  const DesktopNoticeHost({
    required this.child,
    required this.error,
    required this.onClearError,
    super.key,
  });

  final Widget child;
  final String? error;
  final VoidCallback onClearError;

  static void show(
    BuildContext context, {
    required String message,
    bool isError = false,
    Duration duration = const Duration(seconds: 2),
  }) {
    final host = context.findAncestorStateOfType<_DesktopNoticeHostState>();
    assert(host != null, 'DesktopNoticeHost must wrap the application.');
    host?._show(message, isError, duration);
  }

  @override
  State<DesktopNoticeHost> createState() => _DesktopNoticeHostState();
}

class _DesktopNoticeHostState extends State<DesktopNoticeHost> {
  Timer? _timer;
  String? _message;
  bool _isError = false;

  void _show(String message, bool isError, Duration duration) {
    _timer?.cancel();
    setState(() {
      _message = message;
      _isError = isError;
    });
    _timer = Timer(duration, _dismiss);
  }

  void _dismiss() {
    _timer?.cancel();
    setState(() => _message = null);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final padding = MediaQuery.paddingOf(context);
    final error = widget.error;
    final message = _message;
    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        if (error != null || message != null)
          Positioned(
            top: math.max(70, padding.top + 18),
            right: padding.right + 18,
            width: math.min(
              380,
              math.max(
                0,
                MediaQuery.sizeOf(context).width - padding.horizontal - 36,
              ),
            ),
            child: Material(
              type: MaterialType.transparency,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (error != null)
                    DesktopNotice(
                      key: const ValueKey('workspace-error-notice'),
                      message: context.l10n.knownMessage(error),
                      isError: true,
                      onClose: widget.onClearError,
                    ),
                  if (message != null && message != error) ...[
                    if (error != null) const SizedBox(height: 8),
                    DesktopNotice(
                      key: const ValueKey('desktop-transient-notice'),
                      message: message,
                      isError: _isError,
                      onClose: _dismiss,
                    ),
                  ],
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class DesktopNotice extends StatelessWidget {
  const DesktopNotice({
    required this.message,
    required this.onClose,
    this.isError = false,
    super.key,
  });

  final String message;
  final VoidCallback onClose;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final dark = theme.brightness == Brightness.dark;
    final accent = isError ? colors.error : colors.primary;
    return Semantics(
      liveRegion: true,
      label: message,
      child: GlassCard(
        padding: EdgeInsets.zero,
        shape: const LiquidRoundedSuperellipse(borderRadius: 16),
        useOwnLayer: true,
        settings: LiquidGlassSettings(
          glassColor: colors.surfaceContainerHigh.withValues(alpha: 0.94),
          visibility: 0.96,
          blur: 3,
          thickness: 4,
          chromaticAberration: 0,
          lightIntensity: 0.1,
          saturation: 1,
          glowIntensity: 0,
          standardOpacityMultiplier: dark ? 0.92 : 0.94,
        ),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: accent.withValues(alpha: 0.26)),
          ),
          padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
          child: Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: dark ? 0.2 : 0.1),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  isError
                      ? CupertinoIcons.exclamationmark
                      : CupertinoIcons.check_mark,
                  color: accent,
                  size: 15,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  message,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: colors.onSurface,
                  ),
                ),
              ),
              IconButton(
                tooltip: context.l10n.text('common.close'),
                onPressed: onClose,
                icon: const Icon(CupertinoIcons.xmark, size: 15),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
