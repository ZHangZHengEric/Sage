import 'dart:convert';

import 'package:flutter/widgets.dart';

String toolPresentationLanguage(BuildContext context) {
  final language = Localizations.localeOf(context).languageCode.toLowerCase();
  if (const {
    'zh',
    'en',
    'pt',
    'es',
    'fr',
    'de',
    'ja',
    'ko',
    'ru',
  }.contains(language)) {
    return language;
  }
  return 'en';
}

String localizedToolName(String rawName, String language) {
  final translations = _toolNames[rawName.toLowerCase()];
  if (translations == null) return _humanizeToolName(rawName);
  return translations[language] ??
      (language == 'en'
          ? translations['en']
          : _genericToolLabel(rawName, language)) ??
      rawName;
}

class ToolArgumentPresentation {
  const ToolArgumentPresentation({this.primary = '', this.metadata = const []});

  final String primary;
  final List<String> metadata;

  String get compact => [
    if (primary.isNotEmpty) primary,
    ...metadata.where((value) => value.isNotEmpty),
  ].join(' · ');
}

String? _genericToolLabel(String rawName, String language) =>
    switch (language) {
      'es' => 'Herramienta: $rawName',
      'fr' => 'Outil : $rawName',
      'de' => 'Werkzeug: $rawName',
      'ja' => 'ツール：$rawName',
      'ko' => '도구: $rawName',
      'ru' => 'Инструмент: $rawName',
      _ => null,
    };

String toolPresentationCategory(String rawName) {
  final name = rawName.toLowerCase();
  if (name.startsWith('browser_')) return 'browser';
  if (const {
    'sys_spawn_agent',
    'sys_delegate_task',
    'sys_team_delegate_task',
  }.contains(name)) {
    return 'agent';
  }
  if (const {
    'todo_write',
    'todo_read',
    'goal_submit',
    'plan_submit',
    'goal_complete',
    'turn_status',
  }.contains(name)) {
    return 'planning';
  }
  if (const {'questionnaire', 'questionnaire_async'}.contains(name)) {
    return 'interaction';
  }
  if (name == 'search_memory' || name == 'compress_conversation_history') {
    return 'memory';
  }
  if (name == 'load_skill' || name == 'tool_expand_tools') return 'skill';
  if (name == 'analyze_image') return 'image';
  if (const {'grep', 'glob', 'search_web', 'fetch_webpages'}.contains(name)) {
    return 'search';
  }
  if (const {
    'file_read',
    'read_file',
    'list_dir',
    'read_lints',
  }.contains(name)) {
    return 'read';
  }
  if (const {
    'file_write',
    'write_file',
    'file_update',
    'update_file',
    'apply_patch',
  }.contains(name)) {
    return 'write';
  }
  if (const {
    'execute_shell_command',
    'await_shell',
    'kill_shell',
  }.contains(name)) {
    return 'shell';
  }
  return 'other';
}

String toolArgumentPreview(
  String rawName,
  Map<String, Object?> arguments,
  String language,
) => toolArgumentPresentation(rawName, arguments, language).compact;

ToolArgumentPresentation toolArgumentPresentation(
  String rawName,
  Map<String, Object?> arguments,
  String language,
) {
  if (arguments.isEmpty) return const ToolArgumentPresentation();
  final name = rawName.toLowerCase();
  final path = _firstText(arguments, const ['file_path', 'image_path', 'path']);
  final command = _firstText(arguments, const ['command', 'cmd']);
  final query = _firstText(arguments, const [
    'query',
    'pattern',
    'search_pattern',
    'text',
  ]);

  switch (name) {
    case 'file_read':
    case 'read_file':
      return _presentation(path, [_lineRange(arguments, language)]);
    case 'file_write':
    case 'write_file':
      return _presentation(path, [
        _contentSize(arguments['content'], language),
        _writeMode(arguments['mode'], language),
      ]);
    case 'file_update':
    case 'update_file':
      final operations = _objectList(arguments['operations']);
      return _presentation(path, [
        if (operations.isNotEmpty)
          _countLabel('changes', operations.length, language),
        if (operations.isEmpty) _firstText(arguments, const ['search_pattern']),
      ]);
    case 'apply_patch':
      final files = _patchFiles(arguments['patch']?.toString() ?? '');
      return _presentation(files.take(2).join(' · '), [
        if (files.isNotEmpty) _countLabel('files', files.length, language),
      ]);
    case 'grep':
      return _presentation(_quoted(query), [
        _firstText(arguments, const ['path']),
        _firstText(arguments, const ['glob', 'type']),
        if (arguments['case_insensitive'] == true)
          _flagLabel('caseInsensitive', language),
        if (arguments['multiline'] == true) _flagLabel('multiline', language),
      ]);
    case 'glob':
      return _presentation(
        _quoted(_firstText(arguments, const ['pattern', 'glob'])),
        [
          _firstText(arguments, const ['path']),
          _limit(arguments, language),
        ],
      );
    case 'list_dir':
      return _presentation(path, [
        _numberFact(arguments, 'depth', 'depth', language),
        if (arguments['include_hidden'] == true)
          _flagLabel('includeHidden', language),
      ]);
    case 'execute_shell_command':
      return _presentation(command, [
        _firstText(arguments, const ['workdir', 'cwd']),
        _shellWait(arguments, language),
      ]);
    case 'await_shell':
      return _presentation(_taskReference(arguments, language), [
        _firstText(arguments, const ['match_pattern', 'pattern']),
      ]);
    case 'kill_shell':
      return _presentation(_taskReference(arguments, language), const []);
    case 'read_lints':
      return _presentation(
        _pathList(arguments['paths'], fallback: path),
        const [],
      );
    case 'todo_write':
      return _taskListPresentation(arguments['tasks'], language);
    case 'todo_read':
      return const ToolArgumentPresentation();
    case 'goal_submit':
    case 'plan_submit':
      final content = arguments['content']?.toString() ?? '';
      return _presentation(_firstMeaningfulLine(content), [
        _contentLines(content, language),
      ]);
    case 'goal_complete':
      return _presentation(
        _firstText(arguments, const ['summary', 'content']),
        const [],
      );
    case 'questionnaire':
    case 'questionnaire_async':
      return _questionnairePresentation(arguments, language);
    case 'turn_status':
      return _presentation(
        _turnStatus(arguments['status']?.toString(), language),
        [
          _firstText(arguments, const ['note', 'message']),
        ],
      );
    case 'search_memory':
    case 'search_web':
      return _presentation(_quoted(query), [_limit(arguments, language)]);
    case 'fetch_webpages':
      return _urlPresentation(arguments, language);
    case 'analyze_image':
      return _presentation(path, [
        _firstText(arguments, const ['prompt', 'question']),
      ]);
    case 'tool_expand_tools':
      final names = _stringList(arguments['tool_names']);
      return _presentation(names.take(3).join(', '), [
        if (names.isNotEmpty) _countLabel('tools', names.length, language),
      ]);
    case 'load_skill':
      return _presentation(
        _firstText(arguments, const ['name', 'skill_name']),
        const [],
      );
    case 'sys_spawn_agent':
      return _presentation(_firstText(arguments, const ['name', 'role']), [
        _firstText(arguments, const ['description']),
      ]);
    case 'sys_delegate_task':
    case 'sys_team_delegate_task':
      return _delegationPresentation(arguments, language);
    case 'browser_navigate':
      return _presentation(_displayUrl(arguments['url']), const []);
    case 'browser_find_text':
      return _presentation(_quoted(query), const []);
    case 'browser_scroll':
      return _presentation(
        _browserDirection(arguments['direction']?.toString(), language),
        [_browserPages(arguments['pages'], language)],
      );
    case 'browser_send_keys':
      return _presentation(_quoted(_firstText(arguments, const ['keys'])), [
        _firstText(arguments, const ['selector']),
        if (arguments['submit'] == true) _flagLabel('submit', language),
      ]);
    case 'browser_wait':
      return _presentation(_seconds(arguments['seconds'], language), const []);
    case 'browser_switch_tab':
      return _presentation(_browserTabReference(arguments, language), const []);
    case 'browser_select_dropdown':
      return _presentation(
        _quoted(_firstText(arguments, const ['text', 'value'])),
        [
          _firstText(arguments, const ['selector']),
        ],
      );
    case 'browser_upload_file':
      return _presentation(
        _firstText(arguments, const ['file_name', 'fileName']),
        [
          _firstText(arguments, const ['file_mime_type', 'mimeType']),
        ],
      );
    case 'browser_screenshot':
      return _presentation(_firstText(arguments, const ['format']), [
        _numberFact(arguments, 'quality', 'quality', language),
      ]);
    case 'browser_dom_action':
      return _browserActionPresentation(arguments, language);
    case 'browser_get_context':
    case 'browser_list_tabs':
    case 'compress_conversation_history':
      return const ToolArgumentPresentation();
  }

  final orderedKeys = <String>[...?_toolArgumentOrder[name], ...arguments.keys];
  final seen = <String>{};
  final values = <String>[];
  for (final key in orderedKeys) {
    if (!seen.add(key) || _isHiddenArgument(key)) continue;
    final value = arguments[key];
    final formatted = _formatArgument(key, value, language);
    if (formatted.isEmpty) continue;
    values.add(formatted);
    if (values.length == 3) break;
  }
  return _presentation(values.isEmpty ? '' : values.first, values.skip(1));
}

ToolArgumentPresentation _presentation(
  String primary,
  Iterable<String> metadata,
) {
  final normalizedPrimary = _ellipsize(_compactValue(primary), 150);
  final seen = <String>{normalizedPrimary};
  final normalizedMetadata = <String>[];
  for (final value in metadata) {
    final normalized = _ellipsize(_compactValue(value), 90);
    if (normalized.isEmpty || !seen.add(normalized)) continue;
    normalizedMetadata.add(normalized);
  }
  return ToolArgumentPresentation(
    primary: normalizedPrimary,
    metadata: normalizedMetadata.take(3).toList(growable: false),
  );
}

String _quoted(String value) => value.trim().isEmpty ? '' : '“${value.trim()}”';

String _lineRange(Map<String, Object?> arguments, String language) {
  final start = arguments['start_line'];
  final end = arguments['end_line'];
  if (start is! num && end is! num) return '';
  final value = start is num && end is num
      ? '${start.toInt()}–${end.toInt()}'
      : (start ?? end).toString();
  return switch (language) {
    'zh' => '第 $value 行',
    'pt' => 'Linhas $value',
    _ => 'Lines $value',
  };
}

String _contentSize(Object? raw, String language) {
  final content = raw?.toString() ?? '';
  if (content.isEmpty) return '';
  final lines = '\n'.allMatches(content).length + 1;
  return switch (language) {
    'zh' => '${content.length} 个字符 / $lines 行',
    'pt' => '${content.length} caracteres / $lines linhas',
    _ => '${content.length} characters / $lines lines',
  };
}

String _contentLines(String content, String language) {
  if (content.isEmpty) return '';
  final lines = '\n'.allMatches(content).length + 1;
  return _countLabel('lines', lines, language);
}

String _writeMode(Object? raw, String language) {
  final mode = raw?.toString().toLowerCase() ?? '';
  if (mode.isEmpty) return '';
  if (mode == 'append') return _flagLabel('append', language);
  if (mode == 'overwrite' || mode == 'write') {
    return _flagLabel('overwrite', language);
  }
  return _humanizeToolName(mode);
}

String _flagLabel(String key, String language) {
  const labels = <String, Map<String, String>>{
    'append': {'zh': '追加', 'en': 'Append', 'pt': 'Anexar'},
    'overwrite': {'zh': '覆盖', 'en': 'Overwrite', 'pt': 'Sobrescrever'},
    'caseInsensitive': {
      'zh': '忽略大小写',
      'en': 'Ignore case',
      'pt': 'Ignorar maiúsculas',
    },
    'multiline': {'zh': '跨行匹配', 'en': 'Multiline', 'pt': 'Multilinha'},
    'includeHidden': {
      'zh': '包含隐藏文件',
      'en': 'Include hidden files',
      'pt': 'Incluir ocultos',
    },
    'background': {'zh': '后台运行', 'en': 'Background', 'pt': 'Em segundo plano'},
    'submit': {'zh': '提交表单', 'en': 'Submit', 'pt': 'Enviar'},
  };
  return labels[key]?[language] ?? labels[key]?['en'] ?? '';
}

String _countLabel(String kind, int count, String language) {
  if (count <= 0) return '';
  if (language == 'zh') {
    return switch (kind) {
      'files' => '$count 个文件',
      'changes' => '$count 处变更',
      'tasks' => '$count 个任务',
      'subtasks' => '$count 个子任务',
      'questions' => '$count 个问题',
      'tools' => '$count 个工具',
      'urls' => '$count 个网页',
      'lines' => '$count 行',
      _ => '$count 项',
    };
  }
  if (language == 'pt') {
    return switch (kind) {
      'files' => '$count arquivos',
      'changes' => '$count alterações',
      'tasks' => '$count tarefas',
      'subtasks' => '$count subtarefas',
      'questions' => '$count perguntas',
      'tools' => '$count ferramentas',
      'urls' => '$count páginas',
      'lines' => '$count linhas',
      _ => '$count itens',
    };
  }
  return switch (kind) {
    'files' => '$count ${count == 1 ? 'file' : 'files'}',
    'changes' => '$count ${count == 1 ? 'change' : 'changes'}',
    'tasks' => '$count ${count == 1 ? 'task' : 'tasks'}',
    'subtasks' => '$count ${count == 1 ? 'subtask' : 'subtasks'}',
    'questions' => '$count ${count == 1 ? 'question' : 'questions'}',
    'tools' => '$count ${count == 1 ? 'tool' : 'tools'}',
    'urls' => '$count ${count == 1 ? 'webpage' : 'webpages'}',
    'lines' => '$count ${count == 1 ? 'line' : 'lines'}',
    _ => '$count items',
  };
}

String _numberFact(
  Map<String, Object?> arguments,
  String argumentKey,
  String labelKey,
  String language,
) {
  final value = arguments[argumentKey];
  if (value is! num) return '';
  final label = switch ((labelKey, language)) {
    ('depth', 'zh') => '深度',
    ('quality', 'zh') => '质量',
    ('depth', 'pt') => 'Profundidade',
    ('quality', 'pt') => 'Qualidade',
    ('depth', _) => 'Depth',
    ('quality', _) => 'Quality',
    _ => _humanizeToolName(labelKey),
  };
  return '$label ${value.toInt()}';
}

String _limit(Map<String, Object?> arguments, String language) {
  final value =
      arguments['head_limit'] ?? arguments['max_results'] ?? arguments['limit'];
  if (value is! num) return '';
  return switch (language) {
    'zh' => '最多 ${value.toInt()} 项',
    'pt' => 'Até ${value.toInt()}',
    _ => 'Up to ${value.toInt()}',
  };
}

String _shellWait(Map<String, Object?> arguments, String language) {
  if (arguments['background'] == true || arguments['block'] == false) {
    return _flagLabel('background', language);
  }
  final value = arguments['block_until_ms'];
  if (value is! num) return '';
  if (value.toInt() == 0) return _flagLabel('background', language);
  return switch (language) {
    'zh' => '等待 ${value.toInt()}ms',
    'pt' => 'Aguardar ${value.toInt()}ms',
    _ => 'Wait ${value.toInt()}ms',
  };
}

String _taskReference(Map<String, Object?> arguments, String language) {
  final identifier = _firstText(arguments, const ['task_id', 'process_id']);
  final prefix = switch (language) {
    'zh' => '后台任务',
    'pt' => 'Tarefa em segundo plano',
    _ => 'Background task',
  };
  if (identifier.isEmpty) return prefix;
  final short = identifier.length <= 12
      ? identifier
      : '…${identifier.substring(identifier.length - 8)}';
  return '$prefix $short';
}

List<Map<String, Object?>> _objectList(Object? raw) {
  if (raw is! List) return const [];
  return [
    for (final value in raw)
      if (value is Map)
        value.map((key, item) => MapEntry(key.toString(), item)),
  ];
}

List<String> _stringList(Object? raw) {
  if (raw is! List) return const [];
  return [
    for (final value in raw)
      if (_compactValue(value).isNotEmpty) _compactValue(value),
  ];
}

String _pathList(Object? raw, {String fallback = ''}) {
  final paths = _stringList(raw);
  return paths.isEmpty ? fallback : paths.take(3).join(', ');
}

ToolArgumentPresentation _taskListPresentation(Object? raw, String language) {
  final tasks = _objectList(raw);
  if (tasks.isEmpty) return const ToolArgumentPresentation();
  final first = _firstText(tasks.first, const ['content', 'title', 'name']);
  final statuses = <String, int>{};
  for (final task in tasks) {
    final status = task['status']?.toString().trim() ?? '';
    if (status.isNotEmpty) statuses[status] = (statuses[status] ?? 0) + 1;
  }
  final statusSummary = statuses.entries
      .map((entry) => '${_taskStatus(entry.key, language)} ${entry.value}')
      .join(' / ');
  return _presentation(first, [
    _countLabel('tasks', tasks.length, language),
    statusSummary,
  ]);
}

String _taskStatus(String status, String language) {
  if (language == 'zh') {
    return switch (status) {
      'pending' => '待处理',
      'in_progress' => '进行中',
      'completed' => '已完成',
      _ => status,
    };
  }
  if (language == 'pt') {
    return switch (status) {
      'pending' => 'Pendente',
      'in_progress' => 'Em andamento',
      'completed' => 'Concluída',
      _ => status,
    };
  }
  return switch (status) {
    'pending' => 'Pending',
    'in_progress' => 'In progress',
    'completed' => 'Completed',
    _ => _humanizeToolName(status),
  };
}

String _firstMeaningfulLine(String value) {
  for (final line in value.split('\n')) {
    final normalized = line
        .replaceFirst(RegExp(r'^\s{0,3}#{1,6}\s*'), '')
        .trim();
    if (normalized.isNotEmpty) return normalized;
  }
  return '';
}

ToolArgumentPresentation _questionnairePresentation(
  Map<String, Object?> arguments,
  String language,
) {
  final questions = _objectList(arguments['questions']);
  final first = questions.isEmpty
      ? _firstText(arguments, const ['prompt', 'title'])
      : _firstText(questions.first, const [
          'text',
          'question',
          'title',
          'prompt',
          'header',
        ]);
  return _presentation(first, [
    if (questions.isNotEmpty)
      _countLabel('questions', questions.length, language),
  ]);
}

String _turnStatus(String? status, String language) {
  final value = status?.toLowerCase() ?? '';
  if (language == 'zh') {
    return switch (value) {
      'task_done' => '任务完成',
      'need_user_input' => '等待用户输入',
      'blocked' => '遇到阻塞',
      'continue_work' => '继续工作',
      'failed' => '执行失败',
      _ => value,
    };
  }
  return switch (value) {
    'task_done' => 'Task completed',
    'need_user_input' => 'Waiting for user input',
    'blocked' => 'Blocked',
    'continue_work' => 'Continue working',
    'failed' => 'Failed',
    _ => _humanizeToolName(value),
  };
}

ToolArgumentPresentation _urlPresentation(
  Map<String, Object?> arguments,
  String language,
) {
  final urls = <String>[
    ..._stringList(arguments['urls']),
    if (_firstText(arguments, const ['url']) case final value)
      if (value.isNotEmpty) value,
  ];
  return _presentation(urls.isEmpty ? '' : _displayUrl(urls.first), [
    if (urls.isNotEmpty) _countLabel('urls', urls.length, language),
  ]);
}

String _displayUrl(Object? raw) {
  final value = _compactValue(raw);
  if (value.isEmpty) return '';
  final uri = Uri.tryParse(value);
  if (uri == null || uri.host.isEmpty) return value;
  final path = uri.path == '/' ? '' : uri.path;
  final query = uri.hasQuery ? '?${uri.query}' : '';
  return '${uri.host}$path$query';
}

ToolArgumentPresentation _delegationPresentation(
  Map<String, Object?> arguments,
  String language,
) {
  final tasks = _objectList(arguments['tasks']);
  if (tasks.isNotEmpty) {
    final first = _firstText(tasks.first, const [
      'content',
      'task',
      'prompt',
      'task_name',
    ]);
    return _presentation(first, [
      _countLabel('subtasks', tasks.length, language),
    ]);
  }
  final task = _firstText(arguments, const ['content', 'task', 'prompt']);
  return _presentation(task, [
    if (task.isNotEmpty) _countLabel('subtasks', 1, language),
  ]);
}

String _browserDirection(String? raw, String language) {
  final direction = raw?.toLowerCase() ?? 'down';
  if (language == 'zh') return direction == 'up' ? '向上滚动' : '向下滚动';
  return direction == 'up' ? 'Scroll up' : 'Scroll down';
}

String _browserPages(Object? raw, String language) {
  if (raw is! num) return '';
  return switch (language) {
    'zh' => '${raw.toString()} 页',
    'pt' => '${raw.toString()} páginas',
    _ => '${raw.toString()} pages',
  };
}

String _seconds(Object? raw, String language) {
  if (raw is! num) return '';
  return switch (language) {
    'zh' => '等待 ${raw.toString()} 秒',
    'pt' => 'Aguardar ${raw.toString()}s',
    _ => 'Wait ${raw.toString()}s',
  };
}

String _browserTabReference(Map<String, Object?> arguments, String language) {
  final identifier = arguments['tab_id'] ?? arguments['tab_id_suffix'];
  final prefix = language == 'zh' ? '标签页' : 'Tab';
  return identifier == null ? prefix : '$prefix $identifier';
}

ToolArgumentPresentation _browserActionPresentation(
  Map<String, Object?> arguments,
  String language,
) {
  final action = arguments['action']?.toString().toLowerCase() ?? '';
  final actionLabel = _browserActionLabel(action, language);
  final target = _firstText(arguments, const [
    'text',
    'value',
    'keys',
    'file_name',
    'selector',
  ]);
  return _presentation(actionLabel, [
    if (target.isNotEmpty) _quoted(target),
    if (action == 'scroll')
      _browserDirection(arguments['direction']?.toString(), language),
    if (action == 'wait') _seconds(arguments['seconds'], language),
  ]);
}

String _browserActionLabel(String action, String language) {
  const zh = {
    'click': '点击元素',
    'fill': '填写内容',
    'extract_text': '提取文本',
    'run_script': '运行页面脚本',
    'find_text': '查找文本',
    'scroll': '滚动页面',
    'send_keys': '输入内容',
    'wait': '等待页面',
    'list_tabs': '查看标签页',
    'switch_tab': '切换标签页',
    'select_dropdown': '选择下拉项',
    'upload_file': '上传文件',
    'screenshot': '截取网页',
  };
  if (language == 'zh') return zh[action] ?? _humanizeToolName(action);
  return _humanizeToolName(action);
}

class ApprovalToolPresentation {
  const ApprovalToolPresentation({
    required this.summary,
    required this.technicalDetails,
    this.preview,
    this.previewLabel,
    this.facts = const [],
  });

  final String summary;
  final String? preview;
  final String? previewLabel;
  final List<String> facts;
  final String technicalDetails;
}

ApprovalToolPresentation approvalToolPresentation(
  String rawName,
  Map<String, Object?> arguments,
  String language,
) {
  final name = rawName.toLowerCase();
  final path = _firstText(arguments, const ['file_path', 'path']);
  final command = _firstText(arguments, const ['command', 'cmd']);
  final facts = <String>[];
  String summary = toolArgumentPreview(rawName, arguments, language);
  String? preview;
  String? previewLabel;

  if (name == 'file_write') {
    final content = arguments['content']?.toString() ?? '';
    summary = path.isEmpty ? _approvalText('unnamedFile', language) : path;
    preview = _boundedPreview(content);
    previewLabel = _approvalText('contentPreview', language);
    final lineCount = content.isEmpty ? 0 : '\n'.allMatches(content).length + 1;
    facts.add(_approvalText('characters', language, content.length));
    facts.add(_approvalText('lines', language, lineCount));
    final mode = arguments['mode']?.toString();
    if (mode != null && mode.isNotEmpty) {
      facts.add(
        mode == 'append'
            ? _approvalText('append', language)
            : _approvalText('overwrite', language),
      );
    }
  } else if (name == 'goal_submit') {
    final content = arguments['content']?.toString() ?? '';
    final firstLine = content.split('\n').first.trim();
    summary = firstLine.isEmpty
        ? _approvalText('submittedPlan', language)
        : firstLine;
    preview = _boundedPreview(content, maxCharacters: 12000, maxLines: 120);
    previewLabel = _approvalText('planPreview', language);
    final lineCount = content.isEmpty ? 0 : '\n'.allMatches(content).length + 1;
    facts.add(_approvalText('characters', language, content.length));
    facts.add(_approvalText('lines', language, lineCount));
  } else if (name == 'file_update') {
    summary = path.isEmpty ? _approvalText('unnamedFile', language) : path;
    final operations = arguments['operations'];
    if (operations is List) {
      facts.add(_approvalText('changes', language, operations.length));
      preview = _formatUpdateOperations(operations, language);
      previewLabel = _approvalText('changePreview', language);
    }
  } else if (name == 'apply_patch') {
    final patch = arguments['patch']?.toString() ?? '';
    summary = _patchFiles(patch).join(' · ');
    if (summary.isEmpty) summary = _approvalText('workspacePatch', language);
    preview = _boundedPreview(patch);
    previewLabel = _approvalText('changePreview', language);
  } else if (name == 'execute_shell_command') {
    summary = command;
    final workdir = _firstText(arguments, const ['workdir', 'cwd']);
    if (workdir.isNotEmpty) facts.add(workdir);
    final wait = arguments['block_until_ms'];
    if (wait is num) facts.add(_approvalText('wait', language, wait.toInt()));
  } else {
    summary = toolArgumentPreview(rawName, arguments, language);
  }

  if (summary.trim().isEmpty) {
    summary = _approvalText('reviewArguments', language);
  }
  return ApprovalToolPresentation(
    summary: _ellipsize(summary.trim(), 260),
    preview: preview?.trim().isEmpty ?? true ? null : preview,
    previewLabel: previewLabel,
    facts: facts,
    technicalDetails: _prettyJson(arguments),
  );
}

String _firstText(Map<String, Object?> values, List<String> keys) {
  for (final key in keys) {
    final value = values[key]?.toString().trim() ?? '';
    if (value.isNotEmpty) return value;
  }
  return '';
}

String _boundedPreview(
  String value, {
  int maxCharacters = 1800,
  int maxLines = 18,
}) {
  final lines = value.split('\n');
  var result = lines.take(maxLines).join('\n');
  final truncated = lines.length > maxLines || result.length > maxCharacters;
  if (result.length > maxCharacters) {
    result = result.substring(0, maxCharacters);
  }
  return truncated ? '$result\n…' : result;
}

String _formatUpdateOperations(List<Object?> operations, String language) {
  final sections = <String>[];
  for (var index = 0; index < operations.length && index < 4; index++) {
    final operation = operations[index];
    if (operation is! Map) continue;
    final values = operation.cast<Object?, Object?>();
    final mode = values['update_mode']?.toString();
    if (mode == 'search_replace') {
      final search = values['search_pattern']?.toString() ?? '';
      final replacement = values['replacement']?.toString() ?? '';
      sections.add(
        '${_approvalText('find', language)}\n${_boundedPreview(search, maxCharacters: 500)}\n'
        '${_approvalText('replaceWith', language)}\n${_boundedPreview(replacement, maxCharacters: 700)}',
      );
    } else {
      final start = values['start_line'];
      final end = values['end_line'];
      final replacement = values['replacement']?.toString() ?? '';
      sections.add(
        '${_approvalText('linesRange', language)} $start–$end\n'
        '${_boundedPreview(replacement, maxCharacters: 900)}',
      );
    }
  }
  if (operations.length > 4) sections.add('…');
  return sections.join('\n\n');
}

List<String> _patchFiles(String patch) => RegExp(
  r'^\*\*\* (?:Add|Update|Delete) File: (.+)$',
  multiLine: true,
).allMatches(patch).map((match) => match.group(1)!.trim()).toList();

String _prettyJson(Map<String, Object?> arguments) {
  try {
    return const JsonEncoder.withIndent('  ').convert(arguments);
  } on JsonUnsupportedObjectError {
    return arguments.toString();
  }
}

String _approvalText(String key, String language, [int? value]) {
  if (value != null) {
    return switch ((key, language)) {
      ('characters', 'zh') => '$value 个字符',
      ('characters', 'pt') => '$value caracteres',
      ('characters', 'es') => '$value caracteres',
      ('characters', 'fr') => '$value caractères',
      ('characters', 'de') => '$value Zeichen',
      ('characters', 'ja') => '$value 文字',
      ('characters', 'ko') => '$value자',
      ('characters', 'ru') => '$value симв.',
      ('lines', 'zh') => '$value 行',
      ('lines', 'pt') => '$value linhas',
      ('lines', 'es') => '$value líneas',
      ('lines', 'fr') => '$value lignes',
      ('lines', 'de') => '$value Zeilen',
      ('lines', 'ja') => '$value 行',
      ('lines', 'ko') => '$value줄',
      ('lines', 'ru') => '$value строк',
      ('changes', 'zh') => '$value 处变更',
      ('changes', 'pt') => '$value alterações',
      ('changes', 'es') => '$value cambios',
      ('changes', 'fr') => '$value modifications',
      ('changes', 'de') => '$value Änderungen',
      ('changes', 'ja') => '$value 件の変更',
      ('changes', 'ko') => '$value개 변경',
      ('changes', 'ru') => '$value изменений',
      ('wait', 'zh') => '等待 ${value}ms',
      ('wait', 'pt') => 'Aguardar ${value}ms',
      ('wait', 'es') => 'Esperar ${value}ms',
      ('wait', 'fr') => 'Attendre ${value}ms',
      ('wait', 'de') => '${value}ms warten',
      ('wait', 'ja') => '${value}ms 待機',
      ('wait', 'ko') => '${value}ms 대기',
      ('wait', 'ru') => 'Ожидание $valueмс',
      ('characters', _) => '$value characters',
      ('lines', _) => '$value lines',
      ('changes', _) => '$value changes',
      ('wait', _) => 'Wait ${value}ms',
      _ => key,
    };
  }
  final localized = _approvalLabels[key];
  if (localized != null) return localized[language] ?? localized['en'] ?? key;
  return switch (key) {
    _ => key,
  };
}

const _approvalLabels = <String, Map<String, String>>{
  'unnamedFile': {
    'zh': '未命名文件',
    'en': 'Unnamed file',
    'pt': 'Arquivo sem nome',
    'es': 'Archivo sin nombre',
    'fr': 'Fichier sans nom',
    'de': 'Unbenannte Datei',
    'ja': '無題のファイル',
    'ko': '이름 없는 파일',
    'ru': 'Файл без имени',
  },
  'contentPreview': {
    'zh': '内容预览',
    'en': 'Content preview',
    'pt': 'Prévia do conteúdo',
    'es': 'Vista previa del contenido',
    'fr': 'Aperçu du contenu',
    'de': 'Inhaltsvorschau',
    'ja': '内容プレビュー',
    'ko': '내용 미리보기',
    'ru': 'Предпросмотр содержимого',
  },
  'submittedPlan': {
    'zh': '待审批计划',
    'en': 'Plan awaiting approval',
    'pt': 'Plano aguardando aprovação',
    'es': 'Plan pendiente de aprobación',
    'fr': 'Plan en attente d’approbation',
    'de': 'Plan zur Genehmigung',
    'ja': '承認待ちの計画',
    'ko': '승인 대기 중인 계획',
    'ru': 'План ожидает утверждения',
  },
  'planPreview': {
    'zh': '计划全文',
    'en': 'Full plan',
    'pt': 'Plano completo',
    'es': 'Plan completo',
    'fr': 'Plan complet',
    'de': 'Vollständiger Plan',
    'ja': '計画全文',
    'ko': '전체 계획',
    'ru': 'Полный план',
  },
  'changePreview': {
    'zh': '变更预览',
    'en': 'Change preview',
    'pt': 'Prévia das alterações',
    'es': 'Vista previa de cambios',
    'fr': 'Aperçu des modifications',
    'de': 'Änderungsvorschau',
    'ja': '変更プレビュー',
    'ko': '변경 미리보기',
    'ru': 'Предпросмотр изменений',
  },
  'append': {
    'zh': '追加写入',
    'en': 'Append',
    'pt': 'Anexar',
    'es': 'Añadir',
    'fr': 'Ajouter',
    'de': 'Anhängen',
    'ja': '追記',
    'ko': '추가',
    'ru': 'Добавить',
  },
  'overwrite': {
    'zh': '覆盖写入',
    'en': 'Overwrite',
    'pt': 'Sobrescrever',
    'es': 'Sobrescribir',
    'fr': 'Écraser',
    'de': 'Überschreiben',
    'ja': '上書き',
    'ko': '덮어쓰기',
    'ru': 'Перезаписать',
  },
  'workspacePatch': {
    'zh': '工作区补丁',
    'en': 'Workspace patch',
    'pt': 'Patch do workspace',
    'es': 'Parche del espacio de trabajo',
    'fr': 'Correctif de l’espace de travail',
    'de': 'Workspace-Patch',
    'ja': 'ワークスペースパッチ',
    'ko': '워크스페이스 패치',
    'ru': 'Патч рабочей области',
  },
  'command': {
    'zh': '即将执行',
    'en': 'Command',
    'pt': 'Comando',
    'es': 'Comando',
    'fr': 'Commande',
    'de': 'Befehl',
    'ja': 'コマンド',
    'ko': '명령',
    'ru': 'Команда',
  },
  'reviewArguments': {
    'zh': '请检查此工具调用',
    'en': 'Review this tool call',
    'pt': 'Revise esta chamada de ferramenta',
    'es': 'Revisa esta llamada a la herramienta',
    'fr': 'Vérifiez cet appel d’outil',
    'de': 'Prüfen Sie diesen Werkzeugaufruf',
    'ja': 'このツール呼び出しを確認してください',
    'ko': '이 도구 호출을 확인하세요',
    'ru': 'Проверьте этот вызов инструмента',
  },
  'find': {
    'zh': '查找',
    'en': 'Find',
    'pt': 'Localizar',
    'es': 'Buscar',
    'fr': 'Rechercher',
    'de': 'Suchen',
    'ja': '検索',
    'ko': '찾기',
    'ru': 'Найти',
  },
  'replaceWith': {
    'zh': '替换为',
    'en': 'Replace with',
    'pt': 'Substituir por',
    'es': 'Reemplazar por',
    'fr': 'Remplacer par',
    'de': 'Ersetzen durch',
    'ja': '次に置換',
    'ko': '다음으로 바꾸기',
    'ru': 'Заменить на',
  },
  'linesRange': {
    'zh': '替换行',
    'en': 'Replace lines',
    'pt': 'Substituir linhas',
    'es': 'Reemplazar líneas',
    'fr': 'Remplacer les lignes',
    'de': 'Zeilen ersetzen',
    'ja': '行を置換',
    'ko': '줄 바꾸기',
    'ru': 'Заменить строки',
  },
};

String localizedToolResultSummary(String result, String language) {
  final value = result.trim();
  if (value.isEmpty) return '';
  try {
    final decoded = jsonDecode(value);
    if (decoded is! Map) return '';
    for (final key in const ['localized_summary', 'summary', 'message']) {
      final candidate = decoded[key]?.toString().trim() ?? '';
      if (candidate.isNotEmpty) return _ellipsize(candidate, 120);
    }
    final count = decoded['count'] ?? decoded['total'] ?? decoded['matched'];
    if (count is num) {
      return switch (language) {
        'zh' => '${count.toInt()} 项结果',
        'pt' => '${count.toInt()} resultados',
        _ => '${count.toInt()} results',
      };
    }
    final status = decoded['status']?.toString().trim() ?? '';
    if (status.isNotEmpty && status != 'success' && status != 'completed') {
      return _ellipsize(status, 120);
    }
  } on FormatException {
    // Raw tool output is intentionally not surfaced in the compact activity UI.
  }
  return '';
}

String localizedProcessSummary(
  String category,
  int count,
  String language, {
  required bool mixed,
}) {
  if (mixed || category == 'other') {
    return switch (language) {
      'zh' => '执行了 $count 个操作',
      'pt' => '$count operações executadas',
      _ => 'Ran $count operations',
    };
  }
  return switch ((language, category)) {
    ('zh', 'search') => '搜索了 $count 次内容，共 $count 个操作',
    ('zh', 'read') => '读取了 $count 个文件，共 $count 个操作',
    ('zh', 'write') => '修改了 $count 个文件，共 $count 个操作',
    ('zh', 'shell') => '执行了 $count 个命令，共 $count 个操作',
    ('zh', 'agent') => '调度了 $count 个 Agent，共 $count 个操作',
    ('zh', 'planning') => '更新了 $count 项任务或计划',
    ('zh', 'interaction') => '发起了 $count 次交互',
    ('zh', 'browser') => '执行了 $count 个浏览器操作',
    ('zh', 'memory') => '处理了 $count 次上下文或记忆',
    ('zh', 'skill') => '加载了 $count 项能力',
    ('zh', 'image') => '分析了 $count 张图片',
    ('pt', 'search') => '$count buscas · $count operações',
    ('pt', 'read') => '$count arquivos lidos · $count operações',
    ('pt', 'write') => '$count arquivos alterados · $count operações',
    ('pt', 'shell') => '$count comandos executados · $count operações',
    ('pt', 'agent') => '$count agentes acionados · $count operações',
    ('pt', 'planning') => '$count itens de planejamento atualizados',
    ('pt', 'interaction') => '$count interações iniciadas',
    ('pt', 'browser') => '$count operações do navegador',
    ('pt', 'memory') => '$count operações de memória',
    ('pt', 'skill') => '$count recursos carregados',
    ('pt', 'image') => '$count imagens analisadas',
    (_, 'search') => 'Searched $count times · $count operations',
    (_, 'read') => 'Read $count files · $count operations',
    (_, 'write') => 'Changed $count files · $count operations',
    (_, 'shell') => 'Ran $count commands · $count operations',
    (_, 'agent') => 'Delegated to $count agents · $count operations',
    (_, 'planning') => 'Updated $count planning items',
    (_, 'interaction') => 'Started $count interactions',
    (_, 'browser') => 'Ran $count browser operations',
    (_, 'memory') => 'Processed $count memory operations',
    (_, 'skill') => 'Loaded $count capabilities',
    (_, 'image') => 'Analyzed $count images',
    _ => 'Ran $count operations',
  };
}

String localizedToolFailure(String language) => switch (language) {
  'zh' => '执行失败',
  'pt' => 'Falhou',
  'es' => 'Falló',
  'fr' => 'Échec',
  'de' => 'Fehlgeschlagen',
  'ja' => '実行失敗',
  'ko' => '실행 실패',
  'ru' => 'Ошибка выполнения',
  _ => 'Failed',
};

String _formatArgument(String key, Object? value, String language) {
  if (value == null) return '';
  if (value is bool) {
    if (!value) return '';
    final labels = _argumentLabels[key];
    String? fallback;
    if (language == 'en') {
      fallback = labels == null ? null : labels['en'];
    } else {
      fallback = _genericArgumentLabel(key, language);
    }
    return (labels == null ? null : labels[language]) ??
        fallback ??
        _humanizeToolName(key);
  }
  if (value is num && _argumentLabels.containsKey(key)) {
    final labels = _argumentLabels[key]!;
    final fallback = language == 'en'
        ? labels['en']
        : _genericArgumentLabel(key, language);
    final label = labels[language] ?? fallback ?? key;
    return language == 'zh'
        ? '$label ${value.toInt()}'
        : '$label ${value.toInt()}';
  }
  if (value is List) {
    final items = value
        .map(
          (item) => item is Map
              ? _safeMapSummary(item.cast<Object?, Object?>())
              : _compactValue(item),
        )
        .where((item) => item.isNotEmpty);
    return _ellipsize(items.join(', '), 92);
  }
  if (value is Map) return _safeMapSummary(value.cast<Object?, Object?>());
  final text = _compactValue(value);
  if (text.isEmpty) return '';
  if (_quotedArguments.contains(key)) return '“${_ellipsize(text, 92)}”';
  return _ellipsize(text, key == 'command' || key == 'cmd' ? 132 : 92);
}

String? _genericArgumentLabel(String key, String language) =>
    switch (language) {
      'es' => 'Parámetro $key',
      'fr' => 'Paramètre $key',
      'de' => 'Parameter $key',
      'ja' => 'パラメーター $key',
      'ko' => '매개변수 $key',
      'ru' => 'Параметр $key',
      _ => null,
    };

String _compactValue(Object? value) =>
    value?.toString().replaceAll(RegExp(r'\s+'), ' ').trim() ?? '';

String _safeMapSummary(Map<Object?, Object?> value) {
  for (final key in const [
    'content',
    'task',
    'title',
    'name',
    'query',
    'path',
    'url',
    'status',
  ]) {
    final candidate = _compactValue(value[key]);
    if (candidate.isNotEmpty) return _ellipsize(candidate, 92);
  }
  return '';
}

String _ellipsize(String value, int maxLength) =>
    value.length <= maxLength ? value : '${value.substring(0, maxLength - 1)}…';

String _humanizeToolName(String value) {
  final words = value
      .replaceAll(RegExp(r'^(mcp__|sys_)'), '')
      .split(RegExp(r'[_\-.]+'))
      .where((word) => word.isNotEmpty)
      .toList();
  if (words.isEmpty) return value;
  return [
    words.first[0].toUpperCase() + words.first.substring(1),
    ...words.skip(1),
  ].join(' ');
}

const _hiddenArguments = {
  'session_id',
  'run_id',
  'turn_id',
  'tool_call_id',
  'parent_tool_call_id',
  'child_session_id',
  'child_run_id',
  'agent_id',
  'approval_id',
  'sandbox_approval_mode',
  'command_policy',
  'env_vars',
  'idempotency_key',
  'system_prompt',
  'original_task',
  'file_data_base64',
  'fileDataBase64',
  'data_url',
  'image_base64',
};

bool _isHiddenArgument(String key) {
  if (_hiddenArguments.contains(key)) return true;
  final normalized = key.toLowerCase();
  return normalized.contains('password') ||
      normalized.contains('secret') ||
      normalized == 'token' ||
      normalized.endsWith('_token') ||
      normalized == 'api_key' ||
      normalized.endsWith('_api_key');
}

const _quotedArguments = {
  'pattern',
  'query',
  'search_pattern',
  'name',
  'prompt',
};

const _toolArgumentOrder = <String, List<String>>{
  'file_read': ['file_path', 'path', 'start_line', 'end_line'],
  'file_write': ['file_path', 'path', 'content'],
  'file_update': ['file_path', 'path', 'search_pattern', 'replacement'],
  'apply_patch': ['patch'],
  'grep': ['pattern', 'query', 'path', 'glob', 'type'],
  'glob': ['pattern', 'path', 'head_limit'],
  'list_dir': ['path', 'depth', 'include_hidden'],
  'execute_shell_command': ['command', 'cmd', 'workdir', 'block_until_ms'],
  'await_shell': ['task_id'],
  'kill_shell': ['task_id'],
  'goal_submit': ['content'],
  'read_lints': ['paths', 'path'],
  'search_web': ['query', 'url'],
  'fetch_webpages': ['urls', 'url'],
  'load_skill': ['name', 'skill_name'],
  'sys_spawn_agent': ['role', 'task', 'prompt'],
  'sys_delegate_task': ['tasks', 'task', 'prompt'],
  'sys_team_delegate_task': ['tasks', 'task', 'prompt'],
  'goal_complete': ['summary'],
  'questionnaire_async': ['questions'],
  'turn_status': ['status', 'note'],
  'search_memory': ['query', 'limit'],
  'analyze_image': ['image_path', 'path', 'prompt'],
  'tool_expand_tools': ['tool_names'],
  'browser_navigate': ['url'],
  'browser_find_text': ['text'],
  'browser_scroll': ['direction', 'pages'],
  'browser_send_keys': ['keys', 'selector', 'submit'],
  'browser_wait': ['seconds'],
  'browser_switch_tab': ['tab_id', 'tab_id_suffix'],
  'browser_select_dropdown': ['text', 'selector'],
  'browser_upload_file': ['file_name', 'file_mime_type'],
  'browser_screenshot': ['format', 'quality'],
  'browser_dom_action': ['action', 'text', 'value', 'selector'],
};

const _argumentLabels = <String, Map<String, String>>{
  'depth': {'zh': '深度', 'en': 'Depth', 'pt': 'Profundidade'},
  'head_limit': {'zh': '上限', 'en': 'Limit', 'pt': 'Limite'},
  'start_line': {'zh': '起始行', 'en': 'Start line', 'pt': 'Linha inicial'},
  'end_line': {'zh': '结束行', 'en': 'End line', 'pt': 'Linha final'},
  'block_until_ms': {'zh': '等待 ms', 'en': 'Wait ms', 'pt': 'Espera ms'},
  'include_hidden': {
    'zh': '包含隐藏文件',
    'en': 'Include hidden files',
    'pt': 'Incluir arquivos ocultos',
  },
  'case_insensitive': {
    'zh': '忽略大小写',
    'en': 'Ignore case',
    'pt': 'Ignorar maiúsculas',
  },
  'multiline': {'zh': '跨行匹配', 'en': 'Multiline', 'pt': 'Multilinha'},
};

const _toolNames = <String, Map<String, String>>{
  'file_read': {'zh': '读取文件', 'en': 'Read file', 'pt': 'Ler arquivo'},
  'read_file': {'zh': '读取文件', 'en': 'Read file', 'pt': 'Ler arquivo'},
  'file_write': {'zh': '写入文件', 'en': 'Write file', 'pt': 'Gravar arquivo'},
  'write_file': {'zh': '写入文件', 'en': 'Write file', 'pt': 'Gravar arquivo'},
  'file_update': {'zh': '更新文件', 'en': 'Update file', 'pt': 'Atualizar arquivo'},
  'update_file': {'zh': '更新文件', 'en': 'Update file', 'pt': 'Atualizar arquivo'},
  'apply_patch': {'zh': '应用补丁', 'en': 'Apply patch', 'pt': 'Aplicar patch'},
  'grep': {'zh': '搜索内容', 'en': 'Search content', 'pt': 'Pesquisar conteúdo'},
  'glob': {'zh': '查找文件', 'en': 'Find files', 'pt': 'Localizar arquivos'},
  'list_dir': {'zh': '查看目录', 'en': 'List directory', 'pt': 'Listar diretório'},
  'execute_shell_command': {
    'zh': '执行命令',
    'en': 'Run command',
    'pt': 'Executar comando',
  },
  'await_shell': {
    'zh': '等待命令',
    'en': 'Wait for command',
    'pt': 'Aguardar comando',
  },
  'kill_shell': {'zh': '终止命令', 'en': 'Stop command', 'pt': 'Encerrar comando'},
  'read_lints': {
    'zh': '检查诊断',
    'en': 'Check diagnostics',
    'pt': 'Verificar diagnósticos',
  },
  'todo_write': {'zh': '更新任务', 'en': 'Update tasks', 'pt': 'Atualizar tarefas'},
  'todo_read': {'zh': '查看任务', 'en': 'Read tasks', 'pt': 'Ler tarefas'},
  'goal_submit': {'zh': '提交目标', 'en': 'Submit goal', 'pt': 'Enviar objetivo'},
  'plan_submit': {'zh': '提交计划', 'en': 'Submit plan', 'pt': 'Enviar plano'},
  'goal_complete': {
    'zh': '完成目标',
    'en': 'Complete goal',
    'pt': 'Concluir objetivo',
  },
  'questionnaire': {
    'zh': '发起问卷',
    'en': 'Ask questions',
    'pt': 'Fazer perguntas',
  },
  'questionnaire_async': {
    'zh': '发起问卷',
    'en': 'Ask questions',
    'pt': 'Fazer perguntas',
  },
  'turn_status': {
    'zh': '更新状态',
    'en': 'Update status',
    'pt': 'Atualizar status',
  },
  'search_memory': {
    'zh': '搜索记忆',
    'en': 'Search memory',
    'pt': 'Pesquisar memória',
  },
  'search_web': {'zh': '搜索网页', 'en': 'Search web', 'pt': 'Pesquisar na web'},
  'fetch_webpages': {
    'zh': '获取网页',
    'en': 'Fetch webpages',
    'pt': 'Obter páginas',
  },
  'analyze_image': {
    'zh': '分析图片',
    'en': 'Analyze image',
    'pt': 'Analisar imagem',
  },
  'tool_expand_tools': {
    'zh': '加载工具',
    'en': 'Load tools',
    'pt': 'Carregar ferramentas',
  },
  'load_skill': {'zh': '加载技能', 'en': 'Load skill', 'pt': 'Carregar skill'},
  'compress_conversation_history': {
    'zh': '整理上下文',
    'en': 'Compact context',
    'pt': 'Compactar contexto',
  },
  'sys_spawn_agent': {
    'zh': '创建子 Agent',
    'en': 'Create sub-agent',
    'pt': 'Criar subagente',
  },
  'sys_delegate_task': {
    'zh': '委派任务',
    'en': 'Delegate task',
    'pt': 'Delegar tarefa',
  },
  'sys_team_delegate_task': {
    'zh': '团队委派',
    'en': 'Delegate to team',
    'pt': 'Delegar à equipe',
  },
  'browser_get_context': {
    'zh': '查看浏览器',
    'en': 'Inspect browser',
    'pt': 'Inspecionar navegador',
  },
  'browser_navigate': {
    'zh': '打开网页',
    'en': 'Open webpage',
    'pt': 'Abrir página',
  },
  'browser_find_text': {
    'zh': '查找网页文本',
    'en': 'Find page text',
    'pt': 'Localizar texto',
  },
  'browser_scroll': {
    'zh': '滚动网页',
    'en': 'Scroll webpage',
    'pt': 'Rolar página',
  },
  'browser_send_keys': {
    'zh': '输入网页内容',
    'en': 'Type on webpage',
    'pt': 'Digitar na página',
  },
  'browser_wait': {
    'zh': '等待网页',
    'en': 'Wait for webpage',
    'pt': 'Aguardar página',
  },
  'browser_list_tabs': {'zh': '查看标签页', 'en': 'List tabs', 'pt': 'Listar abas'},
  'browser_switch_tab': {'zh': '切换标签页', 'en': 'Switch tab', 'pt': 'Mudar aba'},
  'browser_select_dropdown': {
    'zh': '选择下拉项',
    'en': 'Select option',
    'pt': 'Selecionar opção',
  },
  'browser_upload_file': {
    'zh': '上传网页文件',
    'en': 'Upload webpage file',
    'pt': 'Enviar arquivo',
  },
  'browser_screenshot': {
    'zh': '截取网页',
    'en': 'Capture webpage',
    'pt': 'Capturar página',
  },
  'browser_dom_action': {
    'zh': '操作网页',
    'en': 'Interact with webpage',
    'pt': 'Interagir com página',
  },
};
