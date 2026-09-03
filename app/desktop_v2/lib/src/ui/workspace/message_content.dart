part of '../workspace_screen.dart';

class _ThreadScrollToBottomButton extends StatelessWidget {
  const _ThreadScrollToBottomButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => _GlassSurface(
    child: InkWell(
      key: const ValueKey('thread-scroll-to-bottom'),
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      child: const SizedBox(
        width: 36,
        height: 36,
        child: Icon(CupertinoIcons.arrow_down, size: 16),
      ),
    ),
  );
}

class _ThreadActionButton extends StatelessWidget {
  const _ThreadActionButton({
    required this.keyValue,
    required this.icon,
    required this.tooltip,
    required this.onTap,
  });

  final String keyValue;
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: InkWell(
          key: ValueKey(keyValue),
          borderRadius: BorderRadius.circular(8),
          hoverColor: colors.onSurface.withValues(alpha: 0.055),
          focusColor: colors.primary.withValues(alpha: 0.1),
          highlightColor: colors.onSurface.withValues(alpha: 0.075),
          splashColor: colors.onSurface.withValues(alpha: 0.08),
          onTap: onTap,
          child: SizedBox(
            width: 26,
            height: 26,
            child: Icon(
              icon,
              size: 12.5,
              color: colors.onSurfaceVariant.withValues(alpha: 0.62),
            ),
          ),
        ),
      ),
    );
  }
}

MarkdownStyleSheet _messageMarkdownStyle(BuildContext context) {
  final theme = Theme.of(context);
  final colors = theme.colorScheme;
  final base = MarkdownStyleSheet.fromTheme(theme);
  final body = theme.textTheme.bodyMedium?.copyWith(
    fontSize: 14.5,
    height: 1.55,
  );
  return base.copyWith(
    p: body,
    h1: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
    h2: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
    h3: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
    listBullet: body,
    blockquote: body?.copyWith(color: colors.onSurfaceVariant),
    code: theme.textTheme.bodySmall?.copyWith(
      fontFamily: 'Menlo',
      fontSize: 12.5,
      height: 1.45,
      color: colors.primary,
      backgroundColor: colors.primary.withValues(alpha: 0.09),
    ),
    codeblockPadding: EdgeInsets.zero,
    codeblockDecoration: const BoxDecoration(),
  );
}

enum _MessageReferenceKind { file, directory, quote }

class _MessageContentPart {
  const _MessageContentPart.markdown(this.value)
    : referenceKind = null,
      referenceSource = null,
      referencePreview = null;

  const _MessageContentPart.reference(
    this.value,
    this.referenceKind,
    this.referenceSource,
    this.referencePreview,
  );

  final String value;
  final _MessageReferenceKind? referenceKind;
  final String? referenceSource;
  final String? referencePreview;

  bool get isReference => referenceKind != null;
}

List<_MessageContentPart> _splitUserMessageContent(String data) {
  final lines = data.replaceAll('\r\n', '\n').split('\n');
  final parts = <_MessageContentPart>[];
  final markdownLines = <String>[];

  void flushMarkdown() {
    final markdown = markdownLines.join('\n').trim();
    markdownLines.clear();
    if (markdown.isNotEmpty) {
      parts.add(_MessageContentPart.markdown(markdown));
    }
  }

  for (var index = 0; index < lines.length; index++) {
    final match = RegExp(r'^\s*@(.+?)\s*$').firstMatch(lines[index]);
    if (match == null) {
      markdownLines.add(lines[index]);
      continue;
    }

    flushMarkdown();
    final source = match.group(1)!;
    final normalized = source
        .replaceAll('\\', '/')
        .replaceFirst(RegExp(r'/+$'), '');
    final label = normalized.split('/').lastOrNull ?? normalized;
    var next = index + 1;
    while (next < lines.length && lines[next].trim().isEmpty) {
      next++;
    }
    final kind = next < lines.length && lines[next].trimLeft().startsWith('>')
        ? _MessageReferenceKind.quote
        : label.contains('.')
        ? _MessageReferenceKind.file
        : _MessageReferenceKind.directory;
    String? preview;
    if (kind == _MessageReferenceKind.quote) {
      final quoted = <String>[];
      while (next < lines.length) {
        final line = lines[next].trimLeft();
        if (!line.startsWith('>')) break;
        quoted.add(line.substring(1).trimLeft());
        next++;
      }
      preview = quoted.join('\n').trim();
    }
    parts.add(_MessageContentPart.reference(label, kind, source, preview));
  }
  flushMarkdown();
  return parts;
}

class _UserMessageContent extends StatelessWidget {
  const _UserMessageContent({
    required this.data,
    this.content = const [],
    this.onReferenceSelection,
    this.onLoadReference,
    super.key,
  });

  final String data;
  final List<ChatMessageContent> content;
  final ValueChanged<String>? onReferenceSelection;
  final Future<WorkspaceFileContent> Function(String source)? onLoadReference;

  @override
  Widget build(BuildContext context) {
    if (content.any((part) => part.isReference)) {
      return _ConversationMarkdown(
        data: _structuredMessageMarkdown(content),
        onReferenceSelection: onReferenceSelection,
        inlineSyntaxes: [_MessageReferenceSyntax()],
        builders: {
          'sage-reference': _MessageReferenceBuilder(
            content: content,
            onLoadReference: onLoadReference,
          ),
        },
      );
    }
    final parts = _splitUserMessageContent(data);
    if (!parts.any((part) => part.isReference)) {
      return _ConversationMarkdown(
        data: data,
        onReferenceSelection: onReferenceSelection,
      );
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var index = 0; index < parts.length; index++) ...[
          if (index > 0) const SizedBox(height: 7),
          if (parts[index].isReference)
            _MessageReferenceChip(
              part: parts[index],
              onLoadReference: onLoadReference,
            )
          else
            _ConversationMarkdown(
              data: parts[index].value,
              onReferenceSelection: onReferenceSelection,
            ),
        ],
      ],
    );
  }
}

const _messageReferenceMarker = '\u{E000}sage-reference:';
const _messageReferenceMarkerEnd = '\u{E001}';

String _structuredMessageMarkdown(List<ChatMessageContent> content) {
  final markdown = StringBuffer();
  for (var index = 0; index < content.length; index++) {
    final part = content[index];
    if (part.isText) {
      markdown.write(part.text);
    } else if (part.isReference) {
      markdown.write(
        '$_messageReferenceMarker$index$_messageReferenceMarkerEnd',
      );
    }
  }
  return markdown.toString();
}

class _MessageReferenceSyntax extends md.InlineSyntax {
  _MessageReferenceSyntax()
    : super('$_messageReferenceMarker(\\d+)$_messageReferenceMarkerEnd');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    parser.addNode(
      md.Element.text('sage-reference', '')
        ..attributes['index'] = match.group(1)!,
    );
    return true;
  }
}

class _MessageReferenceBuilder extends MarkdownElementBuilder {
  _MessageReferenceBuilder({required this.content, this.onLoadReference});

  final List<ChatMessageContent> content;
  final Future<WorkspaceFileContent> Function(String source)? onLoadReference;

  @override
  Widget? visitElementAfterWithContext(
    BuildContext context,
    md.Element element,
    TextStyle? preferredStyle,
    TextStyle? parentStyle,
  ) {
    final index = int.tryParse(element.attributes['index'] ?? '');
    if (index == null || index < 0 || index >= content.length) return null;
    final reference = content[index];
    if (!reference.isReference) return null;
    final label = reference.citationLabel ?? reference.fileName;
    final kind = reference.quote.isNotEmpty
        ? _MessageReferenceKind.quote
        : reference.isDirectory
        ? _MessageReferenceKind.directory
        : _MessageReferenceKind.file;
    final chip = _MessageReferenceChip(
      part: _MessageContentPart.reference(
        label,
        kind,
        reference.path,
        reference.quote.isEmpty ? null : reference.quote,
      ),
      onLoadReference: onLoadReference,
    );
    return Text.rich(
      TextSpan(
        children: [
          WidgetSpan(alignment: PlaceholderAlignment.middle, child: chip),
        ],
      ),
    );
  }
}

class _MessageReferenceChip extends StatefulWidget {
  const _MessageReferenceChip({required this.part, this.onLoadReference});

  final _MessageContentPart part;
  final Future<WorkspaceFileContent> Function(String source)? onLoadReference;

  @override
  State<_MessageReferenceChip> createState() => _MessageReferenceChipState();
}

class _MessageReferenceChipState extends State<_MessageReferenceChip> {
  final LayerLink _layerLink = LayerLink();
  OverlayEntry? _previewOverlay;
  Future<WorkspaceFileContent>? _content;
  bool _hovered = false;
  bool _focused = false;

  _MessageContentPart get part => widget.part;

  @override
  void didUpdateWidget(covariant _MessageReferenceChip oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.part.referenceSource != part.referenceSource ||
        oldWidget.part.referencePreview != part.referencePreview) {
      _content = null;
      _previewOverlay?.markNeedsBuild();
    }
  }

  @override
  void dispose() {
    _previewOverlay?.remove();
    super.dispose();
  }

  void _updatePreviewVisibility() {
    if (_hovered || _focused) {
      _showPreview();
    } else {
      _previewOverlay?.remove();
      _previewOverlay = null;
    }
  }

  void _showPreview() {
    if (_previewOverlay != null) return;
    final source = part.referenceSource;
    if (part.referenceKind != _MessageReferenceKind.quote &&
        source != null &&
        widget.onLoadReference != null) {
      _content ??= widget.onLoadReference!(source);
    }
    _previewOverlay = OverlayEntry(builder: _buildPreviewOverlay);
    Overlay.of(context, rootOverlay: true).insert(_previewOverlay!);
  }

  Widget _buildPreviewOverlay(BuildContext overlayContext) {
    final renderObject = context.findRenderObject();
    if (renderObject is! RenderBox || !renderObject.attached) {
      return const SizedBox.shrink();
    }
    final screen = MediaQuery.sizeOf(overlayContext);
    final origin = renderObject.localToGlobal(Offset.zero);
    final below = screen.height - origin.dy - renderObject.size.height - 16;
    final above = origin.dy - 16;
    final showAbove = below < 180 && above > below;
    final alignRight =
        origin.dx + renderObject.size.width / 2 > screen.width / 2;
    final width = min(420.0, max(220.0, screen.width - 32));
    final availableHeight = showAbove ? above : below;
    final maxHeight = min(320.0, max(96.0, availableHeight - 8));
    return Positioned(
      left: 0,
      top: 0,
      width: width,
      child: IgnorePointer(
        child: CompositedTransformFollower(
          link: _layerLink,
          showWhenUnlinked: false,
          targetAnchor: showAbove
              ? (alignRight ? Alignment.topRight : Alignment.topLeft)
              : (alignRight ? Alignment.bottomRight : Alignment.bottomLeft),
          followerAnchor: showAbove
              ? (alignRight ? Alignment.bottomRight : Alignment.bottomLeft)
              : (alignRight ? Alignment.topRight : Alignment.topLeft),
          offset: Offset(0, showAbove ? -8 : 8),
          child: Material(
            color: Colors.transparent,
            child: GlassCard(
              key: ValueKey(
                'message-reference-preview:${part.referenceSource}',
              ),
              width: width,
              padding: const EdgeInsets.all(12),
              shape: const LiquidRoundedSuperellipse(borderRadius: 14),
              useOwnLayer: true,
              settings: _composerGlassSettings(overlayContext),
              child: ConstrainedBox(
                constraints: BoxConstraints(maxHeight: maxHeight),
                child: _buildPreviewContent(overlayContext),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildPreviewContent(BuildContext context) {
    final quoted = part.referencePreview;
    if (part.referenceKind == _MessageReferenceKind.quote &&
        quoted != null &&
        quoted.isNotEmpty) {
      return _MessageReferenceTextPreview(
        text: quoted,
        referenceSource: part.referenceSource,
      );
    }
    final content = _content;
    if (content == null) return _previewFallback(context, loading: false);
    return FutureBuilder<WorkspaceFileContent>(
      future: content,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return _previewFallback(context, loading: true);
        }
        final value = snapshot.data;
        if (snapshot.hasError || value == null) {
          return _previewFallback(context, loading: false);
        }
        if (value.isImage) {
          return Image.memory(
            value.bytes,
            key: ValueKey(
              'message-reference-preview-image:${part.referenceSource}',
            ),
            fit: BoxFit.contain,
            gaplessPlayback: true,
            semanticLabel: part.value,
            errorBuilder: (context, _, _) =>
                _previewFallback(context, loading: false),
          );
        }
        if (value.isText) {
          return _MessageReferenceTextPreview(
            text: utf8.decode(value.bytes, allowMalformed: true),
            referenceSource: part.referenceSource,
          );
        }
        return _previewFallback(context, loading: false);
      },
    );
  }

  Widget _previewFallback(BuildContext context, {required bool loading}) {
    final colors = Theme.of(context).colorScheme;
    return SizedBox(
      height: 72,
      child: Center(
        child: loading
            ? CupertinoActivityIndicator(
                radius: 8,
                color: colors.onSurfaceVariant,
              )
            : Icon(
                CupertinoIcons.doc,
                size: 24,
                color: colors.onSurfaceVariant,
              ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final animationsDisabled =
        MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    final icon = switch (part.referenceKind!) {
      _MessageReferenceKind.file => CupertinoIcons.doc,
      _MessageReferenceKind.directory => CupertinoIcons.folder,
      _MessageReferenceKind.quote => CupertinoIcons.quote_bubble,
    };
    return CompositedTransformTarget(
      link: _layerLink,
      child: MouseRegion(
        onEnter: (_) {
          setState(() => _hovered = true);
          _updatePreviewVisibility();
        },
        onExit: (_) {
          setState(() => _hovered = false);
          _updatePreviewVisibility();
        },
        child: Focus(
          onFocusChange: (focused) {
            setState(() => _focused = focused);
            _updatePreviewVisibility();
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 1),
            child: AnimatedContainer(
              key: ValueKey('message-reference-chip:${part.referenceSource}'),
              duration: animationsDisabled
                  ? Duration.zero
                  : const Duration(milliseconds: 160),
              curve: Curves.easeOutCubic,
              height: 25,
              constraints: BoxConstraints(
                maxWidth: min(280, MediaQuery.sizeOf(context).width * 0.42),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 8),
              decoration: BoxDecoration(
                color: colors.primaryContainer.withValues(
                  alpha: _hovered || _focused ? 0.56 : 0.42,
                ),
                borderRadius: BorderRadius.circular(7),
                border: Border.all(
                  color: colors.primary.withValues(
                    alpha: _hovered || _focused ? 0.38 : 0.24,
                  ),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, size: 11, color: colors.primary),
                  const SizedBox(width: 5),
                  Flexible(
                    child: Text(
                      part.value,
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
          ),
        ),
      ),
    );
  }
}

class _MessageReferenceTextPreview extends StatelessWidget {
  const _MessageReferenceTextPreview({
    required this.text,
    required this.referenceSource,
  });

  final String text;
  final String? referenceSource;

  @override
  Widget build(BuildContext context) {
    const maximumCharacters = 12000;
    final preview = text.length > maximumCharacters
        ? '${text.substring(0, maximumCharacters)}\n…'
        : text;
    return SingleChildScrollView(
      child: Text(
        preview,
        key: ValueKey('message-reference-preview-text:$referenceSource'),
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
          color: Theme.of(context).colorScheme.onSurface,
          fontFamily: 'Menlo',
          fontSize: 12.5,
          height: 1.45,
        ),
      ),
    );
  }
}

class _ConversationMarkdown extends StatelessWidget {
  const _ConversationMarkdown({
    required this.data,
    this.onReferenceSelection,
    this.inlineSyntaxes = const [],
    this.builders = const {},
    super.key,
  });

  final String data;
  final ValueChanged<String>? onReferenceSelection;
  final List<md.InlineSyntax> inlineSyntaxes;
  final Map<String, MarkdownElementBuilder> builders;

  @override
  Widget build(BuildContext context) {
    final markdown = MarkdownBody(
      data: data,
      selectable: false,
      fitContent: false,
      styleSheet: _messageMarkdownStyle(context),
      inlineSyntaxes: inlineSyntaxes,
      builders: {'pre': _MessageCodeBlockBuilder(), ...builders},
    );
    final callback = onReferenceSelection;
    if (callback == null) return SelectionArea(child: markdown);
    return _ReferenceableMessageSelectionArea(
      onReferenceSelection: callback,
      child: markdown,
    );
  }
}

class _ReferenceableMessageSelectionArea extends StatefulWidget {
  const _ReferenceableMessageSelectionArea({
    required this.child,
    required this.onReferenceSelection,
  });

  final Widget child;
  final ValueChanged<String> onReferenceSelection;

  @override
  State<_ReferenceableMessageSelectionArea> createState() =>
      _ReferenceableMessageSelectionAreaState();
}

class _ReferenceableMessageSelectionAreaState
    extends State<_ReferenceableMessageSelectionArea> {
  String _selection = '';

  @override
  Widget build(BuildContext context) {
    return SelectionArea(
      onSelectionChanged: (content) {
        _selection = content?.plainText ?? '';
      },
      contextMenuBuilder: (context, selectableRegionState) {
        final items = List<ContextMenuButtonItem>.of(
          selectableRegionState.contextMenuButtonItems,
        );
        if (_selection.trim().isNotEmpty) {
          items.add(
            ContextMenuButtonItem(
              label: context.l10n.text('workspace.referenceSelection'),
              onPressed: () {
                widget.onReferenceSelection(_selection);
                selectableRegionState.hideToolbar();
              },
            ),
          );
        }
        return AdaptiveTextSelectionToolbar.buttonItems(
          anchors: selectableRegionState.contextMenuAnchors,
          buttonItems: items,
        );
      },
      child: widget.child,
    );
  }
}

class _MessageCodeBlockBuilder extends MarkdownElementBuilder {
  String _source = '';
  String _language = '';

  @override
  bool isBlockElement() => true;

  @override
  void visitElementBefore(md.Element element) {
    _source = element.textContent;
    if (_source.endsWith('\n')) {
      _source = _source.substring(0, _source.length - 1);
    }
    _language = '';
    final children = element.children;
    if (children == null || children.isEmpty || children.first is! md.Element) {
      return;
    }
    final code = children.first as md.Element;
    final className = code.attributes['class'] ?? '';
    if (className.startsWith('language-')) {
      _language = className.substring('language-'.length);
    }
  }

  @override
  Widget visitElementAfterWithContext(
    BuildContext context,
    md.Element element,
    TextStyle? preferredStyle,
    TextStyle? parentStyle,
  ) {
    return _MessageCodeBlock(source: _source, language: _language);
  }
}

class _MessageCodeBlock extends StatelessWidget {
  const _MessageCodeBlock({required this.source, required this.language});

  final String source;
  final String language;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final label = language.trim().isEmpty
        ? context.l10n.text('common.sourceCode')
        : language.trim();
    return Container(
      key: const ValueKey('message-code-block'),
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 7),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(
          alpha: dark ? 0.46 : 0.64,
        ),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: dark ? 0.42 : 0.7),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: 32,
            padding: const EdgeInsets.only(left: 12, right: 5),
            decoration: BoxDecoration(
              color: colors.surfaceContainerHigh.withValues(
                alpha: dark ? 0.58 : 0.72,
              ),
              border: Border(
                bottom: BorderSide(
                  color: colors.outlineVariant.withValues(alpha: 0.46),
                ),
              ),
            ),
            child: Row(
              children: [
                Text(
                  label,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    fontFamily: 'Menlo',
                    fontSize: 10.5,
                    color: colors.onSurfaceVariant,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const Spacer(),
                Tooltip(
                  message: context.l10n.text('common.copy'),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(7),
                    onTap: () => Clipboard.setData(ClipboardData(text: source)),
                    child: Padding(
                      padding: const EdgeInsets.all(7),
                      child: Icon(
                        CupertinoIcons.doc_on_doc,
                        size: 12,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(13, 11, 13, 12),
            child: Text(
              source,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                fontFamily: 'Menlo',
                fontSize: 12.5,
                height: 1.5,
                color: colors.onSurface,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

String _messageTime(DateTime value) {
  final local = value.toLocal();
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$hour:$minute';
}

bool _isInlineQuestionnaire(PendingInteraction interaction) {
  final explicitQuestionnaire =
      interaction.type == 'questionnaire' ||
      (interaction.type == 'user_input' &&
          interaction.payload['source'] == 'questionnaire_async');
  if (!explicitQuestionnaire) {
    return false;
  }
  final questions = interaction.payload['questions'];
  return questions is List && questions.any((value) => value is Map);
}

PendingInteraction? _latestValidatedToolQuestionnaire(
  Conversation conversation,
) {
  final latestUser = conversation.messages
      .where((message) => message.role == 'user')
      .lastOrNull;
  if (latestUser == null) return null;
  for (final panel in conversation.processPanels.reversed) {
    if (panel.anchorMessageId != latestUser.id) continue;
    for (final activity in panel.activities.reversed) {
      if (activity.label.trim().toLowerCase() != 'questionnaire_async' ||
          activity.failed ||
          activity.result.trim().isEmpty) {
        continue;
      }
      Object? decoded;
      try {
        decoded = jsonDecode(activity.result);
      } on FormatException {
        continue;
      }
      if (decoded is! Map ||
          decoded['success'] != true ||
          decoded['validation_passed'] != true) {
        continue;
      }
      final questions = decoded['questions'];
      if (questions is! List || questions.isEmpty) continue;
      return PendingInteraction(
        id: 'questionnaire:${panel.runId}:${activity.id}',
        type: 'questionnaire',
        allowedDecisions: const ['submit'],
        payload: {
          'source': 'questionnaire_async',
          '_process_panel_id': panel.id,
          'title': decoded['title']?.toString() ?? '',
          'questions': questions,
          if (decoded['questionnaire_kind'] != null)
            'questionnaire_kind': decoded['questionnaire_kind'],
        },
      );
    }
  }
  return null;
}

String _questionnaireResponseMessage(
  PendingInteraction questionnaire,
  Map<String, Object?> answers,
  String responseLabel,
) {
  final title = questionnaire.payload['title']?.toString().trim() ?? '';
  final rawQuestions = questionnaire.payload['questions'];
  final lines = <String>[
    title.isEmpty ? responseLabel : '$responseLabel：$title',
  ];
  if (rawQuestions is List) {
    for (final entry in rawQuestions.indexed) {
      final raw = entry.$2;
      if (raw is! Map) continue;
      final question = raw.cast<Object?, Object?>();
      final id = question['id']?.toString() ?? 'q${entry.$1 + 1}';
      final text =
          question['title']?.toString() ??
          question['question']?.toString() ??
          question['text']?.toString() ??
          id;
      final rawAnswer = answers[id];
      final values = rawAnswer is List
          ? rawAnswer.map((value) => value.toString()).toList(growable: false)
          : [if (rawAnswer != null) rawAnswer.toString()];
      final labels = <String, String>{};
      final options = question['options'];
      if (options is List) {
        for (final option in options) {
          if (option is Map) {
            final value = option['value']?.toString() ?? '';
            final label = option['label']?.toString() ?? value;
            if (value.isNotEmpty) labels[value] = label;
          }
        }
      }
      lines
        ..add('${entry.$1 + 1}. $text')
        ..add(values.map((value) => labels[value] ?? value).join('、'));
    }
  }
  return lines.join('\n');
}

class _InlineQuestionnaireOtherAnswer {
  const _InlineQuestionnaireOtherAnswer();
}

class _InlineQuestionnaireCard extends StatefulWidget {
  const _InlineQuestionnaireCard({
    super.key,
    required this.interaction,
    required this.onReply,
  });

  final PendingInteraction interaction;
  final Future<void> Function(
    String decision, {
    String text,
    Map<String, Object?> payload,
  })
  onReply;

  @override
  State<_InlineQuestionnaireCard> createState() =>
      _InlineQuestionnaireCardState();
}

class _InlineQuestionnaireCardState extends State<_InlineQuestionnaireCard> {
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, Object?> _answers = {};
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _resetAnswers();
  }

  List<Map<String, Object?>> get _questions {
    final raw = widget.interaction.payload['questions'];
    if (raw is! List) return const [];
    return [
      for (final value in raw)
        if (value is Map) value.cast<String, Object?>(),
    ];
  }

  String _questionId(Map<String, Object?> question, int index) =>
      question['id']?.toString() ?? 'q${index + 1}';

  String _questionText(Map<String, Object?> question, int index) =>
      question['title']?.toString() ??
      question['question']?.toString() ??
      question['text']?.toString() ??
      _questionId(question, index);

  String _optionValue(Object? option) => option is Map
      ? option['value']?.toString() ?? option['label']?.toString() ?? ''
      : option?.toString() ?? '';

  String _optionLabel(Object? option) => option is Map
      ? option['label']?.toString() ?? option['value']?.toString() ?? ''
      : option?.toString() ?? '';

  @override
  void didUpdateWidget(covariant _InlineQuestionnaireCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.interaction.id == widget.interaction.id) return;
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    _controllers.clear();
    _resetAnswers();
    _submitting = false;
  }

  void _resetAnswers() {
    _answers.clear();
    for (final entry in _questions.indexed) {
      final question = entry.$2;
      final id = _questionId(question, entry.$1);
      final type = question['type']?.toString().trim().toLowerCase() ?? 'text';
      final defaultValue = question['default'];
      if ((type == 'multiple' ||
              type == 'multiple_choice' ||
              type == 'multi_choice') &&
          defaultValue is List) {
        _answers[id] = [for (final value in defaultValue) value.toString()];
      } else if ((type == 'single' || type == 'single_choice') &&
          defaultValue != null &&
          defaultValue.toString().isNotEmpty) {
        _answers[id] = defaultValue.toString();
      }
    }
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) return;
    final answers = <String, Object?>{};
    for (final entry in _questions.indexed) {
      final question = entry.$2;
      final id = _questionId(question, entry.$1);
      final type = question['type']?.toString().trim().toLowerCase() ?? 'text';
      final answer = _answers[id];
      if (type == 'text' || type == 'free_text') {
        answers[id] = _controllers[id]?.text.trim() ?? '';
      } else if (answer is _InlineQuestionnaireOtherAnswer) {
        answers[id] = _controllers[id]?.text.trim() ?? '';
      } else if (answer != null) {
        answers[id] = answer;
      }
    }
    final decisions = widget.interaction.allowedDecisions;
    final decision = decisions.contains('submit')
        ? 'submit'
        : decisions.firstWhere(
            (value) => value != 'cancel',
            orElse: () => 'submit',
          );
    setState(() => _submitting = true);
    try {
      await widget.onReply(
        decision,
        text: jsonEncode({'answers': answers}),
        payload: {'answers': answers},
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Widget _question(
    BuildContext context,
    Map<String, Object?> question,
    int index,
  ) {
    final id = _questionId(question, index);
    final text = _questionText(question, index);
    final type = question['type']?.toString().trim().toLowerCase() ?? 'text';
    final rawOptions = question['options'];
    final options = rawOptions is List ? rawOptions : const <Object?>[];
    final isMultiple =
        type == 'multiple' ||
        type == 'multiple_choice' ||
        type == 'multi_choice';
    final isSingle = type == 'single' || type == 'single_choice';
    final allowOther = question['allow_other'] == true;
    final otherSelected = _answers[id] is _InlineQuestionnaireOtherAnswer;
    final style = Theme.of(context).textTheme.bodyMedium?.copyWith(
      color: Theme.of(context).colorScheme.onSurface,
      fontSize: 13,
      height: 1.35,
    );

    return KeyedSubtree(
      key: ValueKey('questionnaire-question-$id'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (text.isNotEmpty) ...[
            Text(text, style: style?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
          ],
          if (isSingle || isMultiple)
            _InlineQuestionnaireOptionWrap(
              children: [
                for (final option in options)
                  _InlineQuestionnaireOptionPill(
                    key: ValueKey(
                      'interaction-question-$id-option-${_optionValue(option)}',
                    ),
                    label: _optionLabel(option),
                    selected: isMultiple
                        ? ((_answers[id] as List?) ?? const <Object?>[])
                              .map((value) => value.toString())
                              .contains(_optionValue(option))
                        : !otherSelected &&
                              _answers[id]?.toString() == _optionValue(option),
                    onTap: () {
                      if (isMultiple) {
                        final selected = <String>{
                          ...((_answers[id] as List?)?.map(
                                (value) => value.toString(),
                              ) ??
                              const <String>[]),
                        };
                        final value = _optionValue(option);
                        selected.contains(value)
                            ? selected.remove(value)
                            : selected.add(value);
                        setState(
                          () => _answers[id] = selected.toList(growable: false),
                        );
                      } else {
                        setState(() => _answers[id] = _optionValue(option));
                      }
                    },
                  ),
                if (isSingle && allowOther)
                  _InlineQuestionnaireOptionPill(
                    key: ValueKey('interaction-question-$id-option-other'),
                    label: context.l10n.text('questionnaire.other'),
                    selected: otherSelected,
                    onTap: () => setState(
                      () => _answers[id] =
                          const _InlineQuestionnaireOtherAnswer(),
                    ),
                  ),
              ],
            )
          else
            _InlineQuestionnaireTextField(
              key: ValueKey('interaction-question-$id-field'),
              controller: _controllers.putIfAbsent(
                id,
                () => TextEditingController(
                  text: question['default']?.toString() ?? '',
                ),
              ),
              fieldKey: ValueKey('interaction-question-$id'),
            ),
          if (isSingle && allowOther && otherSelected) ...[
            const SizedBox(height: 8),
            _InlineQuestionnaireTextField(
              key: ValueKey('interaction-question-$id-other-field'),
              controller: _controllers.putIfAbsent(
                id,
                TextEditingController.new,
              ),
              fieldKey: ValueKey('interaction-question-$id-other'),
              autofocus: true,
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final payload = widget.interaction.payload;
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final title = payload['title']?.toString().trim() ?? '';
    final prompt = payload['prompt']?.toString().trim() ?? '';
    final heading = title.isNotEmpty ? title : prompt;
    final style = Theme.of(context).textTheme.bodyMedium?.copyWith(
      color: colors.onSurface,
      fontSize: 13,
      height: 1.35,
    );

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: SizedBox(
          width: double.infinity,
          child: DecoratedBox(
            key: const ValueKey('questionnaire-border'),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: colors.outlineVariant.withValues(
                  alpha: dark ? 0.58 : 0.92,
                ),
                width: dark ? 1 : 1.15,
              ),
              boxShadow: [
                BoxShadow(
                  color: colors.shadow.withValues(alpha: dark ? 0.24 : 0.16),
                  blurRadius: dark ? 18 : 22,
                  spreadRadius: dark ? 0 : 0.5,
                  offset: const Offset(0, 8),
                ),
                BoxShadow(
                  color: dark
                      ? colors.onSurface.withValues(alpha: 0.08)
                      : const Color(0xFF667085).withValues(alpha: 0.12),
                  blurRadius: 5,
                  offset: const Offset(0, 1),
                ),
              ],
            ),
            child: GlassCard(
              key: const ValueKey('questionnaire-block'),
              padding: const EdgeInsets.all(12),
              shape: const LiquidRoundedSuperellipse(borderRadius: 12),
              useOwnLayer: true,
              settings: _composerGlassSettings(context),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (heading.isNotEmpty) ...[
                    Text(
                      heading,
                      style: style?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 12),
                  ],
                  for (final entry in _questions.indexed) ...[
                    _question(context, entry.$2, entry.$1),
                    if (entry.$1 != _questions.length - 1)
                      const SizedBox(height: 12),
                  ],
                  const SizedBox(height: 14),
                  _InlineQuestionnaireSubmitButton(
                    submitting: _submitting,
                    onTap: _submit,
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

class _InlineQuestionnaireOptionWrap extends StatelessWidget {
  const _InlineQuestionnaireOptionWrap({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: 8, runSpacing: 8, children: children);
  }
}

class _InlineQuestionnaireOptionPill extends StatelessWidget {
  const _InlineQuestionnaireOptionPill({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return InkWell(
      borderRadius: BorderRadius.circular(999),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 140),
        constraints: const BoxConstraints(maxWidth: 320, minHeight: 30),
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
        decoration: BoxDecoration(
          color: selected
              ? colors.onSurface.withValues(alpha: dark ? 0.16 : 0.12)
              : colors.surfaceContainerHighest.withValues(
                  alpha: dark ? 0.28 : 0.36,
                ),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(
            color: selected
                ? colors.onSurface.withValues(alpha: 0.56)
                : colors.outlineVariant.withValues(alpha: dark ? 0.42 : 0.62),
          ),
        ),
        child: Text(
          label,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
            color: colors.onSurface,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
            height: 1.1,
          ),
        ),
      ),
    );
  }
}

class _InlineQuestionnaireTextField extends StatelessWidget {
  const _InlineQuestionnaireTextField({
    super.key,
    required this.controller,
    required this.fieldKey,
    this.autofocus = false,
  });

  final TextEditingController controller;
  final Key fieldKey;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 520),
      child: TextField(
        key: fieldKey,
        controller: controller,
        autofocus: autofocus,
        minLines: 1,
        maxLines: 4,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
          color: colors.onSurface,
          fontSize: 13,
          height: 1.35,
        ),
        cursorColor: colors.onSurface,
        decoration: InputDecoration(
          isDense: true,
          filled: true,
          fillColor: colors.surfaceContainerHighest.withValues(
            alpha: dark ? 0.34 : 0.48,
          ),
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 10,
            vertical: 9,
          ),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(
              color: colors.outlineVariant.withValues(alpha: 0.7),
            ),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(
              color: colors.outlineVariant.withValues(alpha: 0.7),
            ),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide(
              color: colors.onSurface.withValues(alpha: 0.54),
            ),
          ),
        ),
      ),
    );
  }
}

class _InlineQuestionnaireSubmitButton extends StatelessWidget {
  const _InlineQuestionnaireSubmitButton({
    required this.submitting,
    required this.onTap,
  });

  final bool submitting;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerRight,
      child: InkWell(
        key: const ValueKey('interaction-submit-submit'),
        borderRadius: BorderRadius.circular(999),
        onTap: submitting ? null : onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: colors.onSurface,
            borderRadius: BorderRadius.circular(999),
          ),
          child: Center(
            widthFactor: 1,
            child: Text(
              context.l10n.text('decision.submit'),
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: colors.surface,
                fontWeight: FontWeight.w800,
                height: 1,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _InteractionCard extends StatefulWidget {
  const _InteractionCard({required this.interaction, required this.onReply});

  final PendingInteraction interaction;
  final Future<void> Function(
    String decision, {
    String text,
    Map<String, Object?> payload,
  })
  onReply;

  @override
  State<_InteractionCard> createState() => _InteractionCardState();
}

class _InteractionCardState extends State<_InteractionCard> {
  final _answer = TextEditingController();
  final Map<String, TextEditingController> _questionControllers = {};
  final Map<String, Object?> _questionAnswers = {};
  bool _submitting = false;
  bool _previewExpanded = false;

  Future<void> _reply(String decision) async {
    if (_submitting) return;
    setState(() => _submitting = true);
    try {
      final answers = <String, Object?>{..._questionAnswers};
      for (final entry in _questionControllers.entries) {
        answers[entry.key] = entry.value.text.trim();
      }
      await widget.onReply(
        decision,
        text: answers.isEmpty ? _answer.text : jsonEncode({'answers': answers}),
        payload: answers.isEmpty ? const {} : {'answers': answers},
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  List<String> _visibleDecisions(bool approval) {
    final decisions = widget.interaction.allowedDecisions;
    if (!approval || !decisions.contains('deny')) return decisions;
    return decisions.where((value) => value != 'cancel').toList();
  }

  @override
  void dispose() {
    _answer.dispose();
    for (final controller in _questionControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  List<Map<String, Object?>> _questions(Map<String, Object?> payload) {
    final raw = payload['questions'];
    if (raw is! List) return const [];
    return [
      for (final value in raw)
        if (value is Map) value.cast<String, Object?>(),
    ];
  }

  String _questionId(Map<String, Object?> question, int index) =>
      question['id']?.toString() ?? 'q${index + 1}';

  Widget _questionField(
    BuildContext context,
    Map<String, Object?> question,
    int index,
  ) {
    final id = _questionId(question, index);
    final type = question['type']?.toString() ?? 'text';
    final title =
        question['title']?.toString() ?? question['question']?.toString() ?? id;
    final rawOptions = question['options'];
    final options = rawOptions is List ? rawOptions : const <Object?>[];
    String optionValue(Object? option) => option is Map
        ? option['value']?.toString() ?? option['label']?.toString() ?? ''
        : option?.toString() ?? '';
    String optionLabel(Object? option) => option is Map
        ? option['label']?.toString() ?? option['value']?.toString() ?? ''
        : option?.toString() ?? '';
    if (type == 'single') {
      final selected = _questionAnswers[id]?.toString();
      return Padding(
        padding: const EdgeInsets.only(top: 10),
        child: DropdownButtonFormField<String>(
          key: ValueKey('interaction-question-$id'),
          initialValue: selected,
          decoration: InputDecoration(labelText: title, isDense: true),
          items: [
            for (final option in options)
              DropdownMenuItem(
                value: optionValue(option),
                child: Text(optionLabel(option)),
              ),
          ],
          onChanged: (value) => setState(() => _questionAnswers[id] = value),
        ),
      );
    }
    if (type == 'multiple') {
      final selected = <String>{
        ...((_questionAnswers[id] as List?)?.map((value) => value.toString()) ??
            const <String>[]),
      };
      return Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 6),
            Wrap(
              spacing: 7,
              runSpacing: 5,
              children: [
                for (final option in options)
                  FilterChip(
                    label: Text(optionLabel(option)),
                    selected: selected.contains(optionValue(option)),
                    onSelected: (enabled) {
                      final updated = {...selected};
                      enabled
                          ? updated.add(optionValue(option))
                          : updated.remove(optionValue(option));
                      setState(
                        () => _questionAnswers[id] = updated.toList(
                          growable: false,
                        ),
                      );
                    },
                  ),
              ],
            ),
          ],
        ),
      );
    }
    final controller = _questionControllers.putIfAbsent(
      id,
      () => TextEditingController(text: question['default']?.toString() ?? ''),
    );
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: TextField(
        key: ValueKey('interaction-question-$id'),
        controller: controller,
        decoration: InputDecoration(
          labelText: title,
          hintText: question['placeholder']?.toString(),
          isDense: true,
        ),
        minLines: 1,
        maxLines: 4,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final payload = widget.interaction.payload;
    final questions = _questions(payload);
    final approval = widget.interaction.type == 'approval';
    final prompt =
        payload['prompt']?.toString() ??
        payload['reason']?.toString() ??
        (approval
            ? context.l10n.text('workspace.requestApproval')
            : widget.interaction.type);
    final toolName = payload['tool_name']?.toString();
    final language = toolPresentationLanguage(context);
    final rawArguments = payload['arguments'];
    final arguments = rawArguments is Map
        ? rawArguments.map((key, value) => MapEntry(key.toString(), value))
        : <String, Object?>{};
    final presentation = approval && toolName != null
        ? approvalToolPresentation(toolName, arguments, language)
        : null;
    final riskReason = payload['risk_reason']?.toString();
    final riskCategory = payload['risk_category']?.toString();
    final sideEffectLevel = payload['side_effect_level']?.toString();
    final displayedRiskReason = _riskReason(
      riskCategory,
      riskReason,
      context.l10n,
    );
    final decisions = _visibleDecisions(approval);
    final colors = Theme.of(context).colorScheme;
    final recovery = payload['reason'] == 'tool_outcome_unknown';
    final title = _interactionTitle(
      prompt: prompt,
      approval: approval,
      recovery: recovery,
      toolName: toolName,
      riskCategory: riskCategory,
      arguments: arguments,
      language: language,
    );
    final elevatedRisk =
        sideEffectLevel == 'irreversible' ||
        riskCategory == 'destructive_filesystem' ||
        riskCategory == 'filesystem_delete' ||
        riskCategory == 'external_side_effect';
    final subtitle = _interactionSubtitle(
      payload: payload,
      approval: approval,
      recovery: recovery,
      toolName: toolName,
      arguments: arguments,
      riskReason: displayedRiskReason,
      language: language,
    );
    final badge = approval && !recovery
        ? _interactionBadge(
            toolName,
            riskCategory,
            sideEffectLevel,
            context.l10n,
          )
        : null;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 680),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 6, 20, 10),
          child: Container(
            width: double.infinity,
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: colors.surfaceContainerHigh.withValues(alpha: 0.96),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(
                color: elevatedRisk
                    ? colors.error.withValues(alpha: 0.22)
                    : colors.outlineVariant.withValues(alpha: 0.65),
              ),
              boxShadow: [
                BoxShadow(
                  color: colors.shadow.withValues(alpha: 0.18),
                  blurRadius: 28,
                  offset: const Offset(0, 12),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(18, 17, 18, 14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            width: 38,
                            height: 38,
                            decoration: BoxDecoration(
                              color: recovery
                                  ? colors.errorContainer.withValues(alpha: 0.5)
                                  : colors.primaryContainer.withValues(
                                      alpha: 0.55,
                                    ),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Icon(
                              _interactionIcon(toolName, approval, recovery),
                              size: 19,
                              color: recovery
                                  ? colors.onErrorContainer
                                  : colors.onPrimaryContainer,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  title,
                                  style: Theme.of(context).textTheme.titleMedium
                                      ?.copyWith(
                                        fontWeight: FontWeight.w700,
                                        letterSpacing: -0.2,
                                      ),
                                ),
                                if (subtitle.isNotEmpty) ...[
                                  const SizedBox(height: 3),
                                  Text(
                                    subtitle,
                                    style: Theme.of(context).textTheme.bodySmall
                                        ?.copyWith(
                                          color: colors.onSurfaceVariant,
                                          height: 1.35,
                                        ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                          if (badge != null) ...[
                            const SizedBox(width: 12),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 5,
                              ),
                              decoration: BoxDecoration(
                                color:
                                    (elevatedRisk
                                            ? colors.errorContainer
                                            : colors.tertiaryContainer)
                                        .withValues(alpha: 0.55),
                                borderRadius: BorderRadius.circular(999),
                              ),
                              child: Text(
                                badge,
                                style: Theme.of(context).textTheme.labelSmall
                                    ?.copyWith(
                                      color: elevatedRisk
                                          ? colors.onErrorContainer
                                          : colors.onTertiaryContainer,
                                      fontWeight: FontWeight.w600,
                                    ),
                              ),
                            ),
                          ],
                        ],
                      ),
                      if (presentation != null) ...[
                        const SizedBox(height: 14),
                        Container(
                          key: const ValueKey('interaction-command'),
                          width: double.infinity,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 10,
                          ),
                          decoration: BoxDecoration(
                            color: colors.surfaceContainerHighest.withValues(
                              alpha: 0.62,
                            ),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: colors.outlineVariant.withValues(
                                alpha: 0.7,
                              ),
                            ),
                          ),
                          child: Wrap(
                            spacing: 6,
                            runSpacing: 4,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              SelectableText(
                                presentation.summary,
                                style: TextStyle(
                                  color: colors.onSurface,
                                  fontFamily: 'monospace',
                                  fontSize: 12.5,
                                  height: 1.45,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              for (final fact in presentation.facts)
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 7,
                                    vertical: 2,
                                  ),
                                  decoration: BoxDecoration(
                                    color: colors.surface.withValues(
                                      alpha: 0.5,
                                    ),
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Text(
                                    fact,
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelSmall
                                        ?.copyWith(
                                          color: colors.onSurfaceVariant,
                                        ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                        if (presentation.preview case final preview?) ...[
                          const SizedBox(height: 10),
                          Text(
                            presentation.previewLabel ?? '',
                            style: Theme.of(context).textTheme.labelSmall
                                ?.copyWith(
                                  color: colors.onSurfaceVariant,
                                  fontWeight: FontWeight.w600,
                                ),
                          ),
                          const SizedBox(height: 5),
                          Container(
                            key: const ValueKey('interaction-preview'),
                            width: double.infinity,
                            constraints: BoxConstraints(
                              maxHeight: toolName == 'goal_submit'
                                  ? 360
                                  : _previewExpanded
                                  ? 320
                                  : 156,
                            ),
                            decoration: BoxDecoration(
                              color: colors.surfaceContainerLowest.withValues(
                                alpha: 0.58,
                              ),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(
                                color: colors.outlineVariant.withValues(
                                  alpha: 0.5,
                                ),
                              ),
                            ),
                            child: SingleChildScrollView(
                              child: presentation.previewLines.isNotEmpty
                                  ? _ApprovalDiffPreview(
                                      lines: presentation.previewLines,
                                    )
                                  : Padding(
                                      padding: const EdgeInsets.all(11),
                                      child: SelectableText(
                                        preview,
                                        style: TextStyle(
                                          color: colors.onSurface,
                                          fontFamily: 'monospace',
                                          fontSize: 12,
                                          height: 1.5,
                                        ),
                                      ),
                                    ),
                            ),
                          ),
                          if (toolName != 'goal_submit')
                            Align(
                              alignment: Alignment.centerLeft,
                              child: TextButton.icon(
                                key: const ValueKey(
                                  'interaction-preview-toggle',
                                ),
                                onPressed: () => setState(
                                  () => _previewExpanded = !_previewExpanded,
                                ),
                                icon: Icon(
                                  _previewExpanded
                                      ? CupertinoIcons.chevron_up
                                      : CupertinoIcons.chevron_down,
                                  size: 12,
                                ),
                                label: Text(
                                  _previewToggleLabel(
                                    language,
                                    _previewExpanded,
                                  ),
                                ),
                                style: TextButton.styleFrom(
                                  visualDensity: VisualDensity.compact,
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 2,
                                  ),
                                  foregroundColor: colors.onSurfaceVariant,
                                ),
                              ),
                            ),
                        ],
                      ],
                      if (widget.interaction.type == 'user_input' &&
                          questions.isNotEmpty)
                        for (final entry in questions.indexed)
                          _questionField(context, entry.$2, entry.$1),
                      if (widget.interaction.type == 'user_input' &&
                          questions.isEmpty) ...[
                        const SizedBox(height: 10),
                        TextField(
                          key: const ValueKey('interaction-input'),
                          controller: _answer,
                          autofocus: true,
                          onSubmitted: (_) => _reply(decisions.first),
                        ),
                      ],
                    ],
                  ),
                ),
                Container(
                  decoration: BoxDecoration(
                    border: Border(
                      top: BorderSide(
                        color: colors.outlineVariant.withValues(alpha: 0.45),
                      ),
                    ),
                  ),
                  padding: const EdgeInsets.fromLTRB(16, 11, 16, 12),
                  child: Wrap(
                    alignment: WrapAlignment.end,
                    spacing: 9,
                    runSpacing: 8,
                    children: [
                      for (final decision in decisions)
                        _InteractionDecisionButton(
                          decision: decision,
                          label: _interactionDecisionLabel(
                            decision,
                            toolName,
                            context.l10n,
                          ),
                          primary:
                              decision == 'approve_and_remember' ||
                              (decision != 'deny' &&
                                  decision != 'cancel' &&
                                  !(decision == 'approve_once' &&
                                      decisions.contains(
                                        'approve_and_remember',
                                      ))),
                          submitting: _submitting,
                          onPressed: () => _reply(decision),
                        ),
                    ],
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

class _ApprovalDiffPreview extends StatelessWidget {
  const _ApprovalDiffPreview({required this.lines});

  final List<ApprovalPreviewLine> lines;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final addedColor = dark ? const Color(0xFF7EE787) : const Color(0xFF1A7F37);
    final removedColor = dark
        ? const Color(0xFFFFA198)
        : const Color(0xFFCF222E);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final line in lines)
          Container(
            color: switch (line.kind) {
              ApprovalPreviewLineKind.added => const Color(
                0xFF238636,
              ).withValues(alpha: 0.16),
              ApprovalPreviewLineKind.removed => colors.error.withValues(
                alpha: 0.14,
              ),
              ApprovalPreviewLineKind.context => Colors.transparent,
            },
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 3),
            child: SelectableText(
              '${switch (line.kind) {
                ApprovalPreviewLineKind.added => '+ ',
                ApprovalPreviewLineKind.removed => '- ',
                ApprovalPreviewLineKind.context => '  ',
              }}${line.text}',
              style: TextStyle(
                color: switch (line.kind) {
                  ApprovalPreviewLineKind.added => addedColor,
                  ApprovalPreviewLineKind.removed => removedColor,
                  ApprovalPreviewLineKind.context => colors.onSurfaceVariant,
                },
                fontFamily: 'monospace',
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ),
      ],
    );
  }
}

class _InteractionDecisionButton extends StatelessWidget {
  const _InteractionDecisionButton({
    required this.decision,
    required this.label,
    required this.primary,
    required this.submitting,
    required this.onPressed,
  });

  final String decision;
  final String label;
  final bool primary;
  final bool submitting;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final quiet = decision == 'deny' || decision == 'cancel';
    final child = submitting && primary
        ? const SizedBox.square(
            dimension: 15,
            child: CircularProgressIndicator(strokeWidth: 2),
          )
        : Text(label, style: const TextStyle(fontWeight: FontWeight.w600));
    if (quiet) {
      return TextButton(
        key: ValueKey('interaction-submit-$decision'),
        onPressed: submitting ? null : onPressed,
        child: child,
      );
    }
    final style = ButtonStyle(
      minimumSize: const WidgetStatePropertyAll(Size(0, 40)),
      padding: const WidgetStatePropertyAll(
        EdgeInsets.symmetric(horizontal: 18),
      ),
      shape: WidgetStatePropertyAll(
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(11)),
      ),
    );
    if (primary) {
      return FilledButton(
        key: ValueKey('interaction-submit-$decision'),
        onPressed: submitting ? null : onPressed,
        style: style,
        child: child,
      );
    }
    return OutlinedButton(
      key: ValueKey('interaction-submit-$decision'),
      onPressed: submitting ? null : onPressed,
      style: style,
      child: child,
    );
  }
}

String _interactionTitle({
  required String prompt,
  required bool approval,
  required bool recovery,
  required String? toolName,
  required String? riskCategory,
  required Map<String, Object?> arguments,
  required String language,
}) {
  if (!approval || toolName == null) return prompt;
  if (recovery) {
    return language == 'zh' ? '需要核对工具结果' : 'Tool result needs review';
  }
  if (toolName == 'goal_submit' && riskCategory == 'plan_approval') {
    return _planApprovalTitle(language);
  }
  final path =
      arguments['file_path']?.toString() ?? arguments['path']?.toString() ?? '';
  final pathParts = path
      .replaceAll('\\', '/')
      .split('/')
      .where((value) => value.isNotEmpty)
      .toList(growable: false);
  final fileName = pathParts.isEmpty ? null : pathParts.last;
  if (fileName != null) {
    if (language == 'zh') {
      return switch (toolName) {
        'file_update' || 'update_file' => '更新 $fileName',
        'file_write' || 'write_file' => '写入 $fileName',
        _ => localizedToolName(toolName, language),
      };
    }
    return '${localizedToolName(toolName, language)} · $fileName';
  }
  return localizedToolName(toolName, language);
}

String _interactionSubtitle({
  required Map<String, Object?> payload,
  required bool approval,
  required bool recovery,
  required String? toolName,
  required Map<String, Object?> arguments,
  required String? riskReason,
  required String language,
}) {
  if (recovery) return payload['prompt']?.toString() ?? '';
  if (approval && toolName != null) {
    if (toolName == 'file_update' || toolName == 'update_file') {
      final operations = arguments['operations'];
      final count = operations is List ? operations.length : 0;
      return language == 'zh'
          ? '将修改 $count 处内容，执行前请检查变更'
          : '$count changes will be applied; review them before running';
    }
    if (toolName == 'file_write' || toolName == 'write_file') {
      final content = arguments['content']?.toString() ?? '';
      final count = content.isEmpty ? 0 : '\n'.allMatches(content).length + 1;
      return language == 'zh'
          ? '将写入 $count 行内容，执行前请检查文件'
          : '$count lines will be written; review the file before running';
    }
    if (toolName == 'apply_patch') {
      final patch = arguments['patch']?.toString() ?? '';
      final count = RegExp(
        r'^\*\*\* (?:Add|Update|Delete) File:',
        multiLine: true,
      ).allMatches(patch).length;
      return language == 'zh'
          ? '将修改 $count 个文件，执行前请检查补丁'
          : '$count files will change; review the patch before running';
    }
  }
  if (riskReason != null && riskReason.isNotEmpty) return riskReason;
  return payload['guidance']?.toString() ?? '';
}

String _interactionBadge(
  String? toolName,
  String? riskCategory,
  String? sideEffectLevel,
  SageLocalizations l10n,
) {
  if ({
    'file_write',
    'write_file',
    'file_update',
    'update_file',
    'apply_patch',
  }.contains(toolName)) {
    return l10n.languageCode == 'zh' ? '文件写入' : 'File write';
  }
  if (toolName == 'goal_submit') {
    return l10n.languageCode == 'zh' ? '计划审批' : 'Plan approval';
  }
  return _riskLabel(riskCategory, sideEffectLevel, l10n);
}

IconData _interactionIcon(String? toolName, bool approval, bool recovery) {
  if (recovery) return CupertinoIcons.exclamationmark_triangle;
  if ({
    'file_write',
    'write_file',
    'file_update',
    'update_file',
    'apply_patch',
  }.contains(toolName)) {
    return CupertinoIcons.pencil_outline;
  }
  if (toolName == 'execute_shell_command') {
    return CupertinoIcons.chevron_left_slash_chevron_right;
  }
  if (toolName == 'goal_submit') return CupertinoIcons.list_bullet;
  return approval
      ? CupertinoIcons.checkmark_shield
      : CupertinoIcons.question_circle;
}

String _previewToggleLabel(String language, bool expanded) {
  if (language == 'zh') return expanded ? '收起完整变更' : '查看完整变更';
  return expanded ? 'Collapse full changes' : 'View full changes';
}
