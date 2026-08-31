class UsageOverview {
  const UsageOverview({
    this.rangeDays = 30,
    this.totals = const UsageTotals(),
    this.daily = const [],
    this.models = const [],
    this.agents = const [],
    this.tools = const [],
  });

  final int rangeDays;
  final UsageTotals totals;
  final List<UsageDay> daily;
  final List<UsageBreakdown> models;
  final List<UsageBreakdown> agents;
  final List<ToolUsage> tools;

  factory UsageOverview.fromJson(Map<String, Object?> json) => UsageOverview(
    rangeDays: _integer(json['range_days'], 30),
    totals: UsageTotals.fromJson(_map(json['totals'])),
    daily: _list(json['daily'], UsageDay.fromJson),
    models: _list(json['models'], UsageBreakdown.fromJson),
    agents: _list(json['agents'], UsageBreakdown.fromJson),
    tools: _list(json['tools'], ToolUsage.fromJson),
  );
}

class UsageTotals {
  const UsageTotals({
    this.inputTokens = 0,
    this.outputTokens = 0,
    this.cachedInputTokens = 0,
    this.reasoningTokens = 0,
    this.totalTokens = 0,
    this.modelRequests = 0,
    this.failedModelRequests = 0,
    this.turns = 0,
    this.toolCalls = 0,
    this.sessions = 0,
    this.averageFirstTokenLatencyMs,
    this.outputTokensPerSecond,
  });

  final int inputTokens;
  final int outputTokens;
  final int cachedInputTokens;
  final int reasoningTokens;
  final int totalTokens;
  final int modelRequests;
  final int failedModelRequests;
  final int turns;
  final int toolCalls;
  final int sessions;
  final double? averageFirstTokenLatencyMs;
  final double? outputTokensPerSecond;

  int get nonCachedInputTokens =>
      inputTokens > cachedInputTokens ? inputTokens - cachedInputTokens : 0;

  double get promptCacheUtilization => inputTokens == 0
      ? 0
      : cachedInputTokens >= inputTokens
      ? 1
      : cachedInputTokens / inputTokens;

  factory UsageTotals.fromJson(Map<String, Object?> json) => UsageTotals(
    inputTokens: _integer(json['input_tokens']),
    outputTokens: _integer(json['output_tokens']),
    cachedInputTokens: _integer(json['cached_input_tokens']),
    reasoningTokens: _integer(json['reasoning_tokens']),
    totalTokens: _integer(json['total_tokens']),
    modelRequests: _integer(json['model_requests']),
    failedModelRequests: _integer(json['failed_model_requests']),
    turns: _integer(json['turns']),
    toolCalls: _integer(json['tool_calls']),
    sessions: _integer(json['sessions']),
    averageFirstTokenLatencyMs: _number(json['average_first_token_latency_ms']),
    outputTokensPerSecond: _number(json['output_tokens_per_second']),
  );
}

class UsageDay {
  const UsageDay({
    required this.date,
    this.inputTokens = 0,
    this.outputTokens = 0,
    this.cachedInputTokens = 0,
    this.reasoningTokens = 0,
    this.totalTokens = 0,
    this.turns = 0,
    this.toolCalls = 0,
  });

  final DateTime date;
  final int inputTokens;
  final int outputTokens;
  final int cachedInputTokens;
  final int reasoningTokens;
  final int totalTokens;
  final int turns;
  final int toolCalls;

  int get nonCachedInputTokens =>
      inputTokens > cachedInputTokens ? inputTokens - cachedInputTokens : 0;

  double get promptCacheUtilization => inputTokens == 0
      ? 0
      : cachedInputTokens >= inputTokens
      ? 1
      : cachedInputTokens / inputTokens;

  factory UsageDay.fromJson(Map<String, Object?> json) => UsageDay(
    date: DateTime.tryParse(json['date']?.toString() ?? '') ?? DateTime(1970),
    inputTokens: _integer(json['input_tokens']),
    outputTokens: _integer(json['output_tokens']),
    cachedInputTokens: _integer(json['cached_input_tokens']),
    reasoningTokens: _integer(json['reasoning_tokens']),
    totalTokens: _integer(json['total_tokens']),
    turns: _integer(json['turns']),
    toolCalls: _integer(json['tool_calls']),
  );
}

class UsageBreakdown {
  const UsageBreakdown({
    this.id = '',
    required this.name,
    this.inputTokens = 0,
    this.outputTokens = 0,
    this.cachedInputTokens = 0,
    this.reasoningTokens = 0,
    this.totalTokens = 0,
    this.requests = 0,
    this.turns = 0,
    this.toolCalls = 0,
  });

  final String id;
  final String name;
  final int inputTokens;
  final int outputTokens;
  final int cachedInputTokens;
  final int reasoningTokens;
  final int totalTokens;
  final int requests;
  final int turns;
  final int toolCalls;

  int get nonCachedInputTokens =>
      inputTokens > cachedInputTokens ? inputTokens - cachedInputTokens : 0;

  double get promptCacheUtilization => inputTokens == 0
      ? 0
      : cachedInputTokens >= inputTokens
      ? 1
      : cachedInputTokens / inputTokens;

  factory UsageBreakdown.fromJson(Map<String, Object?> json) => UsageBreakdown(
    id: json['id']?.toString() ?? '',
    name: json['name']?.toString() ?? '',
    inputTokens: _integer(json['input_tokens']),
    outputTokens: _integer(json['output_tokens']),
    cachedInputTokens: _integer(json['cached_input_tokens']),
    reasoningTokens: _integer(json['reasoning_tokens']),
    totalTokens: _integer(json['total_tokens']),
    requests: _integer(json['requests']),
    turns: _integer(json['turns']),
    toolCalls: _integer(json['tool_calls']),
  );
}

class ToolUsage {
  const ToolUsage({required this.name, this.count = 0});

  final String name;
  final int count;

  factory ToolUsage.fromJson(Map<String, Object?> json) => ToolUsage(
    name: json['name']?.toString() ?? '',
    count: _integer(json['count']),
  );
}

int _integer(Object? value, [int fallback = 0]) =>
    value is num ? value.toInt() : int.tryParse('$value') ?? fallback;

double? _number(Object? value) =>
    value is num ? value.toDouble() : double.tryParse('$value');

Map<String, Object?> _map(Object? value) =>
    value is Map ? value.cast<String, Object?>() : const {};

List<T> _list<T>(Object? value, T Function(Map<String, Object?>) decode) =>
    value is List
    ? [
        for (final item in value)
          if (item is Map) decode(item.cast<String, Object?>()),
      ]
    : <T>[];
