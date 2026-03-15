export const MODEL_PROVIDERS = [
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    models: ['deepseek-chat', 'deepseek-reasoner'],
    website: 'https://platform.deepseek.com/api_keys',
    model_list_url: 'https://platform.deepseek.com/api_keys'
  },
  {
    name: 'Aliyun',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3-max', 'qwen3.5-plus', 'qwen-plus', 'qwen3.5-flash', 'qwen-flash', 'qwen-turbo', 'qwq-plus', 'qwen-long', 'deepseek-v3.2'],
    website: 'https://bailian.console.aliyun.com/',
    model_list_url: 'https://help.aliyun.com/zh/model-studio/getting-started/models'
  },
  {
    name: 'ByteDance',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    models: ['doubao-seed-2-0-lite-260215', 'doubao-seed-2-0-pro-260215', 'doubao-seedance-2-0', 'doubao-seedream-5-0', 'doubao-pro-32k', 'doubao-lite-32k', 'doubao-pro-128k', 'deepseek-r1-250120', 'deepseek-v3-241226'],
    website: 'https://console.volcengine.com/ark/region:ark+cn-beijing/endpoint',
    model_list_url: 'https://www.volcengine.com/docs/82379/1099475'
  },
  {
    name: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    models: ['gpt-5.4', 'gpt-5', 'gpt-5-mini', 'gpt-4o', 'gpt-4o-mini', 'gpt-5-nano-2025-08-07'],
    website: 'https://platform.openai.com/api-keys',
    model_list_url: 'https://platform.openai.com/docs/models'
  },
  {
    name: 'OpenRouter',
    base_url: 'https://openrouter.ai/api/v1',
    models: [
      'stepfun/step-3.5-flash:free',
      'arcee-ai/trinity-large-preview:free',
      'nvidia/nemotron-3-nano-30b-a3b:free',
      'qwen/qwen3-next-80b-a3b-instruct:free',
      'openai/gpt-oss-120b:free',
      'z-ai/glm-4.5-air:free',
      'nousresearch/hermes-3-llama-3.1-405b:free'
    ],
    website: 'https://openrouter.ai/keys',
    model_list_url: 'https://openrouter.ai/models'
  }
]
