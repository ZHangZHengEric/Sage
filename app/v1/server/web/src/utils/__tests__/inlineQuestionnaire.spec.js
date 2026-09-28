import { describe, expect, it } from 'vitest'

import {
  buildQuestionnaireSubmission,
  canSubmitQuestionnaireMessage,
  displayTextForAnswers,
  initialQuestionnaireDraft,
  questionnaireFromAsyncToolResult,
  splitInlineQuestionnaireContent,
} from '../inlineQuestionnaire.js'

describe('inlineQuestionnaire', () => {
  it('parses movo artifacts and keeps them in message order', () => {
    const parts = splitInlineQuestionnaireContent(
      String.raw`本次产出：
<movo-artifacts>{\"title\":\"本次更新\",\"items\":[{\"type\":\"markdown\",\"title\":\"正式视频计划\",\"path\":\"video_projects/dog-owner-bond-20260615/videos/video-01/video_plan.md\",\"status\":\"created\"}]}</movo-artifacts>
继续。`,
      'artifacts_1'
    )

    expect(parts).toHaveLength(3)
    expect(parts[1]).toMatchObject({
      type: 'artifacts',
      tag: 'movo-artifacts',
    })
    expect(parts[1].payload.title).toBe('本次更新')
    expect(parts[1].rawText).toContain('<movo-artifacts>')
    expect(parts[1].payload.items[0]).toMatchObject({
      type: 'markdown',
      title: '正式视频计划',
      path: 'video_projects/dog-owner-bond-20260615/videos/video-01/video_plan.md',
      status: 'created',
    })
  })

  it('supports all artifacts tag aliases', () => {
    for (const tag of ['ling-artifacts', 'sage-artifacts', 'artifacts']) {
      const parts = splitInlineQuestionnaireContent(
        `<${tag}>{"items":[{"title":"报告","path":"reports/out.pdf","status":"created"}]}</${tag}>`,
        tag
      )
      expect(parts[0].type).toBe('artifacts')
      expect(parts[0].payload.tag).toBe(tag)
      expect(parts[0].payload.items[0]).toMatchObject({
        type: 'pdf',
        title: '报告',
        path: 'reports/out.pdf',
      })
    }
  })

  it('parses sage questionnaire tags at their markdown position', () => {
    const parts = splitInlineQuestionnaireContent(
      '先确认。\n\n<sage-questionnaire>{"title":"小狗视频确认","questions":[{"type":"single_choice","text":"成片画幅？","options":["9:16","16:9"],"default":"9:16"},{"type":"free_text","text":"补充？","default":""}]}</sage-questionnaire>',
      'assistant_1'
    )

    expect(parts).toHaveLength(2)
    expect(parts[0]).toMatchObject({ type: 'markdown' })
    expect(parts[1]).toMatchObject({
      type: 'questionnaire',
      tag: 'sage-questionnaire',
    })
    expect(parts[1].payload.title).toBe('小狗视频确认')
    expect(parts[1].payload.questions[0]).toMatchObject({
      id: 'q1',
      type: 'single_choice',
      text: '成片画幅？',
      defaultValue: '9:16',
    })
  })

  it('supports only generic and sage-prefixed questionnaire tags', () => {
    for (const tag of ['sage-questionnaire', 'questionnaire']) {
      const parts = splitInlineQuestionnaireContent(
        `<${tag}>{"questions":[{"type":"multiple_choice","text":"选项？","options":["A","B"],"default":["A"]}]}</${tag}>`,
        tag
      )
      expect(parts[0].type).toBe('questionnaire')
      expect(parts[0].payload.tag).toBe(tag)
      expect(parts[0].payload.questions[0].type).toBe('multi_choice')
      expect(parts[0].payload.questions[0].defaultValues).toEqual(['A'])
    }

    for (const tag of ['yiii-questionnaire', 'movo-questionnaire', 'ling-questionnaire']) {
      const source = `<${tag}>{"questions":[{"type":"free_text","text":"补充？","default":""}]}</${tag}>`
      expect(splitInlineQuestionnaireContent(source, tag)).toEqual([
        expect.objectContaining({ type: 'markdown', content: source }),
      ])
    }
  })

  it('parses a generic markdown questionnaire fence with YAML', () => {
    const parts = splitInlineQuestionnaireContent(
      `已达到本轮最大循环次数（50），任务已暂停。

\`\`\`questionnaire
title: 任务已暂停
questions:
  - type: single_choice
    text: 是否继续当前任务？
    options:
      - 继续
    default: 继续
\`\`\``,
      'max_loop'
    )

    expect(parts).toHaveLength(2)
    expect(parts[0]).toMatchObject({
      type: 'markdown',
      content: '已达到本轮最大循环次数（50），任务已暂停。\n\n',
    })
    expect(parts[1]).toMatchObject({
      type: 'questionnaire',
      tag: 'questionnaire',
    })
    expect(parts[1].payload).toMatchObject({
      title: '任务已暂停',
      questions: [
        {
          id: 'q1',
          type: 'single_choice',
          text: '是否继续当前任务？',
          defaultValue: '继续',
          options: [{ value: '继续', label: '继续' }],
        },
      ],
    })

    const submission = buildQuestionnaireSubmission(
      parts[1].payload,
      initialQuestionnaireDraft(parts[1].payload)
    )
    expect(submission.agentText).toContain('<questionnaire-response>')
    expect(submission.agentText).not.toContain('<movo-questionnaire-response>')
  })

  it('round-trips a sage-prefixed fenced questionnaire and response', () => {
    const parts = splitInlineQuestionnaireContent(
      '请确认。\n\n```sage-questionnaire\ntitle: 继续执行\nquestions:\n  - type: single_choice\n    text: 是否继续？\n    options: [继续]\n    default: 继续\n```',
      'sage_fence'
    )
    expect(parts[1]).toMatchObject({ type: 'questionnaire', tag: 'sage-questionnaire' })

    const submission = buildQuestionnaireSubmission(
      parts[1].payload,
      initialQuestionnaireDraft(parts[1].payload)
    )
    expect(submission.agentText).toContain('<sage-questionnaire-response>')
    expect(splitInlineQuestionnaireContent(submission.agentText, 'sage_response')[0]).toMatchObject({
      type: 'questionnaire_response',
      tag: 'sage-questionnaire',
    })
  })

  it('parses html entity and escaped transport payloads', () => {
    const htmlParts = splitInlineQuestionnaireContent(
      '&lt;questionnaire&gt;{&quot;questions&quot;:[{&quot;type&quot;:&quot;single_choice&quot;,&quot;text&quot;:&quot;能量？&quot;,&quot;options&quot;:[&quot;低&quot;,&quot;高&quot;]}]}&lt;/questionnaire&gt;',
      'html'
    )
    expect(htmlParts[0].payload.questions[0].text).toBe('能量？')

    const escapedParts = splitInlineQuestionnaireContent(
      String.raw`<sage-questionnaire>{\"questions\":[{\"type\":\"free_text\",\"text\":\"补充？\",\"default\":\"先轻一点\"}]}<\/sage-questionnaire>`,
      'escaped'
    )
    expect(escapedParts[0].payload.questions[0]).toMatchObject({
      type: 'free_text',
      defaultText: '先轻一点',
    })
  })

  it('builds a frontend submission input and display text', () => {
    const questionnaire = splitInlineQuestionnaireContent(
      '<questionnaire>{"questions":[{"type":"single_choice","text":"画幅？","options":["9:16","16:9"],"default":"9:16"},{"type":"multi_choice","text":"风格？","options":["温暖","活泼"]},{"type":"free_text","text":"补充？","default":"无"}]}</questionnaire>',
      'assistant'
    )[0].payload
    const draft = initialQuestionnaireDraft(questionnaire)
    draft.q1.value = '16:9'
    draft.q2.values = ['温暖', '活泼']
    draft.q3 = '不要字幕'

    const submission = buildQuestionnaireSubmission(questionnaire, draft)

    expect(submission.agentText).toContain('<questionnaire-response>')
    expect(submission.agentText).toContain('"questionnaire_id":"assistant_q1"')
    expect(submission.displayText).toBe(
      displayTextForAnswers(submission.answers)
    )
    expect(submission.displayText).toContain('画幅？：16:9')
    expect(submission.displayText).toContain('风格？：温暖、活泼')
    expect(submission.displayText).toContain('补充？：不要字幕')
  })

  it('uses questionnaire-provided localized UI text for other answers', () => {
    const questionnaire = splitInlineQuestionnaireContent(
      '<sage-questionnaire>{"title":"Confirmacao","ui_text":{"other":"Outro","answer_title":"Respostas do questionario","question_fallback":"Pergunta","unanswered":"Nao respondido","unselected":"Nao selecionado","answer_separator":": ","list_separator":", "},"questions":[{"id":"action","type":"single_choice","text":"Como continuar?","options":[{"value":"continue","label":"Continuar"}],"allow_other":true}]}</sage-questionnaire>',
      'portuguese'
    )[0].payload
    const draft = initialQuestionnaireDraft(questionnaire)
    draft.action.value = '__questionnaire_other__'
    draft.action.otherText = 'Usar outra estrategia'

    const submission = buildQuestionnaireSubmission(questionnaire, draft)

    expect(questionnaire.uiText.other).toBe('Outro')
    expect(submission.answers[0].label).toBe('Outro')
    expect(submission.displayText).toContain('Respostas do questionario')
    expect(submission.displayText).toContain(
      'Como continuar?: Outro, Usar outra estrategia'
    )
    expect(submission.displayText).not.toMatch(/问卷|其他|未选择/)
  })

  it('does not parse questionnaire examples nested in another markdown fence', () => {
    const source = `示例：\n\n\`\`\`\`markdown\n\`\`\`questionnaire\ntitle: 示例\nquestions:\n  - type: free_text\n    text: 内容？\n    default: \"\"\n\`\`\`\n\`\`\`\``
    const parts = splitInlineQuestionnaireContent(source, 'nested')
    expect(parts).toEqual([
      expect.objectContaining({ type: 'markdown', content: source }),
    ])
  })

  it('does not parse XML questionnaire examples inside inline code', () => {
    const source = '请按 `<questionnaire>{"questions":[]}</questionnaire>` 格式输出。'
    expect(splitInlineQuestionnaireContent(source, 'inline_code')).toEqual([
      expect.objectContaining({ type: 'markdown', content: source }),
    ])
  })

  it('does not parse XML questionnaire examples inside indented code', () => {
    const source = '示例：\n\n    <questionnaire>{"title":"演示","questions":[{"type":"free_text","text":"内容？","default":""}]}</questionnaire>'
    expect(splitInlineQuestionnaireContent(source, 'indented_code')).toEqual([
      expect.objectContaining({ type: 'markdown', content: source }),
    ])
  })

  it.each([
    ['extra top-level field', 'title: 暂停\nextra: true\nquestions:\n  - type: free_text\n    text: 继续？\n    default: ""'],
    ['missing default', 'title: 暂停\nquestions:\n  - type: free_text\n    text: 继续？'],
    ['type alias', 'title: 暂停\nquestions:\n  - type: multiple_choice\n    text: 继续？\n    options: [继续]\n    default: [继续]'],
    ['object option', 'title: 暂停\nquestions:\n  - type: single_choice\n    text: 继续？\n    options:\n      - value: continue\n        label: 继续\n    default: continue'],
  ])('keeps strictly invalid fenced YAML as markdown: %s', (_name, yaml) => {
    const source = `请确认。\n\n\`\`\`questionnaire\n${yaml}\n\`\`\``
    expect(splitInlineQuestionnaireContent(source, 'invalid')).toEqual([
      expect.objectContaining({ type: 'markdown', content: '请确认。\n\n' }),
      expect.objectContaining({ type: 'markdown', content: expect.stringContaining('```questionnaire') }),
    ])
  })

  it('requires visible prose before the first fenced questionnaire', () => {
    const source = '```questionnaire\ntitle: 暂停\nquestions:\n  - type: free_text\n    text: 继续？\n    default: ""\n```'
    expect(splitInlineQuestionnaireContent(source, 'no_preface')).toEqual([
      expect.objectContaining({ type: 'markdown', content: source }),
    ])
  })

  it('normalizes questionnaire_async tool results into a generic questionnaire', () => {
    const questionnaire = questionnaireFromAsyncToolResult({
      content: {
        success: true,
        validation_passed: true,
        title: '继续执行',
        questions: [{
          id: 'action',
          type: 'single_choice',
          text: '是否继续？',
          options: [{ value: 'continue', label: '继续' }],
          default: 'continue',
          allow_other: false,
        }],
      },
    }, { id: 'call_1' })

    expect(questionnaire).toMatchObject({
      id: 'call_1',
      tag: 'questionnaire',
      questions: [{ id: 'action', defaultValue: 'continue' }],
    })
  })

  it('allows submission only from the latest meaningful assistant message', () => {
    const messages = [
      { role: 'assistant', content: 'first' },
      { role: 'tool', content: '{}' },
      { role: 'assistant', content: 'replacement' },
      { role: 'assistant', message_type: 'token_usage' },
    ]

    expect(canSubmitQuestionnaireMessage(messages, 0)).toBe(false)
    expect(canSubmitQuestionnaireMessage(messages, 2)).toBe(true)
    expect(canSubmitQuestionnaireMessage(messages, 2, true)).toBe(false)
    expect(canSubmitQuestionnaireMessage([...messages, { role: 'user', content: 'answer' }], 2)).toBe(false)
  })
})
