import { load } from 'js-yaml'

const isPlainObject = (value) => value && typeof value === 'object' && !Array.isArray(value)

export const parseAgentConfigImport = (content) => {
  const parsed = load(content)

  if (!isPlainObject(parsed)) {
    throw new Error('Imported agent config must be an object')
  }

  return parsed
}

export const buildImportedAgentDraft = (importedConfig, importSuffix = '') => {
  if (!isPlainObject(importedConfig) || !importedConfig.name) {
    throw new Error('Imported agent config is missing required name')
  }

  return {
    name: `${importedConfig.name}${importSuffix}`,
    llm_provider_id: importedConfig.llm_provider_id || null,
    description: importedConfig.description || '',
    systemPrefix: importedConfig.systemPrefix || '',
    deepThinking: importedConfig.deepThinking || false,
    multiAgent: importedConfig.multiAgent || false,
    maxLoopCount: importedConfig.maxLoopCount ?? null,
    availableTools: importedConfig.availableTools || [],
    availableSkills: importedConfig.availableSkills || [],
    systemContext: importedConfig.systemContext || {},
    availableWorkflows: importedConfig.availableWorkflows || {},
    llmConfig: importedConfig.llmConfig || {},
  }
}
