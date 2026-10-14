part of '../workspace_screen.dart';

class _OpenUiWorkspacePanelPlugin extends WorkspacePanelPluginBase {
  const _OpenUiWorkspacePanelPlugin();
  @override
  String get id => 'sage.workspace.openui';
  @override
  IconData get icon => CupertinoIcons.rectangle_on_rectangle;
  @override
  String title(
    BuildContext context,
    WorkspacePanelServices services, {
    WorkspacePanelInstance? instance,
  }) => Localizations.localeOf(context).languageCode == 'zh'
      ? '交互界面'
      : 'Interactive UI';
  @override
  Widget build(BuildContext context, WorkspacePanelContext panelContext) {
    final controller = panelContext.services.read<WorkspaceController>();
    return ColoredBox(
      key: const ValueKey('openui-panel-background'),
      color: Theme.of(context).colorScheme.surface.withValues(alpha: 1),
      child: SizedBox.expand(
        child: ListenableBuilder(
          listenable: controller,
          builder: (context, _) {
            final surface = controller.expandedOpenUiSurface;
            if (surface == null) return const SizedBox.shrink();
            final tree = surface['tree'];
            if (tree is Map && tree['component'] == 'Deck') {
              final complete =
                  surface['complete'] != false &&
                  surface['surface_id'] != null &&
                  (surface['error']?.toString() ?? '').isEmpty;
              return OpenUiDeck(
                key: ValueKey(controller.expandedOpenUiKey),
                node: tree,
                workspace: true,
                ready: complete,
                previewMessage: complete
                    ? null
                    : (Localizations.localeOf(context).languageCode == 'zh'
                          ? ((surface['error']?.toString() ?? '').isNotEmpty
                                ? '生成内容未通过校验，仅供预览'
                                : '正在生成预览')
                          : ((surface['error']?.toString() ?? '').isNotEmpty
                                ? 'Generated content failed validation'
                                : 'Generating preview')),
                onExport: (dark) => controller.exportOpenUiDeck(surface, dark),
              );
            }
            return SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: OpenUiSurface(
                key: ValueKey(controller.expandedOpenUiKey),
                surface: surface,
                onExport: (dark) => controller.exportOpenUiDeck(surface, dark),
                enabled:
                    controller.canSubmitOpenUi(surface) &&
                    !supersededOpenUiMessages(
                      controller.selectedDisplayConversation?.messages ?? [],
                    ).contains(surface['message_id']),
                onDraftChanged: (values) =>
                    controller.updateOpenUiDraft(surface, values),
                onSubmit: (action, values) =>
                    controller.submitOpenUi(surface, action, values),
              ),
            );
          },
        ),
      ),
    );
  }
}
