part of '../workspace_screen.dart';

class _ConversationReplay extends StatefulWidget {
  const _ConversationReplay({
    required this.source,
    required this.controller,
    required this.onFrame,
    required this.onClose,
  });

  final Conversation source;
  final WorkspaceController controller;
  final ValueChanged<ReplayHtmlFrame?> onFrame;
  final VoidCallback onClose;

  @override
  State<_ConversationReplay> createState() => _ConversationReplayState();
}

typedef _ReplayEvent = ({
  DateTime at,
  bool immediate,
  void Function(Conversation) show,
});

class _ConversationReplayState extends State<_ConversationReplay> {
  static const _speeds = [1, 2, 4, 8];
  late final List<_ReplayEvent> _events = _buildEvents();
  late final Conversation _playback = Conversation(
    id: 'replay:${widget.source.id}',
  );
  final _wait = Stopwatch();
  Timer? _timer;
  double _remainingMs = 0;
  int _index = 0;
  int _speedIndex = 1;
  ReplayHtmlFrame? _frame;

  @override
  void initState() {
    super.initState();
    _advance();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onFrame(_frame);
    });
  }

  List<_ReplayEvent> _buildEvents() {
    final events = <_ReplayEvent>[];
    void add(
      DateTime at,
      void Function(Conversation) show, {
      bool immediate = false,
    }) {
      events.add((at: at, immediate: immediate, show: show));
    }

    for (final original in widget.source.messages) {
      final saved = original.toJson();
      add(original.createdAt, (chat) {
        chat.messages.add(ChatMessage.fromJson(saved));
      }, immediate: original.role == 'user');
    }
    for (final original in widget.source.processPanels) {
      final panel = RuntimeProcessPanel(
        id: original.id,
        anchorMessageId: original.anchorMessageId,
        startedAt: original.startedAt,
      );
      add(original.startedAt, (chat) {
        panel.activities.clear();
        panel.running = true;
        panel.completedAt = null;
        panel.failed = false;
        panel.failureMessage = '';
        chat.processPanels.add(panel);
      });
      for (final original in original.activities) {
        final saved = original.toJson();
        late RuntimeActivity activity;
        add(original.startedAt, (_) {
          activity = RuntimeActivity.fromJson({
            ...saved,
            'active': true,
            'failed': false,
            'result': '',
            'completed_at': null,
          });
          panel.activities.add(activity);
        });
        final completedAt = original.completedAt;
        if (completedAt != null) {
          add(completedAt, (_) {
            activity.active = false;
            activity.failed = saved['failed'] == true;
            activity.result = saved['result']?.toString() ?? '';
            activity.completedAt = completedAt;
          });
        }
      }
      final completedAt = original.completedAt;
      if (completedAt != null) {
        final failed = original.failed;
        final message = original.failureMessage;
        add(completedAt, (_) {
          panel.running = false;
          panel.completedAt = completedAt;
          panel.failed = failed;
          panel.failureMessage = message;
        });
      }
    }
    for (final frame in widget.source.replayHtml) {
      add(frame.at, (_) => _frame = frame);
    }
    // Preserve insertion order for events with identical timestamps.
    final ordered = events.indexed.toList()
      ..sort((a, b) {
        final order = a.$2.at.compareTo(b.$2.at);
        return order == 0 ? a.$1.compareTo(b.$1) : order;
      });
    return ordered.map((entry) => entry.$2).toList();
  }

  void _advance() {
    while (_index < _events.length) {
      final event = _events[_index];
      if (_index > 0 && !event.immediate) {
        final gap = event.at.difference(_events[_index - 1].at).inMilliseconds;
        if (gap > 0) {
          _remainingMs = gap.toDouble();
          _schedule();
          return;
        }
      }
      event.show(_playback);
      _index++;
    }
  }

  void _schedule() {
    _wait
      ..reset()
      ..start();
    _timer = Timer(
      Duration(milliseconds: (_remainingMs / _speeds[_speedIndex]).ceil()),
      () {
        _wait.stop();
        setState(() {
          _events[_index++].show(_playback);
          _advance();
        });
        widget.onFrame(_frame);
      },
    );
  }

  double get _unplayedMs => max(
    0.0,
    _remainingMs - _wait.elapsedMicroseconds / 1000 * _speeds[_speedIndex],
  );

  DateTime _replayNow() {
    if (_index == _events.length) return _events.last.at;
    return _events[_index].at.subtract(
      Duration(microseconds: (_unplayedMs * 1000).round()),
    );
  }

  void _setSpeed(int index) {
    if (index == _speedIndex) return;
    final pending = _timer?.isActive ?? false;
    if (pending) {
      _timer?.cancel();
      _remainingMs = _unplayedMs;
    }
    setState(() => _speedIndex = index);
    if (pending) _schedule();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _wait.stop();
    final clearFrame = widget.onFrame;
    WidgetsBinding.instance.addPostFrameCallback((_) => clearFrame(null));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return Column(
      key: const ValueKey('inline-conversation-replay'),
      children: [
        Expanded(
          child: _MessageList(
            key: ObjectKey(_playback),
            controller: widget.controller,
            conversation: _playback,
            readOnly: true,
            replayNow: _replayNow,
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          child: Wrap(
            alignment: WrapAlignment.center,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            runSpacing: 8,
            children: [
              Semantics(
                label: l10n.text('workspace.replaySpeed'),
                child: SizedBox(
                  width: 184,
                  child: GlassSegmentedControl(
                    height: 30,
                    segments: [
                      for (final speed in _speeds)
                        GlassSegment(label: '$speed×'),
                    ],
                    selectedIndex: _speedIndex,
                    onSegmentSelected: _setSpeed,
                  ),
                ),
              ),
              TextButton.icon(
                onPressed: widget.onClose,
                icon: const Icon(CupertinoIcons.xmark, size: 13),
                label: Text(l10n.text('workspace.closeReplay')),
                style: TextButton.styleFrom(
                  foregroundColor: Theme.of(
                    context,
                  ).colorScheme.onSurfaceVariant,
                  minimumSize: const Size(0, 30),
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(6),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

Widget _replayFilePreview(ReplayHtmlFrame frame) {
  final bytes = utf8.encode(frame.source);
  return WorkspaceFilePreview(
    key: ValueKey('replay:${frame.path}'),
    node: WorkspaceFileNode(
      name: frame.path.split('/').last,
      path: frame.path,
      isDirectory: false,
      size: bytes.length,
    ),
    content: WorkspaceFileContent(bytes: bytes, mediaType: 'text/html'),
    onReferenceSelection: (_) {},
  );
}
