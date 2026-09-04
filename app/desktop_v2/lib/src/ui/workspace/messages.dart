part of '../workspace_screen.dart';

class _ToolActivityShimmer extends StatefulWidget {
  const _ToolActivityShimmer({
    required this.child,
    this.enabled = true,
    required this.shimmerKey,
  });

  final Widget child;
  final bool enabled;
  final Key shimmerKey;

  @override
  State<_ToolActivityShimmer> createState() => _ToolActivityShimmerState();
}

class _ToolActivityShimmerState extends State<_ToolActivityShimmer>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    );
    if (widget.enabled) _controller.repeat();
  }

  @override
  void didUpdateWidget(covariant _ToolActivityShimmer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled) {
      _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.maybeOf(context);
    final animationsDisabled =
        (media?.disableAnimations ?? false) ||
        (media?.accessibleNavigation ?? false);
    if (!widget.enabled || animationsDisabled) return widget.child;

    final colors = Theme.of(context).colorScheme;
    final base = colors.onSurfaceVariant.withValues(alpha: 0.72);
    final highlight = colors.onSurface;
    return RepaintBoundary(
      key: widget.shimmerKey,
      child: AnimatedBuilder(
        animation: _controller,
        child: widget.child,
        builder: (context, child) => ShaderMask(
          blendMode: BlendMode.srcIn,
          shaderCallback: (bounds) {
            final sweepWidth = max(bounds.width * 0.52, 42.0);
            final travel = bounds.width + sweepWidth * 2;
            final left = -sweepWidth + travel * _controller.value;
            return LinearGradient(
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
              colors: [base, base, highlight, base, base],
              stops: const [0, 0.32, 0.5, 0.68, 1],
            ).createShader(Rect.fromLTWH(left, 0, sweepWidth, bounds.height));
          },
          child: child,
        ),
      ),
    );
  }
}

class _MessageBubble extends StatefulWidget {
  const _MessageBubble({
    required this.message,
    this.onEdit,
    this.onBranch,
    this.onReference,
    this.onLoadReference,
    super.key,
  });

  final ChatMessage message;
  final Future<void> Function(String value)? onEdit;
  final Future<bool> Function()? onBranch;
  final ValueChanged<String>? onReference;
  final Future<WorkspaceFileContent> Function(String source)? onLoadReference;

  @override
  State<_MessageBubble> createState() => _MessageBubbleState();
}

class _MessageBubbleState extends State<_MessageBubble> {
  late final TextEditingController _editor = TextEditingController(
    text: widget.message.text,
  );
  bool _editing = false;
  bool _submitting = false;

  ChatMessage get message => widget.message;

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: message.text));
    if (!mounted) return;
    DesktopNoticeHost.show(context, message: context.l10n.text('common.copied'));
  }

  @override
  void didUpdateWidget(covariant _MessageBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_editing && oldWidget.message.text != widget.message.text) {
      _editor.text = widget.message.text;
    }
  }

  @override
  void dispose() {
    _editor.dispose();
    super.dispose();
  }

  Future<void> _submitEdit() async {
    final value = _editor.text.trim();
    if (value.isEmpty || _submitting || widget.onEdit == null) return;
    setState(() => _submitting = true);
    try {
      await widget.onEdit!(value);
      if (mounted) setState(() => _editing = false);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final user = message.role == 'user';
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: Column(
          crossAxisAlignment: user
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            Align(
              alignment: user ? Alignment.centerRight : Alignment.centerLeft,
              child: _editing
                  ? GlassCard(
                      key: ValueKey('message-edit-card:${message.id}'),
                      width: min(608, MediaQuery.sizeOf(context).width - 68),
                      padding: const EdgeInsets.all(12),
                      shape: const LiquidRoundedSuperellipse(borderRadius: 18),
                      useOwnLayer: true,
                      settings: _composerGlassSettings(context),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          TextField(
                            key: ValueKey('message-edit-field:${message.id}'),
                            controller: _editor,
                            autofocus: true,
                            minLines: 2,
                            maxLines: 8,
                            onSubmitted: (_) => _submitEdit(),
                          ),
                          const SizedBox(height: 10),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              TextButton(
                                onPressed: _submitting
                                    ? null
                                    : () => setState(() => _editing = false),
                                child: Text(context.l10n.text('common.cancel')),
                              ),
                              const SizedBox(width: 8),
                              GlassButton.custom(
                                key: ValueKey(
                                  'message-edit-submit:${message.id}',
                                ),
                                width: 76,
                                height: 34,
                                label: context.l10n.text('common.save'),
                                enabled: !_submitting,
                                onTap: _submitEdit,
                                shape: const LiquidRoundedRectangle(
                                  borderRadius: 10,
                                ),
                                settings: _composerGlassSettings(context),
                                child: _submitting
                                    ? const CupertinoActivityIndicator(
                                        radius: 7,
                                      )
                                    : Text(context.l10n.text('common.save')),
                              ),
                            ],
                          ),
                        ],
                      ),
                    )
                  : Container(
                      constraints: BoxConstraints(maxWidth: user ? 608 : 760),
                      padding: user
                          ? const EdgeInsets.symmetric(
                              horizontal: 15,
                              vertical: 12,
                            )
                          : EdgeInsets.zero,
                      decoration: BoxDecoration(
                        color: user
                            ? colors.surfaceContainerHighest.withValues(
                                alpha: 0.48,
                              )
                            : Colors.transparent,
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: user
                          ? _UserMessageContent(
                              key: ValueKey('message-selection:${message.id}'),
                              data: _messageDisplayText(context, message),
                              content: message.content,
                              onReferenceSelection: widget.onReference,
                              onLoadReference: widget.onLoadReference,
                            )
                          : _ConversationMarkdown(
                              key: ValueKey('message-selection:${message.id}'),
                              data:
                                  _messageDisplayText(context, message) +
                                  (message.streaming ? '\n\n▍' : ''),
                              onReferenceSelection: widget.onReference,
                            ),
                    ),
            ),
            const SizedBox(height: 5),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _ThreadActionButton(
                  keyValue: 'message-copy:${message.id}',
                  icon: CupertinoIcons.doc_on_doc,
                  tooltip: context.l10n.text('common.copy'),
                  onTap: _copy,
                ),
                if (widget.onReference != null) ...[
                  const SizedBox(width: 4),
                  _ThreadActionButton(
                    keyValue: 'message-reference:${message.id}',
                    icon: CupertinoIcons.quote_bubble,
                    tooltip: context.l10n.text('workspace.reference'),
                    onTap: () => widget.onReference!(message.text),
                  ),
                ],
                if (widget.onEdit != null) ...[
                  const SizedBox(width: 4),
                  _ThreadActionButton(
                    keyValue: 'message-edit:${message.id}',
                    icon: CupertinoIcons.pencil,
                    tooltip: context.l10n.text('common.edit'),
                    onTap: () => setState(() => _editing = true),
                  ),
                ],
                if (widget.onBranch != null) ...[
                  const SizedBox(width: 4),
                  _ThreadActionButton(
                    keyValue: 'message-branch:${message.id}',
                    icon: CupertinoIcons.arrow_branch,
                    tooltip: context.l10n.text('workspace.branchToNewChat'),
                    onTap: () => widget.onBranch!(),
                  ),
                ],
                const SizedBox(width: 7),
                Text(
                  _messageTime(message.createdAt),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    fontSize: 10.5,
                    color: colors.onSurfaceVariant.withValues(alpha: 0.68),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
