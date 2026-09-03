part of '../workspace_screen.dart';

class _ThreadPanel extends StatelessWidget {
  const _ThreadPanel({
    required this.controller,
    required this.railCollapsed,
    required this.workspaceCollapsed,
    required this.onToggleRail,
    required this.onToggleWorkspace,
    this.compact = false,
  });

  final WorkspaceController controller;
  final bool railCollapsed;
  final bool workspaceCollapsed;
  final VoidCallback onToggleRail;
  final VoidCallback onToggleWorkspace;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final conversation = controller.selectedDisplayConversation;
    if (conversation == null) return const SizedBox.shrink();
    final readOnly = controller.viewingSubSession;
    return DecoratedBox(
      decoration: BoxDecoration(color: Theme.of(context).colorScheme.surface),
      child: Column(
        children: [
          _ThreadHeader(
            controller: controller,
            conversation: conversation,
            railCollapsed: railCollapsed,
            compact: compact,
            workspaceCollapsed: workspaceCollapsed,
            onToggleRail: onToggleRail,
            onToggleWorkspace: onToggleWorkspace,
          ),
          if (conversation.messages.isEmpty &&
              conversation.pendingInteraction == null)
            Expanded(
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 900),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          context.l10n.text('workspace.emptyPrompt'),
                          style: Theme.of(context).textTheme.headlineMedium
                              ?.copyWith(
                                fontSize: 30,
                                fontWeight: FontWeight.w500,
                                letterSpacing: -0.6,
                              ),
                        ),
                        const SizedBox(height: 42),
                        if (!readOnly)
                          _Composer(
                            controller: controller,
                            conversation: conversation,
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            )
          else ...[
            Expanded(
              child: _MessageList(
                controller: controller,
                conversation: conversation,
                subSessions:
                    controller.selectedConversation?.subSessions ?? const [],
              ),
            ),
            if (conversation.pendingInteraction case final interaction?
                when !_isInlineQuestionnaire(interaction))
              _InteractionCard(
                interaction: interaction,
                onReply: readOnly
                    ? controller.replyDisplayInteraction
                    : controller.replyInteraction,
              ),
            if (!readOnly)
              Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 820),
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(34, 8, 34, compact ? 18 : 24),
                    child: _Composer(
                      controller: controller,
                      conversation: conversation,
                    ),
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _ThreadHeader extends StatelessWidget {
  const _ThreadHeader({
    required this.controller,
    required this.conversation,
    required this.railCollapsed,
    required this.compact,
    required this.workspaceCollapsed,
    required this.onToggleRail,
    required this.onToggleWorkspace,
  });

  final WorkspaceController controller;
  final Conversation conversation;
  final bool railCollapsed;
  final bool compact;
  final bool workspaceCollapsed;
  final VoidCallback onToggleRail;
  final VoidCallback onToggleWorkspace;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: desktopPaneHeaderHeight,
      padding: EdgeInsets.only(left: railCollapsed ? 136 : 10, right: 18),
      child: Row(
        children: [
          if (railCollapsed || compact) ...[
            _HeaderIconButton(
              keyValue: railCollapsed
                  ? 'rail-expand-button'
                  : 'rail-collapse-button',
              icon: CupertinoIcons.sidebar_left,
              tooltip: context.l10n.text(
                railCollapsed
                    ? 'workspace.expandSidebar'
                    : 'workspace.collapseSidebar',
              ),
              semanticsLabel: context.l10n.text(
                railCollapsed
                    ? 'workspace.expandSidebar'
                    : 'workspace.collapseSidebar',
              ),
              highlighted: railCollapsed,
              onTap: onToggleRail,
            ),
            const SizedBox(width: 14),
          ],
          Expanded(
            child: Text(
              context.l10n.conversationTitle(conversation.title),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontSize: 15,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          if (conversation.status != RunStatus.idle) ...[
            _RunStatusChip(status: conversation.status),
            const SizedBox(width: 4),
          ],
          if ({
            RunStatus.starting,
            RunStatus.running,
          }.contains(conversation.status))
            _HeaderIconButton(
              icon: CupertinoIcons.pause,
              onTap: controller.pause,
            ),
          if (conversation.status == RunStatus.suspended &&
              conversation.pendingInteraction == null)
            _HeaderIconButton(
              icon: CupertinoIcons.play,
              onTap: controller.resume,
            ),
          if ({
            RunStatus.starting,
            RunStatus.running,
            RunStatus.suspending,
            RunStatus.suspended,
          }.contains(conversation.status))
            _HeaderIconButton(
              icon: CupertinoIcons.stop_fill,
              onTap: controller.cancel,
            ),
          const SizedBox(width: 8),
          _HeaderIconButton(
            keyValue: workspaceCollapsed
                ? 'canvas-expand-button'
                : 'canvas-collapse-button',
            icon: CupertinoIcons.sidebar_right,
            onTap: onToggleWorkspace,
          ),
        ],
      ),
    );
  }
}

class _MessageList extends StatefulWidget {
  const _MessageList({
    required this.controller,
    required this.conversation,
    this.subSessions = const [],
  });

  final WorkspaceController controller;
  final Conversation conversation;
  final List<Conversation> subSessions;

  @override
  State<_MessageList> createState() => _MessageListState();
}

class _MessageListState extends State<_MessageList> {
  final _scrollController = ScrollController();
  final _scrollViewportKey = GlobalKey();
  final Map<int, GlobalKey> _messageKeys = {};
  bool _showScrollToBottom = false;
  bool _jumpFocusUpdateScheduled = false;
  bool _jumpInProgress = false;
  int _jumpRequestId = 0;
  int? _activeJumpMessageIndex;
  String _contentSignature = '';

  Conversation get conversation => widget.conversation;

  @override
  void initState() {
    super.initState();
    _contentSignature = _signature();
    _scrollController.addListener(_handleScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToBottom());
  }

  @override
  void didUpdateWidget(covariant _MessageList oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.conversation.id != widget.conversation.id) {
      _jumpRequestId++;
      _jumpInProgress = false;
      _activeJumpMessageIndex = null;
      _messageKeys.clear();
      WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToBottom());
    }
    final nextSignature = _signature();
    if (nextSignature == _contentSignature) return;
    final shouldFollow =
        !_scrollController.hasClients ||
        _scrollController.position.maxScrollExtent -
                _scrollController.position.pixels <
            96;
    _contentSignature = nextSignature;
    if (shouldFollow) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
    }
  }

  @override
  void dispose() {
    _scrollController
      ..removeListener(_handleScroll)
      ..dispose();
    super.dispose();
  }

  String _signature() {
    final messageSignature = conversation.messages
        .map(
          (message) =>
              '${message.id}:${message.renderedText.length}:${message.streaming}:${message.processOnly}',
        )
        .join('|');
    final processSignature = conversation.processPanels
        .map(
          (panel) =>
              '${panel.id}:${panel.running}:${panel.activities.length}:'
              '${panel.activities.where((value) => value.active).length}:'
              '${panel.activities.fold<int>(0, (sum, value) => sum + value.result.length)}',
        )
        .join('|');
    final subSessionSignature = widget.subSessions
        .map(
          (value) =>
              '${value.sessionId}:${value.status}:${value.runSequence}:'
              '${value.messages.fold<int>(0, (sum, message) => sum + message.text.length)}:'
              '${value.pendingInteraction?.id ?? ''}',
        )
        .join('|');
    final interaction = conversation.pendingInteraction;
    final interactionSignature = interaction == null
        ? ''
        : '${interaction.id}:${interaction.type}:${interaction.payload.hashCode}';
    return '$messageSignature:$processSignature:$subSessionSignature:'
        '${conversation.thinking}:$interactionSignature';
  }

  void _handleScroll() {
    if (!_scrollController.hasClients) return;
    final next =
        _scrollController.position.maxScrollExtent -
            _scrollController.position.pixels >
        140;
    if (next != _showScrollToBottom && mounted) {
      setState(() => _showScrollToBottom = next);
    }
    _scheduleJumpFocusUpdate(_jumpTargets());
  }

  void _jumpToBottom() {
    if (!mounted || !_scrollController.hasClients) return;
    _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
  }

  void _scrollToBottom() {
    if (!mounted || !_scrollController.hasClients) return;
    _scrollController.animateTo(
      _scrollController.position.maxScrollExtent,
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
    );
  }

  List<_ThreadJumpTarget> _jumpTargets() {
    final targets = <_ThreadJumpTarget>[];
    for (var index = 0; index < conversation.messages.length; index++) {
      final message = conversation.messages[index];
      if (message.processOnly) continue;
      final key = _messageKeys.putIfAbsent(index, GlobalKey.new);
      if (message.role != 'user') continue;
      targets.add(
        _ThreadJumpTarget(
          messageIndex: index,
          userLabel: _threadJumpLabel(message.text),
          summaryLabel: _threadJumpSummaryLabel(conversation.messages, index),
          key: key,
        ),
      );
    }
    _messageKeys.removeWhere(
      (index, _) =>
          index >= conversation.messages.length ||
          conversation.messages[index].processOnly,
    );
    return targets;
  }

  void _scheduleJumpFocusUpdate(List<_ThreadJumpTarget> targets) {
    if (_jumpFocusUpdateScheduled || _jumpInProgress || targets.isEmpty) {
      return;
    }
    _jumpFocusUpdateScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _jumpFocusUpdateScheduled = false;
      _updateJumpFocus(targets);
    });
  }

  void _updateJumpFocus(List<_ThreadJumpTarget> targets) {
    if (!mounted || _jumpInProgress || targets.isEmpty) return;
    final viewportRender = _scrollViewportKey.currentContext
        ?.findRenderObject();
    if (viewportRender is! RenderBox || !viewportRender.attached) return;
    final viewportTop = viewportRender.localToGlobal(Offset.zero).dy;
    final anchorY = viewportTop + 96;
    _ThreadJumpTarget? bestAbove;
    _ThreadJumpTarget? bestBelow;
    var bestAboveTop = -double.infinity;
    var bestBelowTop = double.infinity;

    for (final target in targets) {
      final renderObject = target.key.currentContext?.findRenderObject();
      if (renderObject is! RenderBox || !renderObject.attached) continue;
      final top = renderObject.localToGlobal(Offset.zero).dy;
      final bottom = top + renderObject.size.height;
      if (bottom < viewportTop) continue;
      if (top <= anchorY && top > bestAboveTop) {
        bestAbove = target;
        bestAboveTop = top;
      } else if (top < bestBelowTop) {
        bestBelow = target;
        bestBelowTop = top;
      }
    }

    final active = bestAbove ?? bestBelow;
    if (active == null || active.messageIndex == _activeJumpMessageIndex) {
      return;
    }
    setState(() => _activeJumpMessageIndex = active.messageIndex);
  }

  void _jumpToTarget(_ThreadJumpTarget target) {
    final requestId = ++_jumpRequestId;
    setState(() {
      _jumpInProgress = true;
      _activeJumpMessageIndex = target.messageIndex;
      _showScrollToBottom = false;
    });
    unawaited(
      _jumpToTargetAsync(target, requestId).whenComplete(() {
        if (!mounted || requestId != _jumpRequestId) return;
        setState(() => _jumpInProgress = false);
        _scheduleJumpFocusUpdate(_jumpTargets());
      }),
    );
  }

  Future<void> _jumpToTargetAsync(
    _ThreadJumpTarget target,
    int requestId,
  ) async {
    if (await _revealMountedTarget(target, requestId)) return;
    if (!_jumpRequestIsCurrent(requestId) || !_scrollController.hasClients) {
      return;
    }

    var position = _scrollController.position;
    var lowerBound = position.minScrollExtent;
    var upperBound = position.maxScrollExtent;
    final messageCount = max(1, conversation.messages.length);
    var probe = upperBound * (target.messageIndex / max(1, messageCount - 1));

    for (var attempt = 0; attempt < 8; attempt++) {
      if (!_jumpRequestIsCurrent(requestId) || !_scrollController.hasClients) {
        return;
      }
      position = _scrollController.position;
      upperBound = max(upperBound, position.maxScrollExtent);
      probe = probe.clamp(position.minScrollExtent, position.maxScrollExtent);
      if ((position.pixels - probe).abs() > 0.5) position.jumpTo(probe);
      await WidgetsBinding.instance.endOfFrame;
      if (await _revealMountedTarget(target, requestId)) return;

      final visibleRange = _visibleMessageRange();
      if (visibleRange != null) {
        if (target.messageIndex < visibleRange.first) {
          upperBound = min(upperBound, position.pixels);
        } else if (target.messageIndex > visibleRange.last) {
          lowerBound = max(lowerBound, position.pixels);
        } else {
          await WidgetsBinding.instance.endOfFrame;
          if (await _revealMountedTarget(target, requestId)) return;
        }
      }
      if (upperBound - lowerBound <= 1) break;
      probe = (lowerBound + upperBound) / 2;
    }

    if (!_jumpRequestIsCurrent(requestId) || !_scrollController.hasClients) {
      return;
    }
    position = _scrollController.position;
    position.jumpTo(
      probe.clamp(position.minScrollExtent, position.maxScrollExtent),
    );
    await WidgetsBinding.instance.endOfFrame;
    await _revealMountedTarget(target, requestId);
  }

  bool _jumpRequestIsCurrent(int requestId) {
    return mounted && requestId == _jumpRequestId;
  }

  ({int first, int last})? _visibleMessageRange() {
    final viewportRender = _scrollViewportKey.currentContext
        ?.findRenderObject();
    if (viewportRender is! RenderBox || !viewportRender.attached) return null;
    final viewportTop = viewportRender.localToGlobal(Offset.zero).dy;
    final viewportBottom = viewportTop + viewportRender.size.height;
    int? first;
    int? last;
    for (final entry in _messageKeys.entries) {
      final renderObject = entry.value.currentContext?.findRenderObject();
      if (renderObject is! RenderBox || !renderObject.attached) continue;
      final top = renderObject.localToGlobal(Offset.zero).dy;
      final bottom = top + renderObject.size.height;
      if (bottom < viewportTop || top > viewportBottom) continue;
      first = first == null ? entry.key : min(first, entry.key);
      last = last == null ? entry.key : max(last, entry.key);
    }
    if (first == null || last == null) return null;
    return (first: first, last: last);
  }

  Future<bool> _revealMountedTarget(
    _ThreadJumpTarget target,
    int requestId,
  ) async {
    if (!_jumpRequestIsCurrent(requestId) || !_scrollController.hasClients) {
      return false;
    }
    final targetRender = target.key.currentContext?.findRenderObject();
    if (targetRender is! RenderBox || !targetRender.attached) return false;
    final viewport = RenderAbstractViewport.maybeOf(targetRender);
    if (viewport == null) return false;
    final position = _scrollController.position;
    final revealOffset = viewport.getOffsetToReveal(targetRender, 0.08).offset;
    await position.animateTo(
      revealOffset.clamp(position.minScrollExtent, position.maxScrollExtent),
      duration: const Duration(milliseconds: 240),
      curve: Curves.easeOutCubic,
    );
    if (!_jumpRequestIsCurrent(requestId)) return false;
    await WidgetsBinding.instance.endOfFrame;
    return _correctTargetVisibility(target, requestId);
  }

  Future<bool> _correctTargetVisibility(
    _ThreadJumpTarget target,
    int requestId,
  ) async {
    if (!_jumpRequestIsCurrent(requestId) || !_scrollController.hasClients) {
      return false;
    }
    final targetRender = target.key.currentContext?.findRenderObject();
    final viewportRender = _scrollViewportKey.currentContext
        ?.findRenderObject();
    if (targetRender is! RenderBox ||
        viewportRender is! RenderBox ||
        !targetRender.attached ||
        !viewportRender.attached) {
      return false;
    }

    final targetTop = targetRender.localToGlobal(Offset.zero).dy;
    final targetProbeBottom = targetTop + min(targetRender.size.height, 72.0);
    final viewportTop = viewportRender.localToGlobal(Offset.zero).dy + 10;
    final viewportBottom = viewportTop + viewportRender.size.height - 20;
    var delta = 0.0;
    if (targetTop < viewportTop) {
      delta = targetTop - viewportTop;
    } else if (targetProbeBottom > viewportBottom) {
      delta = targetProbeBottom - viewportBottom;
    }
    if (delta.abs() < 1) return true;

    final position = _scrollController.position;
    final correctedOffset = (position.pixels + delta).clamp(
      position.minScrollExtent,
      position.maxScrollExtent,
    );
    if ((correctedOffset - position.pixels).abs() < 1) return true;
    await position.animateTo(
      correctedOffset,
      duration: const Duration(milliseconds: 160),
      curve: Curves.easeOutCubic,
    );
    return _jumpRequestIsCurrent(requestId);
  }

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    final attachedPanelIds = <String>{};
    final pendingInteraction = conversation.pendingInteraction;
    final pendingQuestionnaire =
        pendingInteraction != null && _isInlineQuestionnaire(pendingInteraction)
        ? pendingInteraction
        : null;
    final completedQuestionnaire = pendingQuestionnaire == null
        ? _latestValidatedToolQuestionnaire(conversation)
        : null;
    final inlineQuestionnaire = pendingQuestionnaire ?? completedQuestionnaire;
    final questionnairePanelId =
        completedQuestionnaire?.payload['_process_panel_id']?.toString() ?? '';
    bool hiddenByQuestionnaire(ChatMessage message) =>
        questionnairePanelId.isNotEmpty &&
        message.role == 'assistant' &&
        _panelForMessage(message)?.id == questionnairePanelId;
    Widget questionnaireCard() => _InlineQuestionnaireCard(
      key: ValueKey('inline-questionnaire:${inlineQuestionnaire!.id}'),
      interaction: inlineQuestionnaire,
      onReply: completedQuestionnaire != null
          ? (decision, {text = '', payload = const {}}) async {
              if (decision != 'submit') return;
              final rawAnswers = payload['answers'];
              final answers = rawAnswers is Map
                  ? rawAnswers.cast<String, Object?>()
                  : const <String, Object?>{};
              await widget.controller.send(
                _questionnaireResponseMessage(
                  completedQuestionnaire,
                  answers,
                  context.l10n.text('questionnaire.response'),
                ),
              );
            }
          : widget.controller.viewingSubSession
          ? widget.controller.replyDisplayInteraction
          : widget.controller.replyInteraction,
    );
    var questionnaireInserted = false;
    var lastVisibleMessageIndex = -1;
    for (var index = conversation.messages.length - 1; index >= 0; index--) {
      if (!conversation.messages[index].processOnly &&
          !hiddenByQuestionnaire(conversation.messages[index])) {
        lastVisibleMessageIndex = index;
        break;
      }
    }
    for (
      var messageIndex = 0;
      messageIndex < conversation.messages.length;
      messageIndex++
    ) {
      final message = conversation.messages[messageIndex];
      if (message.processOnly || hiddenByQuestionnaire(message)) continue;
      final panel = message.role == 'assistant'
          ? _panelForMessage(message)
          : null;
      children.add(
        KeyedSubtree(
          key: _messageKeys.putIfAbsent(messageIndex, GlobalKey.new),
          child: _MessageBubble(
            key: ValueKey(message.id),
            message: message,
            onEdit:
                widget.controller.canRewriteLastUserMessage(
                  conversation,
                  message,
                )
                ? (value) => widget.controller.rewriteLastUserMessage(
                    message.id,
                    value,
                  )
                : null,
            onBranch:
                panel != null &&
                    panel.runId.isNotEmpty &&
                    !panel.running &&
                    panel.completedAt != null &&
                    !widget.controller.viewingSubSession
                ? () => widget.controller.branchFromRun(panel.runId)
                : null,
            onReference: (value) => widget.controller.referenceMessage(
              message,
              value,
              label: context.l10n.text('workspace.reference'),
            ),
            onLoadReference: widget.controller.loadMessageReference,
          ),
        ),
      );
      final attachedPanels = conversation.processPanels
          .where(
            (value) =>
                value.anchorMessageId == message.id && _shouldShowPanel(value),
          )
          .toList(growable: false);
      for (final panel in attachedPanels) {
        attachedPanelIds.add(panel.id);
        children.add(const SizedBox(height: 14));
        children.add(
          _ProcessPanel(
            key: ValueKey(panel.id),
            panel: panel,
            messages: _processMessagesFor(panel),
            subSessions: _subSessionsFor(panel),
            forceCollapsed: panel.id == questionnairePanelId,
          ),
        );
        if (panel.id == questionnairePanelId && inlineQuestionnaire != null) {
          children.add(const SizedBox(height: 14));
          children.add(questionnaireCard());
          questionnaireInserted = true;
        }
      }
      final followedByQuestionnaire =
          inlineQuestionnaire != null &&
          messageIndex == lastVisibleMessageIndex &&
          attachedPanels.isEmpty;
      children.add(
        SizedBox(
          height: followedByQuestionnaire
              ? 10
              : attachedPanels.isEmpty
              ? 26
              : 16,
        ),
      );
    }
    for (final panel in conversation.processPanels.where(
      (value) =>
          !attachedPanelIds.contains(value.id) && _shouldShowPanel(value),
    )) {
      children.add(
        _ProcessPanel(
          key: ValueKey(panel.id),
          panel: panel,
          messages: _processMessagesFor(panel),
          subSessions: _subSessionsFor(panel),
          forceCollapsed: panel.id == questionnairePanelId,
        ),
      );
      if (panel.id == questionnairePanelId && inlineQuestionnaire != null) {
        children.add(const SizedBox(height: 14));
        children.add(questionnaireCard());
        questionnaireInserted = true;
      }
      children.add(const SizedBox(height: 26));
    }
    if (conversation.thinking) {
      children.add(const _RunningThinkingStatus());
      children.add(const SizedBox(height: 14));
    }
    if (inlineQuestionnaire != null && !questionnaireInserted) {
      children.add(questionnaireCard());
      children.add(const SizedBox(height: 26));
    }
    final jumpTargets = _jumpTargets();
    final activeJumpMessageIndex =
        jumpTargets.any(
          (target) => target.messageIndex == _activeJumpMessageIndex,
        )
        ? _activeJumpMessageIndex
        : null;
    if (jumpTargets.length >= 3) _scheduleJumpFocusUpdate(jumpTargets);
    return Stack(
      children: [
        KeyedSubtree(
          key: _scrollViewportKey,
          child: ListView(
            key: const ValueKey('thread-message-list'),
            controller: _scrollController,
            padding: const EdgeInsets.fromLTRB(34, 28, 34, 34),
            children: children,
          ),
        ),
        if (jumpTargets.length >= 3)
          Positioned(
            left: 5,
            top: 18,
            bottom: 18,
            child: _ThreadUserJumpRail(
              targets: jumpTargets,
              activeMessageIndex: activeJumpMessageIndex,
              onJump: _jumpToTarget,
            ),
          ),
        if (_showScrollToBottom)
          Positioned(
            right: 34,
            bottom: 12,
            child: _ThreadScrollToBottomButton(onTap: _scrollToBottom),
          ),
      ],
    );
  }

  bool _shouldShowPanel(RuntimeProcessPanel panel) {
    return panel.running ||
        panel.activities.isNotEmpty ||
        _processMessagesFor(panel).isNotEmpty ||
        _subSessionsFor(panel).isNotEmpty;
  }

  RuntimeProcessPanel? _panelForMessage(ChatMessage message) {
    final messageIndex = conversation.messages.indexWhere(
      (value) => value.id == message.id,
    );
    if (messageIndex < 0) return null;
    RuntimeProcessPanel? result;
    var resultAnchorIndex = -1;
    for (final panel in conversation.processPanels) {
      final anchorIndex = conversation.messages.indexWhere(
        (value) => value.id == panel.anchorMessageId,
      );
      if (anchorIndex < 0 || anchorIndex >= messageIndex) continue;
      final hasLaterUser = conversation.messages
          .sublist(anchorIndex + 1, messageIndex)
          .any((value) => value.role == 'user');
      if (!hasLaterUser && anchorIndex > resultAnchorIndex) {
        result = panel;
        resultAnchorIndex = anchorIndex;
      }
    }
    return result;
  }

  List<ChatMessage> _processMessagesFor(RuntimeProcessPanel panel) {
    final anchorIndex = conversation.messages.indexWhere(
      (value) => value.id == panel.anchorMessageId,
    );
    if (anchorIndex < 0) return const [];
    var endIndex = conversation.messages.length;
    for (
      var index = anchorIndex + 1;
      index < conversation.messages.length;
      index++
    ) {
      if (conversation.messages[index].role == 'user') {
        endIndex = index;
        break;
      }
    }
    return [
      for (final message in conversation.messages.sublist(
        anchorIndex + 1,
        endIndex,
      ))
        if (message.role == 'assistant' && message.processOnly) message,
    ];
  }

  List<Conversation> _subSessionsFor(RuntimeProcessPanel panel) {
    final parentSessionId = conversation.sessionId;
    final values = <Conversation>[
      for (final value in widget.subSessions)
        if (value.parentSessionId == parentSessionId &&
            (panel.runId.isEmpty || value.parentRunId == panel.runId))
          value,
    ];
    final includedSessionIds = {for (final value in values) value.sessionId};
    var added = true;
    while (added) {
      added = false;
      for (final value in widget.subSessions) {
        if (values.contains(value) ||
            !includedSessionIds.contains(value.parentSessionId)) {
          continue;
        }
        values.add(value);
        includedSessionIds.add(value.sessionId);
        added = true;
      }
    }
    return values;
  }
}

class _ThreadJumpTarget {
  const _ThreadJumpTarget({
    required this.messageIndex,
    required this.userLabel,
    required this.summaryLabel,
    required this.key,
  });

  final int messageIndex;
  final String userLabel;
  final String? summaryLabel;
  final GlobalKey key;
}

class _ThreadUserJumpRail extends StatelessWidget {
  const _ThreadUserJumpRail({
    required this.targets,
    required this.activeMessageIndex,
    required this.onJump,
  });

  final List<_ThreadJumpTarget> targets;
  final int? activeMessageIndex;
  final ValueChanged<_ThreadJumpTarget> onJump;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      key: const ValueKey('thread-user-jump-rail'),
      width: 42,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final itemExtent = (constraints.maxHeight / targets.length).clamp(
            13.0,
            26.0,
          );
          return Align(
            alignment: Alignment.centerLeft,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (final target in targets)
                  SizedBox(
                    height: itemExtent,
                    child: _ThreadUserJumpRailItem(
                      target: target,
                      active: target.messageIndex == activeMessageIndex,
                      onJump: onJump,
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _ThreadUserJumpRailItem extends StatefulWidget {
  const _ThreadUserJumpRailItem({
    required this.target,
    required this.active,
    required this.onJump,
  });

  final _ThreadJumpTarget target;
  final bool active;
  final ValueChanged<_ThreadJumpTarget> onJump;

  @override
  State<_ThreadUserJumpRailItem> createState() =>
      _ThreadUserJumpRailItemState();
}

class _ThreadUserJumpRailItemState extends State<_ThreadUserJumpRailItem> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final highlighted = widget.active || _hovered;
    final lineColor = highlighted
        ? colors.onSurface
        : colors.onSurfaceVariant.withValues(alpha: dark ? 0.42 : 0.5);
    return MouseRegion(
      key: ValueKey<String>(
        'thread-user-jump-marker-${widget.target.messageIndex}',
      ),
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: () => widget.onJump(widget.target),
        child: OverflowBox(
          alignment: Alignment.centerLeft,
          minWidth: 42,
          maxWidth: 430,
          minHeight: 0,
          maxHeight: 96,
          child: SizedBox(
            width: 430,
            height: 96,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                AnimatedContainer(
                  key: ValueKey<String>(
                    'thread-user-jump-line-${widget.target.messageIndex}',
                  ),
                  duration: const Duration(milliseconds: 160),
                  curve: Curves.easeOutCubic,
                  width: _hovered ? 24 : 8,
                  height: _hovered ? 2.6 : 2,
                  decoration: BoxDecoration(
                    color: lineColor,
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
                const SizedBox(width: 8),
                IgnorePointer(
                  child: AnimatedOpacity(
                    duration: const Duration(milliseconds: 140),
                    opacity: _hovered ? 1 : 0,
                    child: GlassCard(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      shape: const LiquidRoundedRectangle(borderRadius: 10),
                      useOwnLayer: true,
                      settings: desktopSidebarGlassSettings(context),
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 330),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              widget.target.userLabel,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.labelLarge
                                  ?.copyWith(
                                    color: colors.onSurface,
                                    fontWeight: FontWeight.w700,
                                  ),
                            ),
                            if (widget.target.summaryLabel != null) ...[
                              const SizedBox(height: 4),
                              Text(
                                widget.target.summaryLabel!,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.labelMedium
                                    ?.copyWith(
                                      color: colors.onSurfaceVariant,
                                      fontWeight: FontWeight.w600,
                                    ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

String _threadJumpLabel(String text, {int limit = 34}) {
  final collapsed = text
      .replaceAll('\r\n', '\n')
      .split('\n')
      .where((line) => line.trim() != '[image]')
      .join(' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (collapsed.isEmpty) return 'User';
  if (collapsed.length <= limit) return collapsed;
  return '${collapsed.substring(0, limit)}...';
}

String? _threadJumpSummaryLabel(List<ChatMessage> messages, int userIndex) {
  String? summary;
  for (var index = userIndex + 1; index < messages.length; index++) {
    final message = messages[index];
    if (message.role == 'user') break;
    if (message.role != 'assistant' || message.processOnly) continue;
    final collapsed = message.text.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (collapsed.isNotEmpty) {
      summary = _threadJumpLabel(collapsed, limit: 56);
    }
  }
  return summary;
}

class _RunningThinkingStatus extends StatefulWidget {
  const _RunningThinkingStatus();

  @override
  State<_RunningThinkingStatus> createState() => _RunningThinkingStatusState();
}

class _RunningThinkingStatusState extends State<_RunningThinkingStatus> {
  late final Timer _timer;
  var _dotCount = 1;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 420), (_) {
      if (mounted) setState(() => _dotCount = (_dotCount % 3) + 1);
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final label =
        '${context.l10n.text('workspace.thinking')}'
        '${'.' * _dotCount}';
    return Semantics(
      key: const ValueKey('thread-thinking-status'),
      liveRegion: true,
      label: context.l10n.text('workspace.thinking'),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CupertinoActivityIndicator(
                  radius: 7,
                  color: colors.onSurfaceVariant,
                ),
                const SizedBox(width: 9),
                Text(
                  label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: colors.onSurface.withValues(alpha: 0.82),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
