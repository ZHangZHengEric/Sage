/**
 * HTML导出工具
 * 用于将对话记录导出为HTML文件，支持Markdown渲染、表格和ECharts图表
 */

/**
 * 导出对话记录为HTML文件
 * @param {Object} conversation - 对话记录对象
 * @param {Array} visibleMessages - 可见的消息列表
 */
export const exportToHTML = (conversation, visibleMessages) => {
  console.log('🚀 exportToHTML 函数开始执行');
  console.log('📋 conversation:', conversation);
  console.log('📝 原始消息数量:', conversation.messages?.length || 0);
  console.log('✅ 过滤后的可见消息数量:', visibleMessages.length);
  console.log('📄 可见消息内容:', visibleMessages);

  const htmlContent = generateHTMLContent(conversation, visibleMessages);
  downloadHTML(htmlContent, conversation.title);
};

/**
 * 生成HTML内容
 * @param {Object} conversation - 对话记录对象
 * @param {Array} visibleMessages - 可见的消息列表
 * @returns {string} HTML内容字符串
 */
const generateHTMLContent = (conversation, visibleMessages) => {
  const title = conversation.title || '对话记录';
  const exportTime = new Date().toLocaleString('zh-CN');
  const messageCount = visibleMessages.length;
  
  // 构建消息HTML
  let messagesHtml = '';
  
  visibleMessages.forEach((message, index) => {
    if (message.role === 'user') {
      const content = renderMarkdown(message.content || '');
      messagesHtml += `
        <div class="message user">
          <div class="avatar">👤</div>
          <div class="message-bubble">
            <div class="message-content">${content}</div>
          </div>
        </div>`;
    } else if (message.role === 'assistant') {
      if (message.tool_calls && message.tool_calls.length > 0) {
        // 工具调用消息
        message.tool_calls.forEach(toolCall => {
          const toolName = toolCall.function?.name || '未知工具';
          const toolArgs = toolCall.function?.arguments || '{}';
          messagesHtml += `
            <div class="message tool">
              <div class="avatar">🔧</div>
              <div class="message-bubble">
                <div class="tool-info">工具调用: ${escapeHtml(toolName)}</div>
                <div class="message-content">
                  <pre><code>${escapeHtml(toolArgs)}</code></pre>
                </div>
              </div>
            </div>`;
        });
      } else if (message.show_content) {
        // AI助手回复
        const content = renderMarkdown(message.show_content);
        messagesHtml += `
          <div class="message assistant">
            <div class="avatar">🤖</div>
            <div class="message-bubble">
              <div class="message-content">${content}</div>
            </div>
          </div>`;
      }
    } else if (message.role === 'tool') {
      const toolName = message.name || '未知工具';
      const content = typeof message.content === 'object' 
        ? JSON.stringify(message.content, null, 2) 
        : (message.content || '');
      messagesHtml += `
        <div class="message tool-result">
          <div class="avatar">📋</div>
          <div class="message-bubble">
            <div class="tool-info">执行结果</div>
            <div class="message-content">
              <pre><code>${escapeHtml(content)}</code></pre>
            </div>
          </div>
        </div>`;
    }
  });
  
  // 构建完整的HTML
  const htmlContent = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>对话记录 - ${escapeHtml(title)}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #2d3748;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 32px;
            margin-bottom: 12px;
            font-weight: 700;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        .meta {
            opacity: 0.9;
            font-size: 16px;
            font-weight: 500;
        }
        
        .messages {
            padding: 40px;
            background: #f8fafc;
        }
        
        .message {
            display: flex;
            margin-bottom: 32px;
            align-items: flex-start;
            animation: fadeInUp 0.5s ease-out;
        }
        
        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .message.user {
            justify-content: flex-end;
        }
        
        .avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: 600;
            color: white;
            flex-shrink: 0;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .message.user .avatar {
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            margin-left: 16px;
            order: 2;
        }
        
        .message.assistant .avatar {
            background: linear-gradient(135deg, #10b981 0%, #047857 100%);
            margin-right: 16px;
        }
        
        .message.tool .avatar {
            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
            margin-right: 16px;
        }
        
        .message.tool-result .avatar {
            background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
            margin-right: 16px;
        }
        
        .message-bubble {
            max-width: 75%;
            padding: 20px 24px;
            border-radius: 20px;
            position: relative;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
            backdrop-filter: blur(10px);
        }
        
        .message.user .message-bubble {
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            color: white;
        }
        
        .message.assistant .message-bubble {
            background: white;
            color: #1a202c;
            border: 1px solid #e2e8f0;
        }
        
        .message.tool .message-bubble {
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #fbbf24;
        }
        
        .message.tool-result .message-bubble {
            background: #f3e8ff;
            color: #6b46c1;
            border: 1px solid #c084fc;
        }
        
        .tool-info {
            font-weight: 700;
            margin-bottom: 12px;
            font-size: 14px;
            opacity: 0.8;
        }
        
        .message-content {
            word-wrap: break-word;
            line-height: 1.7;
        }
        
        /* Markdown 样式 */
        .message-content h1,
        .message-content h2,
        .message-content h3,
        .message-content h4,
        .message-content h5,
        .message-content h6 {
            margin: 16px 0 12px 0;
            font-weight: 700;
            line-height: 1.3;
        }
        
        .message-content h1 { font-size: 24px; }
        .message-content h2 { font-size: 20px; }
        .message-content h3 { font-size: 18px; }
        .message-content h4 { font-size: 16px; }
        .message-content h5 { font-size: 14px; }
        .message-content h6 { font-size: 12px; }
        
        .message-content p {
            margin: 12px 0;
        }
        
        .message-content strong {
            font-weight: 700;
        }
        
        .message-content em {
            font-style: italic;
        }
        
        .message-content ul,
        .message-content ol {
            margin: 12px 0;
            padding-left: 24px;
        }
        
        .message-content li {
            margin: 4px 0;
        }
        
        .message-content blockquote {
            border-left: 4px solid #e2e8f0;
            padding-left: 16px;
            margin: 16px 0;
            font-style: italic;
            opacity: 0.8;
        }
        
        .message.user .message-content blockquote {
            border-left-color: rgba(255, 255, 255, 0.3);
        }
        
        .message-content pre {
            background: #1a202c;
            color: #e2e8f0;
            padding: 20px;
            border-radius: 12px;
            overflow-x: auto;
            margin: 16px 0;
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            font-size: 14px;
            line-height: 1.5;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .message-content code {
            background: #f1f5f9;
            color: #e53e3e;
            padding: 3px 8px;
            border-radius: 6px;
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            font-size: 13px;
            font-weight: 600;
        }
        
        .message.user .message-content code {
            background: rgba(255, 255, 255, 0.2);
            color: #fed7d7;
        }
        
        .message-content pre code {
            background: none;
            color: inherit;
            padding: 0;
            border-radius: 0;
        }
        
        /* 表格样式 */
        .message-content table {
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        .message-content th,
        .message-content td {
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        
        .message-content th {
            background: #f8fafc;
            font-weight: 700;
            color: #2d3748;
        }
        
        .message-content tr:hover {
            background: #f7fafc;
        }
        
        .message.user .message-content table {
            background: rgba(255, 255, 255, 0.1);
        }
        
        .message.user .message-content th {
            background: rgba(255, 255, 255, 0.2);
            color: white;
        }
        
        .message.user .message-content td {
            color: white;
            border-bottom-color: rgba(255, 255, 255, 0.2);
        }
        
        /* ECharts 容器样式 */
        .echarts-container {
            width: 100%;
            height: 400px;
            margin: 16px 0;
            border-radius: 12px;
            background: white;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        
        .message.user .echarts-container {
            background: rgba(255, 255, 255, 0.1);
        }
        
        /* 响应式设计 */
        @media (max-width: 768px) {
            body {
                padding: 10px;
            }
            
            .container {
                margin: 0;
                border-radius: 12px;
            }
            
            .header {
                padding: 30px 20px;
            }
            
            .header h1 {
                font-size: 24px;
            }
            
            .messages {
                padding: 20px;
            }
            
            .message-bubble {
                max-width: 90%;
                padding: 16px 20px;
            }
            
            .avatar {
                width: 40px;
                height: 40px;
                font-size: 16px;
            }
            
            .echarts-container {
                height: 300px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>${escapeHtml(title)}</h1>
            <div class="meta">
                📅 导出时间: ${escapeHtml(exportTime)}<br>
                💬 消息数量: ${messageCount} 条
            </div>
        </div>
        <div class="messages">${messagesHtml}
        </div>
    </div>
    

</body>
</html>`;

  return htmlContent;
};

/**
 * 渲染Markdown内容
 * @param {string} text - Markdown文本
 * @returns {string} 渲染后的HTML
 */
const renderMarkdown = (text) => {
  if (!text) return '';
  
  let html = escapeHtml(text);
  
  // 处理ECharts代码块
  html = processEChartsBlocks(html);
  
  // 处理代码块（在其他处理之前）
  html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  
  // 处理行内代码
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  
  // 处理标题
  html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>');
  
  // 处理粗体和斜体
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  
  // 处理链接
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  
  // 处理列表
  html = html.replace(/^\* (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  
  // 处理有序列表
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  
  // 处理引用
  html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
  
  // 处理表格
  html = processMarkdownTables(html);
  
  // 处理段落
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';
  
  // 清理空段落
  html = html.replace(/<p><\/p>/g, '');
  html = html.replace(/<p>\s*<\/p>/g, '');
  
  return html;
};

/**
 * 处理ECharts代码块
 * @param {string} html - HTML内容
 * @returns {string} 处理后的HTML
 */
const processEChartsBlocks = (html) => {
  // 首先处理纯ECharts JSON配置格式（以echarts开头的代码块）
  const echartsJsonRegex = /```(?:echarts|json)?\s*(echarts[\s\S]*?)```/gi;
  html = html.replace(echartsJsonRegex, (match, content) => {
    try {
      // 提取JSON配置部分
      const jsonMatch = content.match(/echarts\s*\n?\s*({[\s\S]*})/i);
      if (jsonMatch) {
        const config = jsonMatch[1];
        const chartId = 'chart_' + Math.random().toString(36).substr(2, 9);
        return `<div class="echarts-container" id="${chartId}"></div>
<script>
(function() {
  try {
    const chartDom = document.getElementById('${chartId}');
    const myChart = echarts.init(chartDom);
    const option = ${config};
    
    // 自动调整图例位置以避免与标题重叠
    if (option.title && option.legend && !option.legend.top) {
      if (option.title.subtext) {
        option.legend.top = '15%'; // 有副标题时，图例位置更靠下
      } else {
        option.legend.top = '10%'; // 只有主标题时，图例位置稍微靠下
      }
    }
    
    myChart.setOption(option);
    window.addEventListener('resize', () => myChart.resize());
  } catch (error) {
    console.error('ECharts图表渲染失败:', error);
  }
})();
</script>`;
      }
    } catch (error) {
      console.error('ECharts JSON配置处理失败:', error);
    }
    return `<pre><code>${escapeHtml(content)}</code></pre>`;
  });
  
  // 然后处理JavaScript代码块中的ECharts代码
  const echartsRegex = /```(?:javascript|js)?\s*([\s\S]*?)```/gi;
  
  return html.replace(echartsRegex, (match, code) => {
    // 检查代码块是否包含ECharts相关代码
    if (!(code.includes('echarts') || code.includes('ECharts'))) {
      return `<pre><code>${escapeHtml(code)}</code></pre>`;
    }
    try {
        const chartId = 'chart_' + Math.random().toString(36).substr(2, 9);
        
        // 如果包含完整的ECharts代码，优先使用完整代码执行模式
        if (code.includes('echarts.init')) {
          // 替换DOM元素引用为我们的chartId
          let modifiedCode = code.replace(/document\.getElementById\(['"][^'"]*['"]\)/g, `document.getElementById('${chartId}')`);
          // 如果代码中使用了变量dom，也要替换
          modifiedCode = modifiedCode.replace(/echarts\.init\(dom\)/g, `echarts.init(document.getElementById('${chartId}'))`);
          
          return `<div class="echarts-container" id="${chartId}"></div>
<script>
(function() {
  try {
    ${modifiedCode}
  } catch (error) {
    console.error('ECharts图表渲染失败:', error);
  }
})();
</script>`;
        }
        
        // 否则尝试提取配置对象
        const configMatch = code.match(/(?:setOption|option)\s*\(\s*({[\s\S]*?})\s*\)/i);
        if (configMatch) {
          const config = configMatch[1];
          return `<div class="echarts-container" id="${chartId}"></div>
<script>
(function() {
  try {
    const chartDom = document.getElementById('${chartId}');
    const myChart = echarts.init(chartDom);
    const option = ${config};
    
    // 自动调整图例位置以避免与标题重叠
    if (option.title && option.legend && !option.legend.top) {
      if (option.title.subtext) {
        option.legend.top = '15%'; // 有副标题时，图例位置更靠下
      } else {
        option.legend.top = '10%'; // 只有主标题时，图例位置稍微靠下
      }
    }
    
    myChart.setOption(option);
    window.addEventListener('resize', () => myChart.resize());
  } catch (error) {
    console.error('ECharts图表渲染失败:', error);
  }
})();
</script>`;
        }
        
        // 如果没有匹配到任何ECharts模式，返回原始代码块
        return `<pre><code>${escapeHtml(code)}</code></pre>`;
    } catch (error) {
      console.error('ECharts代码块处理失败:', error);
      return `<pre><code>${escapeHtml(code)}</code></pre>`;
    }
  });
};

/**
 * 处理Markdown表格
 * @param {string} html - HTML内容
 * @returns {string} 处理后的HTML
 */
const processMarkdownTables = (html) => {
  // 匹配Markdown表格
  const tableRegex = /\|(.+)\|\n\|([\s\S]*?)\|\n((?:\|.*\|\n?)*)/g;
  
  return html.replace(tableRegex, (match, header, separator, rows) => {
    const headerCells = header.split('|').map(cell => cell.trim()).filter(cell => cell);
    const rowLines = rows.trim().split('\n').filter(line => line.trim());
    
    let tableHtml = '<table><thead><tr>';
    headerCells.forEach(cell => {
      tableHtml += `<th>${cell}</th>`;
    });
    tableHtml += '</tr></thead><tbody>';
    
    rowLines.forEach(line => {
      const cells = line.split('|').map(cell => cell.trim()).filter(cell => cell);
      tableHtml += '<tr>';
      cells.forEach(cell => {
        tableHtml += `<td>${cell}</td>`;
      });
      tableHtml += '</tr>';
    });
    
    tableHtml += '</tbody></table>';
    return tableHtml;
  });
};

/**
 * 转义HTML特殊字符
 * @param {string} text - 需要转义的文本
 * @returns {string} 转义后的文本
 */
const escapeHtml = (text) => {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
};

/**
 * 下载HTML文件
 * @param {string} htmlContent - HTML内容
 * @param {string} filename - 文件名
 */
const downloadHTML = (htmlContent, filename) => {
  console.log('📄 HTML内容长度:', htmlContent.length);
  console.log('🔍 HTML内容预览:', htmlContent.substring(0, 200) + '...');
  
  const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
  console.log('📦 Blob创建成功，大小:', blob.size, 'bytes');
  
  const url = URL.createObjectURL(blob);
  console.log('🔗 URL创建成功:', url);
  
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filename || '对话记录'}.html`;
  console.log('💾 下载文件名:', a.download);
  
  document.body.appendChild(a);
  a.click();
  console.log('✅ 下载链接已点击');
  
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  console.log('🧹 清理完成');
};