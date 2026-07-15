import { describe, expect, it } from 'vitest'

import {
  buildQuestionnaireSubmission,
  displayTextForAnswers,
  initialQuestionnaireDraft,
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

  it('parses movo questionnaire tags at their markdown position', () => {
    const parts = splitInlineQuestionnaireContent(
      '先确认。\n\n<movo-questionnaire>{"title":"小狗视频确认","questions":[{"type":"single_choice","text":"成片画幅？","options":["9:16","16:9"],"default":"9:16"},{"type":"free_text","text":"补充？","default":""}]}</movo-questionnaire>',
      'assistant_1'
    )

    expect(parts).toHaveLength(2)
    expect(parts[0]).toMatchObject({ type: 'markdown' })
    expect(parts[1]).toMatchObject({
      type: 'questionnaire',
      tag: 'movo-questionnaire',
    })
    expect(parts[1].payload.title).toBe('小狗视频确认')
    expect(parts[1].payload.questions[0]).toMatchObject({
      id: 'q1',
      type: 'single_choice',
      text: '成片画幅？',
      defaultValue: '9:16',
    })
  })

  it('supports all questionnaire tag aliases and multiple choice synonyms', () => {
    for (const tag of ['ling-questionnaire', 'sage-questionnaire', 'questionnaire']) {
      const parts = splitInlineQuestionnaireContent(
        `<${tag}>{"questions":[{"type":"multiple_choice","text":"选项？","options":["A","B"],"default":["A"]}]}</${tag}>`,
        tag
      )
      expect(parts[0].type).toBe('questionnaire')
      expect(parts[0].payload.tag).toBe(tag)
      expect(parts[0].payload.questions[0].type).toBe('multi_choice')
      expect(parts[0].payload.questions[0].defaultValues).toEqual(['A'])
    }
  })

  it('parses html entity and escaped transport payloads', () => {
    const htmlParts = splitInlineQuestionnaireContent(
      '&lt;ling-questionnaire&gt;{&quot;questions&quot;:[{&quot;type&quot;:&quot;single_choice&quot;,&quot;text&quot;:&quot;能量？&quot;,&quot;options&quot;:[&quot;低&quot;,&quot;高&quot;]}]}&lt;/ling-questionnaire&gt;',
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
      '<movo-questionnaire>{"questions":[{"type":"single_choice","text":"画幅？","options":["9:16","16:9"],"default":"9:16"},{"type":"multi_choice","text":"风格？","options":["温暖","活泼"]},{"type":"free_text","text":"补充？","default":"无"}]}</movo-questionnaire>',
      'assistant'
    )[0].payload
    const draft = initialQuestionnaireDraft(questionnaire)
    draft.q1.value = '16:9'
    draft.q2.values = ['温暖', '活泼']
    draft.q3 = '不要字幕'

    const submission = buildQuestionnaireSubmission(questionnaire, draft)

    expect(submission.agentText).toContain('<movo-questionnaire-response>')
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
      '<movo-questionnaire>{"title":"Confirmacao","ui_text":{"other":"Outro","answer_title":"Respostas do questionario","question_fallback":"Pergunta","unanswered":"Nao respondido","unselected":"Nao selecionado","answer_separator":": ","list_separator":", "},"questions":[{"id":"action","type":"single_choice","text":"Como continuar?","options":[{"value":"continue","label":"Continuar"}],"allow_other":true}]}</movo-questionnaire>',
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
})
