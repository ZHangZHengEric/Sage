import 'dart:convert';

import 'package:flutter/widgets.dart';

String toolPresentationLanguage(BuildContext context) {
  final language = Localizations.localeOf(context).languageCode.toLowerCase();
  if (language == 'zh' || language == 'pt') return language;
  return 'en';
}

String localizedToolName(String rawName, String language) {
  final translations = _toolNames[rawName.toLowerCase()];
  if (translations == null) return _humanizeToolName(rawName);
  return translations[language] ?? translations['en'] ?? rawName;
}

String toolArgumentPreview(
  String rawName,
  Map<String, Object?> arguments,
  String language,
) {
  if (arguments.isEmpty) return '';
  final name = rawName.toLowerCase();
  final orderedKeys = <String>[...?_toolArgumentOrder[name], ...arguments.keys];
  final seen = <String>{};
  final values = <String>[];
  for (final key in orderedKeys) {
    if (!seen.add(key) || _hiddenArguments.contains(key)) continue;
    final value = arguments[key];
    final formatted = _formatArgument(key, value, language);
    if (formatted.isEmpty) continue;
    values.add(formatted);
    if (values.length == 3) break;
  }
  return values.join(' · ');
}

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
    ('pt', 'search') => '$count buscas · $count operações',
    ('pt', 'read') => '$count arquivos lidos · $count operações',
    ('pt', 'write') => '$count arquivos alterados · $count operações',
    ('pt', 'shell') => '$count comandos executados · $count operações',
    ('pt', 'agent') => '$count agentes acionados · $count operações',
    (_, 'search') => 'Searched $count times · $count operations',
    (_, 'read') => 'Read $count files · $count operations',
    (_, 'write') => 'Changed $count files · $count operations',
    (_, 'shell') => 'Ran $count commands · $count operations',
    (_, 'agent') => 'Delegated to $count agents · $count operations',
    _ => 'Ran $count operations',
  };
}

String localizedToolFailure(String language) => switch (language) {
  'zh' => '执行失败',
  'pt' => 'Falhou',
  _ => 'Failed',
};

String _formatArgument(String key, Object? value, String language) {
  if (value == null) return '';
  if (value is bool) {
    if (!value) return '';
    final labels = _argumentLabels[key];
    return labels?[language] ?? labels?['en'] ?? _humanizeToolName(key);
  }
  if (value is num && _argumentLabels.containsKey(key)) {
    final label =
        _argumentLabels[key]![language] ?? _argumentLabels[key]!['en'] ?? key;
    return language == 'zh'
        ? '$label ${value.toInt()}'
        : '$label ${value.toInt()}';
  }
  if (value is List) {
    final items = value.map(_compactValue).where((item) => item.isNotEmpty);
    return _ellipsize(items.join(', '), 92);
  }
  if (value is Map) return '';
  final text = _compactValue(value);
  if (text.isEmpty) return '';
  if (_quotedArguments.contains(key)) return '“${_ellipsize(text, 92)}”';
  return _ellipsize(text, key == 'command' || key == 'cmd' ? 132 : 92);
}

String _compactValue(Object? value) =>
    value?.toString().replaceAll(RegExp(r'\s+'), ' ').trim() ?? '';

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
  'approval_id',
  'sandbox_approval_mode',
  'command_policy',
  'env_vars',
  'idempotency_key',
};

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
  'read_lints': ['paths', 'path'],
  'search_web': ['query', 'url'],
  'fetch_webpages': ['urls', 'url'],
  'load_skill': ['name', 'skill_name'],
  'sys_spawn_agent': ['role', 'task', 'prompt'],
  'sys_delegate_task': ['task', 'prompt', 'agent_id'],
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
  'file_write': {'zh': '写入文件', 'en': 'Write file', 'pt': 'Gravar arquivo'},
  'file_update': {'zh': '更新文件', 'en': 'Update file', 'pt': 'Atualizar arquivo'},
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
