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
  console.log('🚀 exportToHTML 函数开始执行')
  console.log('📋 conversation:', conversation)
  console.log('📝 原始消息数量:', conversation.messages?.length || 0)
  console.log('✅ 过滤后的可见消息数量:', visibleMessages.length)
  console.log('📄 可见消息内容:', visibleMessages)

  const htmlContent = generateHTMLContent(conversation, visibleMessages)
  downloadHTML(htmlContent, conversation.title)
}

export const exportToMarkdown = (conversation, agentName, visibleMessages) => {
  
  let markdown = `# ${conversation.title}\n\n`
  markdown += `**导出时间**: ${new Date().toLocaleString()}\n`
  markdown += `**Agent**: ${agentName}\n`
  markdown += `**消息数量**: ${visibleMessages.length}\n\n`
  markdown += '---\n\n'
  
  visibleMessages.forEach((message, index) => {
    if (message.role === 'user') {
      markdown += `## 用户 ${index + 1}\n\n${message.content}\n\n`
    } else if (message.role === 'assistant') {
      if (message.show_content) {
        markdown += `## 助手 ${index + 1}\n\n${message.show_content}\n\n`
      } else if (message.tool_calls) {
        markdown += `## 助手 ${index + 1} (工具调用)\n\n`
        message.tool_calls.forEach(tool => {
          markdown += `**工具**: ${tool.function.name}\n`
          markdown += `**参数**: \`\`\`json\n${JSON.stringify(tool.function.arguments, null, 2)}\n\`\`\`\n\n`
        })
      }
    }
  })
  
  // 下载文件
  const blob = new Blob([markdown], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${conversation.title}_${new Date().toISOString().split('T')[0]}.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)

}

/**
 * 生成HTML内容
 * @param {Object} conversation - 对话记录对象
 * @param {Array} visibleMessages - 可见的消息列表
 * @returns {string} HTML内容字符串
 */
const generateHTMLContent = (conversation, visibleMessages) => {
  const title = conversation.title || '对话记录'
  const exportTime = new Date().toLocaleString('zh-CN')
  const messageCount = visibleMessages.length
  
  // 构建消息HTML
  let messagesHtml = ''
  
  visibleMessages.forEach((message, index) => {
    if (message.role === 'user') {
      const content = renderMarkdown(message.content || '')
      messagesHtml += `
        <div class="message user">
          <div class="avatar">👤</div>
          <div class="message-bubble">
            <div class="message-content">${content}</div>
          </div>
        </div>`
    } else if (message.role === 'assistant') {
      if (message.tool_calls && message.tool_calls.length > 0) {
        // 工具调用消息
        message.tool_calls.forEach(toolCall => {
          const toolName = toolCall.function?.name || '未知工具'
          const toolArgs = toolCall.function?.arguments || '{}'
          messagesHtml += `
            <div class="message tool">
              <div class="avatar">🔧</div>
              <div class="message-bubble">
                <div class="tool-info">工具调用: ${escapeHtml(toolName)}</div>
                <div class="message-content">
                  <pre><code>${escapeHtml(toolArgs)}</code></pre>
                </div>
              </div>
            </div>`
        })
      } else if (message.show_content) {
        // AI助手回复
        const content = renderMarkdown(message.show_content)
        messagesHtml += `
          <div class="message assistant">
            <div class="avatar">🤖</div>
            <div class="message-bubble">
              <div class="message-content">${content}</div>
            </div>
          </div>`
      }
    } else if (message.role === 'tool') {
      const toolName = message.name || '未知工具'
      const content = typeof message.content === 'object' 
        ? JSON.stringify(message.content, null, 2) 
        : (message.content || '')
      messagesHtml += `
        <div class="message tool-result">
          <div class="avatar">📋</div>
          <div class="message-bubble">
            <div class="tool-info">执行结果</div>
            <div class="message-content">
              <pre><code>${escapeHtml(content)}</code></pre>
            </div>
          </div>
        </div>`
    }
  })
  
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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2em;
            margin-bottom: 10px;
        }
        
        .header .meta {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .messages {
            padding: 20px;
        }
        
        .message {
            display: flex;
            margin-bottom: 20px;
            align-items: flex-start;
        }
        
        .message.user {
            flex-direction: row-reverse;
        }
        
        .avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2em;
            margin: 0 10px;
            flex-shrink: 0;
        }
        
        .message.user .avatar {
            background: #007bff;
            color: white;
        }
        
        .message.assistant .avatar {
            background: #28a745;
            color: white;
        }
        
        .message.tool .avatar,
        .message.tool-result .avatar {
            background: #ffc107;
            color: #333;
        }
        
        .message-bubble {
            max-width: 70%;
            padding: 15px;
            border-radius: 18px;
            position: relative;
        }
        
        .message.user .message-bubble {
            background: #007bff;
            color: white;
        }
        
        .message.assistant .message-bubble {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
        }
        
        .message.tool .message-bubble,
        .message.tool-result .message-bubble {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
        }
        
        .tool-info {
            font-weight: bold;
            margin-bottom: 8px;
            color: #856404;
        }
        
        .message-content {
            word-wrap: break-word;
        }
        
        .message-content pre {
            background: rgba(0,0,0,0.05);
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
            margin: 10px 0;
        }
        
        .message-content code {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
        }
        
        .message-content h1,
        .message-content h2,
        .message-content h3,
        .message-content h4,
        .message-content h5,
        .message-content h6 {
            margin: 15px 0 10px 0;
            color: #333;
        }
        
        .message-content p {
            margin: 10px 0;
        }
        
        .message-content ul,
        .message-content ol {
            margin: 10px 0;
            padding-left: 20px;
        }
        
        .message-content blockquote {
            border-left: 4px solid #ddd;
            margin: 15px 0;
            padding-left: 15px;
            color: #666;
        }
        
        .message-content table {
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }
        
        .message-content th,
        .message-content td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        
        .message-content th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        
        .echarts-container {
            margin: 15px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
        }
        
        @media (max-width: 768px) {
            body {
                padding: 10px;
            }
            
            .header {
                padding: 20px;
            }
            
            .header h1 {
                font-size: 1.5em;
            }
            
            .messages {
                padding: 15px;
            }
            
            .message-bubble {
                max-width: 85%;
            }
            
            .avatar {
                width: 35px;
                height: 35px;
                font-size: 1em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>${escapeHtml(title)}</h1>
            <div class="meta">
                导出时间: ${exportTime} | 消息数量: ${messageCount}
            </div>
        </div>
        <div class="messages">
            ${messagesHtml}
        </div>
    </div>
    
    <script>
        // 初始化所有ECharts图表
        document.addEventListener('DOMContentLoaded', function() {
            const echartsContainers = document.querySelectorAll('.echarts-container');
            echartsContainers.forEach(container => {
                try {
                    const configScript = container.querySelector('script');
                    if (configScript && window.echarts) {
                        const chart = echarts.init(container);
                        const config = eval('(' + configScript.textContent + ')');
                        chart.setOption(config);
                        
                        // 响应式调整
                        window.addEventListener('resize', () => {
                            chart.resize();
                        });
                    }
                } catch (error) {
                    console.error('初始化ECharts图表失败:', error);
                }
            });
        });
    </script>
</body>
</html>`

  return htmlContent
}

/**
 * 简单的Markdown渲染器
 * @param {string} text - Markdown文本
 * @returns {string} 渲染后的HTML
 */
const renderMarkdown = (text) => {
  if (!text) return ''
  
  let html = escapeHtml(text)
  
  // 处理代码块
  html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
    return `<pre><code class="language-${lang || 'text'}">${code.trim()}</code></pre>`
  })
  
  // 处理行内代码
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  
  // 处理标题
  html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>')
  
  // 处理粗体和斜体
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')
  
  // 处理链接
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
  
  // 处理换行
  html = html.replace(/\n/g, '<br>')
  
  // 处理ECharts代码块
  html = processEChartsBlocks(html)
  
  // 处理表格
  html = processMarkdownTables(html)
  
  return html
}

/**
 * 处理ECharts代码块
 * @param {string} html - HTML内容
 * @returns {string} 处理后的HTML
 */
const processEChartsBlocks = (html) => {
  return html.replace(/<pre><code class="language-echarts">([\s\S]*?)<\/code><\/pre>/g, (match, code) => {
    try {
      // 解码HTML实体
      const decodedCode = code
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
        .replace(/&quot;/g, '"')
        .replace(/&#x27;/g, "'")
      
      // 生成唯一ID
      const chartId = 'chart_' + Math.random().toString(36).substr(2, 9)
      
      return `
        <div class="echarts-container" id="${chartId}" style="width: 100%; height: 400px;">
          <script type="text/javascript">
            ${decodedCode}
          </script>
        </div>
      `
    } catch (error) {
      console.error('处理ECharts代码块失败:', error)
      return match
    }
  })
}

/**
 * 处理Markdown表格
 * @param {string} html - HTML内容
 * @returns {string} 处理后的HTML
 */
const processMarkdownTables = (html) => {
  // 匹配Markdown表格格式
  const tableRegex = /(\|.*\|.*\n\|[-\s|:]+\|.*\n(?:\|.*\|.*\n?)*)/g
  
  return html.replace(tableRegex, (match) => {
    const lines = match.trim().split('\n')
    if (lines.length < 2) return match
    
    const headerLine = lines[0]
    const separatorLine = lines[1]
    const dataLines = lines.slice(2)
    
    // 解析表头
    const headers = headerLine.split('|').map(h => h.trim()).filter(h => h)
    
    // 构建HTML表格
    let tableHtml = '<table><thead><tr>'
    headers.forEach(header => {
      tableHtml += `<th>${header}</th>`
    })
    tableHtml += '</tr></thead><tbody>'
    
    // 处理数据行
    dataLines.forEach(line => {
      if (line.trim()) {
        const cells = line.split('|').map(c => c.trim()).filter(c => c)
        tableHtml += '<tr>'
        cells.forEach(cell => {
          tableHtml += `<td>${cell}</td>`
        })
        tableHtml += '</tr>'
      }
    })
    
    tableHtml += '</tbody></table>'
    return tableHtml
  })
}

/**
 * HTML转义
 * @param {string} text - 需要转义的文本
 * @returns {string} 转义后的文本
 */
const escapeHtml = (text) => {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

/**
 * 下载HTML文件
 * @param {string} htmlContent - HTML内容
 * @param {string} filename - 文件名
 */
const downloadHTML = (htmlContent, filename) => {
  const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename || '对话记录'}.html`
  link.style.display = 'none'
  
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  
  URL.revokeObjectURL(url)
  
  console.log('✅ HTML文件下载完成:', link.download)
}