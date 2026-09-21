import 'models.dart';

/// Desktop Studio presentation records. Execution remains owned by v2 Runs.
class StudioMember {
  const StudioMember({
    required this.id,
    required this.agentId,
    required this.name,
    required this.conversationId,
  });
  final String id;
  final String agentId;
  final String name;
  final String conversationId;
  Map<String, Object?> toJson() => {
    'id': id,
    'agent_id': agentId,
    'name': name,
    'conversation_id': conversationId,
  };
  factory StudioMember.fromJson(Map<String, Object?> json) => StudioMember(
    id: json['id'] as String,
    agentId: json['agent_id'] as String,
    name: json['name'] as String,
    conversationId: json['conversation_id'] as String,
  );
}

class StudioTurn {
  StudioTurn({
    required this.id,
    required this.text,
    required this.memberId,
    required this.executionMessageId,
    this.explicitMention = false,
    this.addressed = false,
    Map<String, String>? executionMessageIds,
    List<String>? pendingMemberIds,
    List<String>? startingMemberIds,
    this.content = const [],
    this.preferredSkills = const [],
    this.approvalMode = 'high_risk',
    this.invocationMode = 'normal',
  }) : executionMessageIds =
           executionMessageIds ?? {memberId: executionMessageId},
       pendingMemberIds = pendingMemberIds ?? [],
       startingMemberIds = startingMemberIds ?? [];
  final Map<String, String> executionMessageIds;
  final List<String> pendingMemberIds;
  final List<String> startingMemberIds;
  final List<ChatMessageContent> content;
  final List<String> preferredSkills;
  final String approvalMode;
  final String invocationMode;
  List<String> get memberIds => executionMessageIds.keys.toList();
  final String id;
  final String text;
  final String memberId;
  final String executionMessageId;
  final bool explicitMention;
  final bool addressed;
  Map<String, Object?> toJson() => {
    'id': id,
    'text': text,
    'member_id': memberId,
    'execution_message_id': executionMessageId,
    'explicit_mention': explicitMention,
    'addressed': addressed,
    'execution_message_ids': executionMessageIds,
    'pending_member_ids': pendingMemberIds,
    'starting_member_ids': startingMemberIds,
    'content': [for (final part in content) part.toJson()],
    'preferred_skills': preferredSkills,
    'approval_mode': approvalMode,
    'invocation_mode': invocationMode,
  };
  factory StudioTurn.fromJson(Map<String, Object?> json) => StudioTurn(
    id: json['id'] as String,
    text: json['text'] as String,
    memberId: json['member_id'] as String,
    executionMessageId: json['execution_message_id'] as String,
    explicitMention: json['explicit_mention'] == true,
    addressed: json['addressed'] == true,
    executionMessageIds: (json['execution_message_ids'] as Map?)
        ?.cast<String, String>(),
    pendingMemberIds: (json['pending_member_ids'] as List?)?.cast<String>(),
    startingMemberIds: (json['starting_member_ids'] as List?)?.cast<String>(),
    content: [
      for (final part in json['content'] as List? ?? [])
        ChatMessageContent.fromJson((part as Map).cast<String, Object?>()),
    ],
    preferredSkills: (json['preferred_skills'] as List? ?? []).cast<String>(),
    approvalMode: json['approval_mode'] as String? ?? 'high_risk',
    invocationMode: json['invocation_mode'] as String? ?? 'normal',
  );
}

class Studio {
  Studio({
    required this.id,
    required this.name,
    required this.members,
    required this.coordinatorId,
    List<StudioTurn>? turns,
    Set<String>? pinnedTurnIds,
    Set<String>? syncedTurnIds,
    List<Map<String, Object?>>? publicMessages,
    this.messageCursor = 0,
    this.hostRegistered = false,
    Conversation? draft,
  }) : draft =
           draft ??
           Conversation(
             id: id,
             agentId: members.firstWhere((m) => m.id == coordinatorId).agentId,
           ),
       turns = turns ?? [],
       pinnedTurnIds = pinnedTurnIds ?? {},
       syncedTurnIds = syncedTurnIds ?? {},
       publicMessages = publicMessages ?? [];
  final String id;
  final String name;
  final Conversation draft;
  final List<StudioMember> members;
  String coordinatorId;
  bool updatingCoordinator = false;
  final List<StudioTurn> turns;
  final Set<String> pinnedTurnIds;
  final Set<String> syncedTurnIds;
  final List<Map<String, Object?>> publicMessages;
  int messageCursor;
  bool hostRegistered;
  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    'members': [for (final m in members) m.toJson()],
    'coordinator_id': coordinatorId,
    'turns': [for (final t in turns) t.toJson()],
    'pinned_turn_ids': pinnedTurnIds.toList(),
    'synced_turn_ids': syncedTurnIds.toList(),
    'public_messages': publicMessages,
    'message_cursor': messageCursor,
    'host_registered': hostRegistered,
    'draft': draft.toJson(),
  };
  factory Studio.fromJson(Map<String, Object?> json) => Studio(
    id: json['id'] as String,
    name: json['name'] as String,
    publicMessages: [
      for (final message in json['public_messages'] as List? ?? [])
        (message as Map).cast<String, Object?>(),
    ],
    messageCursor: (json['message_cursor'] as num?)?.toInt() ?? 0,
    hostRegistered: json['host_registered'] == true,
    syncedTurnIds: (json['synced_turn_ids'] as List? ?? [])
        .cast<String>()
        .toSet(),
    draft: json['draft'] is Map
        ? Conversation.fromJson((json['draft'] as Map).cast<String, Object?>())
        : null,
    pinnedTurnIds: (json['pinned_turn_ids'] as List? ?? [])
        .cast<String>()
        .toSet(),
    members: [
      for (final m in json['members'] as List)
        StudioMember.fromJson((m as Map).cast<String, Object?>()),
    ],
    coordinatorId: json['coordinator_id'] as String,
    turns: [
      for (final t in json['turns'] as List)
        StudioTurn.fromJson((t as Map).cast<String, Object?>()),
    ],
  );
}

/// Parse explicit mentions without treating code, quotes or emails as routing.
List<String> studioMentionedMemberIds(String text, List<StudioMember> members) {
  final names = <String, Set<String>>{};
  for (final member in members) {
    names.putIfAbsent(member.name, () => {}).add(member.id);
  }
  for (final member in members) {
    names[member.id] = {member.id};
  }
  if (names.isEmpty) return [];
  final labels = names.keys.toList()
    ..sort((a, b) => b.length.compareTo(a.length));
  final ignored = RegExp(
    r'```[\s\S]*?```|`[^`\n]*`|^[ \t]*>[^\n]*',
    multiLine: true,
  ).allMatches(text).toList();
  final pattern = RegExp(
    r'(?<![\p{L}\p{N}_@\\])@(' +
        labels.map(RegExp.escape).join('|') +
        r')(?![\p{L}\p{N}_])',
    unicode: true,
  );
  return {
    for (final match in pattern.allMatches(text))
      if (names[match.group(1)]!.length == 1 &&
          !ignored.any(
            (span) => span.start <= match.start && match.start < span.end,
          ))
        names[match.group(1)]!.single,
  }.toList();
}
