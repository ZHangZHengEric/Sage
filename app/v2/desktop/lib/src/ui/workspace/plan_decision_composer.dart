part of '../workspace_screen.dart';

bool _isPlanApproval(PendingInteraction? interaction) =>
    interaction?.type == 'approval' &&
    interaction?.payload['tool_name'] == 'goal_submit' &&
    interaction?.payload['risk_category'] == 'plan_approval';

class _PlanDecisionComposer extends StatefulWidget {
  const _PlanDecisionComposer({
    required this.interaction,
    required this.onReply,
    required this.initialFeedback,
    required this.onFeedbackChanged,
    super.key,
  });

  final PendingInteraction interaction;
  final String initialFeedback;
  final ValueChanged<String> onFeedbackChanged;
  final Future<void> Function(
    String decision, {
    String text,
    Map<String, Object?> payload,
  })
  onReply;

  @override
  State<_PlanDecisionComposer> createState() => _PlanDecisionComposerState();
}

class _PlanDecisionComposerState extends State<_PlanDecisionComposer> {
  late final _feedback = TextEditingController(text: widget.initialFeedback);
  bool _submitting = false;

  @override
  void dispose() {
    _feedback.dispose();
    super.dispose();
  }

  Future<void> _reply(String decision) async {
    if (_submitting) return;
    setState(() => _submitting = true);
    try {
      await widget.onReply(
        decision,
        text: decision == 'deny' ? _feedback.text.trim() : '',
        payload: decision == 'deny' ? const {} : const {'execute_plan': true},
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final muted = colors.onSurfaceVariant.withValues(alpha: 0.8);
    Widget leading(Widget child) => ExcludeSemantics(
      child: Container(
        width: 24,
        height: 24,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(
            color: colors.onSurface.withValues(alpha: dark ? 0.16 : 0.12),
          ),
        ),
        child: child,
      ),
    );
    final decisions = widget.interaction.allowedDecisions;
    final approve = [
      'approve_once',
      'approve',
      'approve_and_remember',
    ].where(decisions.contains).firstOrNull;
    return GlassCard(
      key: const ValueKey('plan-decision-composer'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      shape: const LiquidRoundedSuperellipse(borderRadius: 18),
      useOwnLayer: true,
      settings: _composerGlassSettings(context),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (approve != null)
            Material(
              color: colors.onSurface.withValues(alpha: dark ? 0.075 : 0.055),
              borderRadius: BorderRadius.circular(12),
              child: InkWell(
                key: ValueKey('interaction-submit-$approve'),
                onTap: _submitting ? null : () => _reply(approve),
                borderRadius: BorderRadius.circular(12),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                  child: Row(
                    children: [
                      leading(
                        Text('1', style: TextStyle(fontSize: 13, color: muted)),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          context.l10n.text('plan.implement'),
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: colors.onSurface,
                          ),
                        ),
                      ),
                      if (_submitting)
                        const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      else
                        Icon(
                          CupertinoIcons.chevron_right,
                          size: 13,
                          color: muted,
                        ),
                    ],
                  ),
                ),
              ),
            ),
          if (decisions.contains('deny')) ...[
            const SizedBox(height: 4),
            Container(
              constraints: const BoxConstraints(minHeight: 40),
              padding: const EdgeInsets.fromLTRB(10, 0, 4, 0),
              child: Row(
                children: [
                  leading(Icon(CupertinoIcons.pencil, size: 14, color: muted)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      key: const ValueKey('plan-feedback-input'),
                      controller: _feedback,
                      onChanged: widget.onFeedbackChanged,
                      enabled: !_submitting,
                      minLines: 1,
                      maxLines: 4,
                      style: TextStyle(
                        color: colors.onSurface,
                        fontSize: 14,
                        height: 1.4,
                      ),
                      decoration: InputDecoration(
                        hintText: context.l10n.text('plan.feedbackPlaceholder'),
                        hintStyle: TextStyle(
                          color: muted.withValues(alpha: 0.65),
                          fontSize: 14,
                        ),
                        filled: false,
                        isDense: true,
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        disabledBorder: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(vertical: 8),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  ValueListenableBuilder<TextEditingValue>(
                    valueListenable: _feedback,
                    builder: (context, value, _) => OutlinedButton(
                      key: const ValueKey('plan-feedback-submit'),
                      onPressed: _submitting ? null : () => _reply('deny'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: colors.onSurfaceVariant,
                        minimumSize: const Size(0, 32),
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        textStyle: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                        ),
                        side: BorderSide(
                          color: colors.onSurface.withValues(
                            alpha: dark ? 0.15 : 0.18,
                          ),
                        ),
                        shape: const StadiumBorder(),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      child: Text(
                        context.l10n.text(
                          value.text.trim().isEmpty
                              ? 'plan.skip'
                              : 'decision.submit',
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
