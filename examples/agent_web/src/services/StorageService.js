class StorageService {
  static KEYS = {
    AGENTS: 'agent_platform_agents',
    CONVERSATIONS: 'agent_platform_conversations',
    SETTINGS: 'agent_platform_settings'
  };

  // Agent 相关方法
  static getAgents() {
    try {
      const agents = localStorage.getItem(this.KEYS.AGENTS);
      return agents ? JSON.parse(agents) : this.getDefaultAgents();
    } catch (error) {
      console.error('Error loading agents:', error);
      return this.getDefaultAgents();
    }
  }

  static saveAgents(agents) {
    try {
      localStorage.setItem(this.KEYS.AGENTS, JSON.stringify(agents));
    } catch (error) {
      console.error('Error saving agents:', error);
    }
  }

  static getDefaultAgents() {
    return [
      {
        id: 'default',
        name: '智能助手',
        description: '一个通用型人工智能助手，擅长解答问题并提供有价值的后续建议。',
        systemPrefix: '# 角色\n你是一个友好且专业的AI助手，旨在为用户提供准确、全面的信息和服务。在与用户互动时，你会积极鼓励用户提问，并通过反问收集更多信息以优化回答质量。\n\n## 目标\n为用户提供准确、及时的信息和服务，同时通过互动收集更多信息以优化后续回答。\n\n## 技能\n### 技能1: 数学计算\n支持基本数学运算、阶乘计算等数学相关功能。\n\n### 技能2: 系统操作\n可以执行Shell命令、Python代码，获取系统信息，检查命令可用性等。\n\n### 技能3: 文件处理\n支持多种文件格式的文本提取、内容搜索、替换和转换，包括PDF、Word、Excel等。\n\n### 技能4: 网络搜索\n提供强大的统一搜索引擎，支持按时间和类别筛选搜索结果。\n\n### 技能5: 数据可视化\n支持绘制折线图、柱状图、饼图等多种图表。\n\n### 技能6: 图像处理\n可以理解图像内容、提取文字和描述图像。\n\n### 技能7: 统计分析\n提供描述性统计、相关性分析、回归预测等多种统计功能。\n\n## 限制\n- 限制1：只能使用已提供的工具能力\n\n## 输出形式要求\n- 要求1：语言风格口语化，适当使用emoji\n- 要求2：在回答完问题后，要提出相关的后续问题\n\n## 其他特殊要求\n- 要求1：多肯定和鼓励用户提问\n- 要求2：在合适的场合使用\"这真是个好问题\"等鼓励性语言',
        deepThinking: null,
        multiAgent: null,
        moreSuggest: false,
        maxLoopCount: 20,
        llmConfig:null,
        systemContext: {},
        availableWorkflows: {},
        availableTools: [
          'complete_task',
          'file_read',
          'file_write',
          'replace_text_in_file',
          'unified_web_search',
          'extract_text_from_non_text_file',
          'download_file_from_url',
          'extract_text_from_url',
          'execute_shell_command',
          'execute_python_code'
        ],
        createdAt: new Date().toISOString()
      }
    ];
  }

  // 对话相关方法
  static getConversations() {
    try {
      console.log('🔍 StorageService: 开始从localStorage加载对话数据...');
      const conversationsStr = localStorage.getItem(this.KEYS.CONVERSATIONS);
      
      if (!conversationsStr) {
        console.log('📭 StorageService: localStorage中没有对话数据，返回空数组');
        return [];
      }
      
      const conversations = JSON.parse(conversationsStr);
      console.log('📊 StorageService: 成功加载对话数据', {
        conversationsCount: conversations.length,
        conversations: conversations.map(conv => ({
          id: conv.id,
          sessionId: conv.sessionId,
          title: conv.title,
          hasTokenUsage: !!conv.tokenUsage,
          tokenUsageType: typeof conv.tokenUsage,
          tokenUsageKeys: conv.tokenUsage ? Object.keys(conv.tokenUsage) : null,
          tokenUsage: conv.tokenUsage,
          messagesCount: conv.messages?.length || 0,
          createdAt: conv.createdAt,
          updatedAt: conv.updatedAt
        }))
      });
      
      return conversations;
    } catch (error) {
      console.error('❌ StorageService: 加载对话数据时出错:', error);
      return [];
    }
  }

  static saveConversations(conversations) {
    try {
      console.log('💾 StorageService: 开始保存对话数据到localStorage...', {
        conversationsCount: conversations.length,
        conversations: conversations.map(conv => ({
          id: conv.id,
          sessionId: conv.sessionId,
          title: conv.title,
          hasTokenUsage: !!conv.tokenUsage,
          tokenUsageType: typeof conv.tokenUsage,
          tokenUsageKeys: conv.tokenUsage ? Object.keys(conv.tokenUsage) : null,
          tokenUsage: conv.tokenUsage,
          messagesCount: conv.messages?.length || 0,
          createdAt: conv.createdAt,
          updatedAt: conv.updatedAt
        }))
      });
      
      localStorage.setItem(this.KEYS.CONVERSATIONS, JSON.stringify(conversations));
      console.log('✅ StorageService: 对话数据保存成功');
    } catch (error) {
      console.error('❌ StorageService: 保存对话数据时出错:', error);
    }
  }

  static getConversation(id) {
    const conversations = this.getConversations();
    return conversations.find(conv => conv.id === id);
  }

  static saveConversation(conversation) {
    const conversations = this.getConversations();
    const index = conversations.findIndex(conv => conv.id === conversation.id);
    
    if (index >= 0) {
      conversations[index] = conversation;
    } else {
      conversations.unshift(conversation);
    }

    // 获取最大对话数量设置，默认为 100
    const settings = this.getSettings();
    const maxConversations = settings.maxConversations || 100;

    // 如果对话数量超过最大值，则删除最旧的对话
    if (conversations.length > maxConversations) {
      conversations.splice(maxConversations);
    }
    
    this.saveConversations(conversations);
  }

  static deleteConversation(id) {
    const conversations = this.getConversations();
    const filtered = conversations.filter(conv => conv.id !== id);
    this.saveConversations(filtered);
  }

  // 设置相关方法
  static getSettings() {
    try {
      const settings = localStorage.getItem(this.KEYS.SETTINGS);
      return settings ? JSON.parse(settings) : this.getDefaultSettings();
    } catch (error) {
      console.error('Error loading settings:', error);
      return this.getDefaultSettings();
    }
  }

  static saveSettings(settings) {
    try {
      localStorage.setItem(this.KEYS.SETTINGS, JSON.stringify(settings));
    } catch (error) {
      console.error('Error saving settings:', error);
    }
  }

  static getDefaultSettings() {
    return {
      theme: 'dark',
      language: 'zh-CN',
      autoSave: true,
      maxConversations: 100
    };
  }

  // 清理方法
  static clearAll() {
    try {
      localStorage.removeItem(this.KEYS.AGENTS);
      localStorage.removeItem(this.KEYS.CONVERSATIONS);
      localStorage.removeItem(this.KEYS.SETTINGS);
    } catch (error) {
      console.error('Error clearing storage:', error);
    }
  }

  static exportData() {
    return {
      agents: this.getAgents(),
      conversations: this.getConversations(),
      settings: this.getSettings(),
      exportTime: new Date().toISOString()
    };
  }

  static importData(data) {
    try {
      if (data.agents) this.saveAgents(data.agents);
      if (data.conversations) this.saveConversations(data.conversations);
      if (data.settings) this.saveSettings(data.settings);
      return true;
    } catch (error) {
      console.error('Error importing data:', error);
      return false;
    }
  }
}

export default StorageService;