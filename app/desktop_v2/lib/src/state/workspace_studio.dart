part of 'workspace_controller.dart';

/// Desktop Studio adapter. The host owns public history and per-Run tools.
/// Task dispatch remains explicit; mentions never trigger runs from text.
extension StudioWorkspace on WorkspaceController {
  Studio? get selectedStudio =>
      studios.where((s) => s.id == selectedStudioId).firstOrNull;

  Conversation? studioExecution(Studio studio, StudioMember member) =>
      _conversations[studio.id]
          ?.where((c) => c.id == member.conversationId)
          .firstOrNull;

  bool studioMemberBusy(Studio studio, StudioMember member) {
    final c = studioExecution(studio, member);
    return c != null &&
        (_isActive(c.status) ||
            c.status == RunStatus.suspended ||
            c.pendingInteraction != null);
  }

  // Multiple explicitly mentioned members may run concurrently in separate Sessions.
  bool studioMemberAvailable(StudioMember member) =>
      agents.any((a) => a.id == member.agentId);

  bool get studioBusy =>
      studios.any(
        (s) =>
            s.members.any((m) => studioMemberBusy(s, m)) ||
            s.turns.any((t) => t.pendingMemberIds.isNotEmpty),
      ) ||
      _studioDispatching.isNotEmpty;

  bool get studioSending => _studioSending.contains(selectedStudioId);

  List<StudioMember> get studioRecipients {
    final studio = selectedStudio;
    if (studio == null) return const [];
    final ids = studioRecipientIds.isEmpty
        ? [studio.coordinatorId]
        : studioRecipientIds;
    return studio.members.where((m) => ids.contains(m.id)).toList();
  }

  Future<Studio> createStudio(
    String name,
    List<String> agentIds, {
    required String coordinatorAgentId,
  }) async {
    final chosen = agentIds.toSet();
    final available = agents.where((a) => chosen.contains(a.id)).toList();
    if (name.trim().isEmpty ||
        available.isEmpty ||
        available.length != chosen.length ||
        !chosen.contains(coordinatorAgentId)) {
      throw ArgumentError('Invalid Studio members or name');
    }
    final members = [
      for (final agent in available)
        StudioMember(
          id: _id('member'),
          agentId: agent.id,
          name: agent.name,
          conversationId: _id('studio_session'),
        ),
    ];
    final value = Studio(
      id: _id('studio'),
      name: name.trim(),
      members: members,
      coordinatorId: members
          .firstWhere((m) => m.agentId == coordinatorAgentId)
          .id,
    );
    _conversations[value.id] = [
      for (final member in value.members)
        Conversation(id: member.conversationId, agentId: member.agentId),
    ];
    studios.add(value);
    try {
      await _saveStudios();
    } on Object {
      studios.remove(value);
      _conversations.remove(value.id);
      rethrow;
    }
    selectStudio(value.id);
    return value;
  }

  void selectStudio(String id) {
    final value = studios.where((s) => s.id == id).firstOrNull;
    if (value == null) return;
    selectedStudioId = value.id;
    selectedStudioMemberId = '';
    studioRecipientId = '';
    studioRecipientIds.clear();
    _studioPollTimer ??= Timer.periodic(const Duration(seconds: 1), (_) {
      final current = selectedStudio;
      if (current != null && _hostStudios.contains(current.id)) {
        unawaited(refreshStudioMessages(current));
      }
    });
    _notifyStudioChanged();
    unawaited(refreshSkills());
  }

  void selectStudioMember(String id, {bool mention = false}) {
    if (!(selectedStudio?.members.any((m) => m.id == id) ?? false)) return;
    selectedStudioMemberId = id;
    if (mention) {
      if (!studioRecipientIds.contains(id)) studioRecipientIds.add(id);
      studioRecipientId = studioRecipientIds.first;
    }
    _notifyStudioChanged();
  }

  void setStudioApprovalMode(
    Studio studio,
    StudioMember member,
    ApprovalMode mode,
  ) {
    if (studioMemberBusy(studio, member)) return;
    final execution = studioExecution(studio, member);
    if (execution == null) return;
    execution.approvalMode = mode;
    studio.draft.approvalMode = mode;
    _persist();
    _notifyStudioChanged();
  }

  void removeStudioMention(String id) {
    studioRecipientIds.remove(id);
    studioRecipientId = studioRecipientIds.firstOrNull ?? '';
    _notifyStudioChanged();
  }

  void clearStudioMention() {
    studioRecipientId = '';
    studioRecipientIds.clear();
    _notifyStudioChanged();
  }

  Future<void> setStudioCoordinator(Studio studio, String memberId) async {
    if (studio.updatingCoordinator ||
        !studios.contains(studio) ||
        !studio.members.any((m) => m.id == memberId) ||
        studio.coordinatorId == memberId) {
      return;
    }
    final previous = studio.coordinatorId;
    studio.updatingCoordinator = true;
    studio.coordinatorId = memberId;
    _notifyStudioChanged();
    try {
      // Unregistered groups have no host sessions yet; register on first send.
      if (_hostStudios.contains(studio.id)) await syncStudio(studio);
      await _saveStudios();
    } on Object catch (exception) {
      studio.coordinatorId = previous;
      error = exception.toString();
      await _saveStudios();
    } finally {
      studio.updatingCoordinator = false;
      _notifyStudioChanged();
    }
  }

  DateTime? studioTurnTime(Studio studio, StudioTurn turn) {
    final member = studio.members
        .where((m) => m.id == turn.memberId)
        .firstOrNull;
    if (member == null) return null;
    return studioExecution(studio, member)?.messages
        .where((m) => m.id == turn.executionMessageId)
        .firstOrNull
        ?.createdAt;
  }

  List<ChatMessage> studioReplies(
    Studio studio,
    StudioTurn turn, {
    String? memberId,
  }) {
    final member = studio.members
        .where((m) => m.id == (memberId ?? turn.memberId))
        .firstOrNull;
    if (member == null) return const [];
    final messages =
        studioExecution(studio, member)?.messages ?? const <ChatMessage>[];
    final start = messages.indexWhere(
      (m) => m.id == turn.executionMessageIds[memberId ?? turn.memberId],
    );
    if (start < 0) return const [];
    return messages
        .skip(start + 1)
        .takeWhile((m) => m.role != 'user')
        .where(
          (m) => m.role == 'assistant' && !m.processOnly && m.text.isNotEmpty,
        )
        .toList();
  }

  Future<void> toggleStudioContextTurn(Studio studio, String turnId) async {
    if (!studios.contains(studio) || !studio.turns.any((t) => t.id == turnId)) {
      return;
    }
    if (!studio.pinnedTurnIds.remove(turnId)) studio.pinnedTurnIds.add(turnId);
    _notifyStudioChanged();
    try {
      await _saveStudios();
      if (_hostStudios.contains(studio.id)) await syncStudio(studio);
    } on Object catch (exception) {
      if (!studio.pinnedTurnIds.remove(turnId)) {
        studio.pinnedTurnIds.add(turnId);
      }
      error = exception.toString();
      _notifyStudioChanged();
    }
  }

  Future<bool> sendStudioMessage(
    String text, {
    List<ChatMessageContent> content = const [],
  }) async {
    final studio = selectedStudio;
    final prompt = text.trim();
    if (studio == null ||
        (prompt.isEmpty && !content.any((p) => p.isReference)) ||
        _studioSending.contains(studio.id) ||
        _studioDispatching.contains(studio.id) ||
        studio.updatingCoordinator) {
      return false;
    }
    final ids = studioRecipientIds.isEmpty
        ? [studio.coordinatorId]
        : studioRecipientIds.toSet().toList();
    final members = [
      for (final id in ids) studio.members.firstWhere((m) => m.id == id),
    ];
    if (members.any((m) => !studioMemberAvailable(m))) return false;
    final explicitMention = studioRecipientIds.isNotEmpty;
    final turnSkills = preferredSkills.toList();
    final approvalMode = studio.draft.approvalMode.wireValue;
    final invocationMode = studio.draft.invocationMode.wireValue;
    _studioSending.add(studio.id);
    _notifyStudioChanged();
    try {
      // Cancel only addressed members. Wait for authoritative terminal state before
      // reusing their Session; a cancellation acknowledgement alone is insufficient.
      await Future.wait(
        members.map((member) async {
          final execution = studioExecution(studio, member)!;
          if (!studioMemberBusy(studio, member)) return;
          final deadline = DateTime.now().add(const Duration(seconds: 10));
          while (execution.runId.isEmpty &&
              DateTime.now().isBefore(deadline) &&
              !_disposed) {
            await Future<void>.delayed(const Duration(milliseconds: 100));
          }
          if (_disposed || execution.runId.isEmpty) {
            throw StateError('Studio member is still starting');
          }
          await _api.cancel(execution.runId);
          do {
            await _refreshConversationSnapshot(execution);
            if (_isTerminal(execution.status)) break;
            await Future<void>.delayed(const Duration(milliseconds: 150));
          } while (!_disposed && DateTime.now().isBefore(deadline));
          if (_disposed || !_isTerminal(execution.status)) {
            throw StateError('Studio member has not stopped yet');
          }
          await _streams.remove(execution.id)?.cancel();
          execution.pendingInteraction = null;
        }),
      );
      final anchors = {for (final m in members) m.id: _id('message')};
      final turn = StudioTurn(
        id: _id('studio_message'),
        text: prompt,
        memberId: ids.first,
        executionMessageId: anchors[ids.first]!,
        executionMessageIds: anchors,
        pendingMemberIds: [...ids],
        explicitMention: explicitMention,
        addressed: true,
        content: content,
        preferredSkills: turnSkills,
        approvalMode: approvalMode,
        invocationMode: invocationMode,
      );
      studio.turns.add(turn);
      for (final m in studio.members) {
        studioExecution(studio, m)!.sessionId ??= _newSessionId();
      }
      for (final member in members) {
        studioExecution(studio, member)!.messages.add(
          ChatMessage(
            id: anchors[member.id]!,
            role: 'user',
            text: prompt,
            content: content,
          ),
        );
      }
      error = null;
      try {
        await _saveStudios();
      } on Object catch (exception) {
        studio.turns.remove(turn);
        for (final member in members) {
          studioExecution(
            studio,
            member,
          )!.messages.removeWhere((m) => m.id == anchors[member.id]);
        }
        error = exception.toString();
        _notifyStudioChanged();
        return false;
      }
      _attachments[studio.id] = [];
      clearComposerReferences(studio.id);
      if (selectedStudioId == studio.id) clearStudioMention();
      await _dispatchStudioMembers(studio);
      return true;
    } on Object catch (exception) {
      error = exception.toString();
      _notifyStudioChanged();
      return false;
    } finally {
      _studioSending.remove(studio.id);
      if (!_disposed) _notifyStudioChanged();
    }
  }

  Future<void> _dispatchStudioMembers(Studio studio) async {
    if (_disposed || !_studioDispatching.add(studio.id)) {
      return;
    }
    final turn = studio.turns
        .where((t) => t.pendingMemberIds.isNotEmpty)
        .firstOrNull;
    if (turn == null) {
      _studioDispatching.remove(studio.id);
      return;
    }
    try {
      final pending = [...turn.pendingMemberIds];
      for (final memberId in pending) {
        if (!turn.pendingMemberIds.contains(memberId)) continue;
        final member = studio.members.firstWhere((m) => m.id == memberId);
        final execution = studioExecution(studio, member)!;
        // Remove before I/O: a lost acknowledgement must never replay an uncertain Run.
        turn.pendingMemberIds.remove(memberId);
        execution.runId = '';
        execution.turnId = '';
        execution.runSequence = 0;
        execution.status = RunStatus.starting;
        execution.processPanels.add(
          RuntimeProcessPanel(
            id: _id('process'),
            anchorMessageId: turn.executionMessageIds[member.id]!,
            startedAt: DateTime.now(),
          ),
        );
        _notifyStudioChanged();
        try {
          await _saveStudios();
          await syncStudio(studio);
          _listen(
            execution,
            _api.startRun({
              'studio_id': studio.id,
              'studio_member_id': member.id,
              'studio_message_id': turn.id,
              'agent_id': member.agentId,
              'session_id': execution.sessionId,
              'response_language': settings.language == 'system'
                  ? PlatformDispatcher.instance.locale.languageCode
                  : settings.language,
              'messages': [
                {
                  'role': 'user',
                  'text': turn.text,
                  if (turn.content.isNotEmpty)
                    'content': [for (final p in turn.content) p.toJson()],
                },
              ],
              'preferred_skills': turn.preferredSkills,
              'approval_mode': turn.approvalMode,
              'invocation_mode': turn.invocationMode,
              'idempotency_key': 'desktop-studio:${turn.id}:${member.id}',
            }),
          );
        } on Object catch (exception) {
          execution.status = RunStatus.failed;

          error = exception.toString();
          await _saveStudios();
          _notifyStudioChanged();
        }
      }
    } finally {
      _studioDispatching.remove(studio.id);
    }
  }

  Future<void> _syncStudioExecution(Conversation execution) async {
    final studio = studios
        .where((s) => s.members.any((m) => m.conversationId == execution.id))
        .firstOrNull;
    if (studio == null || !_hostStudios.contains(studio.id)) return;
    try {
      await syncStudio(studio);
    } on Object catch (exception) {
      if (!_disposed) {
        error = exception.toString();
        _notifyStudioChanged();
      }
    }
  }

  Future<void> syncStudio(Studio studio) async {
    await _api.syncStudio(studio.id, {
      'name': studio.name,
      'members': [
        for (final m in studio.members)
          {
            'id': m.id,
            'agent_id': m.agentId,
            'name': m.name,
            'session_id': studioExecution(studio, m)!.sessionId,
          },
      ],
      'coordinator_id': studio.coordinatorId,
      'pinned_turn_ids': const <String>[],
      'messages': [
        for (final turn in studio.turns) ...[
          {
            'id': turn.id,
            'turn_id': turn.id,
            'sender': 'user',
            'text': turn.text,
            'kind': 'user',
            if (turn.addressed) 'recipient_member_ids': turn.memberIds,
            if (turn.content.isNotEmpty)
              'content': [for (final p in turn.content) p.toJson()],
          },
          for (final memberId in turn.memberIds)
            if (!_studioTurnActive(studio, turn, memberId))
              for (final reply in studioReplies(
                studio,
                turn,
                memberId: memberId,
              ))
                {
                  'id': 'result:${turn.id}:${reply.id}',
                  'turn_id': turn.id,
                  'sender': memberId,
                  'text': reply.text,
                  'kind': 'result',
                },
        ],
      ],
    });
    _hostStudios.add(studio.id);
    studio.hostRegistered = true;
    await _saveStudios();
    await refreshStudioMessages(studio);
  }

  bool _studioTurnActive(Studio studio, StudioTurn turn, String memberId) {
    final member = studio.members.firstWhere((m) => m.id == memberId);
    return studioMemberBusy(studio, member) &&
        studio.turns.lastWhere((t) => t.memberIds.contains(member.id)).id ==
            turn.id;
  }

  Future<void> refreshStudioMessages(Studio studio) async {
    if (_disposed || !_studioRefreshing.add(studio.id)) return;
    try {
      var more = true;
      // Bound each poll; the next tick continues from the persisted cursor.
      for (var page = 0; more && page < 10; page++) {
        final result = await _api.studioMessages(
          studio.id,
          afterSequence: studio.messageCursor,
        );
        if (_disposed) return;
        final messages = (result['messages'] as List? ?? []).cast<Map>();
        for (final raw in messages) {
          final message = raw.cast<String, Object?>();
          if (message['kind'] == 'note' &&
              !studio.publicMessages.any((m) => m['id'] == message['id'])) {
            studio.publicMessages.add(message);
          }
          final sequence = (message['sequence'] as num?)?.toInt() ?? 0;
          if (sequence > studio.messageCursor) studio.messageCursor = sequence;
        }
        more = result['has_more'] == true && messages.isNotEmpty;
        if (messages.isNotEmpty) {
          _notifyStudioChanged();
          await _saveStudios();
        }
      }
    } on Object catch (exception) {
      if (!_disposed) {
        error = exception.toString();
        _notifyStudioChanged();
      }
    } finally {
      _studioRefreshing.remove(studio.id);
    }
  }

  Future<void> cancelStudioMember(Studio studio, StudioMember member) async {
    final execution = studioExecution(studio, member);
    if (execution == null || execution.runId.isEmpty) return;
    try {
      await _api.cancel(execution.runId);
      await _refreshConversationSnapshot(execution);
    } on Object catch (exception) {
      error = exception.toString();
      _notifyStudioChanged();
    }
  }

  Future<void> resumeStudioMember(Studio studio, StudioMember member) async {
    final execution = studioExecution(studio, member);
    if (execution == null ||
        execution.status != RunStatus.suspended ||
        execution.pendingInteraction != null) {
      return;
    }
    try {
      await _api.resume(execution.runId);
      execution.status = RunStatus.running;
      _subscribe(execution);
      _notifyStudioChanged();
    } on Object catch (exception) {
      error = exception.toString();
      _notifyStudioChanged();
    }
  }

  Future<void> replyStudioInteraction(
    Studio studio,
    StudioMember member,
    String decision, {
    String text = '',
    Map<String, Object?> payload = const {},
  }) => _replyInteractionFor(
    studioExecution(studio, member),
    decision,
    text: text,
    payload: payload,
  );

  Future<void> _saveStudios() async {
    final saved = await _preferences?.setString(
      WorkspaceController._studiosKey,
      jsonEncode([
        for (final studio in studios)
          {
            'studio': studio.toJson(),
            'executions': [
              for (final c in _conversations[studio.id] ?? <Conversation>[])
                c.toJson(),
            ],
          },
      ]),
    );
    if (saved == false) throw StateError('Could not save Studio');
  }

  void _restoreStudios() {
    final raw = _preferences?.getString(WorkspaceController._studiosKey);
    if (raw == null) return;
    final restored = <Studio>[];
    final executions = <String, List<Conversation>>{};
    try {
      for (final entry in jsonDecode(raw) as List) {
        final studio = Studio.fromJson(
          (entry['studio'] as Map).cast<String, Object?>(),
        );
        final values = [
          for (final c in entry['executions'] as List)
            Conversation.fromJson((c as Map).cast<String, Object?>()),
        ];
        for (final turn in studio.turns) {
          for (final id in turn.pendingMemberIds) {
            final member = studio.members.where((m) => m.id == id).firstOrNull;
            final execution = values
                .where((c) => c.id == member?.conversationId)
                .firstOrNull;
            if (execution != null) execution.status = RunStatus.failed;
          }
          turn.pendingMemberIds.clear();
        }
        if (!studio.members.any((m) => m.id == studio.coordinatorId) ||
            studio.members.any(
              (m) => !values.any(
                (c) => c.id == m.conversationId && c.agentId == m.agentId,
              ),
            )) {
          throw const FormatException('Invalid Studio mapping');
        }
        // A start without a recorded Run handle cannot safely be replayed.
        for (final c in values) {
          if (c.status == RunStatus.starting && c.runId.isEmpty) {
            c.status = RunStatus.failed;
          }
        }
        restored.add(studio);
        if (studio.hostRegistered) _hostStudios.add(studio.id);
        executions[studio.id] = values;
      }
      studios
        ..clear()
        ..addAll(restored);
      _conversations.addAll(executions);
    } on Object catch (exception) {
      error = 'Studio: $exception';
    }
  }
}
