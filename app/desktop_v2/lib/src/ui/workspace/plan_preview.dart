part of '../workspace_screen.dart';

class _PlanPreviewState extends ValueNotifier<String> {
  _PlanPreviewState() : super('');
}

class _PlanWorkspacePanelPlugin extends WorkspacePanelPluginBase {
  const _PlanWorkspacePanelPlugin();

  @override
  String get id => 'sage.workspace.plan';

  @override
  IconData get icon => CupertinoIcons.doc_text;

  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => context.l10n.text('workspace.planDetails');

  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) =>
      ValueListenableBuilder<String>(
        valueListenable: panelContext.services.read<_PlanPreviewState>(),
        builder: (context, content, _) => ColoredBox(
          key: const ValueKey('plan-detail-surface'),
          color: Theme.of(context).colorScheme.surface.withValues(alpha: 1),
          child: SizedBox.expand(
            child: SingleChildScrollView(
              key: const ValueKey('plan-detail-panel'),
              padding: const EdgeInsets.all(20),
              child: _ConversationMarkdown(data: content),
            ),
          ),
        ),
      );
}

class _PlanRejectionFeedbackDialog extends StatefulWidget {
  const _PlanRejectionFeedbackDialog();

  @override
  State<_PlanRejectionFeedbackDialog> createState() =>
      _PlanRejectionFeedbackDialogState();
}

class _PlanRejectionFeedbackDialogState
    extends State<_PlanRejectionFeedbackDialog> {
  final _reason = TextEditingController();

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Dialog(
      backgroundColor: Colors.transparent,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: GlassCard(
          useOwnLayer: true,
          padding: const EdgeInsets.all(20),
          settings: LiquidGlassSettings(
            glassColor: colors.surfaceContainerHigh.withValues(alpha: 0.95),
            chromaticAberration: 0,
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  context.l10n.text('approval.rejectionReason'),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 16),
                Semantics(
                  label: context.l10n.text('approval.rejectionReason'),
                  child: GlassTextField(
                    key: const ValueKey('interaction-rejection-reason'),
                    controller: _reason,
                    autofocus: true,
                    minLines: 3,
                    maxLines: 6,
                    textStyle: TextStyle(color: colors.onSurface),
                  ),
                ),
                const SizedBox(height: 16),
                Wrap(
                  alignment: WrapAlignment.end,
                  spacing: 8,
                  children: [
                    TextButton(
                      key: const ValueKey('interaction-rejection-cancel'),
                      onPressed: () => Navigator.of(context).pop(),
                      child: Text(context.l10n.text('common.cancel')),
                    ),
                    FilledButton(
                      key: const ValueKey('interaction-rejection-confirm'),
                      onPressed: () =>
                          Navigator.of(context).pop(_reason.text.trim()),
                      child: Text(
                        context.l10n.text('approval.confirmRejection'),
                      ),
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
