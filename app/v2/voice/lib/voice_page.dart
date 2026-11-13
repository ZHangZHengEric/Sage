import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import 'brand.dart';
import 'voice_engine.dart';
import 'voice_locale.dart';

class VoicePage extends StatefulWidget {
  const VoicePage({
    super.key,
    required this.engine,
    required this.onToggle,
    required this.onSettings,
    required this.onNew,
    required this.onWorkbench,
  });

  final VoiceEngine engine;
  final VoidCallback onToggle;
  final VoidCallback onSettings;
  final VoidCallback onNew;
  final VoidCallback onWorkbench;

  @override
  State<VoicePage> createState() => _VoicePageState();
}

class _VoicePageState extends State<VoicePage>
    with SingleTickerProviderStateMixin {
  late final animation = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 44),
  )..repeat();

  @override
  void dispose() {
    animation.dispose();
    super.dispose();
  }

  Widget control(
    BuildContext context,
    String tooltip,
    IconData icon,
    VoidCallback? action, {
    bool active = false,
    bool busy = false,
  }) {
    final colors = Theme.of(context).colorScheme;
    final radius = active ? 16.0 : 13.0;
    return GlassContainer(
      width: active ? 52 : 44,
      height: active ? 52 : 44,
      shape: LiquidRoundedRectangle(borderRadius: radius),
      useOwnLayer: true,
      settings: LiquidGlassSettings(
        glassColor: active ? colors.primary : colors.surfaceContainer,
        blur: 2,
        thickness: 4,
        lightIntensity: 0,
        glowIntensity: 0,
        shadowElevation: 0,
      ),
      child: IconButton(
        tooltip: tooltip,
        style: IconButton.styleFrom(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(radius),
          ),
          foregroundColor: active ? colors.onPrimary : colors.onSurfaceVariant,
        ),
        onPressed: action,
        icon: busy
            ? const SizedBox.square(
                dimension: 17,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Icon(icon, size: 21),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final engine = widget.engine;
    final colors = Theme.of(context).colorScheme;
    final error = engine.error;
    final accent = engine.interrupted
        ? const Color(0xff9a664a)
        : colors.primary;
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    return TickerMode(
      enabled: !reduceMotion,
      child: Column(
        children: [
          const SizedBox(
            height: voiceTitleBarHeight,
            child: Center(child: SageBrand(size: 16)),
          ),
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                LayoutBuilder(
                  builder: (context, constraints) => Center(
                    child: SizedBox(
                      width: math.min(680, constraints.maxWidth * .78),
                      height: math.min(650, constraints.maxHeight * .90),
                      child: RepaintBoundary(
                        child: CustomPaint(
                          painter: VoiceField(
                            animation,
                            engine.state,
                            engine.level,
                            reduceMotion,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                if (engine.transcript.isNotEmpty)
                  Positioned(
                    left: 48,
                    right: 48,
                    bottom: 8,
                    child: Text(
                      engine.transcript,
                      textAlign: TextAlign.center,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: colors.onSurface, fontSize: 18),
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 48),
            child: Semantics(
              liveRegion: true,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    error != null
                        ? Icons.error_outline_rounded
                        : engine.interrupted
                        ? Icons.pause_rounded
                        : engine.state == VoiceState.speaking
                        ? Icons.graphic_eq_rounded
                        : Icons.radio_button_checked,
                    size: 16,
                    color: error == null ? accent : colors.error,
                  ),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      voiceMessage(context, error ?? engine.status),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: error == null ? accent : colors.onSurfaceVariant,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(26, 14, 26, 22),
            child: Stack(
              alignment: Alignment.center,
              children: [
                Align(
                  alignment: Alignment.centerLeft,
                  child: control(
                    context,
                    context.tr('设置', 'Settings'),
                    Icons.settings_outlined,
                    engine.editingSettings ? widget.onSettings : null,
                  ),
                ),
                control(
                  context,
                  !engine.connected
                      ? context.tr('重新连接', 'Reconnect')
                      : engine.active
                      ? context.tr('结束语音', 'End voice')
                      : context.tr('开始聆听', 'Start listening'),
                  !engine.connected ? Icons.refresh : Icons.mic_none_rounded,
                  engine.busy ? null : widget.onToggle,
                  active: engine.active,
                  busy: engine.busy,
                ),
                Align(
                  alignment: Alignment.centerRight,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (engine.conversation.isNotEmpty) ...[
                        control(
                          context,
                          context.tr('新对话', 'New conversation'),
                          Icons.add,
                          engine.busy ? null : widget.onNew,
                        ),
                        const SizedBox(width: 10),
                      ],
                      control(
                        context,
                        context.tr('切换至工作台', 'Open workbench'),
                        Icons.grid_view_rounded,
                        widget.onWorkbench,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class VoiceField extends CustomPainter {
  VoiceField(this.clock, this.state, this.level, this.reduceMotion)
    : super(repaint: reduceMotion ? null : clock);

  final Animation<double> clock;
  final VoiceState state;
  final double level;
  final bool reduceMotion;

  static const palette = [
    Color(0xff4381ff),
    Color(0xff4fc9ff),
    Color(0xff7e63ff),
    Color(0xffffbf5c),
    Color(0xffff70a6),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final phase = reduceMotion ? 1.0 : clock.value * 2 * math.pi;
    final syllable =
        .52 + .26 * math.sin(phase * 29) + .16 * math.cos(phase * 47);
    final energy = switch (state) {
      VoiceState.speaking => .10 + syllable * .64,
      VoiceState.listening => .08 + (level * 4).clamp(0.0, .56),
      VoiceState.thinking || VoiceState.transcribing => .19,
      _ => .09,
    };
    final center = size.center(
      Offset(4 * math.sin(phase), 3 * math.cos(phase)),
    );
    final aura = Rect.fromCenter(
      center: center,
      width: size.width * .95,
      height: size.height,
    );
    canvas.drawOval(
      aura,
      Paint()
        ..shader = const RadialGradient(
          colors: [Color(0x1a63b2ff), Color(0x0d9174ff), Color(0x009174ff)],
          stops: [0, .48, 1],
        ).createShader(aura),
    );

    final cell = size.width < 520 ? 11.0 : 13.0;
    final radiusX = size.width * (.29 + energy * .09);
    final radiusY = size.height * (.31 + energy * .08);
    final paint = Paint();
    for (var row = 0; row < size.height / cell; row++) {
      for (var column = 0; column < size.width / cell; column++) {
        final x = (column * cell - center.dx) / radiusX;
        final y = (row * cell - center.dy) / radiusY;
        final u = x + .10 * math.sin(y * 2.7 + phase * 5);
        final v = y + .085 * math.cos(x * 2.4 - phase * 4);
        final distance = math.sqrt(u * u + v * v);
        final angle = math.atan2(v, u);
        final field = math.exp(-distance * distance * 2.25);
        final wave = math.sin(distance * 9.2 - phase * 8 + angle * 2.7);
        final grain = math.sin(column * 19.41 + row * 37.11);
        final orbit = distance - 1.04 - .08 * math.sin(angle * 3 - phase * 2);
        final halo =
            math.exp(-orbit * orbit * 52) *
            (.08 + .14 * math.pow(math.sin(angle * 3 + phase * 5), 2));
        final presence = field * (.66 + wave * .22 + grain * .14) + halo;
        if (presence < .105) continue;

        final hue =
            ((angle / (2 * math.pi) + distance * .19 + phase / math.pi) % 1) *
            palette.length;
        final index = hue.floor();
        paint.color = Color.lerp(
          palette[index],
          palette[(index + 1) % palette.length],
          hue - index,
        )!.withValues(alpha: (presence * (.65 + energy * .55)).clamp(0.0, .83));
        final width = (cell - 3.4) * (.84 + presence * .13 + grain * .07);
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(
              center: Offset(
                column * cell + 1.2 * math.sin(phase * 5 + row * .16),
                row * cell + 1.2 * math.cos(phase * 4 + column * .14),
              ),
              width: width,
              height: width,
            ),
            const Radius.circular(2),
          ),
          paint,
        );
      }
    }
  }

  @override
  bool shouldRepaint(VoiceField oldDelegate) =>
      state != oldDelegate.state ||
      level != oldDelegate.level ||
      reduceMotion != oldDelegate.reduceMotion;
}
