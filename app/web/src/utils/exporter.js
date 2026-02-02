/**
 * HTML导出工具
 * 用于将对话记录导出为HTML文件，支持Markdown渲染、表格和ECharts图表
 */

import { getMessageLabel } from './messageLabels'
import { marked } from 'marked'

// 配置 marked
marked.setOptions({
  breaks: true, // 支持 GitHub 风格的换行
  gfm: true, // 启用 GitHub 风格 Markdown
})

/**
 * 导出对话记录为HTML文件
 * @param {Object} conversation - 对话记录对象
 * @param {Array} visibleMessages - 可见的消息列表
 */
export const exportToHTML = (conversation, visibleMessages) => {
  console.log('🚀 exportToHTML 函数开始执行')
  
  const htmlContent = generateHTMLContent(conversation, visibleMessages)
  downloadHTML(htmlContent, conversation.title)
}

/**
 * 下载HTML文件
 */
const downloadHTML = (content, filename) => {
  const blob = new Blob([content], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename || 'conversation'}_${new Date().toISOString().split('T')[0]}.html`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
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
  
  // 构建消息HTML
  let messagesHtml = ''
  
  visibleMessages.forEach((message) => {
    if (message.role === 'user') {
      const content = renderMarkdown(message.content || '')
      const label = getMessageLabel({
        role: message.role,
        type: message.type,
        messageType: message.message_type
      })
      
      messagesHtml += `
        <!-- 用户消息 -->
        <div class="flex flex-row-reverse items-start gap-3 px-4 group mb-6">
          <div class="flex-none mt-1">
             <div class="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border shadow-sm bg-background">
                <i data-lucide="user" class="h-4 w-4"></i>
             </div>
          </div>
          <div class="flex flex-col items-end max-w-[85%] sm:max-w-[75%]">
            <div class="mb-1 mr-1 text-xs font-medium text-muted-foreground select-none">
              ${escapeHtml(label)}
            </div>
            <div class="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-5 py-3.5 shadow-sm overflow-hidden break-words text-sm leading-relaxed tracking-wide message-content prose prose-invert max-w-none">
              ${content}
            </div>
          </div>
        </div>`
    } else if (message.role === 'assistant') {
      if (message.tool_calls && message.tool_calls.length > 0) {
        // 工具调用消息
        message.tool_calls.forEach(toolCall => {
          const toolName = toolCall.function?.name || '未知工具'
          const toolArgs = toolCall.function?.arguments || '{}'
          const label = getMessageLabel({
             role: message.role,
             type: message.type,
             messageType: message.message_type,
             toolName: toolName
          })
          
          messagesHtml += `
            <!-- 工具调用 -->
            <div class="flex flex-row items-start gap-3 px-4 mb-2">
              <div class="flex-none mt-1">
                <div class="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border shadow-sm bg-background">
                    <i data-lucide="wrench" class="h-4 w-4"></i>
                </div>
              </div>
              <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
                 <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground">
                    ${escapeHtml(label)}
                 </div>
                 <div class="bg-secondary/30 text-secondary-foreground border border-border/30 rounded-2xl rounded-tl-sm p-2 shadow-sm overflow-hidden break-words w-full sm:w-auto min-w-[260px]">
                  <div class="flex flex-col gap-2">
                    <div class="relative flex items-center justify-between p-2 rounded-xl bg-background border border-border/50">
                      <div class="absolute left-0 top-3 bottom-3 w-1 rounded-r-full bg-green-500/50"></div>
                      <div class="flex items-center gap-3 flex-1 min-w-0 pl-3">
                        <div class="flex flex-col min-w-0 gap-0.5">
                          <span class="font-medium text-sm truncate text-foreground/90">${escapeHtml(toolName)}</span>
                          <span class="text-[10px] text-muted-foreground truncate font-mono opacity-80 flex items-center gap-1">
                             <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                             已完成
                          </span>
                        </div>
                      </div>
                      <div class="flex items-center gap-2">
                         <div class="h-8 w-8 flex items-center justify-center text-muted-foreground rounded-full">
                            <i data-lucide="chevron-right" class="h-4 w-4"></i>
                         </div>
                      </div>
                    </div>
                    
                    <!-- 参数显示 -->
                    <div class="px-2 py-1">
                        <pre class="text-xs font-mono bg-muted/50 p-2 rounded overflow-x-auto text-foreground"><code>${escapeHtml(toolArgs)}</code></pre>
                    </div>

                  </div>
                 </div>
              </div>
            </div>`
        })
      } else if (message.show_content) {
        // AI助手回复
        const content = renderMarkdown(message.show_content)
        const label = getMessageLabel({
          role: message.role,
          type: message.type,
          messageType: message.message_type
        })
        
        messagesHtml += `
          <!-- 助手消息 -->
          <div class="flex flex-row items-start gap-3 px-4 mb-6">
            <div class="flex-none mt-1">
              <div class="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border shadow-sm bg-background">
                <i data-lucide="bot" class="h-4 w-4"></i>
              </div>
            </div>
            <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
              <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground flex items-center gap-2">
                ${escapeHtml(label)}
                <span class="text-[10px] opacity-60 font-normal">
                  ${message.timestamp ? new Date(message.timestamp).toLocaleTimeString() : ''}
                </span>
              </div>
              <div class="bg-card text-card-foreground border border-border/40 rounded-2xl rounded-tl-sm px-5 py-3.5 shadow-sm overflow-hidden break-words w-full message-content prose dark:prose-invert max-w-none">
                ${content}
              </div>
            </div>
          </div>`
      }
    } else if (message.role === 'tool') {
       // Tool Result 通常已经在 Assistant 的 Tool Calls 中或者紧接着显示，或者在 SharedChat 中可能不直接显示 Tool Result 详情
       // 为了简化，我们展示 Tool Result
       const toolName = message.name || '未知工具'
       const content = typeof message.content === 'object' 
        ? JSON.stringify(message.content, null, 2) 
        : (message.content || '')
        
       messagesHtml += `
        <!-- 工具结果 -->
        <div class="flex flex-row items-start gap-3 px-4 mb-6">
          <div class="flex-none mt-1">
             <div class="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border shadow-sm bg-background">
                <i data-lucide="clipboard-list" class="h-4 w-4"></i>
             </div>
          </div>
          <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
             <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground">
                工具执行结果
             </div>
             <div class="bg-muted/30 text-muted-foreground border border-border/20 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm overflow-hidden break-words w-full">
                <pre class="text-xs font-mono overflow-x-auto"><code>${escapeHtml(content)}</code></pre>
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
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com?plugins=typography"></script>
    
    <!-- Lucide Icons -->
    <script src="https://unpkg.com/lucide@latest"></script>
    
    <!-- ECharts -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>

    <!-- Highlight.js -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>

    <script>
      tailwind.config = {
        darkMode: 'class',
        theme: {
          extend: {
            colors: {
              border: "hsl(var(--border))",
              input: "hsl(var(--input))",
              ring: "hsl(var(--ring))",
              background: "hsl(var(--background))",
              foreground: "hsl(var(--foreground))",
              primary: {
                DEFAULT: "hsl(var(--primary))",
                foreground: "hsl(var(--primary-foreground))",
              },
              secondary: {
                DEFAULT: "hsl(var(--secondary))",
                foreground: "hsl(var(--secondary-foreground))",
              },
              destructive: {
                DEFAULT: "hsl(var(--destructive))",
                foreground: "hsl(var(--destructive-foreground))",
              },
              muted: {
                DEFAULT: "hsl(var(--muted))",
                foreground: "hsl(var(--muted-foreground))",
              },
              accent: {
                DEFAULT: "hsl(var(--accent))",
                foreground: "hsl(var(--accent-foreground))",
              },
              popover: {
                DEFAULT: "hsl(var(--popover))",
                foreground: "hsl(var(--popover-foreground))",
              },
              card: {
                DEFAULT: "hsl(var(--card))",
                foreground: "hsl(var(--card-foreground))",
              },
            },
            borderRadius: {
              lg: "var(--radius)",
              md: "calc(var(--radius) - 2px)",
              sm: "calc(var(--radius) - 4px)",
            },
          }
        }
      }
    </script>

    <style>
      :root {
        --background: 0 0% 100%;
        --foreground: 222.2 84% 4.9%;
        --card: 0 0% 100%;
        --card-foreground: 222.2 84% 4.9%;
        --popover: 0 0% 100%;
        --popover-foreground: 222.2 84% 4.9%;
        --primary: 222.2 47.4% 11.2%;
        --primary-foreground: 210 40% 98%;
        --secondary: 210 40% 96.1%;
        --secondary-foreground: 222.2 47.4% 11.2%;
        --muted: 210 40% 96.1%;
        --muted-foreground: 215.4 16.3% 46.9%;
        --accent: 210 40% 96.1%;
        --accent-foreground: 222.2 47.4% 11.2%;
        --destructive: 0 84.2% 60.2%;
        --destructive-foreground: 210 40% 98%;
        --border: 214.3 31.8% 91.4%;
        --input: 214.3 31.8% 91.4%;
        --ring: 222.2 84% 4.9%;
        --radius: 0.5rem;
      }
     
      .dark {
        --background: 222.2 84% 4.9%;
        --foreground: 210 40% 98%;
        --card: 222.2 84% 4.9%;
        --card-foreground: 210 40% 98%;
        --popover: 222.2 84% 4.9%;
        --popover-foreground: 210 40% 98%;
        --primary: 210 40% 98%;
        --primary-foreground: 222.2 47.4% 11.2%;
        --secondary: 217.2 32.6% 17.5%;
        --secondary-foreground: 210 40% 98%;
        --muted: 217.2 32.6% 17.5%;
        --muted-foreground: 215 20.2% 65.1%;
        --accent: 217.2 32.6% 17.5%;
        --accent-foreground: 210 40% 98%;
        --destructive: 0 62.8% 30.6%;
        --destructive-foreground: 210 40% 98%;
        --border: 217.2 32.6% 17.5%;
        --input: 217.2 32.6% 17.5%;
        --ring: 212.7 26.8% 83.9%;
      }
      
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      }
      
      /* Markdown Styles Override for Tailwind Typography */
      .prose pre {
        background-color: transparent;
        padding: 0;
        margin: 0;
      }
      
      .message-content p:first-child {
        margin-top: 0;
      }
      .message-content p:last-child {
        margin-bottom: 0;
      }
    </style>
</head>
<body class="bg-background text-foreground min-h-screen flex flex-col">
    <div class="h-screen w-full flex flex-col">
        <!-- Header -->
        <div class="border-b bg-card p-4 flex justify-between items-center shadow-sm z-10">
            <div>
                <h1 class="font-semibold text-lg">${escapeHtml(title)}</h1>
                <p class="text-xs text-muted-foreground">导出时间: ${exportTime} | 消息数量: ${visibleMessages.length}</p>
            </div>
            <div class="text-sm font-medium text-primary">
                Zavixai Agent
            </div>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-hidden relative bg-muted/5">
            <div class="h-full overflow-y-auto p-4 sm:p-6 scroll-smooth">
                <div class="pb-8 max-w-4xl mx-auto w-full">
                    ${messagesHtml}
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // 初始化图标
        lucide.createIcons();
        
        // 初始化代码高亮
        hljs.highlightAll();

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
 * 简单的Markdown渲染器 (配合 marked 库)
 * @param {string} text - Markdown文本
 * @returns {string} 渲染后的HTML
 */
const renderMarkdown = (text) => {
  if (!text) return ''
  
  // 使用 marked 渲染
  let html = marked.parse(text)
  
  // 处理ECharts代码块
  html = processEChartsBlocks(html)
  
  return html
}

/**
 * HTML转义
 */
const escapeHtml = (unsafe) => {
  if (typeof unsafe !== 'string') return ''
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * 处理ECharts代码块
 * @param {string} html - HTML内容
 * @returns {string} 处理后的HTML
 */
const processEChartsBlocks = (html) => {
  // 这里的正则可能需要适配 marked 渲染后的 HTML 结构
  // marked 渲染的代码块通常是 <pre><code class="language-echarts">...</code></pre>
  return html.replace(/<pre><code class="language-echarts">([\s\S]*?)<\/code><\/pre>/g, (match, code) => {
    try {
      // 解码HTML实体
      const decodedCode = code
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'") // marked 可能会转义单引号
        .replace(/&#x27;/g, "'")
      
      // 生成唯一ID
      const chartId = 'chart_' + Math.random().toString(36).substr(2, 9)
      
      return `
        <div class="echarts-container my-4 border rounded-lg p-2 bg-card" id="${chartId}" style="width: 100%; height: 400px;">
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
