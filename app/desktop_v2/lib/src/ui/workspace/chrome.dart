part of '../workspace_screen.dart';

class _GlassSurface extends StatelessWidget {
  const _GlassSurface({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: EdgeInsets.zero,
      shape: const LiquidRoundedSuperellipse(borderRadius: 18),
      useOwnLayer: true,
      settings: _composerGlassSettings(context),
      child: child,
    );
  }
}

class _HeaderIconButton extends StatelessWidget {
  const _HeaderIconButton({
    required this.icon,
    required this.onTap,
    this.keyValue,
    this.tooltip,
    this.semanticsLabel,
    this.highlighted = false,
  });

  final IconData icon;
  final VoidCallback? onTap;
  final String? keyValue;
  final String? tooltip;
  final String? semanticsLabel;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final button = Semantics(
      button: true,
      enabled: onTap != null,
      label: semanticsLabel,
      child: InkWell(
        key: keyValue == null ? null : ValueKey<String>(keyValue!),
        borderRadius: BorderRadius.circular(highlighted ? 13 : 7),
        onTap: onTap,
        child: Container(
          width: highlighted ? 32 : 24,
          height: highlighted ? 32 : 24,
          decoration: highlighted
              ? BoxDecoration(
                  color: colors.onSurface.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(13),
                )
              : null,
          child: Icon(
            icon,
            size: highlighted ? 17 : 16,
            color: highlighted ? colors.onSurface : colors.onSurfaceVariant,
          ),
        ),
      ),
    );
    final message = tooltip;
    return message == null ? button : Tooltip(message: message, child: button);
  }
}

class _SplitResizeHandle extends StatelessWidget {
  const _SplitResizeHandle({super.key, required this.onDragUpdate});

  final GestureDragUpdateCallback onDragUpdate;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final dividerColor = dark
        ? const Color(0xFF3A3A3C)
        : const Color(0xFFD1D1D6);
    return MouseRegion(
      cursor: SystemMouseCursors.resizeLeftRight,
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onHorizontalDragUpdate: onDragUpdate,
        child: SizedBox(
          width: desktopSplitHandleWidth,
          child: Center(
            child: DecoratedBox(
              decoration: BoxDecoration(color: dividerColor),
              child: const SizedBox.expand(),
            ),
          ),
        ),
      ),
    );
  }
}

class _SplitResizeHitTarget extends StatelessWidget {
  const _SplitResizeHitTarget({required this.onDragUpdate});

  final GestureDragUpdateCallback onDragUpdate;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.resizeLeftRight,
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onHorizontalDragUpdate: onDragUpdate,
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _SidebarIconButton extends StatelessWidget {
  const _SidebarIconButton({
    required this.tooltip,
    required this.icon,
    required this.onTap,
    this.keyValue,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback onTap;
  final String? keyValue;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: InkWell(
          key: keyValue == null ? null : ValueKey<String>(keyValue!),
          borderRadius: BorderRadius.circular(6),
          onTap: onTap,
          child: SizedBox.square(
            dimension: 24,
            child: Icon(
              icon,
              size: 16,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ),
    );
  }
}

class _SidebarFooterAction extends StatelessWidget {
  const _SidebarFooterAction({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 2, 14, 8),
      child: InkWell(
        key: const ValueKey('settings-button'),
        borderRadius: BorderRadius.circular(9),
        onTap: onTap,
        child: SizedBox(
          height: 36,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Row(
              children: [
                Icon(icon, size: 16, color: colors.onSurfaceVariant),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      fontSize: 13,
                      color: colors.onSurface,
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

LiquidGlassSettings _composerGlassSettings(BuildContext context) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return LiquidGlassSettings(
    visibility: dark ? 0.94 : 0.96,
    glassColor: dark
        ? const Color(0xFF2F2F31).withValues(alpha: 0.9)
        : const Color(0xFFFFFFFF).withValues(alpha: 0.94),
    thickness: 4,
    blur: 3,
    chromaticAberration: 0,
    lightIntensity: 0.1,
    saturation: 1,
    glowIntensity: 0,
    standardOpacityMultiplier: dark ? 0.92 : 0.94,
    shadowElevation: 0.06,
  );
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.status});

  final RunStatus status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      RunStatus.running || RunStatus.starting => Colors.green,
      RunStatus.suspending || RunStatus.suspended => Colors.orange,
      RunStatus.failed => Colors.red,
      RunStatus.cancelled => Colors.grey,
      _ => Theme.of(context).colorScheme.outline,
    };
    return Container(
      width: 7,
      height: 7,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    );
  }
}

class _RunStatusChip extends StatelessWidget {
  const _RunStatusChip({required this.status});

  final RunStatus status;

  @override
  Widget build(BuildContext context) {
    return Text(
      _statusLabel(status, context.l10n),
      style: Theme.of(context).textTheme.labelMedium?.copyWith(
        fontSize: 11.5,
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
    );
  }
}

class _ErrorNotice extends StatelessWidget {
  const _ErrorNotice({required this.message, required this.onClose});

  final String message;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final localizedMessage = context.l10n.knownMessage(message);
    return Semantics(
      key: const ValueKey('workspace-error-notice'),
      liveRegion: true,
      label: localizedMessage,
      child: GlassCard(
        padding: EdgeInsets.zero,
        shape: const LiquidRoundedSuperellipse(borderRadius: 16),
        useOwnLayer: true,
        settings: _composerGlassSettings(context),
        child: Container(
          decoration: BoxDecoration(
            color: colors.errorContainer.withValues(alpha: 0.18),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: colors.error.withValues(alpha: 0.26)),
          ),
          padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
          child: Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: colors.errorContainer.withValues(alpha: 0.72),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  CupertinoIcons.exclamationmark,
                  color: colors.onErrorContainer,
                  size: 15,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  localizedMessage,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: colors.onSurface),
                ),
              ),
              IconButton(
                tooltip: context.l10n.text('common.close'),
                onPressed: onClose,
                icon: const Icon(CupertinoIcons.xmark, size: 15),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _riskLabel(
  String? category,
  String? sideEffectLevel,
  SageLocalizations l10n,
) => switch (category) {
  'destructive_filesystem' || 'filesystem_delete' => l10n.text('risk.files'),
  'external_side_effect' => l10n.text('risk.external'),
  'command_policy' => l10n.text('risk.command'),
  _ => switch (sideEffectLevel) {
    'none' => _approvalCardText('noSideEffect', l10n.languageCode),
    'read' => _approvalCardText('readOnly', l10n.languageCode),
    'write' ||
    'reversible' => _approvalCardText('writeOperation', l10n.languageCode),
    'irreversible' => _approvalCardText('highRisk', l10n.languageCode),
    _ => l10n.text('risk.generic'),
  },
};

String _approvalCardText(String key, String language) {
  final zh = language == 'zh';
  return switch (key) {
    'noSideEffect' => zh ? '无副作用' : 'No side effects',
    'readOnly' => zh ? '只读操作' : 'Read only',
    'writeOperation' => zh ? '写入操作' : 'Writes data',
    'highRisk' => zh ? '高风险操作' : 'High risk',
    _ => key,
  };
}

String _planApprovalTitle(String language) => switch (language) {
  'zh' => '审批计划',
  'pt' => 'Revisar plano',
  'es' => 'Revisar plan',
  'fr' => 'Examiner le plan',
  'de' => 'Plan prüfen',
  'ja' => '計画を確認',
  'ko' => '계획 검토',
  'ru' => 'Проверить план',
  _ => 'Review plan',
};

String? _riskReason(
  String? category,
  String? fallback,
  SageLocalizations l10n,
) => switch (category) {
  'destructive_filesystem' ||
  'filesystem_delete' => l10n.text('risk.filesReason'),
  'permission_change' => l10n.text('risk.permission'),
  'git_remote_write' => l10n.text('risk.gitRemote'),
  'git_worktree_destructive' => l10n.text('risk.gitWorktree'),
  'dependency_install' => l10n.text('risk.dependencies'),
  'process_control' => l10n.text('risk.process'),
  'untrusted_command' => l10n.text('risk.untrusted'),
  'shell_redirection' => l10n.text('risk.redirection'),
  'shell_parse' => l10n.text('risk.parse'),
  _ => fallback,
};

String _statusLabel(RunStatus status, SageLocalizations l10n) =>
    switch (status) {
      RunStatus.idle => l10n.text('status.idle'),
      RunStatus.starting => l10n.text('status.starting'),
      RunStatus.running => l10n.text('status.running'),
      RunStatus.suspending => l10n.text('status.suspending'),
      RunStatus.suspended => l10n.text('status.suspended'),
      RunStatus.completed => l10n.text('status.completed'),
      RunStatus.failed => l10n.text('status.failed'),
      RunStatus.cancelled => l10n.text('status.cancelled'),
    };

String _decisionLabel(String decision, SageLocalizations l10n) =>
    switch (decision) {
      'approve' => l10n.text('decision.approve'),
      'approve_once' => l10n.text('decision.approveOnce'),
      'approve_and_remember' => l10n.text('decision.approveAndRemember'),
      'allow' => l10n.text('decision.allow'),
      'deny' => l10n.text('decision.deny'),
      'cancel' => l10n.text('common.cancel'),
      'submit' => l10n.text('decision.submit'),
      'confirm_succeeded' => l10n.text('decision.confirmSucceeded'),
      'mark_failed' => l10n.text('decision.markFailed'),
      'continue' => _localizedRuntimeDecision('continue', l10n.languageCode),
      'change_direction' => _localizedRuntimeDecision(
        'change_direction',
        l10n.languageCode,
      ),
      'reconcile' => _localizedRuntimeDecision('reconcile', l10n.languageCode),
      'retry' => l10n.text('common.retry'),
      _ => decision,
    };

String _interactionDecisionLabel(
  String decision,
  String? toolName,
  SageLocalizations l10n,
) {
  if (toolName == 'goal_submit' &&
      {'approve', 'approve_once', 'approve_and_remember'}.contains(decision)) {
    return switch (l10n.languageCode) {
      'zh' => '批准计划',
      'pt' => 'Aprovar plano',
      'es' => 'Aprobar plan',
      'fr' => 'Approuver le plan',
      'de' => 'Plan genehmigen',
      'ja' => '計画を承認',
      'ko' => '계획 승인',
      'ru' => 'Утвердить план',
      _ => 'Approve plan',
    };
  }
  return _decisionLabel(decision, l10n);
}

String _localizedRuntimeDecision(String decision, String language) {
  const values = <String, Map<String, String>>{
    'continue': {
      'zh': '继续',
      'en': 'Continue',
      'pt': 'Continuar',
      'es': 'Continuar',
      'fr': 'Continuer',
      'de': 'Fortfahren',
      'ja': '続行',
      'ko': '계속',
      'ru': 'Продолжить',
    },
    'change_direction': {
      'zh': '改变方向',
      'en': 'Change direction',
      'pt': 'Mudar direção',
      'es': 'Cambiar de dirección',
      'fr': 'Changer de direction',
      'de': 'Richtung ändern',
      'ja': '方針を変更',
      'ko': '방향 변경',
      'ru': 'Изменить направление',
    },
    'reconcile': {
      'zh': '核对工具结果',
      'en': 'Check Tool result',
      'pt': 'Verificar resultado',
      'es': 'Comprobar resultado',
      'fr': 'Vérifier le résultat',
      'de': 'Ergebnis prüfen',
      'ja': 'ツール結果を確認',
      'ko': '도구 결과 확인',
      'ru': 'Проверить результат',
    },
  };
  return values[decision]?[language] ?? values[decision]?['en'] ?? decision;
}
