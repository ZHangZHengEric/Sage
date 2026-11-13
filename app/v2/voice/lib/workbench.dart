import 'package:flutter/material.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';

import 'brand.dart';
import 'voice_engine.dart';
import 'voice_glass.dart';
import 'voice_locale.dart';

class VoiceWorkbench extends StatefulWidget {
  const VoiceWorkbench({
    super.key,
    required this.engine,
    required this.dark,
    required this.onToggleTheme,
    required this.onVoice,
    required this.onToggle,
    required this.onSettings,
    required this.onNew,
  });

  final VoiceEngine engine;
  final bool dark;
  final VoidCallback onToggleTheme;
  final VoidCallback onVoice;
  final VoidCallback onToggle;
  final VoidCallback onSettings;
  final VoidCallback onNew;

  @override
  State<VoiceWorkbench> createState() => _VoiceWorkbenchState();
}

class _VoiceWorkbenchState extends State<VoiceWorkbench> {
  final composer = TextEditingController();
  bool monitor = false;
  bool events = false;
  bool submitting = false;

  VoiceEngine get engine => widget.engine;

  @override
  void dispose() {
    composer.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    final message = composer.text;
    if (submitting || message.trim().isEmpty) return;
    setState(() => submitting = true);
    final sent = await engine.submitText(message);
    if (!mounted) return;
    if (sent && composer.text == message) composer.clear();
    setState(() => submitting = false);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        SizedBox(
          height: 46,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(88, 0, 16, 0),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final showLabels = constraints.maxWidth >= 800;
                return Row(
                  children: [
                    const SageBrand(size: 16),
                    const Spacer(),
                    VoiceGlassButton(
                      tooltip: context.tr('新对话', 'New conversation'),
                      label: showLabels
                          ? context.tr('新对话', 'New conversation')
                          : null,
                      icon: Icons.add_rounded,
                      onPressed: engine.connected && !engine.busy
                          ? widget.onNew
                          : null,
                    ),
                    const SizedBox(width: 6),
                    VoiceGlassButton(
                      tooltip: context.tr('语音界面', 'Voice view'),
                      label: showLabels
                          ? context.tr('语音界面', 'Voice view')
                          : null,
                      icon: Icons.graphic_eq_rounded,
                      onPressed: widget.onVoice,
                    ),
                    const SizedBox(width: 6),
                    VoiceGlassButton(
                      tooltip: context.tr('监控', 'Monitor'),
                      label: showLabels ? context.tr('监控', 'Monitor') : null,
                      icon: Icons.tune_rounded,
                      selected: monitor,
                      onPressed: () => setState(() => monitor = !monitor),
                    ),
                    const SizedBox(width: 6),
                    VoiceGlassButton(
                      tooltip: context.tr('配置', 'Settings'),
                      label: showLabels ? context.tr('配置', 'Settings') : null,
                      icon: Icons.settings_outlined,
                      onPressed: engine.editingSettings
                          ? widget.onSettings
                          : null,
                    ),
                    const SizedBox(width: 6),
                    VoiceGlassButton(
                      tooltip: widget.dark
                          ? context.tr('浅色模式', 'Light mode')
                          : context.tr('深色模式', 'Dark mode'),
                      icon: widget.dark
                          ? Icons.light_mode_outlined
                          : Icons.dark_mode_outlined,
                      onPressed: widget.onToggleTheme,
                    ),
                    const SizedBox(width: 12),
                    VoiceGlassButton(
                      primary: true,
                      icon: engine.connected
                          ? (engine.active
                                ? Icons.stop_rounded
                                : Icons.mic_none_rounded)
                          : Icons.refresh_rounded,
                      onPressed: engine.busy ? null : widget.onToggle,
                      label: !engine.connected
                          ? context.tr('重新连接', 'Reconnect')
                          : engine.active
                          ? context.tr('结束语音', 'End voice')
                          : context.tr('开始语音', 'Start voice'),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: Row(
            children: [
              Expanded(
                child: Column(
                  children: [
                    Expanded(child: conversation(context)),
                    Align(
                      alignment: Alignment.bottomCenter,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 752),
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 18),
                          child: GlassContainer(
                            shape: const LiquidRoundedRectangle(
                              borderRadius: 16,
                            ),
                            useOwnLayer: true,
                            settings: LiquidGlassSettings(
                              glassColor: colors.surfaceContainerLow,
                              blur: 3,
                              thickness: 4,
                              standardOpacityMultiplier: 1,
                            ),
                            child: Padding(
                              padding: const EdgeInsets.fromLTRB(14, 10, 10, 8),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Icon(
                                        Icons.graphic_eq_rounded,
                                        size: 17,
                                        color: colors.primary,
                                      ),
                                      const SizedBox(width: 7),
                                      Expanded(
                                        child: Text(
                                          voiceMessage(
                                            context,
                                            engine.error ?? engine.status,
                                          ),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            fontSize: 12,
                                            color: engine.error == null
                                                ? colors.onSurfaceVariant
                                                : colors.error,
                                          ),
                                        ),
                                      ),
                                      if (engine.canInterrupt)
                                        TextButton(
                                          onPressed: engine.interrupt,
                                          child: Text(
                                            context.tr('打断', 'Interrupt'),
                                          ),
                                        ),
                                    ],
                                  ),
                                  Row(
                                    children: [
                                      Expanded(
                                        child: TextField(
                                          controller: composer,
                                          enabled:
                                              engine.canSubmit && !submitting,
                                          onSubmitted: (_) => submit(),
                                          decoration: InputDecoration(
                                            border: InputBorder.none,
                                            enabledBorder: InputBorder.none,
                                            disabledBorder: InputBorder.none,
                                            focusedBorder: InputBorder.none,
                                            hintText: engine.canSubmit
                                                ? context.tr(
                                                    '输入消息…',
                                                    'Type a message…',
                                                  )
                                                : context.tr(
                                                    '请先开始语音',
                                                    'Start voice to send a message',
                                                  ),
                                          ),
                                        ),
                                      ),
                                      IconButton.filled(
                                        tooltip: context.tr('发送', 'Send'),
                                        onPressed:
                                            engine.canSubmit && !submitting
                                            ? submit
                                            : null,
                                        icon: const Icon(
                                          Icons.arrow_upward,
                                          size: 18,
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
                    ),
                  ],
                ),
              ),
              if (monitor) ...[
                const VerticalDivider(width: 1),
                SizedBox(width: 250, child: monitorPanel(context)),
              ],
            ],
          ),
        ),
        const Divider(height: 1),
        ListTile(
          dense: true,
          title: Text(context.tr('运行事件', 'Runtime events')),
          trailing: Icon(
            events ? Icons.expand_more : Icons.expand_less,
            size: 18,
          ),
          onTap: () => setState(() => events = !events),
        ),
        if (events)
          SizedBox(
            height: 124,
            child: engine.events.isEmpty
                ? Center(child: Text(context.tr('暂无运行事件', 'No runtime events')))
                : ListView.builder(
                    reverse: true,
                    itemCount: engine.events.length,
                    itemBuilder: (context, index) {
                      final event =
                          engine.events[engine.events.length - index - 1];
                      final time = TimeOfDay.fromDateTime(
                        event.time,
                      ).format(context);
                      return Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 20,
                          vertical: 3,
                        ),
                        child: Text(
                          '$time   ${voiceMessage(context, event.message)}',
                          style: const TextStyle(fontSize: 12),
                        ),
                      );
                    },
                  ),
          ),
      ],
    );
  }

  Widget conversation(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    if (engine.conversation.isEmpty && engine.transcript.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset(sageLogoAsset, width: 44, height: 44),
            const SizedBox(height: 12),
            Text(
              engine.canSubmit
                  ? context.tr('可以开始了', 'Ready')
                  : context.tr('语音尚未开启', 'Voice is off'),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ],
        ),
      );
    }
    final live =
        engine.transcript.isNotEmpty &&
        (engine.state == VoiceState.listening ||
            engine.state == VoiceState.transcribing);
    return ListView.builder(
      reverse: true,
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 16),
      itemCount: engine.conversation.length + (live ? 1 : 0),
      itemBuilder: (context, index) {
        final pending = live && index == 0;
        final item = pending
            ? (user: true, text: engine.transcript)
            : engine.conversation[engine.conversation.length -
                  index -
                  (live ? 0 : 1)];
        return Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: LayoutBuilder(
              builder: (context, constraints) => Align(
                alignment: item.user
                    ? Alignment.centerRight
                    : Alignment.centerLeft,
                child: Container(
                  constraints: BoxConstraints(
                    maxWidth: constraints.maxWidth * .82,
                  ),
                  margin: const EdgeInsets.symmetric(vertical: 7),
                  padding: item.user
                      ? const EdgeInsets.symmetric(horizontal: 13, vertical: 9)
                      : EdgeInsets.zero,
                  decoration: item.user
                      ? BoxDecoration(
                          color: pending
                              ? colors.primary.withValues(alpha: .67)
                              : colors.primary,
                          borderRadius: const BorderRadius.only(
                            topLeft: Radius.circular(15),
                            topRight: Radius.circular(15),
                            bottomLeft: Radius.circular(15),
                            bottomRight: Radius.circular(5),
                          ),
                        )
                      : null,
                  child: SelectableText(
                    item.text,
                    style: TextStyle(
                      color: item.user ? colors.onPrimary : colors.onSurface,
                      height: 1.5,
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget monitorPanel(BuildContext context) => ListView(
    padding: const EdgeInsets.all(18),
    children: [
      Text(
        context.tr('监控', 'Monitor'),
        style: Theme.of(context).textTheme.titleSmall,
      ),
      const SizedBox(height: 20),
      Text(context.tr('麦克风输入', 'Microphone input')),
      const SizedBox(height: 8),
      LinearProgressIndicator(value: (engine.level * 5).clamp(0.0, 1.0)),
      const SizedBox(height: 22),
      for (final entry in {
        'vad': context.tr('停顿确认', 'Pause confirmation'),
        'turn_detection': context.tr('发言结束判断', 'End-of-turn detection'),
        'asr': context.tr('识别收尾', 'Transcription finalization'),
        'agent': context.tr('Agent 首段输出', 'First agent output'),
        'tts': context.tr('合成首段音频', 'First synthesized audio'),
        'playback': engine.metrics['progress_cue'] == true
            ? context.tr(
                '停说到首声（含提示）',
                'End of speech to first audio (with cue)',
              )
            : context.tr('停说到首段播放', 'End of speech to playback'),
        'turn': context.tr('回合总耗时', 'Total turn time'),
      }.entries)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(
                child: Text(entry.value, style: const TextStyle(fontSize: 12)),
              ),
              Text(switch (engine.metrics[entry.key]) {
                final num value => '${value.round()} ms',
                _ => '—',
              }, style: const TextStyle(fontSize: 12)),
            ],
          ),
        ),
    ],
  );
}
