part of '../workspace_screen.dart';

class _StudioDetailsPlugin extends WorkspacePanelPluginBase {
  const _StudioDetailsPlugin();
  @override
  String get id => 'sage.workspace.studio';
  @override
  bool supports(WorkspacePanelServices services) =>
      services.maybeRead<WorkspaceController>()?.selectedStudio != null;
  @override
  IconData get icon => CupertinoIcons.person_2;
  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => context.l10n.text('studio.details');

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) {
    final controller = panelContext.services.read<WorkspaceController>();
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final studio = controller.selectedStudio;
        if (studio == null) return const SizedBox.shrink();
        return _StudioDetailsView(
          key: ValueKey(studio.id),
          controller: controller,
          studio: studio,
        );
      },
    );
  }
}

class _StudioDetailsView extends StatefulWidget {
  const _StudioDetailsView({
    super.key,
    required this.controller,
    required this.studio,
  });
  final WorkspaceController controller;
  final Studio studio;
  @override
  State<_StudioDetailsView> createState() => _StudioDetailsViewState();
}

class _StudioDetailsViewState extends State<_StudioDetailsView> {
  String? _memberId;
  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final studio = widget.studio;
    final colors = Theme.of(context).colorScheme;
    final member = studio.members.where((m) => m.id == _memberId).firstOrNull;
    if (member != null) {
      final execution = controller.studioExecution(studio, member)!;
      return Material(
        color: colors.surface,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              child: Row(
                children: [
                  _ThreadActionButton(
                    keyValue: 'studio-member-back',
                    icon: CupertinoIcons.chevron_left,
                    tooltip: context.l10n.text('studio.members'),
                    onTap: () => setState(() => _memberId = null),
                  ),
                  const SizedBox(width: 10),
                  _StudioMemberAvatar(member: member),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      member.name,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                  ),
                  _ThreadActionButton(
                    keyValue: 'studio-session-mention:${member.id}',
                    icon: CupertinoIcons.at,
                    tooltip: '@ ${member.name}',
                    onTap: () =>
                        controller.selectStudioMember(member.id, mention: true),
                  ),
                  const SizedBox(width: 8),
                  _StudioMemberStatus(
                    controller: controller,
                    studio: studio,
                    member: member,
                  ),
                ],
              ),
            ),
            Divider(height: 1, color: colors.outlineVariant),
            Expanded(
              child: _MessageList(
                key: ValueKey('studio-member-session:${member.id}'),
                controller: controller,
                conversation: execution,
                subSessions: execution.subSessions,
                readOnly: true,
              ),
            ),
          ],
        ),
      );
    }
    return Material(
      color: colors.surface,
      child: ListView(
        key: ValueKey('studio-details:${studio.id}'),
        padding: const EdgeInsets.all(20),
        children: [
          Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _StudioDetailsCard(
                    child: Column(
                      children: [
                        Row(
                          children: [
                            Container(
                              width: 40,
                              height: 40,
                              decoration: BoxDecoration(
                                color: colors.primary.withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Icon(
                                CupertinoIcons.person_3,
                                size: 22,
                                color: colors.primary,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                studio.name,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w600),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 18),
                        Row(
                          children: [
                            Text(
                              context.l10n.text('studio.coordinator'),
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(color: colors.onSurfaceVariant),
                            ),
                            const SizedBox(width: 20),
                            Expanded(
                              child: Align(
                                alignment: Alignment.centerRight,
                                child: _StudioOwnerPicker(
                                  controller: controller,
                                  studio: studio,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 24, 4, 10),
                    child: Text(
                      '${context.l10n.text('studio.members')}  ${studio.members.length}',
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ),
                  LayoutBuilder(
                    builder: (context, constraints) => GridView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: studio.members.length,
                      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: constraints.maxWidth < 280 ? 1 : 2,
                        mainAxisSpacing: 12,
                        crossAxisSpacing: 12,
                        mainAxisExtent:
                            132 * MediaQuery.textScalerOf(context).scale(1),
                      ),
                      itemBuilder: (context, index) {
                        final member = studio.members[index];
                        return _StudioMemberCard(
                          controller: controller,
                          studio: studio,
                          member: member,
                          onTap: () => setState(() => _memberId = member.id),
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StudioDetailsCard extends StatelessWidget {
  const _StudioDetailsCard({required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => GlassCard(
    padding: const EdgeInsets.all(16),
    shape: const LiquidRoundedSuperellipse(borderRadius: 18),
    useOwnLayer: true,
    settings: _composerGlassSettings(context),
    child: child,
  );
}

class _StudioMemberAvatar extends StatelessWidget {
  const _StudioMemberAvatar({required this.member});
  final StudioMember member;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        color: colors.onSurface.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Icon(
        CupertinoIcons.person_crop_circle,
        size: 20,
        color: colors.onSurfaceVariant,
      ),
    );
  }
}

class _StudioMemberStatus extends StatelessWidget {
  const _StudioMemberStatus({
    required this.controller,
    required this.studio,
    required this.member,
  });
  final WorkspaceController controller;
  final Studio studio;
  final StudioMember member;
  @override
  Widget build(BuildContext context) {
    final execution = controller.studioExecution(studio, member)!;
    final colors = Theme.of(context).colorScheme;
    final waiting = execution.pendingInteraction != null;
    final unavailable = !controller.studioMemberAvailable(member);
    final busy = controller.studioMemberBusy(studio, member);
    final color = waiting || unavailable
        ? colors.error
        : busy
        ? colors.primary
        : colors.onSurfaceVariant;
    return Text(
      context.l10n.text(
        unavailable
            ? 'studio.unavailable'
            : waiting
            ? 'studio.needsYou'
            : 'status.${execution.status.name}',
      ),
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: Theme.of(context).textTheme.labelSmall?.copyWith(color: color),
    );
  }
}

class _StudioMemberCard extends StatelessWidget {
  const _StudioMemberCard({
    required this.controller,
    required this.studio,
    required this.member,
    required this.onTap,
  });
  final WorkspaceController controller;
  final Studio studio;
  final StudioMember member;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: member.name,
    child: InkWell(
      key: ValueKey('studio-member-open:${member.id}'),
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      child: _StudioDetailsCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _StudioMemberAvatar(member: member),
                const Spacer(),
                _ThreadActionButton(
                  keyValue: 'studio-mention:${member.id}',
                  icon: CupertinoIcons.at,
                  tooltip: '@ ${member.name}',
                  onTap: () =>
                      controller.selectStudioMember(member.id, mention: true),
                ),
              ],
            ),
            const Spacer(),
            Row(
              children: [
                Flexible(
                  child: Text(
                    member.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (member.id == studio.coordinatorId) ...[
                  const SizedBox(width: 6),
                  Tooltip(
                    message: context.l10n.text('studio.coordinator'),
                    child: Icon(
                      CupertinoIcons.star_fill,
                      size: 12,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 4),
            _StudioMemberStatus(
              controller: controller,
              studio: studio,
              member: member,
            ),
          ],
        ),
      ),
    ),
  );
}

class _StudioOwnerPicker extends StatefulWidget {
  const _StudioOwnerPicker({required this.controller, required this.studio});
  final WorkspaceController controller;
  final Studio studio;
  @override
  State<_StudioOwnerPicker> createState() => _StudioOwnerPickerState();
}

class _StudioOwnerPickerState extends State<_StudioOwnerPicker> {
  final _link = LayerLink();
  final _region = Object();
  OverlayEntry? _entry;
  void _close() {
    _entry?.remove();
    _entry = null;
  }

  @override
  void dispose() {
    _close();
    super.dispose();
  }

  void _toggle() {
    if (_entry != null) {
      _close();
      return;
    }
    _entry = OverlayEntry(
      builder: (context) => Positioned(
        width: 220,
        child: CompositedTransformFollower(
          link: _link,
          showWhenUnlinked: false,
          targetAnchor: Alignment.bottomRight,
          followerAnchor: Alignment.topRight,
          offset: const Offset(0, 8),
          child: TapRegion(
            groupId: _region,
            child: _ComposerGlassMenu(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 280),
                child: ListView(
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  children: [
                    for (final member in widget.studio.members)
                      _ComposerMenuItem(
                        key: ValueKey('studio-owner-option:${member.id}'),
                        selected: member.id == widget.studio.coordinatorId,
                        icon: CupertinoIcons.person_crop_circle,
                        label: member.name,
                        onTap: () {
                          _close();
                          widget.controller.setStudioCoordinator(
                            widget.studio,
                            member.id,
                          );
                        },
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
    Overlay.of(context).insert(_entry!);
  }

  @override
  Widget build(BuildContext context) {
    final owner = widget.studio.members.firstWhere(
      (m) => m.id == widget.studio.coordinatorId,
    );
    return TapRegion(
      groupId: _region,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _link,
        child: InkWell(
          key: ValueKey(
            'studio-owner:${widget.studio.id}:${widget.studio.coordinatorId}',
          ),
          borderRadius: BorderRadius.circular(9),
          onTap: widget.studio.updatingCoordinator ? null : _toggle,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(CupertinoIcons.person_crop_circle, size: 16),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    owner.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                ),
                const SizedBox(width: 8),
                if (widget.studio.updatingCoordinator)
                  const CupertinoActivityIndicator(radius: 6)
                else
                  const Icon(CupertinoIcons.chevron_down, size: 11),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
