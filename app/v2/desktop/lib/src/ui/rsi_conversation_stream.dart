import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

/// Follow new evidence unless the reader has scrolled back into history.
class RsiConversationStream extends StatefulWidget {
  const RsiConversationStream({
    required this.revision,
    required this.children,
    super.key,
  });

  final int revision;
  final List<Widget> children;

  @override
  State<RsiConversationStream> createState() => _RsiConversationStreamState();
}

class _RsiConversationStreamState extends State<RsiConversationStream> {
  final _scroll = ScrollController();
  bool _following = true;
  bool _automatic = false;
  int _scrollGeneration = 0;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_positionChanged);
    _followLatest(initial: true);
  }

  @override
  void didUpdateWidget(RsiConversationStream oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.revision != widget.revision) _followLatest();
  }

  void _positionChanged() {
    if (!_automatic && _scroll.hasClients) {
      _following = _scroll.position.extentAfter < 24;
    }
  }

  void _followLatest({bool initial = false}) {
    if (!_following) return;
    _automatic = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || !_following || !_scroll.hasClients) return;
      final end = _scroll.position.maxScrollExtent;
      if ((end - _scroll.offset).abs() < 1) {
        _automatic = false;
        return;
      }
      final generation = ++_scrollGeneration;
      _automatic = true;
      try {
        if (initial || MediaQuery.disableAnimationsOf(context)) {
          _scroll.jumpTo(end);
        } else {
          await _scroll.animateTo(
            end,
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOut,
          );
        }
      } finally {
        // Lazy text layout can revise the estimated end during scrolling.
        // Verify against the next layout before releasing the follow guard.
        if (mounted && _scrollGeneration == generation && _following) {
          _followLatest(initial: true);
        }
      }
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      NotificationListener<ScrollNotification>(
        onNotification: (notification) {
          if ((notification is ScrollStartNotification &&
                  notification.dragDetails != null) ||
              (notification is UserScrollNotification &&
                  notification.direction != ScrollDirection.idle)) {
            _automatic = false;
            _scrollGeneration++;
            _following = notification.metrics.extentAfter < 24;
          }
          return false;
        },
        child: ListView(
          controller: _scroll,
          primary: false,
          children: widget.children,
        ),
      );
}
