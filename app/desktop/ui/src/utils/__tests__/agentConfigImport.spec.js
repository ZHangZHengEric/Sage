import { describe, expect, it } from 'vitest'

import { buildImportedAgentDraft, parseAgentConfigImport } from '../agentConfigImport.js'

describe('agentConfigImport', () => {
  it('parses yaml agent config and builds an editable draft', () => {
    const yaml = `
name: Research Bot
description: YAML imported agent
deepThinking: true
maxLoopCount: 12
availableTools:
  - web_search
availableSkills:
  - researcher
llmConfig:
  temperature: 0.2
systemContext:
  team: growth
availableWorkflows:
  triage:
    enabled: true
`

    const importedConfig = parseAgentConfigImport(yaml)
    const draft = buildImportedAgentDraft(importedConfig, ' (imported)')

    expect(draft).toMatchObject({
      name: 'Research Bot (imported)',
      description: 'YAML imported agent',
      deepThinking: true,
      maxLoopCount: 12,
      availableTools: ['web_search'],
      availableSkills: ['researcher'],
      llmConfig: { temperature: 0.2 },
      systemContext: { team: 'growth' },
      availableWorkflows: { triage: { enabled: true } },
    })
  })

  it('rejects non-object imports', () => {
    expect(() => parseAgentConfigImport('- just\n- a\n- list\n')).toThrow()
  })

  it('rejects drafts without a name', () => {
    expect(() => buildImportedAgentDraft({}, ' (imported)')).toThrow()
  })
})
