part of '../workspace_screen.dart';

Future<void> _createStudio(
  BuildContext context,
  WorkspaceController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => _StudioCreateDialog(controller: controller),
);

class _StudioCreateDialog extends StatefulWidget {
  const _StudioCreateDialog({required this.controller});
  final WorkspaceController controller;
  @override
  State<_StudioCreateDialog> createState() => _StudioCreateDialogState();
}

class _StudioCreateDialogState extends State<_StudioCreateDialog> {
  final name = TextEditingController();
  final chosen = <String>{};
  String? coordinator;
  bool saving = false;
  String? failure;
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: GlassCard(
        padding: const EdgeInsets.all(24),
        child: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  context.l10n.text('studio.create'),
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 20),
                TextField(
                  key: const ValueKey('studio-name'),
                  controller: name,
                  autofocus: true,
                  decoration: InputDecoration(
                    labelText: context.l10n.text('studio.name'),
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 12),
                Text(context.l10n.text('studio.members')),
                for (final agent in widget.controller.agents)
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(agent.name),
                    value: chosen.contains(agent.id),
                    onChanged: saving
                        ? null
                        : (checked) => setState(() {
                            if (checked == true) {
                              chosen.add(agent.id);
                              coordinator ??= agent.id;
                            } else {
                              chosen.remove(agent.id);
                              if (coordinator == agent.id) {
                                coordinator = chosen.firstOrNull;
                              }
                            }
                          }),
                  ),
                if (chosen.isNotEmpty)
                  DropdownButtonFormField<String>(
                    key: ValueKey('coordinator:$coordinator:${chosen.join()}'),
                    initialValue: coordinator,
                    decoration: InputDecoration(
                      labelText: context.l10n.text('studio.coordinator'),
                    ),
                    items: [
                      for (final a in widget.controller.agents.where(
                        (a) => chosen.contains(a.id),
                      ))
                        DropdownMenuItem(value: a.id, child: Text(a.name)),
                    ],
                    onChanged: saving
                        ? null
                        : (value) => setState(() => coordinator = value),
                  ),
                if (failure != null)
                  Text(
                    failure!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                const SizedBox(height: 20),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: saving ? null : () => Navigator.pop(context),
                      child: Text(context.l10n.text('common.cancel')),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(
                      key: const ValueKey('studio-create-confirm'),
                      onPressed:
                          saving || name.text.trim().isEmpty || chosen.isEmpty
                          ? null
                          : () async {
                              setState(() => saving = true);
                              try {
                                await widget.controller.createStudio(
                                  name.text,
                                  chosen.toList(),
                                  coordinatorAgentId: coordinator!,
                                );
                                if (context.mounted) {
                                  Navigator.pop(context);
                                }
                              } on Object catch (e) {
                                if (context.mounted) {
                                  setState(() {
                                    failure = e.toString();
                                    saving = false;
                                  });
                                }
                              }
                            },
                      child: Text(context.l10n.text('studio.create')),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _StudioRail extends StatelessWidget {
  const _StudioRail({required this.controller, this.compact = false});
  final WorkspaceController controller;
  final bool compact;
  @override
  Widget build(BuildContext context) {
    if (compact) {
      return PopupMenuButton<String>(
        tooltip: 'Studio',
        icon: const Icon(CupertinoIcons.person_3),
        onSelected: (id) => id == 'create'
            ? _createStudio(context, controller)
            : controller.selectStudio(id),
        itemBuilder: (_) => [
          PopupMenuItem(
            value: 'create',
            child: Text(context.l10n.text('studio.create')),
          ),
          for (final s in controller.studios)
            PopupMenuItem(value: s.id, child: Text(s.name)),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(10, 10, 0, 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  'Studio',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
              ),
              IconButton(
                key: const ValueKey('studio-create'),
                tooltip: context.l10n.text('studio.create'),
                visualDensity: VisualDensity.compact,
                onPressed: () => _createStudio(context, controller),
                icon: const Icon(CupertinoIcons.plus, size: 16),
              ),
            ],
          ),
        ),
        for (final studio in controller.studios)
          ListTile(
            key: ValueKey('studio:${studio.id}'),
            dense: true,
            contentPadding: const EdgeInsets.symmetric(horizontal: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            selected: controller.selectedStudioId == studio.id,
            selectedTileColor: Theme.of(
              context,
            ).colorScheme.onSurface.withValues(alpha: 0.08),
            leading: const Icon(CupertinoIcons.person_3, size: 18),
            title: Text(
              studio.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (studio.members.any(
                  (m) => controller.studioMemberBusy(studio, m),
                ))
                  const Icon(CupertinoIcons.circle_fill, size: 8),
                IconButton(
                  key: ValueKey('studio-settings:${studio.id}'),
                  tooltip: context.l10n.text('studio.details'),
                  icon: const Icon(CupertinoIcons.ellipsis, size: 16),
                  onPressed: () {
                    if (controller.selectedStudioId != studio.id) {
                      controller.selectStudio(studio.id);
                    }
                    context
                        .findAncestorStateOfType<_WorkspaceScreenState>()
                        ?._openStudioDetails();
                  },
                ),
              ],
            ),
            onTap: () => controller.selectStudio(studio.id),
          ),
      ],
    );
  }
}

class _StudioThread extends StatefulWidget {
  const _StudioThread({
    required this.controller,
    required this.onDetails,
    required this.onToggleRail,
    required this.onToggleWorkspace,
    required this.workspaceCollapsed,
    required this.railCollapsed,
    super.key,
  });
  final WorkspaceController controller;
  final VoidCallback onDetails;
  final VoidCallback onToggleRail;
  final VoidCallback onToggleWorkspace;
  final bool workspaceCollapsed;
  final bool railCollapsed;
  @override
  State<_StudioThread> createState() => _StudioThreadState();
}

class _StudioThreadState extends State<_StudioThread> {
  final _scroll = ScrollController();
  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final studio = controller.selectedStudio!;
    final colors = Theme.of(context).colorScheme;
    final busyMembers = studio.members
        .where((m) => controller.studioMemberBusy(studio, m))
        .toList();
    final waiting = studio.members
        .where(
          (m) =>
              controller.studioExecution(studio, m)?.pendingInteraction != null,
        )
        .toList();
    final stick = !_scroll.hasClients || _scroll.position.extentAfter < 80;
    if (stick) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scroll.hasClients) {
          _scroll.jumpTo(_scroll.position.maxScrollExtent);
        }
      });
    }
    return Material(
      color: colors.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: desktopPaneHeaderHeight,
            child: Row(
              children: [
                IconButton(
                  tooltip: context.l10n.text(
                    widget.railCollapsed
                        ? 'workspace.expandSidebar'
                        : 'workspace.collapseSidebar',
                  ),
                  onPressed: widget.onToggleRail,
                  icon: const Icon(CupertinoIcons.sidebar_left, size: 18),
                ),
                Expanded(
                  child: Text(
                    studio.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (busyMembers.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: Text(
                      context.l10n.text('studio.active', {
                        'count': busyMembers.length,
                      }),
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ),
                IconButton(
                  key: const ValueKey('studio-details-open'),
                  tooltip: context.l10n.text('studio.details'),
                  onPressed: widget.onDetails,
                  icon: const Icon(CupertinoIcons.person_2, size: 20),
                ),
                if (widget.workspaceCollapsed)
                  _HeaderIconButton(
                    keyValue: 'canvas-expand-button',
                    tooltip: context.l10n.text('workspace.expandSidebar'),
                    icon: CupertinoIcons.sidebar_right,
                    onTap: widget.onToggleWorkspace,
                  ),
              ],
            ),
          ),
          if (controller.error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: SelectableText(
                controller.error!,
                style: TextStyle(color: colors.error),
              ),
            ),
          for (final member in waiting)
            TextButton.icon(
              onPressed: () {
                final interaction = controller
                    .studioExecution(studio, member)!
                    .pendingInteraction!;
                showDialog<void>(
                  context: context,
                  builder: (dialogContext) => Dialog(
                    child: GlassCard(
                      padding: const EdgeInsets.all(20),
                      child: SizedBox(
                        width: 520,
                        child: SingleChildScrollView(
                          child: _InteractionCard(
                            key: ValueKey(interaction.id),
                            interaction: interaction,
                            onOpenPlan: (content) => _PlanPreviewScope.maybeOf(
                              context,
                            )?.call(content),
                            onReply:
                                (
                                  decision, {
                                  text = '',
                                  payload = const {},
                                }) async {
                                  await controller.replyStudioInteraction(
                                    studio,
                                    member,
                                    decision,
                                    text: text,
                                    payload: payload,
                                  );
                                  if (dialogContext.mounted &&
                                      controller
                                              .studioExecution(studio, member)
                                              ?.pendingInteraction ==
                                          null) {
                                    Navigator.of(dialogContext).pop();
                                  }
                                },
                          ),
                        ),
                      ),
                    ),
                  ),
                );
              },
              icon: const Icon(CupertinoIcons.exclamationmark_circle),
              label: Text(
                '${member.name} · ${context.l10n.text('studio.needsYou')}',
              ),
            ),
          Expanded(
            child: studio.turns.isEmpty
                ? Center(
                    child: Icon(
                      CupertinoIcons.person_3,
                      size: 48,
                      color: colors.onSurfaceVariant.withValues(alpha: 0.4),
                    ),
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 24,
                      vertical: 20,
                    ),
                    itemCount: studio.turns.length,
                    itemBuilder: (context, index) {
                      final turn = studio.turns[index];
                      final member = studio.members.firstWhere(
                        (m) => m.id == turn.memberId,
                      );

                      final execution = controller.studioExecution(
                        studio,
                        member,
                      )!;
                      final time = controller
                          .studioTurnTime(studio, turn)
                          ?.toLocal();
                      final previousTime = index > 0
                          ? controller
                                .studioTurnTime(studio, studio.turns[index - 1])
                                ?.toLocal()
                          : null;
                      final entries =
                          <
                            ({
                              String memberId,
                              ChatMessage message,
                              bool note,
                              DateTime? timestamp,
                            })
                          >[
                            for (final message in studio.publicMessages.where(
                              (m) => m['turn_id'] == turn.id,
                            ))
                              (
                                memberId: '${message['sender']}',
                                message: ChatMessage(
                                  id: '${message['id']}',
                                  role: 'assistant',
                                  text: '${message['text']}',
                                ),
                                note: true,
                                timestamp: DateTime.tryParse(
                                  '${message['created_at'] ?? ''}',
                                ),
                              ),
                            for (final target in studio.members.where(
                              (m) => turn.memberIds.contains(m.id),
                            ))
                              for (final reply in controller.studioReplies(
                                studio,
                                turn,
                                memberId: target.id,
                              ))
                                (
                                  memberId: target.id,
                                  message: reply,
                                  note: false,
                                  timestamp: reply.createdAt,
                                ),
                          ];
                      entries.sort(
                        (a, b) => (a.timestamp ?? time ?? DateTime(1970))
                            .compareTo(b.timestamp ?? time ?? DateTime(1970)),
                      );
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (time != null &&
                              (previousTime == null ||
                                  time.year != previousTime.year ||
                                  time.month != previousTime.month ||
                                  time.day != previousTime.day))
                            Padding(
                              padding: const EdgeInsets.only(bottom: 20),
                              child: Center(
                                child: Text(
                                  MaterialLocalizations.of(
                                    context,
                                  ).formatMediumDate(time),
                                  key: ValueKey('studio-date:${turn.id}'),
                                  style: Theme.of(context).textTheme.labelSmall
                                      ?.copyWith(
                                        color: colors.onSurfaceVariant,
                                      ),
                                ),
                              ),
                            ),
                          _StudioBubble(
                            name: turn.explicitMention
                                ? '${context.l10n.text('studio.you')} → ${turn.memberIds.map((id) => studio.members.firstWhere((m) => m.id == id).name).join(', ')}'
                                : context.l10n.text('studio.you'),
                            text: turn.text,
                            content: turn.content,
                            user: true,
                            messageId: turn.id,
                            createdAt: execution.messages
                                .where((m) => m.id == turn.executionMessageId)
                                .firstOrNull
                                ?.createdAt,
                          ),
                          for (final entry in entries)
                            _StudioBubble(
                              key: ValueKey(
                                '${entry.note ? 'studio-public' : 'studio-reply'}:${entry.message.id}',
                              ),
                              name:
                                  studio.members
                                      .where((m) => m.id == entry.memberId)
                                      .firstOrNull
                                      ?.name ??
                                  entry.memberId,
                              text: entry.message.renderedText,
                              messageId: entry.message.id,
                              createdAt: entry.timestamp,
                              onMention: () => controller.selectStudioMember(
                                entry.memberId,
                                mention: true,
                              ),
                              onReference: (text) =>
                                  controller.referenceMessage(
                                    entry.message,
                                    text,
                                    label:
                                        studio.members
                                            .where(
                                              (m) => m.id == entry.memberId,
                                            )
                                            .firstOrNull
                                            ?.name ??
                                        entry.memberId,
                                  ),
                              onTap: () {
                                controller.selectStudioMember(entry.memberId);
                                widget.onDetails();
                              },
                            ),
                          for (final target in studio.members.where(
                            (m) => turn.memberIds.contains(m.id),
                          ))
                            if (studio.turns
                                        .lastWhere(
                                          (t) =>
                                              t.memberIds.contains(target.id),
                                        )
                                        .id ==
                                    turn.id &&
                                !{RunStatus.idle, RunStatus.completed}.contains(
                                  controller
                                      .studioExecution(studio, target)!
                                      .status,
                                ))
                              Align(
                                alignment: Alignment.centerLeft,
                                child: TextButton(
                                  onPressed: () {
                                    controller.selectStudioMember(target.id);
                                    widget.onDetails();
                                  },
                                  child: Text(
                                    '${target.name} · ${context.l10n.text('status.${controller.studioExecution(studio, target)!.status.name}')}',
                                  ),
                                ),
                              ),
                        ],
                      );
                    },
                  ),
          ),
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 820),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(34, 8, 34, 24),
                child: _Composer(
                  controller: controller,
                  conversation: studio.draft,
                  studio: studio,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StudioBubble extends StatelessWidget {
  const _StudioBubble({
    required this.name,
    required this.text,
    required this.messageId,
    this.createdAt,
    this.user = false,
    this.content = const [],
    this.onTap,
    this.onMention,
    this.onReference,
    super.key,
  });
  final String name;
  final String text;
  final String messageId;
  final DateTime? createdAt;
  final bool user;
  final List<ChatMessageContent> content;
  final VoidCallback? onTap;
  final VoidCallback? onMention;
  final ValueChanged<String>? onReference;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final avatar = Container(
      width: 30,
      height: 30,
      decoration: BoxDecoration(
        color: user ? colors.primaryContainer : colors.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Icon(
        user ? CupertinoIcons.person_fill : CupertinoIcons.sparkles,
        size: 16,
        color: user ? colors.onPrimaryContainer : colors.onSurfaceVariant,
      ),
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: LayoutBuilder(
        builder: (context, constraints) => Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: user
              ? MainAxisAlignment.end
              : MainAxisAlignment.start,
          children: [
            if (!user) ...[avatar, const SizedBox(width: 10)],
            Flexible(
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: min(620, constraints.maxWidth - 40),
                ),
                child: Column(
                  crossAxisAlignment: user
                      ? CrossAxisAlignment.end
                      : CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Flexible(
                          child: InkWell(
                            onTap: onTap,
                            child: Padding(
                              padding: const EdgeInsets.only(bottom: 6),
                              child: Text(
                                name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.labelMedium
                                    ?.copyWith(
                                      color: colors.onSurfaceVariant,
                                      fontWeight: FontWeight.w600,
                                    ),
                              ),
                            ),
                          ),
                        ),
                        if (onMention != null)
                          _ThreadActionButton(
                            keyValue: 'studio-message-mention:$messageId',
                            icon: CupertinoIcons.at,
                            tooltip: '@ $name',
                            onTap: onMention!,
                          ),
                      ],
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: user
                            ? colors.primaryContainer.withValues(alpha: 0.6)
                            : colors.surfaceContainerLow,
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: user
                          ? _UserMessageContent(
                              data: text,
                              content: content,
                              fitContent: true,
                            )
                          : _ConversationMarkdown(
                              data: text,
                              fitContent: true,
                              onReferenceSelection: onReference,
                            ),
                    ),
                    const SizedBox(height: 3),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (createdAt != null)
                          Tooltip(
                            message: createdAt!
                                .toLocal()
                                .toString()
                                .split('.')
                                .first,
                            child: Text(
                              _messageTime(createdAt!),
                              key: ValueKey('studio-time:$messageId'),
                              style: Theme.of(context).textTheme.labelSmall
                                  ?.copyWith(
                                    fontSize: 10.5,
                                    color: colors.onSurfaceVariant.withValues(
                                      alpha: 0.68,
                                    ),
                                  ),
                            ),
                          ),
                        const SizedBox(width: 6),
                        if (onReference != null)
                          _ThreadActionButton(
                            keyValue: 'studio-reference:$messageId',
                            icon: CupertinoIcons.quote_bubble,
                            tooltip: context.l10n.text('workspace.reference'),
                            onTap: () => onReference!(text),
                          ),
                        _ThreadActionButton(
                          keyValue: 'studio-copy:$messageId',
                          tooltip: context.l10n.text('common.copy'),
                          icon: CupertinoIcons.doc_on_doc,
                          onTap: () async {
                            await Clipboard.setData(ClipboardData(text: text));
                            if (context.mounted) {
                              DesktopNoticeHost.show(
                                context,
                                message: context.l10n.text('common.copied'),
                              );
                            }
                          },
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            if (user) ...[const SizedBox(width: 10), avatar],
          ],
        ),
      ),
    );
  }
}
