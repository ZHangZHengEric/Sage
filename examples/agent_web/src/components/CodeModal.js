import React, { useState } from 'react';
import { X, Copy, Check } from 'lucide-react';
import './CodeModal.css';

const CodeModal = ({ isOpen, onClose, agent }) => {
  const [activeTab, setActiveTab] = useState('curl');
  const [copiedStates, setCopiedStates] = useState({});

  if (!isOpen || !agent) return null;

  // 获取后端URL，默认使用23232端口
  const backendUrl = 'http://localhost:23232';
  
  // 构建请求数据
  const requestData = {
    messages: [
      {
        role: "user",
        content: "你好，请帮我处理一个任务"
      }
    ],
    session_id: "demo-session",
    deep_thinking: agent.deepThinking,
    multi_agent: agent.multiAgent,
    max_loop_count: agent.maxLoopCount,
    system_prefix: agent.systemPrefix,
    system_context: agent.systemContext,
    available_workflows: agent.availableWorkflows,
    llm_model_config: agent.llmConfig,
    available_tools: agent.availableTools
  };

  const codeExamples = {
    curl: `curl -X POST "${backendUrl}/api/stream" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(requestData, null, 2)}'`,
    
    python: `import requests
import json

url = "${backendUrl}/api/stream"
headers = {
    "Content-Type": "application/json"
}

data = ${JSON.stringify(requestData, null, 2)}

response = requests.post(url, headers=headers, json=data, stream=True)

# 处理流式响应
for line in response.iter_lines():
    if line:
        try:
            result = json.loads(line.decode('utf-8'))
            print(f"收到消息: {result.get('type', 'unknown')}")
            if result.get('type') == 'message':
                print(f"内容: {result.get('content', '')}")
        except json.JSONDecodeError:
            print(f"解析失败: {line}")`,

    javascript: `const url = "${backendUrl}/api/stream";
const headers = {
    "Content-Type": "application/json"
};

const data = ${JSON.stringify(requestData, null, 2)};

async function streamChat() {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(data)
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\\n');

            for (const line of lines) {
                if (line.trim()) {
                    try {
                        const result = JSON.parse(line);
                        console.log('收到消息:', result.type);
                        if (result.type === 'message') {
                            console.log('内容:', result.content);
                        }
                    } catch (e) {
                        console.error('解析JSON失败:', e);
                    }
                }
            }
        }
    } catch (error) {
        console.error('请求失败:', error);
    }
}

streamChat();`,

    go: `package main

import (
    "bufio"
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
    "log"
)

type Message struct {
    Role    string \`json:"role"\`
    Content string \`json:"content"\`
}

type RequestData struct {
    Messages           []Message              \`json:"messages"\`
    SessionID          string                 \`json:"session_id"\`
    DeepThinking       bool                   \`json:"deep_thinking"\`
    MultiAgent         bool                   \`json:"multi_agent"\`
    MaxLoopCount       int                    \`json:"max_loop_count"\`
    SystemPrefix       string                 \`json:"system_prefix"\`
    SystemContext      map[string]interface{} \`json:"system_context"\`
    AvailableWorkflows map[string]interface{} \`json:"available_workflows"\`
    LlmModelConfig     map[string]interface{} \`json:"llm_model_config"\`
    AvailableTools     []string               \`json:"available_tools"\`
}

func main() {
    url := "${backendUrl}/api/stream"
    
    data := RequestData{
        Messages: []Message{
            {
                Role:    "user",
                Content: "你好，请帮我处理一个任务",
            },
        },
        SessionID:          "demo-session",
        DeepThinking:       ${agent.deepThinking},
        MultiAgent:         ${agent.multiAgent},
        MaxLoopCount:       ${agent.maxLoopCount},
        SystemPrefix:       \`${agent.systemPrefix}\`,
        SystemContext:      map[string]interface{}{},
        AvailableWorkflows: map[string]interface{}{},
        LlmModelConfig:     map[string]interface{}{},
        AvailableTools:     []string{${agent.availableTools.map(tool => `"${tool}"`).join(', ')}},
    }

    jsonData, err := json.Marshal(data)
    if err != nil {
        log.Fatal("JSON编码失败:", err)
    }

    resp, err := http.Post(url, "application/json", bytes.NewBuffer(jsonData))
    if err != nil {
        log.Fatal("请求失败:", err)
    }
    defer resp.Body.Close()

    scanner := bufio.NewScanner(resp.Body)
    for scanner.Scan() {
        line := scanner.Text()
        if line != "" {
            var result map[string]interface{}
            if err := json.Unmarshal([]byte(line), &result); err != nil {
                fmt.Printf("解析JSON失败: %v\\n", err)
                continue
            }
            
            fmt.Printf("收到消息: %v\\n", result["type"])
            if result["type"] == "message" {
                fmt.Printf("内容: %v\\n", result["content"])
            }
        }
    }

    if err := scanner.Err(); err != nil {
        log.Fatal("读取响应失败:", err)
    }
}`
  };

  const tabs = [
    { id: 'curl', label: 'cURL', language: 'bash' },
    { id: 'python', label: 'Python', language: 'python' },
    { id: 'javascript', label: 'JavaScript', language: 'javascript' },
    { id: 'go', label: 'Go', language: 'go' }
  ];

  const copyToClipboard = async (text, tabId) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedStates(prev => ({ ...prev, [tabId]: true }));
      setTimeout(() => {
        setCopiedStates(prev => ({ ...prev, [tabId]: false }));
      }, 2000);
    } catch (err) {
      console.error('复制失败:', err);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="code-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>代码示例 - {agent.name}</h3>
          <button className="close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        
        <div className="modal-content">
          <div className="tabs">
            {tabs.map(tab => (
              <button
                key={tab.id}
                className={`tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          
          <div className="code-container">
            <div className="code-header">
              <span className="code-language">{tabs.find(t => t.id === activeTab)?.language}</span>
              <button
                className="copy-btn"
                onClick={() => copyToClipboard(codeExamples[activeTab], activeTab)}
              >
                {copiedStates[activeTab] ? (
                  <>
                    <Check size={16} />
                    已复制
                  </>
                ) : (
                  <>
                    <Copy size={16} />
                    复制
                  </>
                )}
              </button>
            </div>
            <pre className="code-block">
              <code>{codeExamples[activeTab]}</code>
            </pre>
          </div>
          
          <div className="code-description">
            <h4>使用说明：</h4>
            <ul>
              <li>将代码复制到你的项目中</li>
              <li>确保后端服务运行在 {backendUrl}</li>
              <li>根据需要修改消息内容和会话ID</li>
              <li>该示例使用当前Agent的完整配置</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CodeModal;