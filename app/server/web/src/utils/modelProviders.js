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
    name: 'Aliyun Coding Plan',
    base_url: 'https://coding.dashscope.aliyuncs.com/v1',
    models: ['qwen-coder-plus', 'qwen-coder-turbo', 'deepseek-r1', 'deepseek-v3'],
    website: 'https://bailian.console.aliyun.com/',
    model_list_url: 'https://help.aliyun.com/zh/model-studio/coding-plan',
    description: '阿里云百炼编码专属套餐，支持 Claude Code、Cursor 等编程工具'
  },
  {
    name: 'ByteDance',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    models: ['doubao-seed-2-0-lite-260215', 'doubao-seed-2-0-pro-260215', 'doubao-seedance-2-0', 'doubao-seedream-5-0', 'doubao-pro-32k', 'doubao-lite-32k', 'doubao-pro-128k', 'deepseek-r1-250120', 'deepseek-v3-241226'],
    website: 'https://console.volcengine.com/ark/region:ark+cn-beijing/endpoint',
    model_list_url: 'https://www.volcengine.com/docs/82379/1099475'
  },
  {
    name: 'Moonshot',
    base_url: 'https://api.moonshot.cn/v1',
    models: ['kimi-k2-0905-preview', 'kimi-k2-turbo-preview', 'kimi-k2-0711-preview', 'kimi-thinking-preview', 'kimi-latest', 'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
    website: 'https://platform.moonshot.cn',
    model_list_url: 'https://platform.moonshot.cn/docs'
  },
  {
    name: 'MiniMax',
    base_url: 'https://api.minimaxi.com/v1',
    models: ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed','MiniMax-M2.5-highspeed', 'MiniMax-M2.5', 'MiniMax-M2.1-highspeed', 'MiniMax-M2.1', 'MiniMax-M2'],
    website: 'https://platform.minimaxi.com',
    model_list_url: 'https://platform.minimaxi.com/docs/api-reference/api-overview'
  },
  {
    name: 'iFLYTEK',
    base_url: 'https://spark-api-open.xf-yun.com/v1',
    models: ['4.0Ultra', 'generalv3.5', 'max-32k', 'pro-128k', 'generalv3', 'lite'],
    website: 'https://console.xfyun.cn/services/bm35',
    model_list_url: 'https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html'
  },
  {
    name: 'Tencent Hunyuan',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
    models: ['hunyuan-2.0-instruct-20251111', 'hunyuan-2.0-thinking-20251109', 'hunyuan-t1-latest', 'hunyuan-turbos-latest', 'hunyuan-a13b', 'hunyuan-lite'],
    website: 'https://console.cloud.tencent.com/hunyuan',
    model_list_url: 'https://cloud.tencent.com/document/product/1729/104753'
  },
  {
    name: 'Zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-5', 'glm-4.7', 'glm-4.6', 'glm-4.5', 'glm-4.5-air', 'glm-4-plus', 'glm-4-air', 'glm-4-flash'],
    website: 'https://open.bigmodel.cn',
    model_list_url: 'https://docs.bigmodel.cn/cn/guide/models/text/glm-4.5'
  },
  {
    name: 'Zhipu Code Plan',
    base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
    models: ['glm-5.1', 'glm-4.7', 'glm-5', 'glm-4.6', 'glm-4.5'],
    website: 'https://www.bigmodel.cn/glm-coding',
    model_list_url: 'https://docs.bigmodel.cn/cn/coding-plan/quick-start',
    description: '智谱编码专属套餐，支持 Claude Code、Cline 等编程工具'
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
