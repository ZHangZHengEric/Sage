import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:liquid_glass_widgets/liquid_glass_widgets.dart';
import 'package:sage_tool_labels/tool_labels.dart';

import 'brand.dart';
import 'voice_engine.dart';
import 'voice_glass.dart';
import 'voice_locale.dart';

enum SetupStage {
  recognition(Icons.graphic_eq_rounded, '语音识别', 'Speech recognition'),
  agent(Icons.smart_toy_outlined, '智能体', 'Agent'),
  synthesis(Icons.record_voice_over_outlined, '语音合成', 'Speech synthesis');

  const SetupStage(this.icon, this.zh, this.en);
  final IconData icon;
  final String zh;
  final String en;

  String label(BuildContext context) => context.tr(zh, en);
}

enum AgentSection {
  connection(Icons.link_rounded, '模型连接', 'Model connection'),
  generation(Icons.tune_rounded, '生成参数', 'Generation'),
  prompt(Icons.notes_rounded, '系统提示词', 'System prompt'),
  tools(Icons.build_outlined, '工具', 'Tools');

  const AgentSection(this.icon, this.zh, this.en);
  final IconData icon;
  final String zh;
  final String en;

  String label(BuildContext context) => context.tr(zh, en);
}

class VoiceSettings extends StatefulWidget {
  const VoiceSettings({
    super.key,
    required this.engine,
    required this.backLabel,
    required this.onBack,
    this.onLanguageChanged,
  });

  final VoiceEngine engine;
  final String backLabel;
  final VoidCallback onBack;
  final ValueChanged<Locale?>? onLanguageChanged;

  @override
  State<VoiceSettings> createState() => _VoiceSettingsState();
}

class _VoiceSettingsState extends State<VoiceSettings> {
  late final Map<String, TextEditingController> fields;
  late final Map<String, Object?> initial;
  late String provider;
  late final Set<String> enabledTools;
  late final Map<String, Map<String, Object?>> toolSpeech;
  int speechFieldsRevision = 0;
  SetupStage stage = SetupStage.recognition;
  AgentSection agentSection = AgentSection.connection;
  String? reasoningEffort;

  static const numericFields = {'temperature', 'max_output_tokens'};
  bool saving = false;
  String? error;

  Map<String, Object?> get draft => {
    for (final entry in fields.entries)
      if (!numericFields.contains(entry.key))
        entry.key: entry.value.text.trim(),
    for (final key in numericFields)
      key: fields[key]!.text.trim().isEmpty ? null : fields[key]!.text.trim(),
    'reasoning_effort': reasoningEffort,
    'speech_provider': provider,
    'enabled_tools': enabledTools.toList()..sort(),
    'tool_speech': Map.of(toolSpeech),
  };

  bool get dirty {
    final savedSpeech =
        initial['tool_speech'] as Map<String, Map<String, Object?>>;
    return draft.entries.any(
          (entry) =>
              entry.key != 'tool_speech' &&
              entry.key != 'enabled_tools' &&
              entry.value != initial[entry.key],
        ) ||
        !listEquals(
          draft['enabled_tools'] as List,
          initial['enabled_tools'] as List,
        ) ||
        savedSpeech.length != toolSpeech.length ||
        toolSpeech.entries.any(
          (entry) => !mapEquals(entry.value, savedSpeech[entry.key]),
        );
  }

  @override
  void initState() {
    super.initState();
    final saved = widget.engine.settings ?? {};
    fields = {
      for (final entry in const {
        'model_base_url': 'https://api.openai.com/v1',
        'model': '',
        'model_api_key': '',
        'system_prompt': '',
        'temperature': '',
        'max_output_tokens': '',
        'speech_api_key': '',
        'workspace_id': '',
        'voice': '',
      }.entries)
        entry.key: TextEditingController(
          text: saved[entry.key]?.toString() ?? entry.value,
        ),
    };
    reasoningEffort = saved['reasoning_effort'] as String?;
    provider = saved['speech_provider']?.toString() ?? 'qwen_audio';
    enabledTools = (saved['enabled_tools'] as List? ?? [])
        .cast<String>()
        .toSet();
    toolSpeech = {
      for (final entry in ((saved['tool_speech'] as Map?) ?? {}).entries)
        entry.key as String: Map<String, Object?>.from(entry.value as Map),
    };
    initial = draft;
  }

  void editToolSpeech(String name, String key, Object value) {
    setState(() {
      final rule = {...?toolSpeech[name], key: value};
      if (rule['enabled'] != false &&
          (rule['zh'] as String? ?? '').trim().isEmpty &&
          (rule['en'] as String? ?? '').trim().isEmpty) {
        toolSpeech.remove(name);
      } else {
        toolSpeech[name] = rule;
      }
      error = null;
    });
  }

  Widget toolSpeechSettings(String name, Map preset) {
    final rule = toolSpeech[name] ?? {};
    final enabled = rule['enabled'] != false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        heading(context.tr('工具进度播报', 'Tool announcements')),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(context.tr('播报进度', 'Announce progress')),
          value: enabled,
          onChanged: saving
              ? null
              : (value) => editToolSpeech(name, 'enabled', value),
        ),
        for (final language in {'zh': '中文', 'en': 'English'}.entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: TextFormField(
              key: ValueKey((name, language.key, speechFieldsRevision)),
              initialValue: rule[language.key] as String? ?? '',
              enabled: enabled && !saving,
              maxLength: 100,
              decoration: InputDecoration(
                labelText: language.value,
                floatingLabelBehavior: FloatingLabelBehavior.always,
                hintText: preset[language.key] as String?,
                counterText: '',
              ),
              onChanged: (value) => editToolSpeech(name, language.key, value),
            ),
          ),
        if (toolSpeech.containsKey(name))
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: saving
                  ? null
                  : () => setState(() {
                      toolSpeech.remove(name);
                      speechFieldsRevision++;
                      error = null;
                    }),
              child: Text(context.tr('恢复默认播报', 'Restore defaults')),
            ),
          ),
      ],
    );
  }

  @override
  void dispose() {
    for (final field in fields.values) {
      field.dispose();
    }
    super.dispose();
  }

  bool ready(SetupStage step) => switch (step) {
    SetupStage.agent => [
      'model_base_url',
      'model',
      'model_api_key',
    ].every((key) => fields[key]!.text.trim().isNotEmpty),
    SetupStage.recognition ||
    SetupStage.synthesis => fields['speech_api_key']!.text.trim().isNotEmpty,
  };

  Future<void> back() async {
    final leave =
        !dirty ||
        await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                title: Text(
                  context.tr('放弃未保存的更改？', 'Discard unsaved changes?'),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: Text(context.tr('继续编辑', 'Keep editing')),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: Text(context.tr('放弃更改', 'Discard changes')),
                  ),
                ],
              ),
            ) ==
            true;
    if (mounted && leave) widget.onBack();
  }

  Future<void> save() async {
    for (final step in [SetupStage.recognition, SetupStage.agent]) {
      if (!ready(step)) {
        setState(() {
          stage = step;
          if (step == SetupStage.agent) agentSection = AgentSection.connection;
          error = context.tr('请填写必填项。', 'Complete the required fields.');
        });
        return;
      }
    }
    final temperatureText = fields['temperature']!.text.trim();
    final maxTokensText = fields['max_output_tokens']!.text.trim();
    final temperature = double.tryParse(temperatureText);
    final maxTokens = int.tryParse(maxTokensText);
    if (temperatureText.isNotEmpty &&
        (temperature == null ||
            !temperature.isFinite ||
            temperature < 0 ||
            temperature > 2)) {
      setState(() {
        stage = SetupStage.agent;
        agentSection = AgentSection.generation;
        error = context.tr(
          '温度须在 0 到 2 之间。',
          'Temperature must be between 0 and 2.',
        );
      });
      return;
    }
    if (maxTokensText.isNotEmpty && (maxTokens == null || maxTokens < 1)) {
      setState(() {
        stage = SetupStage.agent;
        agentSection = AgentSection.generation;
        error = context.tr(
          '最大输出 Token 数须为正整数。',
          'Max output tokens must be a positive integer.',
        );
      });
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.engine.configure({
        ...draft,
        'temperature': temperature,
        'max_output_tokens': maxTokens,
      });
      if (mounted) widget.onBack();
    } on Object catch (exception) {
      if (!mounted) return;
      setState(() {
        saving = false;
        error = exception.toString();
      });
    }
  }

  Widget field(
    String name,
    String label, {
    bool secret = false,
    int lines = 1,
    int? maxLength,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: TextField(
      controller: fields[name],
      enabled: !saving,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      minLines: lines,
      maxLines: lines == 1 ? 1 : 12,
      maxLength: maxLength,
      decoration: InputDecoration(
        labelText: label,
        floatingLabelBehavior: FloatingLabelBehavior.always,
        counterText: '',
      ),
      onChanged: (_) {
        if (error != null) setState(() => error = null);
      },
    ),
  );

  Widget heading(String title) => Text(
    title,
    style: Theme.of(
      context,
    ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
  );

  Widget section(String title, List<Widget> children) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [heading(title), const SizedBox(height: 16), ...children],
  );

  Future<void> openHelpLink(BuildContext dialogContext, String url) async {
    const platform = MethodChannel('sage.voice/preferences');
    try {
      if (await platform.invokeMethod<bool>('openHelpLink', url) == true) {
        return;
      }
    } on PlatformException {
      // Show the address so it can still be copied.
    } on MissingPluginException {
      // The browser handler is provided by the macOS runner.
    }
    if (!dialogContext.mounted) return;
    await showDialog<void>(
      context: dialogContext,
      builder: (context) => AlertDialog(
        title: Text(context.tr('无法打开网页', 'Could not open the page')),
        content: SelectableText(url),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(context.tr('关闭', 'Close')),
          ),
        ],
      ),
    );
  }

  Widget apiKeyHelp({required bool speech}) => Align(
    alignment: Alignment.centerLeft,
    child: VoiceGlassButton(
      plain: true,
      icon: Icons.help_outline_rounded,
      label: context.tr('如何获取 API Key', 'How to get an API key'),
      onPressed: () => showApiKeyHelp(speech: speech),
    ),
  );

  Future<void> showApiKeyHelp({required bool speech}) {
    final synthesis = stage == SetupStage.synthesis;
    final alibaba = provider == 'qwen_audio';
    return showDialog<void>(
      context: context,
      builder: (context) {
        final title = speech
            ? alibaba
                  ? context.tr(
                      '阿里云百炼 API Key',
                      'Alibaba Cloud Model Studio API key',
                    )
                  : context.tr('豆包语音 API Key', 'Doubao Voice API key')
            : context.tr('模型服务 API Key', 'Model provider API key');
        final instructions = !speech
            ? context.tr(
                '在支持 OpenAI Chat Completions 的服务商控制台创建 API Key，并复制该服务的 Base URL 和模型 ID。使用 OpenAI 时，可从下方进入 API Key 页面和模型目录。',
                'Create an API key in your OpenAI Chat Completions-compatible provider’s console. Copy that provider’s base URL and model ID. If you use OpenAI, its key page and model catalog are linked below.',
              )
            : alibaba
            ? context.tr(
                '在百炼控制台选择华北 2（北京），在对应业务空间创建并复制 API Key。语音识别和合成共用这把 Key。',
                'Select China (Beijing) in Model Studio. Create and copy an API key for your workspace. Speech recognition and synthesis share this key.',
              )
            : context.tr(
                '在豆包语音控制台的「开通管理」开通流式语音识别 2.0（小时版）和语音合成 2.0，再到同一项目的「API 管理」创建并复制 API Key。识别和合成共用这把 Key。',
                'In the Doubao Voice console, activate Streaming ASR 2.0 (hourly) and TTS 2.0. Create and copy an API key in API Management for the same project. Both services share this key.',
              );
        final links = !speech
            ? {
                context.tr('OpenAI API Key', 'OpenAI API keys'):
                    'https://platform.openai.com/api-keys',
                context.tr('OpenAI 模型目录', 'OpenAI model catalog'):
                    'https://developers.openai.com/api/docs/models',
              }
            : alibaba
            ? {
                context.tr(
                  '百炼 API Key 控制台',
                  'Model Studio API keys',
                ): 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key',
                if (synthesis)
                  context.tr('百炼音色列表', 'Model Studio voice list'): context.tr(
                    'https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list',
                    'https://help.aliyun.com/en/model-studio/qwen-audio-tts-voice-list',
                  ),
              }
            : {
                context.tr('豆包语音 API Key 控制台', 'Doubao Voice API keys'):
                    'https://console.volcengine.com/speech/new/setting/apikeys',
                context.tr(
                  '开通与取 Key 指引',
                  'Activation and API key guide',
                ): 'https://docs.volcengine.com/docs/doubao-voice/console-usage-faq?lang=zh',
                if (synthesis)
                  context.tr(
                    '豆包音色列表',
                    'Doubao Voice list',
                  ): 'https://docs.volcengine.com/docs/doubao-voice/tone-list-3?lang=zh',
              };
        return AlertDialog(
          title: Text(title),
          scrollable: true,
          content: SizedBox(
            width: 460,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(instructions),
                if (speech) ...[
                  const SizedBox(height: 14),
                  Text(stage.label(context)),
                  SelectableText(
                    alibaba
                        ? (synthesis
                              ? 'qwen-audio-3.0-tts-flash'
                              : 'qwen-audio-3.0-asr-flash-streaming')
                        : (synthesis
                              ? 'seed-tts-2.0'
                              : 'volc.seedasr.sauc.duration'),
                  ),
                  if (synthesis) ...[
                    const SizedBox(height: 10),
                    Text(
                      context.tr(
                        '留空时使用的音色 ID',
                        'Voice ID used when left blank',
                      ),
                    ),
                    SelectableText(
                      alibaba
                          ? 'longanhuan_v3.6'
                          : 'zh_female_vv_uranus_bigtts',
                    ),
                  ],
                ],
                const SizedBox(height: 12),
                for (final link in links.entries)
                  VoiceGlassButton(
                    plain: true,
                    icon: Icons.open_in_new_rounded,
                    label: link.key,
                    onPressed: () => openHelpLink(context, link.value),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: Text(context.tr('关闭', 'Close')),
            ),
          ],
        );
      },
    );
  }

  Widget speechFields() {
    final colors = Theme.of(context).colorScheme;
    final synthesis = stage == SetupStage.synthesis;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 188,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              heading(context.tr('语音服务', 'Speech service')),
              const SizedBox(height: 8),
              for (final service in {
                'qwen_audio': context.tr('阿里云语音', 'Alibaba Cloud'),
                'volcengine': context.tr('火山引擎语音', 'Volcengine'),
              }.entries)
                ListTile(
                  dense: true,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                  leading: const Icon(Icons.cloud_outlined, size: 17),
                  title: Text(service.value),
                  selected: provider == service.key,
                  selectedTileColor: colors.secondaryContainer,
                  onTap: saving || provider == service.key
                      ? null
                      : () => setState(() {
                          provider = service.key;
                          fields['speech_api_key']!.clear();
                          fields['workspace_id']!.clear();
                          fields['voice']!.clear();
                          error = null;
                        }),
                ),
            ],
          ),
        ),
        const SizedBox(width: 24),
        Expanded(
          child: section(stage.label(context), [
            field('speech_api_key', 'API Key', secret: true),
            apiKeyHelp(speech: true),
            const SizedBox(height: 10),
            if (provider == 'qwen_audio')
              field(
                'workspace_id',
                context.tr('Workspace ID（可选）', 'Workspace ID (optional)'),
              ),
            if (synthesis)
              field('voice', context.tr('音色 ID（可选）', 'Voice ID (optional)')),
          ]),
        ),
      ],
    );
  }

  List<Widget> connectionFields() => [
    field('model_base_url', 'Base URL'),
    field('model_api_key', 'API Key', secret: true),
    apiKeyHelp(speech: false),
    const SizedBox(height: 10),
    field('model', context.tr('模型 ID', 'Model ID')),
  ];

  Widget reasoningField() {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final selected = reasoningEffort ?? '';
    final options = {
      '': context.tr('模型默认', 'Model default'),
      'none': context.tr('关闭', 'Off'),
      'minimal': context.tr('极低', 'Minimal'),
      'low': context.tr('低', 'Low'),
      'medium': context.tr('中', 'Medium'),
      'high': context.tr('高', 'High'),
      'xhigh': context.tr('极高', 'Extra high'),
    };
    final itemShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(8),
    );

    return DropdownMenu<String>(
      key: ValueKey(context.voiceChinese),
      enabled: !saving,
      initialSelection: selected,
      expandedInsets: EdgeInsets.zero,
      selectOnly: true,
      enableSearch: false,
      requestFocusOnTap: true,
      menuHeight: 280,
      alignmentOffset: const Offset(0, 4),
      label: Text(context.tr('思考强度', 'Reasoning effort')),
      trailingIcon: const Icon(Icons.keyboard_arrow_down_rounded, size: 20),
      selectedTrailingIcon: const Icon(
        Icons.keyboard_arrow_up_rounded,
        size: 20,
      ),
      textStyle: theme.textTheme.bodyLarge,
      inputDecorationTheme: theme.inputDecorationTheme.copyWith(
        floatingLabelBehavior: FloatingLabelBehavior.always,
      ),
      menuStyle: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(colors.surfaceContainerHigh),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(3),
        padding: const WidgetStatePropertyAll(EdgeInsets.all(4)),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      dropdownMenuEntries: [
        for (final option in options.entries)
          DropdownMenuEntry(
            value: option.key,
            label: option.value,
            trailingIcon: option.key == selected
                ? Icon(Icons.check_rounded, size: 17, color: colors.primary)
                : null,
            style: MenuItemButton.styleFrom(
              shape: itemShape,
              minimumSize: const Size(0, 34),
              textStyle: theme.textTheme.bodyLarge,
            ),
          ),
      ],
      onSelected: (value) {
        if (value == null) return;
        setState(() {
          reasoningEffort = value.isEmpty ? null : value;
          error = null;
        });
      },
    );
  }

  List<Widget> generationFields() => [
    reasoningField(),
    const SizedBox(height: 16),
    field('temperature', context.tr('温度（可选）', 'Temperature (optional)')),
    field(
      'max_output_tokens',
      context.tr('最大输出 Token 数（可选）', 'Max output tokens (optional)'),
    ),
  ];

  Widget toolParameters(Map schema) {
    final properties = schema['properties'] as Map? ?? {};
    final required = schema['required'] as List? ?? [];
    if (properties.isEmpty) {
      return Text(context.tr('无参数', 'No parameters'));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final entry in properties.entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: parameter(
              entry.key as String,
              entry.value as Map,
              required.contains(entry.key),
            ),
          ),
      ],
    );
  }

  String parameterType(Map schema) {
    if (schema['anyOf'] case final List variants) {
      return variants.map((value) => parameterType(value as Map)).join(' / ');
    }
    if (schema['items'] case final Map items) {
      return '${schema['type'] ?? 'array'}<${parameterType(items)}>';
    }
    return schema['type']?.toString() ?? context.tr('任意类型', 'Any type');
  }

  Widget parameter(String name, Map schema, bool required) {
    final theme = Theme.of(context);
    final description = schema['description'] as String?;
    final choices = schema['enum'] as List?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(name, style: theme.textTheme.labelLarge),
        Text(
          [
            parameterType(schema),
            required
                ? context.tr('必填', 'Required')
                : context.tr('可选', 'Optional'),
            if (schema['default'] case final Object value)
              '${context.tr('默认', 'Default')} $value',
            if (choices != null) choices.join(' / '),
          ].join(' · '),
          style: theme.textTheme.bodySmall,
        ),
        if (description != null) Text(description),
        if (schema['properties'] is Map)
          Padding(
            padding: const EdgeInsets.only(left: 14, top: 8),
            child: toolParameters(schema),
          ),
        if (schema['items'] case final Map items
            when items['properties'] is Map)
          Padding(
            padding: const EdgeInsets.only(left: 14, top: 8),
            child: toolParameters(items),
          ),
      ],
    );
  }

  Widget toolRow(Map<String, Object?> tool) {
    final name = tool['name'] as String;
    final language = context.voiceChinese ? 'zh' : 'en';
    final descriptions = tool['description'] as Map;
    final schema = (tool['input_schema'] as Map)[language] as Map;
    final colors = Theme.of(context).colorScheme;
    return ExpansionTile(
      key: ValueKey(name),
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.fromLTRB(12, 4, 12, 16),
      shape: const Border(),
      collapsedShape: const Border(),
      title: Text(sageToolNames[name]?[language] ?? name),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Tooltip(
            message: context.tr('启用工具', 'Enable tool'),
            child: Switch(
              value: enabledTools.contains(name),
              onChanged: saving
                  ? null
                  : (enabled) => setState(() {
                      if (enabled) {
                        enabledTools.add(name);
                      } else {
                        enabledTools.remove(name);
                      }
                      error = null;
                    }),
            ),
          ),
          const SizedBox(width: 8),
          const Icon(Icons.unfold_more_rounded, size: 18),
        ],
      ),
      expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SelectableText(name, style: TextStyle(color: colors.onSurfaceVariant)),
        const SizedBox(height: 6),
        Text(descriptions[language] as String),
        const SizedBox(height: 12),
        heading(context.tr('参数', 'Parameters')),
        const SizedBox(height: 6),
        toolParameters(schema),
        const SizedBox(height: 14),
        toolSpeechSettings(name, tool['speech'] as Map),
      ],
    );
  }

  List<Widget> toolFields() => widget.engine.tools.map(toolRow).toList();

  Widget agentFields() {
    final colors = Theme.of(context).colorScheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 188,
          child: Column(
            children: [
              for (final item in AgentSection.values)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: ListTile(
                    dense: true,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                    leading: Icon(item.icon, size: 17),
                    title: Text(item.label(context)),
                    selected: agentSection == item,
                    selectedTileColor: colors.secondaryContainer,
                    onTap: saving
                        ? null
                        : () => setState(() {
                            agentSection = item;
                          }),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(width: 24),
        Expanded(
          child: KeyedSubtree(
            key: ValueKey(agentSection),
            child: section(agentSection.label(context), switch (agentSection) {
              AgentSection.connection => connectionFields(),
              AgentSection.generation => generationFields(),
              AgentSection.prompt => [
                field(
                  'system_prompt',
                  context.tr('系统提示词（可选）', 'System prompt (optional)'),
                  lines: 5,
                  maxLength: 12000,
                ),
              ],
              AgentSection.tools => toolFields(),
            }),
          ),
        ),
      ],
    );
  }

  Widget setupNavigation() {
    final colors = Theme.of(context).colorScheme;
    return LayoutBuilder(
      builder: (context, constraints) => Stack(
        children: [
          Positioned(
            left: constraints.maxWidth / 6,
            right: constraints.maxWidth / 6,
            top: 23,
            child: Divider(height: 1, color: colors.outlineVariant),
          ),
          Row(
            children: [
              for (final step in SetupStage.values)
                Expanded(
                  child: Semantics(
                    selected: stage == step,
                    child: TextButton(
                      style:
                          TextButton.styleFrom(
                            overlayColor: Colors.transparent,
                            foregroundColor: stage == step
                                ? colors.primary
                                : colors.onSurfaceVariant,
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ).copyWith(
                            textStyle: WidgetStateProperty.resolveWith(
                              (states) => states.contains(WidgetState.focused)
                                  ? const TextStyle(
                                      decoration: TextDecoration.underline,
                                    )
                                  : null,
                            ),
                          ),
                      onPressed: saving
                          ? null
                          : () {
                              if (stage == step) return;
                              setState(() {
                                stage = step;
                                error = null;
                              });
                            },
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          GlassContainer(
                            width: 34,
                            height: 34,
                            alignment: Alignment.center,
                            shape: const LiquidRoundedRectangle(
                              borderRadius: 10,
                            ),
                            quality: GlassQuality.minimal,
                            settings: LiquidGlassSettings(
                              glassColor: stage == step
                                  ? colors.primaryContainer
                                  : colors.surfaceContainerHighest,
                              lightIntensity: 0,
                              glowIntensity: 0,
                              shadowElevation: 0,
                            ),
                            child: Icon(step.icon, size: 18),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            step.label(context),
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget languageMenu() => MenuAnchor(
    builder: (context, controller, child) => VoiceGlassButton(
      icon: Icons.language_rounded,
      plain: true,
      label: context.tr('界面语言', 'Interface language'),
      onPressed: () {
        if (controller.isOpen) {
          controller.close();
        } else {
          controller.open();
        }
      },
    ),
    menuChildren: [
      MenuItemButton(
        onPressed: () => widget.onLanguageChanged!(null),
        child: Text(context.tr('跟随系统', 'System default')),
      ),
      MenuItemButton(
        onPressed: () => widget.onLanguageChanged!(const Locale('zh')),
        child: const Text('简体中文'),
      ),
      MenuItemButton(
        onPressed: () => widget.onLanguageChanged!(const Locale('en')),
        child: const Text('English'),
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        SizedBox(
          height: voiceTitleBarHeight,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(92, 0, 18, 0),
            child: Row(
              children: [
                Expanded(
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: VoiceGlassButton(
                      icon: Icons.arrow_back_rounded,
                      plain: true,
                      label: widget.backLabel,
                      onPressed: saving ? null : back,
                    ),
                  ),
                ),
                if (widget.onLanguageChanged != null) ...[
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 250),
                    child: languageMenu(),
                  ),
                  const SizedBox(width: 12),
                ],
                const SageBrand(size: 16),
              ],
            ),
          ),
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(28, 12, 28, 28),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1060),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    setupNavigation(),
                    const SizedBox(height: 16),
                    GlassContainer(
                      key: ValueKey(stage),
                      shape: const LiquidRoundedRectangle(borderRadius: 16),
                      quality: GlassQuality.minimal,
                      settings: LiquidGlassSettings(
                        glassColor: colors.surfaceContainerLow,
                        thickness: 2,
                      ),
                      padding: const EdgeInsets.all(22),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (stage == SetupStage.agent)
                            agentFields()
                          else
                            speechFields(),
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  error == null
                                      ? ''
                                      : voiceMessage(context, error!),
                                  style: TextStyle(color: colors.error),
                                ),
                              ),
                              const SizedBox(width: 12),
                              VoiceGlassButton(
                                primary: true,
                                label: saving
                                    ? context.tr('保存中', 'Saving')
                                    : context.tr('保存配置', 'Save settings'),
                                onPressed: saving || !widget.engine.connected
                                    ? null
                                    : save,
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
