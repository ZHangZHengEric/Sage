part of '../workspace_screen.dart';

class _ProcessPanel extends StatefulWidget {
  const _ProcessPanel({
    required this.panel,
    required this.messages,
    this.subSessions = const [],
    this.forceCollapsed = false,
    super.key,
  });

  final RuntimeProcessPanel panel;
  final List<ChatMessage> messages;
  final List<Conversation> subSessions;
  final bool forceCollapsed;

  @override
  State<_ProcessPanel> createState() => _ProcessPanelState();
}

class _ProcessPanelState extends State<_ProcessPanel> {
  late bool _expanded;
  late bool _wasRunning;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _expanded = widget.panel.running && !widget.forceCollapsed;
    _wasRunning = widget.panel.running;
    _syncTimer();
  }

  @override
  void didUpdateWidget(covariant _ProcessPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.forceCollapsed || (_wasRunning && !widget.panel.running)) {
      _expanded = false;
    }
    _wasRunning = widget.panel.running;
    _syncTimer();
  }

  void _syncTimer() {
    if (!widget.panel.running) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    _timer ??= Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final panel = widget.panel;
    final colors = Theme.of(context).colorScheme;
    final elapsed = (panel.completedAt ?? DateTime.now()).difference(
      panel.startedAt,
    );
    final items = _orderedProcessItems(panel, widget.messages);
    final childSessionIds = {
      for (final value in widget.subSessions) value.sessionId,
    };
    final rootSubSessions = [
      for (final value in widget.subSessions)
        if (!childSessionIds.contains(value.parentSessionId)) value,
    ];
    final unlinkedRootSubSessions = _unlinkedSubSessions(
      items,
      rootSubSessions,
    );
    return Center(
      child: ConstrainedBox(
        key: const ValueKey('process-panel'),
        constraints: const BoxConstraints(maxWidth: 760),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              button: true,
              expanded: _expanded,
              label: context.l10n.text(
                panel.running ? 'workspace.processing' : 'workspace.processed',
              ),
              child: InkWell(
                key: const ValueKey('process-panel-toggle'),
                borderRadius: BorderRadius.circular(8),
                onTap: () => setState(() => _expanded = !_expanded),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      if (panel.running) ...[
                        SizedBox.square(
                          dimension: 15,
                          child: CupertinoActivityIndicator(
                            color: colors.primary,
                          ),
                        ),
                        const SizedBox(width: 8),
                      ],
                      Text(
                        panel.running
                            ? context.l10n.text('workspace.processing')
                            : context.l10n.text('workspace.processedTime', {
                                'time': _elapsedLabel(elapsed),
                              }),
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: colors.onSurfaceVariant.withValues(
                            alpha: 0.86,
                          ),
                        ),
                      ),
                      if (panel.running) ...[
                        const SizedBox(width: 5),
                        Text(
                          _elapsedLabel(elapsed),
                          style: Theme.of(context).textTheme.labelMedium
                              ?.copyWith(
                                fontSize: 11.5,
                                color: colors.onSurfaceVariant,
                              ),
                        ),
                      ],
                      const Spacer(),
                      Icon(
                        _expanded
                            ? CupertinoIcons.chevron_up
                            : CupertinoIcons.chevron_right,
                        size: 14,
                        color: colors.onSurfaceVariant,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Divider(
              height: 1,
              color: colors.outlineVariant.withValues(alpha: 0.36),
            ),
            if (_expanded && items.isNotEmpty) ...[
              const SizedBox(height: 12),
              _ProcessStreamLog(
                items: items,
                subSessions: rootSubSessions,
                allSubSessions: widget.subSessions,
              ),
            ],
            if (_expanded && unlinkedRootSubSessions.isNotEmpty) ...[
              if (items.isNotEmpty) const SizedBox(height: 10),
              for (final child in unlinkedRootSubSessions) ...[
                _SubSessionProcessGroup(
                  conversation: child,
                  allSubSessions: widget.subSessions,
                ),
                if (child != unlinkedRootSubSessions.last)
                  const SizedBox(height: 8),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

sealed class _ProcessStreamItem {
  const _ProcessStreamItem({
    required this.sequence,
    required this.createdAt,
    required this.sourceIndex,
  });

  final int sequence;
  final DateTime createdAt;
  final int sourceIndex;
}

class _ProcessActivityItem extends _ProcessStreamItem {
  _ProcessActivityItem({required this.activity, required super.sourceIndex})
    : super(sequence: activity.sequence, createdAt: activity.startedAt);

  final RuntimeActivity activity;
}

class _ProcessMessageItem extends _ProcessStreamItem {
  _ProcessMessageItem({required this.message, required super.sourceIndex})
    : super(sequence: message.sequence, createdAt: message.createdAt);

  final ChatMessage message;
}

List<_ProcessStreamItem> _orderedProcessItems(
  RuntimeProcessPanel panel,
  List<ChatMessage> messages,
) {
  var sourceIndex = 0;
  final items = <_ProcessStreamItem>[
    for (final activity in panel.activities)
      _ProcessActivityItem(activity: activity, sourceIndex: sourceIndex++),
    for (final message in messages)
      _ProcessMessageItem(message: message, sourceIndex: sourceIndex++),
  ];
  items.sort((left, right) {
    if (left.sequence > 0 && right.sequence > 0) {
      final bySequence = left.sequence.compareTo(right.sequence);
      if (bySequence != 0) return bySequence;
    }
    final byTime = left.createdAt.compareTo(right.createdAt);
    if (byTime != 0) return byTime;
    return left.sourceIndex.compareTo(right.sourceIndex);
  });
  return items;
}

class _ProcessStreamLog extends StatelessWidget {
  const _ProcessStreamLog({
    required this.items,
    this.subSessions = const [],
    this.allSubSessions = const [],
  });

  final List<_ProcessStreamItem> items;
  final List<Conversation> subSessions;
  final List<Conversation> allSubSessions;

  @override
  Widget build(BuildContext context) {
    final anchoredActivityIds = {
      for (final child in subSessions)
        if ((child.parentToolCallId ?? '').isNotEmpty) child.parentToolCallId!,
    };
    final entries = _processStreamEntries(
      items,
      separateActivityIds: anchoredActivityIds,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var index = 0; index < entries.length; index++) ...[
          entries[index].build(context),
          for (final child in subSessions.where(
            (value) =>
                (value.parentToolCallId ?? '').isNotEmpty &&
                entries[index].containsActivity(value.parentToolCallId!),
          )) ...[
            const SizedBox(height: 8),
            _SubSessionProcessGroup(
              conversation: child,
              allSubSessions: allSubSessions,
            ),
          ],
          if (index != entries.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

List<_ProcessStreamEntry> _processStreamEntries(
  List<_ProcessStreamItem> items, {
  Set<String> separateActivityIds = const {},
}) {
  final entries = <_ProcessStreamEntry>[];
  var pendingActivities = <RuntimeActivity>[];

  void flushActivities() {
    if (pendingActivities.isEmpty) return;
    if (pendingActivities.length == 1) {
      entries.add(_SingleProcessActivityEntry(pendingActivities.single));
    } else {
      entries.add(_GroupedProcessActivityEntry(List.of(pendingActivities)));
    }
    pendingActivities = <RuntimeActivity>[];
  }

  for (final item in items) {
    if (item is _ProcessActivityItem) {
      if (separateActivityIds.contains(item.activity.id)) {
        flushActivities();
        entries.add(_SingleProcessActivityEntry(item.activity));
        continue;
      }
      if (pendingActivities.isNotEmpty &&
          _activityCategory(pendingActivities.first) !=
              _activityCategory(item.activity)) {
        flushActivities();
      }
      pendingActivities.add(item.activity);
      continue;
    }
    final message = (item as _ProcessMessageItem).message;
    if (message.text.trim().isEmpty) continue;
    flushActivities();
    entries.add(_ProcessMessageEntry(message));
  }
  flushActivities();
  return entries;
}

sealed class _ProcessStreamEntry {
  bool containsActivity(String activityId) => false;

  Widget build(BuildContext context);
}

class _SingleProcessActivityEntry extends _ProcessStreamEntry {
  _SingleProcessActivityEntry(this.activity);

  final RuntimeActivity activity;

  @override
  bool containsActivity(String activityId) => activity.id == activityId;

  @override
  Widget build(BuildContext context) => _ProcessActivityLine(
    key: ValueKey('process-activity:${activity.id}'),
    activity: activity,
  );
}

class _GroupedProcessActivityEntry extends _ProcessStreamEntry {
  _GroupedProcessActivityEntry(this.activities);

  final List<RuntimeActivity> activities;

  @override
  bool containsActivity(String activityId) =>
      activities.any((activity) => activity.id == activityId);

  @override
  Widget build(BuildContext context) => _ProcessActivityGroup(
    key: ValueKey('process-operation-group:${activities.first.id}'),
    activities: activities,
  );
}

class _ProcessMessageEntry extends _ProcessStreamEntry {
  _ProcessMessageEntry(this.message);

  final ChatMessage message;

  @override
  Widget build(BuildContext context) => SizedBox(
    key: ValueKey('process-message:${message.id}'),
    width: double.infinity,
    child: _ConversationMarkdown(
      data:
          _messageDisplayText(context, message) +
          (message.streaming ? '\n\n▍' : ''),
    ),
  );
}

String _messageDisplayText(BuildContext context, ChatMessage message) {
  final media = MediaQuery.maybeOf(context);
  final animationsDisabled =
      (media?.disableAnimations ?? false) ||
      (media?.accessibleNavigation ?? false);
  return animationsDisabled ? message.text : message.renderedText;
}

class _ProcessActivityGroup extends StatefulWidget {
  const _ProcessActivityGroup({required this.activities, super.key});

  final List<RuntimeActivity> activities;

  @override
  State<_ProcessActivityGroup> createState() => _ProcessActivityGroupState();
}

class _ProcessActivityGroupState extends State<_ProcessActivityGroup> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final running = widget.activities.any((activity) => activity.active);
    final title = _processSummary(context, widget.activities);
    return Semantics(
      button: true,
      expanded: _expanded,
      label: title,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            borderRadius: BorderRadius.circular(7),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  _ProcessActivityIcon(
                    icon: _processGroupIcon(widget.activities),
                    running: running,
                    failed: widget.activities.any(
                      (activity) => activity.failed,
                    ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: _processTextStyle(
                        context,
                      )?.copyWith(fontWeight: FontWeight.w600),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Icon(
                    _expanded
                        ? CupertinoIcons.chevron_up
                        : CupertinoIcons.chevron_right,
                    size: 13,
                    color: colors.onSurfaceVariant.withValues(alpha: 0.7),
                  ),
                ],
              ),
            ),
          ),
          if (_expanded) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.only(left: 25),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (
                    var index = 0;
                    index < widget.activities.length;
                    index++
                  ) ...[
                    _ProcessActivityLine(
                      key: ValueKey(
                        'process-activity:${widget.activities[index].id}',
                      ),
                      activity: widget.activities[index],
                    ),
                    if (index != widget.activities.length - 1)
                      const SizedBox(height: 8),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SubSessionProcessGroup extends StatefulWidget {
  const _SubSessionProcessGroup({
    required this.conversation,
    required this.allSubSessions,
  });

  final Conversation conversation;
  final List<Conversation> allSubSessions;

  @override
  State<_SubSessionProcessGroup> createState() =>
      _SubSessionProcessGroupState();
}

class _SubSessionProcessGroupState extends State<_SubSessionProcessGroup> {
  late bool _expanded;

  bool get _active => {
    RunStatus.starting,
    RunStatus.running,
    RunStatus.suspending,
    RunStatus.suspended,
  }.contains(widget.conversation.status);

  @override
  void initState() {
    super.initState();
    _expanded = _active;
  }

  @override
  Widget build(BuildContext context) {
    final conversation = widget.conversation;
    final colors = Theme.of(context).colorScheme;
    final items = _subSessionProcessItems(conversation);
    final children = widget.allSubSessions
        .where((value) => value.parentSessionId == conversation.sessionId)
        .toList();
    final unlinkedChildren = _unlinkedSubSessions(items, children);
    final failed =
        conversation.status == RunStatus.failed ||
        conversation.status == RunStatus.cancelled;
    final waiting = conversation.pendingInteraction != null;
    return Container(
      key: ValueKey('sub-session-process:${conversation.sessionId}'),
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: 0.34),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            borderRadius: BorderRadius.circular(7),
            child: Row(
              children: [
                _ProcessActivityIcon(
                  icon: CupertinoIcons.person_2,
                  running: _active && !waiting,
                  failed: failed,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    conversation.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: _processTextStyle(context)?.copyWith(
                      color: waiting ? colors.tertiary : null,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (waiting) ...[
                  Icon(
                    CupertinoIcons.exclamationmark_circle_fill,
                    size: 13,
                    color: colors.tertiary,
                  ),
                  const SizedBox(width: 5),
                  Text(
                    '等待审批',
                    style: _processTextStyle(
                      context,
                    )?.copyWith(fontSize: 11.5, color: colors.tertiary),
                  ),
                ],
                const SizedBox(width: 7),
                Icon(
                  _expanded
                      ? CupertinoIcons.chevron_up
                      : CupertinoIcons.chevron_right,
                  size: 12,
                  color: colors.onSurfaceVariant,
                ),
              ],
            ),
          ),
          if (_expanded && (items.isNotEmpty || children.isNotEmpty)) ...[
            const SizedBox(height: 9),
            Padding(
              padding: const EdgeInsets.only(left: 23),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (items.isNotEmpty)
                    _ProcessStreamLog(
                      items: items,
                      subSessions: children,
                      allSubSessions: widget.allSubSessions,
                    ),
                  if (items.isNotEmpty && unlinkedChildren.isNotEmpty)
                    const SizedBox(height: 8),
                  for (
                    var index = 0;
                    index < unlinkedChildren.length;
                    index++
                  ) ...[
                    _SubSessionProcessGroup(
                      conversation: unlinkedChildren[index],
                      allSubSessions: widget.allSubSessions,
                    ),
                    if (index != unlinkedChildren.length - 1)
                      const SizedBox(height: 8),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

List<_ProcessStreamItem> _subSessionProcessItems(Conversation conversation) {
  var sourceIndex = 0;
  final items = <_ProcessStreamItem>[
    for (final panel in conversation.processPanels)
      for (final activity in panel.activities)
        _ProcessActivityItem(activity: activity, sourceIndex: sourceIndex++),
    for (final message in conversation.messages)
      if (message.role == 'assistant')
        _ProcessMessageItem(message: message, sourceIndex: sourceIndex++),
  ];
  items.sort((left, right) {
    if (left.sequence > 0 && right.sequence > 0) {
      final bySequence = left.sequence.compareTo(right.sequence);
      if (bySequence != 0) return bySequence;
    }
    final byTime = left.createdAt.compareTo(right.createdAt);
    if (byTime != 0) return byTime;
    return left.sourceIndex.compareTo(right.sourceIndex);
  });
  return items;
}

List<Conversation> _unlinkedSubSessions(
  List<_ProcessStreamItem> items,
  List<Conversation> subSessions,
) {
  final activityIds = {
    for (final item in items)
      if (item is _ProcessActivityItem) item.activity.id,
  };
  return [
    for (final child in subSessions)
      if ((child.parentToolCallId ?? '').isEmpty ||
          !activityIds.contains(child.parentToolCallId))
        child,
  ];
}

class _ProcessActivityIcon extends StatelessWidget {
  const _ProcessActivityIcon({
    required this.icon,
    required this.running,
    required this.failed,
  });

  final IconData icon;
  final bool running;
  final bool failed;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final color = failed
        ? colors.error
        : colors.onSurfaceVariant.withValues(alpha: 0.54);
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: SizedBox.square(
        dimension: 16,
        child: running
            ? CupertinoActivityIndicator(color: color, radius: 6)
            : Icon(
                failed ? CupertinoIcons.exclamationmark_circle : icon,
                size: 15,
                color: color,
              ),
      ),
    );
  }
}

class _ProcessActivityLine extends StatelessWidget {
  const _ProcessActivityLine({required this.activity, super.key});

  final RuntimeActivity activity;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final language = toolPresentationLanguage(context);
    final name = localizedToolName(activity.label, language);
    final arguments = toolArgumentPresentation(
      activity.label,
      activity.arguments,
      language,
    );
    final result = localizedToolResultSummary(activity.result, language);
    final titleColor = activity.failed
        ? colors.error
        : colors.onSurfaceVariant.withValues(alpha: dark ? 0.76 : 0.82);
    final detailColor = colors.onSurfaceVariant.withValues(
      alpha: dark ? 0.58 : 0.66,
    );
    final line = SizedBox(
      width: double.infinity,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ProcessActivityIcon(
            icon: _processGroupIcon([activity]),
            running: activity.active,
            failed: activity.failed,
          ),
          const SizedBox(width: 9),
          Expanded(
            child: _ToolActivityShimmer(
              enabled: activity.active,
              shimmerKey: ValueKey('tool-activity-shimmer:${activity.id}'),
              child: Text.rich(
                TextSpan(
                  children: [
                    TextSpan(
                      text: activity.failed
                          ? '$name · ${localizedToolFailure(language)}'
                          : name,
                      style: _processTextStyle(context)?.copyWith(
                        color: titleColor,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (arguments.primary.isNotEmpty)
                      TextSpan(
                        text: '  ${arguments.primary}',
                        style: _processTextStyle(context)?.copyWith(
                          color: detailColor,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    if (arguments.metadata.isNotEmpty)
                      TextSpan(
                        text: '  ·  ${arguments.metadata.join(' · ')}',
                        style: _processTextStyle(context)?.copyWith(
                          color: detailColor.withValues(alpha: 0.82),
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    if (result.isNotEmpty)
                      TextSpan(
                        text: '  ·  $result',
                        style: _processTextStyle(context)?.copyWith(
                          color: detailColor.withValues(alpha: 0.72),
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                  ],
                ),
                maxLines: 1,
                softWrap: false,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
        ],
      ),
    );
    final content = activity.arguments['content'];
    final isPlan =
        activity.label == 'goal_submit' || activity.label == 'plan_submit';
    if (!isPlan || content is! String || content.trim().isEmpty) return line;
    final onOpenPlan = _PlanPreviewScope.maybeOf(context);
    if (onOpenPlan == null) return line;
    final tooltip = context.l10n.text('workspace.planDetails');
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: '$name · $tooltip',
        child: InkWell(
          key: ValueKey('process-open-plan:${activity.id}'),
          borderRadius: BorderRadius.circular(7),
          hoverColor: colors.onSurface.withValues(alpha: 0.055),
          focusColor: colors.primary.withValues(alpha: 0.1),
          onTap: () => onOpenPlan(content),
          child: line,
        ),
      ),
    );
  }
}

TextStyle? _processTextStyle(BuildContext context) {
  final colors = Theme.of(context).colorScheme;
  return Theme.of(context).textTheme.bodyMedium?.copyWith(
    fontSize: 12.5,
    height: 1.35,
    color: colors.onSurfaceVariant.withValues(alpha: 0.8),
    fontWeight: FontWeight.w500,
  );
}

String _elapsedLabel(Duration value) {
  final seconds = value.inSeconds.clamp(0, 999999);
  if (seconds < 60) return '${seconds}s';
  if (seconds < 3600) {
    return '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')}';
  }
  return '${seconds ~/ 3600}h ${((seconds % 3600) ~/ 60).toString().padLeft(2, '0')}m';
}

String _processSummary(BuildContext context, List<RuntimeActivity> activities) {
  final categories = {for (final value in activities) _activityCategory(value)};
  return localizedProcessSummary(
    categories.length == 1 ? categories.first : 'other',
    activities.length,
    toolPresentationLanguage(context),
    mixed: categories.length != 1,
  );
}

IconData _processGroupIcon(List<RuntimeActivity> activities) =>
    switch (activities.isEmpty ? '' : _activityCategory(activities.first)) {
      'search' => CupertinoIcons.search,
      'read' => CupertinoIcons.doc_text,
      'write' => CupertinoIcons.pencil,
      'shell' => CupertinoIcons.chevron_left_slash_chevron_right,
      'agent' => CupertinoIcons.person_2,
      'planning' => CupertinoIcons.checkmark_square,
      'interaction' => CupertinoIcons.question_circle,
      'browser' => CupertinoIcons.globe,
      'memory' => CupertinoIcons.archivebox,
      'skill' => CupertinoIcons.sparkles,
      'image' => CupertinoIcons.photo,
      _ => CupertinoIcons.square_stack_3d_up,
    };

String _activityCategory(RuntimeActivity activity) =>
    toolPresentationCategory(activity.label);
