import 'package:flutter/material.dart';

import 'brand.dart';
import 'voice_engine.dart';

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
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 14, 16, 10),
          child: Row(
            children: [
              const SageBrand(),
              const Spacer(),
              action(
                '新对话',
                Icons.add,
                engine.connected && !engine.busy ? widget.onNew : null,
              ),
              action('语音界面', Icons.mic_none, widget.onVoice),
              action(
                '监控',
                Icons.tune,
                () => setState(() => monitor = !monitor),
                selected: monitor,
              ),
              action(
                '配置',
                Icons.settings_outlined,
                engine.editingSettings ? widget.onSettings : null,
              ),
              IconButton(
                tooltip: widget.dark ? '浅色模式' : '深色模式',
                onPressed: widget.onToggleTheme,
                icon: Icon(
                  widget.dark
                      ? Icons.light_mode_outlined
                      : Icons.dark_mode_outlined,
                  size: 18,
                ),
              ),
              const SizedBox(width: 6),
              FilledButton(
                onPressed: engine.busy ? null : widget.onToggle,
                child: Text(
                  !engine.connected
                      ? '重新连接'
                      : engine.active
                      ? '结束语音'
                      : '开始语音',
                ),
              ),
            ],
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
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              border: Border.all(color: colors.outlineVariant),
                              borderRadius: BorderRadius.circular(18),
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
                                          engine.error ?? engine.status,
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
                                          child: const Text('打断'),
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
                                                ? '输入消息…'
                                                : '请先开始语音',
                                          ),
                                        ),
                                      ),
                                      IconButton.filled(
                                        tooltip: '发送',
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
          title: const Text('运行事件'),
          trailing: Icon(events ? Icons.expand_more : Icons.expand_less),
          onTap: () => setState(() => events = !events),
        ),
        if (events)
          SizedBox(
            height: 124,
            child: engine.events.isEmpty
                ? const Center(child: Text('暂无运行事件'))
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
                          '$time   ${event.message}',
                          style: const TextStyle(fontSize: 12),
                        ),
                      );
                    },
                  ),
          ),
      ],
    );
  }

  Widget action(
    String label,
    IconData icon,
    VoidCallback? press, {
    bool selected = false,
  }) => TextButton.icon(
    onPressed: press,
    style: TextButton.styleFrom(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      backgroundColor: selected
          ? Theme.of(context).colorScheme.secondaryContainer
          : null,
    ),
    icon: Icon(icon, size: 16),
    label: Text(label),
  );

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
              engine.canSubmit ? '可以开始了' : '语音尚未开启',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 5),
            Text(
              engine.canSubmit ? '直接说话，或在下方输入消息。' : '点击右上角开始语音后查看实时对话。',
              style: TextStyle(color: colors.onSurfaceVariant, fontSize: 12),
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
      Text('监控', style: Theme.of(context).textTheme.titleSmall),
      const SizedBox(height: 20),
      const Text('麦克风输入'),
      const SizedBox(height: 8),
      LinearProgressIndicator(value: (engine.level * 5).clamp(0.0, 1.0)),
      const SizedBox(height: 22),
      for (final entry in {
        'vad': '停顿确认',
        'turn_detection': '发言结束判断',
        'asr': '识别收尾',
        'agent': 'Agent 首段输出',
        'tts': '合成首段音频',
        'playback': engine.metrics['progress_cue'] == true
            ? '停说到首声（含提示）'
            : '停说到首段播放',
        'turn': '回合总耗时',
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
