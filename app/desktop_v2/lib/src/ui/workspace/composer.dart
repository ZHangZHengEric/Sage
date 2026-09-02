part of '../workspace_screen.dart';

class _Composer extends StatefulWidget {
  const _Composer({required this.controller, required this.conversation});

  final WorkspaceController controller;
  final Conversation conversation;

  @override
  State<_Composer> createState() => _ComposerState();
}

class _ComposerState extends State<_Composer> {
  late final _ComposerTextEditingController _text;
  final _focus = FocusNode();
  final _editorRegionKey = GlobalKey();
  OverlayEntry? _referenceHoverOverlay;
  ComposerReference? _hoveredReference;
  Offset _hoverPosition = Offset.zero;

  @override
  void initState() {
    super.initState();
    _text = _ComposerTextEditingController(
      onReferencesRemoved: _removeDeletedReferences,
    );
    widget.controller.addListener(_syncComposerReferences);
    _syncComposerReferences();
  }

  @override
  void didUpdateWidget(covariant _Composer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_syncComposerReferences);
      widget.controller.addListener(_syncComposerReferences);
    }
    if (oldWidget.conversation.id != widget.conversation.id) {
      _text.reset();
    }
    _syncComposerReferences();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_syncComposerReferences);
    _hideReferenceHover();
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _syncComposerReferences() {
    final references = widget.controller.composerReferences;
    _text.syncReferences(references);
    if (_hoveredReference != null && !references.contains(_hoveredReference)) {
      _hideReferenceHover();
    }
  }

  void _removeDeletedReferences(List<ComposerReference> references) {
    for (final reference in references) {
      if (widget.controller.composerReferences.contains(reference)) {
        widget.controller.removeComposerReference(reference);
      }
    }
  }

  void _submit() {
    final value = _text.promptText.trim();
    if (value.isEmpty) return;
    widget.controller.send(value);
    _text.reset();
    widget.controller.clearComposerReferences(widget.conversation.id);
    _focus.requestFocus();
  }

  void _handleEditorHover(PointerHoverEvent event) {
    final reference = _referenceAt(event.position);
    if (reference == null) {
      _hideReferenceHover();
      return;
    }
    _hoveredReference = reference;
    _hoverPosition = event.position;
    if (_referenceHoverOverlay == null) {
      _referenceHoverOverlay = OverlayEntry(builder: _buildReferenceHover);
      Overlay.of(context, rootOverlay: true).insert(_referenceHoverOverlay!);
    } else {
      _referenceHoverOverlay!.markNeedsBuild();
    }
  }

  ComposerReference? _referenceAt(Offset globalPosition) {
    final root = _editorRegionKey.currentContext?.findRenderObject();
    final editable = _findRenderEditable(root);
    if (editable == null) return null;
    final origin = editable.localToGlobal(Offset.zero);
    for (final token in _text.referenceTokens) {
      final boxes = editable.getBoxesForSelection(
        TextSelection(baseOffset: token.offset, extentOffset: token.offset + 1),
      );
      for (final box in boxes) {
        if (box.toRect().shift(origin).inflate(2).contains(globalPosition)) {
          return token.reference;
        }
      }
    }
    return null;
  }

  Widget _buildReferenceHover(BuildContext overlayContext) {
    final reference = _hoveredReference;
    if (reference == null) return const SizedBox.shrink();
    final screen = MediaQuery.sizeOf(overlayContext);
    final width = min(520.0, max(220.0, screen.width - 32));
    final left = (_hoverPosition.dx + 12)
        .clamp(16.0, max(16.0, screen.width - width - 16))
        .toDouble();
    final top = (_hoverPosition.dy + 18)
        .clamp(16.0, max(16.0, screen.height - 260))
        .toDouble();
    final colors = Theme.of(overlayContext).colorScheme;
    return Positioned(
      left: left,
      top: top,
      width: width,
      child: IgnorePointer(
        child: Material(
          key: const ValueKey('composer-inline-reference-hover'),
          elevation: 10,
          color: colors.surfaceContainerHigh,
          shadowColor: colors.shadow.withValues(alpha: 0.28),
          borderRadius: BorderRadius.circular(12),
          clipBehavior: Clip.antiAlias,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 240),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    reference.displayPath,
                    style: Theme.of(overlayContext).textTheme.labelMedium
                        ?.copyWith(
                          color: colors.primary,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  const SizedBox(height: 8),
                  if (reference.text.isNotEmpty)
                    Text(
                      reference.text,
                      style: Theme.of(
                        overlayContext,
                      ).textTheme.bodyMedium?.copyWith(height: 1.45),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _hideReferenceHover() {
    _referenceHoverOverlay?.remove();
    _referenceHoverOverlay = null;
    _hoveredReference = null;
  }

  KeyEventResult _handleKey(KeyEvent event) {
    if (event is! KeyDownEvent ||
        (event.logicalKey != LogicalKeyboardKey.enter &&
            event.logicalKey != LogicalKeyboardKey.numpadEnter)) {
      return KeyEventResult.ignored;
    }
    final composing = _text.value.composing;
    if (composing.isValid && !composing.isCollapsed) {
      return KeyEventResult.ignored;
    }
    if (HardwareKeyboard.instance.isShiftPressed) {
      final value = _text.value;
      final selection = value.selection;
      final offset = selection.isValid ? selection.start : value.text.length;
      final end = selection.isValid ? selection.end : value.text.length;
      final next = value.text.replaceRange(offset, end, '\n');
      _text.value = value.copyWith(
        text: next,
        selection: TextSelection.collapsed(offset: offset + 1),
        composing: TextRange.empty,
      );
      return KeyEventResult.handled;
    }
    _submit();
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) {
    final running = {
      RunStatus.starting,
      RunStatus.running,
      RunStatus.suspending,
    }.contains(widget.conversation.status);
    final approvalLocked = {
      RunStatus.starting,
      RunStatus.running,
      RunStatus.suspending,
      RunStatus.suspended,
    }.contains(widget.conversation.status);
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return DecoratedBox(
      key: const ValueKey('thread-composer-surface'),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: dark ? 0.48 : 0.95),
          width: dark ? 1 : 1.15,
        ),
        boxShadow: dark
            ? [
                BoxShadow(
                  color: colors.shadow.withValues(alpha: 0.16),
                  blurRadius: 18,
                  offset: const Offset(0, 10),
                ),
              ]
            : [
                BoxShadow(
                  color: colors.shadow.withValues(alpha: 0.12),
                  blurRadius: 28,
                  spreadRadius: 1,
                  offset: const Offset(0, 14),
                ),
                BoxShadow(
                  color: const Color(0xFF667085).withValues(alpha: 0.12),
                  blurRadius: 8,
                  offset: const Offset(0, 1),
                ),
              ],
      ),
      child: GlassCard(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
        shape: const LiquidRoundedSuperellipse(borderRadius: 24),
        useOwnLayer: true,
        settings: _composerGlassSettings(context),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _ComposerAssetShelf(
              assets: widget.controller.attachments,
              onRemoved: widget.controller.removeAttachment,
            ),
            _ComposerSkillShelf(
              skills: widget.controller.preferredSkills.toList()..sort(),
              onRemoved: widget.controller.toggleSkill,
            ),
            ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 36, maxHeight: 124),
              child: MouseRegion(
                key: _editorRegionKey,
                onHover: _handleEditorHover,
                onExit: (_) => _hideReferenceHover(),
                child: Focus(
                  onKeyEvent: (_, event) => _handleKey(event),
                  child: TextField(
                    key: const ValueKey('agent-composer'),
                    controller: _text,
                    focusNode: _focus,
                    minLines: 1,
                    maxLines: null,
                    textInputAction: TextInputAction.newline,
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                      fontSize: 14.5,
                      height: 1.35,
                      color: colors.onSurface,
                    ),
                    decoration: InputDecoration(
                      hintText: context.l10n.text(
                        running
                            ? 'workspace.inputSteer'
                            : widget.conversation.planMode
                            ? 'workspace.inputPlan'
                            : widget.conversation.goalMode
                            ? 'workspace.inputGoal'
                            : 'workspace.inputAgent',
                      ),
                      hintStyle: Theme.of(context).textTheme.bodyLarge
                          ?.copyWith(
                            fontSize: 14.5,
                            color: colors.onSurfaceVariant.withValues(
                              alpha: dark ? 0.68 : 0.76,
                            ),
                          ),
                      isDense: true,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      filled: false,
                      contentPadding: EdgeInsets.zero,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            LayoutBuilder(
              builder: (context, constraints) {
                final approvalLabelPainter = TextPainter(
                  text: TextSpan(
                    text: _approvalModeLabel(
                      widget.conversation.approvalMode,
                      context.l10n,
                    ),
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  textDirection: Directionality.of(context),
                  textScaler: MediaQuery.textScalerOf(context),
                  maxLines: 1,
                )..layout();
                final compactApproval =
                    constraints.maxWidth < 400 + approvalLabelPainter.width;
                final compactAgent = constraints.maxWidth < 310;
                final controlGap = compactApproval ? 5.0 : 8.0;
                return Row(
                  children: [
                    _SkillPicker(
                      controller: widget.controller,
                      conversation: widget.conversation,
                    ),
                    SizedBox(width: controlGap),
                    Container(
                      key: const ValueKey('composer-control-cluster'),
                      padding: const EdgeInsets.symmetric(horizontal: 2),
                      decoration: BoxDecoration(
                        color: colors.surfaceContainerHighest.withValues(
                          alpha: dark ? 0.18 : 0.28,
                        ),
                        borderRadius: BorderRadius.circular(11),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _AgentPicker(
                            controller: widget.controller,
                            compact: compactAgent,
                          ),
                          const _ComposerToolbarDivider(),
                          _ApprovalModePicker(
                            controller: widget.controller,
                            conversation: widget.conversation,
                            compact: compactApproval,
                            enabled: !approvalLocked,
                          ),
                        ],
                      ),
                    ),
                    const Spacer(),
                    ValueListenableBuilder<TextEditingValue>(
                      valueListenable: _text,
                      builder: (context, value, _) => _ComposerSendButton(
                        enabled: widget.controller.canSend || running,
                        running: running,
                        hasDraft:
                            value.text.trim().isNotEmpty ||
                            widget.controller.composerReferences.isNotEmpty,
                        onSend: _submit,
                        onStop: widget.controller.cancel,
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

RenderEditable? _findRenderEditable(RenderObject? root) {
  if (root is RenderEditable) return root;
  RenderEditable? result;
  root?.visitChildren((child) {
    result ??= _findRenderEditable(child);
  });
  return result;
}

class _ComposerReferenceToken {
  _ComposerReferenceToken({required this.reference, required this.offset});

  final ComposerReference reference;
  int offset;
}

class _ComposerTextEditingController extends TextEditingController {
  _ComposerTextEditingController({required this.onReferencesRemoved});

  static const _placeholder = '\uFFFC';

  final ValueChanged<List<ComposerReference>> onReferencesRemoved;
  final List<_ComposerReferenceToken> _tokens = [];
  bool _internalUpdate = false;

  List<_ComposerReferenceToken> get referenceTokens =>
      List.unmodifiable(_tokens);

  void syncReferences(List<ComposerReference> references) {
    final removed = [
      for (final token in _tokens)
        if (!references.contains(token.reference)) token,
    ]..sort((left, right) => right.offset.compareTo(left.offset));
    if (removed.isNotEmpty) {
      var nextText = text;
      var nextSelection = selection;
      for (final token in removed) {
        if (token.offset < nextText.length &&
            nextText[token.offset] == _placeholder) {
          nextText = nextText.replaceRange(token.offset, token.offset + 1, '');
          nextSelection = _selectionAfterRemoval(nextSelection, token.offset);
        }
        _tokens.remove(token);
        for (final remaining in _tokens) {
          if (remaining.offset > token.offset) remaining.offset--;
        }
      }
      _setInternalValue(
        value.copyWith(
          text: nextText,
          selection: nextSelection,
          composing: TextRange.empty,
        ),
      );
    }
    for (final reference in references) {
      if (_tokens.any((token) => identical(token.reference, reference))) {
        continue;
      }
      _insertReference(reference);
    }
  }

  void _insertReference(ComposerReference reference) {
    final selectedOffset = selection.isValid
        ? selection.extentOffset
        : text.length;
    final offset = selectedOffset.clamp(0, text.length);
    for (final token in _tokens) {
      if (token.offset >= offset) token.offset++;
    }
    _tokens.add(_ComposerReferenceToken(reference: reference, offset: offset));
    _tokens.sort((left, right) => left.offset.compareTo(right.offset));
    final nextText = text.replaceRange(offset, offset, _placeholder);
    _setInternalValue(
      TextEditingValue(
        text: nextText,
        selection: TextSelection.collapsed(offset: offset + 1),
      ),
    );
  }

  TextSelection _selectionAfterRemoval(
    TextSelection current,
    int removedOffset,
  ) {
    if (!current.isValid) return current;
    int shift(int value) => value > removedOffset ? value - 1 : value;
    return current.copyWith(
      baseOffset: shift(current.baseOffset),
      extentOffset: shift(current.extentOffset),
    );
  }

  @override
  set value(TextEditingValue newValue) {
    if (_internalUpdate) {
      super.value = newValue;
      return;
    }
    final previousText = text;
    final removedReferences = _reconcileExternalEdit(
      previousText,
      newValue.text,
    );
    super.value = newValue;
    if (removedReferences.isNotEmpty) {
      onReferencesRemoved(removedReferences);
    }
  }

  List<ComposerReference> _reconcileExternalEdit(
    String previousText,
    String nextText,
  ) {
    var prefix = 0;
    final shortest = min(previousText.length, nextText.length);
    while (prefix < shortest &&
        previousText.codeUnitAt(prefix) == nextText.codeUnitAt(prefix)) {
      prefix++;
    }
    var suffix = 0;
    while (suffix < previousText.length - prefix &&
        suffix < nextText.length - prefix &&
        previousText.codeUnitAt(previousText.length - suffix - 1) ==
            nextText.codeUnitAt(nextText.length - suffix - 1)) {
      suffix++;
    }
    final previousEnd = previousText.length - suffix;
    final nextEnd = nextText.length - suffix;
    final removed = [
      for (final token in _tokens)
        if (token.offset >= prefix && token.offset < previousEnd) token,
    ];
    _tokens.removeWhere(removed.contains);
    final shift = nextEnd - previousEnd;
    for (final token in _tokens) {
      if (token.offset >= previousEnd) token.offset += shift;
    }
    return [for (final token in removed) token.reference];
  }

  String get promptText {
    final ordered = [..._tokens]
      ..sort((left, right) => left.offset.compareTo(right.offset));
    final buffer = StringBuffer();
    var cursor = 0;
    for (final token in ordered) {
      if (token.offset < cursor || token.offset >= text.length) continue;
      buffer.write(text.substring(cursor, token.offset));
      buffer.write('\n\n${token.reference.promptText}\n\n');
      cursor = token.offset + 1;
    }
    buffer.write(text.substring(cursor));
    return buffer.toString();
  }

  void reset() {
    _tokens.clear();
    _setInternalValue(TextEditingValue.empty);
  }

  void _setInternalValue(TextEditingValue next) {
    _internalUpdate = true;
    try {
      value = next;
    } finally {
      _internalUpdate = false;
    }
  }

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    final tokensByOffset = {for (final token in _tokens) token.offset: token};
    final children = <InlineSpan>[];
    var cursor = 0;
    for (var offset = 0; offset < text.length; offset++) {
      final token = tokensByOffset[offset];
      if (token == null || text[offset] != _placeholder) continue;
      if (cursor < offset) {
        children.add(TextSpan(text: text.substring(cursor, offset)));
      }
      children.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: _ComposerInlineReferenceItem(reference: token.reference),
        ),
      );
      cursor = offset + 1;
    }
    if (cursor < text.length) {
      children.add(TextSpan(text: text.substring(cursor)));
    }
    return TextSpan(style: style, children: children);
  }
}

class _ComposerInlineReferenceItem extends StatelessWidget {
  const _ComposerInlineReferenceItem({required this.reference});

  final ComposerReference reference;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final normalized = reference.text.replaceAll(RegExp(r'\s+'), ' ').trim();
    final preview = normalized.length > 24
        ? '${normalized.substring(0, 24)}…'
        : normalized;
    final label = preview.isEmpty
        ? reference.fileName
        : '${reference.fileName} · $preview';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 1),
      child: Container(
        key: const ValueKey('composer-inline-reference'),
        height: 25,
        constraints: BoxConstraints(
          maxWidth: min(280, MediaQuery.sizeOf(context).width * 0.42),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: colors.primaryContainer.withValues(alpha: 0.42),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(color: colors.primary.withValues(alpha: 0.24)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              reference.isDirectory
                  ? CupertinoIcons.folder
                  : reference.text.isEmpty
                  ? CupertinoIcons.doc
                  : CupertinoIcons.quote_bubble,
              size: 11,
              color: colors.primary,
            ),
            const SizedBox(width: 5),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  fontSize: 11,
                  color: colors.onSurface,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ComposerAssetShelf extends StatelessWidget {
  const _ComposerAssetShelf({required this.assets, required this.onRemoved});

  final List<UploadedAttachment> assets;
  final ValueChanged<UploadedAttachment> onRemoved;

  @override
  Widget build(BuildContext context) {
    if (assets.isEmpty) return const SizedBox.shrink();
    final colors = Theme.of(context).colorScheme;
    return Padding(
      key: const ValueKey('composer-asset-shelf'),
      padding: const EdgeInsets.only(bottom: 12),
      child: SizedBox(
        height: 74,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: assets.length,
          separatorBuilder: (_, _) => const SizedBox(width: 8),
          itemBuilder: (context, index) {
            final asset = assets[index];
            final isImage = _isPreviewableImage(asset.path);
            return Stack(
              clipBehavior: Clip.none,
              children: [
                Container(
                  width: 74,
                  height: 74,
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHighest.withValues(
                      alpha: 0.38,
                    ),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(
                      color: colors.outlineVariant.withValues(alpha: 0.72),
                    ),
                  ),
                  child: isImage
                      ? Image.file(File(asset.path), fit: BoxFit.cover)
                      : Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              _assetIcon(asset),
                              size: 24,
                              color: colors.onSurfaceVariant,
                            ),
                            const SizedBox(height: 6),
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 6,
                              ),
                              child: Text(
                                asset.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.labelMedium
                                    ?.copyWith(
                                      color: colors.onSurfaceVariant,
                                      fontSize: 10,
                                    ),
                              ),
                            ),
                          ],
                        ),
                ),
                Positioned(
                  right: -7,
                  top: -7,
                  child: InkWell(
                    onTap: () => onRemoved(asset),
                    borderRadius: BorderRadius.circular(11),
                    child: Container(
                      width: 22,
                      height: 22,
                      decoration: BoxDecoration(
                        color: colors.surface,
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: colors.outlineVariant.withValues(alpha: 0.8),
                        ),
                      ),
                      child: Icon(
                        CupertinoIcons.xmark,
                        size: 11,
                        color: colors.onSurface,
                      ),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ComposerSkillShelf extends StatelessWidget {
  const _ComposerSkillShelf({required this.skills, required this.onRemoved});

  final List<String> skills;
  final ValueChanged<String> onRemoved;

  @override
  Widget build(BuildContext context) {
    if (skills.isEmpty) return const SizedBox.shrink();
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: SizedBox(
        height: 30,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: skills.length,
          separatorBuilder: (_, _) => const SizedBox(width: 7),
          itemBuilder: (context, index) {
            final skill = skills[index];
            return GlassCard(
              key: ValueKey('composer-selected-skill:$skill'),
              padding: const EdgeInsets.only(left: 9, right: 4),
              shape: const LiquidRoundedSuperellipse(borderRadius: 14),
              useOwnLayer: true,
              settings: LiquidGlassSettings(
                visibility: dark ? 0.78 : 0.82,
                glassColor: colors.primaryContainer.withValues(
                  alpha: dark ? 0.22 : 0.26,
                ),
                thickness: 7,
                blur: 3,
                chromaticAberration: 0,
                lightIntensity: 0.22,
                saturation: dark ? 1.02 : 1.06,
                glowIntensity: 0,
                standardOpacityMultiplier: dark ? 0.74 : 0.7,
                shadowElevation: 0.06,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    CupertinoIcons.sparkles,
                    size: 12,
                    color: colors.primary,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    skill,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontSize: 11.5,
                      color: colors.onSurface,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(width: 2),
                  InkWell(
                    key: ValueKey('composer-remove-skill:$skill'),
                    borderRadius: BorderRadius.circular(12),
                    onTap: () => onRemoved(skill),
                    child: Padding(
                      padding: const EdgeInsets.all(5),
                      child: Icon(
                        CupertinoIcons.xmark,
                        size: 10,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

bool _isPreviewableImage(String path) {
  final lower = path.toLowerCase();
  return lower.endsWith('.png') ||
      lower.endsWith('.jpg') ||
      lower.endsWith('.jpeg') ||
      lower.endsWith('.webp') ||
      lower.endsWith('.gif');
}

IconData _assetIcon(UploadedAttachment asset) {
  if (asset.isDirectory) return CupertinoIcons.folder;
  final lower = asset.name.toLowerCase();
  if (lower.endsWith('.mp4') || lower.endsWith('.mov')) {
    return CupertinoIcons.film;
  }
  if (lower.endsWith('.pdf')) return CupertinoIcons.doc_richtext;
  return CupertinoIcons.doc_text;
}

class _AgentPicker extends StatefulWidget {
  const _AgentPicker({required this.controller, this.compact = false});

  final WorkspaceController controller;
  final bool compact;

  @override
  State<_AgentPicker> createState() => _AgentPickerState();
}

class _AgentPickerState extends State<_AgentPicker> {
  final LayerLink _layerLink = LayerLink();
  final Object _tapRegionGroupId = Object();
  OverlayEntry? _overlayEntry;

  bool get _isOpen => _overlayEntry != null;

  @override
  void dispose() {
    _overlayEntry?.remove();
    super.dispose();
  }

  void _toggle() => _isOpen ? _close() : _open();

  void _open() {
    if (_isOpen) return;
    _overlayEntry = OverlayEntry(
      builder: (context) => Positioned(
        width: 220,
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: Alignment.topLeft,
          followerAnchor: Alignment.bottomLeft,
          offset: const Offset(0, -8),
          child: TapRegion(
            groupId: _tapRegionGroupId,
            child: _ComposerGlassMenu(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 286),
                child: ListView(
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  children: [
                    for (final agent in widget.controller.agents)
                      _ComposerMenuItem(
                        selected: agent.id == widget.controller.selectedAgentId,
                        icon: CupertinoIcons.person_crop_circle,
                        label: agent.name,
                        onTap: () {
                          _close();
                          widget.controller.selectAgent(agent.id);
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
    Overlay.of(context).insert(_overlayEntry!);
    setState(() {});
  }

  void _close() {
    final entry = _overlayEntry;
    if (entry == null) return;
    _overlayEntry = null;
    entry.remove();
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final selected = widget.controller.agents
        .where((value) => value.id == widget.controller.selectedAgentId)
        .firstOrNull;
    return TapRegion(
      groupId: _tapRegionGroupId,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _layerLink,
        child: Tooltip(
          message: context.l10n.text('workspace.chooseAgent'),
          child: InkWell(
            key: const ValueKey('agent-picker'),
            borderRadius: BorderRadius.circular(9),
            onTap: _toggle,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 140),
              curve: Curves.easeOutCubic,
              padding: EdgeInsets.symmetric(
                horizontal: widget.compact ? 8 : 10,
                vertical: 6,
              ),
              decoration: BoxDecoration(
                color: _isOpen
                    ? colors.primary.withValues(alpha: 0.12)
                    : Colors.transparent,
                borderRadius: BorderRadius.circular(9),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    CupertinoIcons.person_crop_circle,
                    size: 13,
                    color: colors.onSurfaceVariant,
                  ),
                  if (!widget.compact) ...[
                    const SizedBox(width: 5),
                    Text(
                      selected?.name ?? context.l10n.text('settings.agent'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: _isOpen ? 0.5 : 0,
                    duration: const Duration(milliseconds: 150),
                    curve: Curves.easeOutCubic,
                    child: Icon(
                      CupertinoIcons.chevron_down,
                      size: 11,
                      color: colors.onSurfaceVariant.withValues(alpha: 0.78),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerToolbarDivider extends StatelessWidget {
  const _ComposerToolbarDivider();

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      width: 1,
      height: 16,
      margin: const EdgeInsets.symmetric(horizontal: 1),
      color: colors.outlineVariant.withValues(alpha: 0.34),
    );
  }
}

class _ApprovalModePicker extends StatefulWidget {
  const _ApprovalModePicker({
    required this.controller,
    required this.conversation,
    required this.compact,
    required this.enabled,
  });

  final WorkspaceController controller;
  final Conversation conversation;
  final bool compact;
  final bool enabled;

  @override
  State<_ApprovalModePicker> createState() => _ApprovalModePickerState();
}

class _ApprovalModePickerState extends State<_ApprovalModePicker> {
  final LayerLink _layerLink = LayerLink();
  final Object _tapRegionGroupId = Object();
  OverlayEntry? _overlayEntry;

  bool get _isOpen => _overlayEntry != null;

  @override
  void dispose() {
    _overlayEntry?.remove();
    super.dispose();
  }

  void _toggle() => _isOpen ? _close() : _open();

  void _open() {
    if (_isOpen || !widget.enabled) return;
    _overlayEntry = OverlayEntry(
      builder: (context) => Positioned(
        width: 340,
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: Alignment.topLeft,
          followerAnchor: Alignment.bottomLeft,
          offset: const Offset(0, -8),
          child: TapRegion(
            groupId: _tapRegionGroupId,
            child: _ComposerGlassMenu(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final option in ApprovalMode.values)
                    _ComposerMenuItem(
                      key: ValueKey('approval-mode-${option.wireValue}'),
                      selected: option == widget.conversation.approvalMode,
                      icon: _approvalModeIcon(option),
                      label: _approvalModeLabel(option, context.l10n),
                      description: _approvalModeDescription(
                        option,
                        context.l10n,
                      ),
                      onTap: () {
                        _close();
                        widget.controller.setApprovalMode(option);
                      },
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    Overlay.of(context).insert(_overlayEntry!);
    setState(() {});
  }

  void _close() {
    final entry = _overlayEntry;
    if (entry == null) return;
    _overlayEntry = null;
    entry.remove();
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final mode = widget.conversation.approvalMode;
    return TapRegion(
      groupId: _tapRegionGroupId,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _layerLink,
        child: Semantics(
          button: true,
          enabled: widget.enabled,
          label: context.l10n.text('workspace.approvalMode', {
            'mode': _approvalModeLabel(mode, context.l10n),
          }),
          child: InkWell(
            key: const ValueKey('approval-mode-picker'),
            borderRadius: BorderRadius.circular(9),
            onTap: widget.enabled ? _toggle : null,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 140),
              curve: Curves.easeOutCubic,
              padding: EdgeInsets.symmetric(
                horizontal: widget.compact ? 8 : 10,
                vertical: 6,
              ),
              decoration: BoxDecoration(
                color: _isOpen
                    ? colors.primary.withValues(alpha: 0.12)
                    : Colors.transparent,
                borderRadius: BorderRadius.circular(9),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    _approvalModeIcon(mode),
                    size: 13,
                    color: widget.enabled
                        ? colors.onSurfaceVariant
                        : colors.onSurfaceVariant.withValues(alpha: 0.45),
                  ),
                  if (!widget.compact) ...[
                    const SizedBox(width: 5),
                    Text(
                      _approvalModeLabel(mode, context.l10n),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: widget.enabled
                            ? colors.onSurface
                            : colors.onSurfaceVariant.withValues(alpha: 0.45),
                      ),
                    ),
                  ],
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: _isOpen ? 0.5 : 0,
                    duration: const Duration(milliseconds: 150),
                    curve: Curves.easeOutCubic,
                    child: Icon(
                      CupertinoIcons.chevron_down,
                      size: 11,
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerGlassMenu extends StatelessWidget {
  const _ComposerGlassMenu({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Material(
      color: Colors.transparent,
      child: GlassCard(
        padding: const EdgeInsets.symmetric(vertical: 6),
        shape: const LiquidRoundedSuperellipse(borderRadius: 16),
        useOwnLayer: true,
        settings: LiquidGlassSettings(
          visibility: dark ? 0.9 : 0.86,
          glassColor: dark
              ? const Color(0xFF242528).withValues(alpha: 0.64)
              : Colors.white.withValues(alpha: 0.68),
          thickness: 11,
          blur: 3,
          chromaticAberration: 0,
          lightIntensity: 0.26,
          saturation: dark ? 1 : 1.06,
          glowIntensity: 0,
          standardOpacityMultiplier: dark ? 0.84 : 0.78,
          shadowElevation: dark ? 0.18 : 0.24,
        ),
        child: child,
      ),
    );
  }
}

class _ComposerMenuItem extends StatelessWidget {
  const _ComposerMenuItem({
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
    this.description,
    super.key,
  });

  final bool selected;
  final IconData icon;
  final String label;
  final String? description;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final hasDescription = description?.isNotEmpty == true;
    return InkWell(
      borderRadius: BorderRadius.circular(11),
      onTap: onTap,
      child: Container(
        constraints: BoxConstraints(minHeight: hasDescription ? 56 : 38),
        margin: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          color: selected
              ? colors.primary.withValues(alpha: 0.12)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(11),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              size: 14,
              color: selected ? colors.primary : colors.onSurfaceVariant,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontSize: 12.5,
                      color: colors.onSurface,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (hasDescription) ...[
                    const SizedBox(height: 2),
                    Text(
                      description!,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontSize: 11,
                        height: 1.25,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 8),
            AnimatedOpacity(
              opacity: selected ? 1 : 0,
              duration: const Duration(milliseconds: 120),
              child: Icon(
                CupertinoIcons.check_mark,
                size: 13,
                color: colors.primary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _approvalModeLabel(ApprovalMode mode, SageLocalizations l10n) =>
    switch (mode) {
      ApprovalMode.alwaysAsk => l10n.text('approval.alwaysAsk'),
      ApprovalMode.highRisk => l10n.text('approval.highRisk'),
      ApprovalMode.autoApprove => l10n.text('approval.autoApprove'),
    };

String _approvalModeDescription(ApprovalMode mode, SageLocalizations l10n) =>
    switch (mode) {
      ApprovalMode.alwaysAsk => l10n.text('approval.alwaysAskDescription'),
      ApprovalMode.highRisk => l10n.text('approval.highRiskDescription'),
      ApprovalMode.autoApprove => l10n.text('approval.autoApproveDescription'),
    };

IconData _approvalModeIcon(ApprovalMode mode) => switch (mode) {
  ApprovalMode.alwaysAsk => CupertinoIcons.hand_raised,
  ApprovalMode.highRisk => CupertinoIcons.checkmark_shield,
  ApprovalMode.autoApprove => CupertinoIcons.lock_open,
};

class _SkillPicker extends StatefulWidget {
  const _SkillPicker({required this.controller, required this.conversation});

  final WorkspaceController controller;
  final Conversation conversation;

  @override
  State<_SkillPicker> createState() => _SkillPickerState();
}

class _SkillPickerState extends State<_SkillPicker> {
  final LayerLink _layerLink = LayerLink();
  final Object _tapRegionGroupId = Object();
  OverlayEntry? _overlayEntry;

  bool get _isOpen => _overlayEntry != null;

  @override
  void dispose() {
    _overlayEntry?.remove();
    super.dispose();
  }

  void _toggle() => _isOpen ? _close() : _open();

  void _open() {
    if (_isOpen) return;
    _overlayEntry = OverlayEntry(
      builder: (context) => Positioned(
        width: 260,
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: Alignment.topLeft,
          followerAnchor: Alignment.bottomLeft,
          offset: const Offset(0, -8),
          child: TapRegion(
            groupId: _tapRegionGroupId,
            child: _ComposerGlassMenu(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 286),
                child: ListView(
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  children: [
                    _ComposerMenuItem(
                      key: const ValueKey('composer-open-file-option'),
                      selected: false,
                      icon: CupertinoIcons.folder_open,
                      label: context.l10n.text('workspace.openFile'),
                      onTap: () {
                        _close();
                        widget.controller.chooseAndUploadFile();
                      },
                    ),
                    _ComposerMenuItem(
                      key: const ValueKey('composer-plan-mode-option'),
                      selected: widget.conversation.planMode,
                      icon: CupertinoIcons.lightbulb,
                      label: context.l10n.text('workspace.planMode'),
                      description: context.l10n.text(
                        'workspace.planModeDescription',
                      ),
                      onTap: () {
                        _close();
                        widget.controller.setInvocationMode(
                          widget.conversation.planMode
                              ? InvocationMode.normal
                              : InvocationMode.plan,
                        );
                      },
                    ),
                    _ComposerMenuItem(
                      key: const ValueKey('composer-goal-mode-option'),
                      selected: widget.conversation.goalMode,
                      icon: CupertinoIcons.scope,
                      label: context.l10n.text('workspace.goalMode'),
                      description: context.l10n.text(
                        'workspace.goalModeDescription',
                      ),
                      onTap: () {
                        _close();
                        widget.controller.setInvocationMode(
                          widget.conversation.goalMode
                              ? InvocationMode.normal
                              : InvocationMode.goal,
                        );
                      },
                    ),
                    Divider(
                      height: 7,
                      thickness: 1,
                      indent: 14,
                      endIndent: 14,
                      color: Theme.of(
                        context,
                      ).colorScheme.outlineVariant.withValues(alpha: 0.4),
                    ),
                    if (widget.controller.skills.isEmpty)
                      Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 10,
                        ),
                        child: Text(context.l10n.text('workspace.noSkills')),
                      ),
                    for (final skill in widget.controller.skills)
                      _ComposerMenuItem(
                        key: ValueKey('composer-skill-option:${skill.name}'),
                        selected: widget.controller.preferredSkills.contains(
                          skill.name,
                        ),
                        icon: CupertinoIcons.sparkles,
                        label: skill.name,
                        onTap: () {
                          _close();
                          widget.controller.toggleSkill(skill.name);
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
    Overlay.of(context).insert(_overlayEntry!);
    setState(() {});
  }

  void _close() {
    final entry = _overlayEntry;
    if (entry == null) return;
    _overlayEntry = null;
    entry.remove();
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return TapRegion(
      groupId: _tapRegionGroupId,
      onTapOutside: (_) => _close(),
      child: CompositedTransformTarget(
        link: _layerLink,
        child: Tooltip(
          message: context.l10n.text('workspace.addContent'),
          child: Semantics(
            key: const ValueKey('skill-picker'),
            button: true,
            child: InkWell(
              key: const ValueKey('composer-upload-button'),
              borderRadius: BorderRadius.circular(9),
              onTap: _toggle,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 140),
                curve: Curves.easeOutCubic,
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
                decoration: BoxDecoration(
                  color:
                      _isOpen ||
                          widget.conversation.invocationMode !=
                              InvocationMode.normal
                      ? colors.primary.withValues(alpha: 0.12)
                      : Colors.transparent,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  CupertinoIcons.add,
                  size: 20,
                  color:
                      _isOpen ||
                          widget.conversation.invocationMode !=
                              InvocationMode.normal
                      ? colors.primary
                      : colors.onSurfaceVariant,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ComposerSendButton extends StatelessWidget {
  const _ComposerSendButton({
    required this.enabled,
    required this.running,
    required this.hasDraft,
    required this.onSend,
    required this.onStop,
  });

  final bool enabled;
  final bool running;
  final bool hasDraft;
  final VoidCallback onSend;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final shouldStop = running && !hasDraft;
    return Semantics(
      key: const ValueKey('send-button'),
      button: true,
      label: context.l10n.text(
        shouldStop
            ? 'common.cancel'
            : running
            ? 'workspace.sendSteer'
            : 'workspace.send',
      ),
      child: InkWell(
        key: const ValueKey('thread-send-button'),
        onTap: enabled ? (shouldStop ? onStop : onSend) : null,
        borderRadius: BorderRadius.circular(17),
        child: SizedBox(
          width: 34,
          height: 34,
          child: Center(
            child: Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                color: dark ? Colors.white : Colors.black,
                shape: BoxShape.circle,
              ),
              child: Icon(
                shouldStop ? CupertinoIcons.stop_fill : CupertinoIcons.arrow_up,
                size: shouldStop ? 13 : 16,
                color: dark ? Colors.black : Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
