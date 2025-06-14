import React, { useState } from 'react';
import { Card, Button, Typography, Space, Divider, Tag, Collapse, message } from 'antd';
import { 
  PlayCircleOutlined,
  CodeOutlined,
  ConsoleSqlOutlined,
  CopyOutlined,
  DownloadOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  InfoCircleOutlined
} from '@ant-design/icons';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';

const { Text, Title } = Typography;
const { Panel } = Collapse;

interface ExecuteViewerProps {
  toolName: string;
  parameters: Record<string, any>;
  result: any;
  success: boolean;
  duration?: number;
  timestamp: Date;
}

const ExecuteViewer: React.FC<ExecuteViewerProps> = ({
  toolName,
  parameters,
  result,
  success,
  duration,
  timestamp
}) => {
  const [activeKey, setActiveKey] = useState<string[]>(['output']);

  // 判断工具类型
  const isShellCommand = toolName === 'execute_shell_command';
  const isPythonCode = toolName === 'execute_python_code';

  // 获取执行内容
  const getExecuteContent = () => {
    if (isShellCommand) {
      return parameters.command || '';
    }
    if (isPythonCode) {
      return parameters.code || '';
    }
    return '';
  };

  // 获取工作目录
  const getWorkdir = () => {
    return parameters.workdir || (isPythonCode ? '临时目录' : '当前目录');
  };

  // 获取执行结果
  const getExecuteResult = () => {
    if (!result) return null;
    
    // 如果result是字符串，尝试解析
    let parsedResult = result;
    if (typeof result === 'string') {
      try {
        parsedResult = JSON.parse(result);
      } catch (e) {
        // 解析失败，使用原始字符串
        return { stdout: result, success: success };
      }
    }
    
    return parsedResult;
  };

  const executeResult = getExecuteResult();
  const executeContent = getExecuteContent();

  // 复制内容到剪贴板
  const handleCopy = async (content: string, type: string) => {
    try {
      await navigator.clipboard.writeText(content);
      message.success(`${type}已复制到剪贴板`);
    } catch (error) {
      message.error('复制失败');
    }
  };

  // 下载内容
  const handleDownload = (content: string, filename: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    message.success('文件下载开始');
  };

  // 获取状态图标和颜色
  const getStatusInfo = () => {
    if (executeResult?.success === false || !success) {
      return {
        icon: <ExclamationCircleOutlined style={{ color: '#f5222d' }} />,
        color: 'error',
        text: '执行失败'
      };
    }
    if (executeResult?.success === true || success) {
      return {
        icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
        color: 'success',
        text: '执行成功'
      };
    }
    return {
      icon: <ClockCircleOutlined style={{ color: '#1890ff' }} />,
      color: 'processing',
      text: '执行中'
    };
  };

  const statusInfo = getStatusInfo();

  // 格式化执行时间
  const formatDuration = (ms?: number) => {
    if (!ms) return '-';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  // 渲染代码高亮
  const renderCode = (code: string, language: string) => {
    return (
      <SyntaxHighlighter
        language={language}
        style={tomorrow as any}
        customStyle={{
          margin: 0,
          borderRadius: '6px',
          fontSize: '13px',
          lineHeight: '1.4',
          maxHeight: '400px',
          overflow: 'auto'
        }}
        showLineNumbers={code.split('\n').length > 5}
      >
        {code}
      </SyntaxHighlighter>
    );
  };

  // 渲染输出内容
  const renderOutput = (content: string, title: string, language: string = 'text') => {
    if (!content) return null;
    
    return (
      <div style={{ marginBottom: '16px' }}>
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: '8px'
        }}>
          <Text strong style={{ fontSize: '14px' }}>{title}</Text>
          <Space>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => handleCopy(content, title)}
            >
              复制
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(content, `${title.toLowerCase()}.txt`)}
            >
              下载
            </Button>
          </Space>
        </div>
        {language === 'text' ? (
          <div style={{
            background: '#f5f5f5',
            padding: '12px',
            borderRadius: '6px',
            border: '1px solid #d9d9d9',
            fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace',
            fontSize: '13px',
            lineHeight: '1.4',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: '300px',
            overflow: 'auto'
          }}>
            {content}
          </div>
        ) : (
          renderCode(content, language)
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: '20px' }}>
      {/* 执行信息头部 */}
      <Card size="small" style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {isShellCommand ? (
              <ConsoleSqlOutlined style={{ color: '#1890ff', marginRight: '8px', fontSize: '16px' }} />
            ) : (
              <CodeOutlined style={{ color: '#722ed1', marginRight: '8px', fontSize: '16px' }} />
            )}
            <div>
              <Title level={5} style={{ margin: 0, fontSize: '14px' }}>
                {isShellCommand ? 'Shell 命令执行' : 'Python 代码执行'}
              </Title>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                {getWorkdir()} • {timestamp.toLocaleString('zh-CN')}
              </Text>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              {statusInfo.icon}
              <Tag color={statusInfo.color} style={{ marginLeft: '4px' }}>
                {statusInfo.text}
              </Tag>
            </div>
            {duration && (
              <Text type="secondary" style={{ fontSize: '12px' }}>
                耗时: {formatDuration(duration)}
              </Text>
            )}
          </div>
        </div>
      </Card>

      {/* 执行内容 */}
      <Card size="small" style={{ marginBottom: '16px' }}>
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: '12px'
        }}>
          <Text strong style={{ fontSize: '14px' }}>
            {isShellCommand ? '执行命令' : '执行代码'}
          </Text>
          <Space>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => handleCopy(executeContent, isShellCommand ? '命令' : '代码')}
            >
              复制
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(
                executeContent, 
                isShellCommand ? 'command.sh' : 'code.py'
              )}
            >
              下载
            </Button>
          </Space>
        </div>
        {renderCode(executeContent, isShellCommand ? 'bash' : 'python')}
      </Card>

      {/* 执行结果 */}
      <Card size="small" style={{ marginBottom: '16px' }}>
        <Collapse 
          activeKey={activeKey} 
          onChange={(keys) => setActiveKey(keys as string[])}
          ghost
        >
          <Panel 
            header={
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <PlayCircleOutlined style={{ marginRight: '8px' }} />
                <Text strong>执行结果</Text>
                {executeResult?.return_code !== undefined && (
                  <Tag 
                    color={executeResult.return_code === 0 ? 'success' : 'error'}
                    style={{ marginLeft: '8px' }}
                  >
                    返回码: {executeResult.return_code}
                  </Tag>
                )}
              </div>
            } 
            key="output"
          >
            {executeResult ? (
              <div>
                {/* 标准输出 */}
                {executeResult.stdout && renderOutput(executeResult.stdout, '标准输出 (stdout)')}
                
                {/* 标准错误 */}
                {executeResult.stderr && renderOutput(executeResult.stderr, '标准错误 (stderr)')}
                
                {/* 错误信息 */}
                {executeResult.error && renderOutput(executeResult.error, '错误信息')}
                
                {/* 执行详情 */}
                <Divider style={{ margin: '16px 0' }} />
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
                  {executeResult.execution_time && (
                    <div>
                      <Text type="secondary" style={{ fontSize: '12px' }}>执行时间</Text>
                      <div>{formatDuration(executeResult.execution_time * 1000)}</div>
                    </div>
                  )}
                  {executeResult.process_id && (
                    <div>
                      <Text type="secondary" style={{ fontSize: '12px' }}>进程ID</Text>
                      <div style={{ fontFamily: 'monospace' }}>{executeResult.process_id}</div>
                    </div>
                  )}
                  {executeResult.pid && (
                    <div>
                      <Text type="secondary" style={{ fontSize: '12px' }}>系统PID</Text>
                      <div style={{ fontFamily: 'monospace' }}>{executeResult.pid}</div>
                    </div>
                  )}
                  {executeResult.timeout && (
                    <div>
                      <Text type="secondary" style={{ fontSize: '12px' }}>超时设置</Text>
                      <div>{executeResult.timeout}秒</div>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '20px', color: '#999' }}>
                <InfoCircleOutlined style={{ fontSize: '24px', marginBottom: '8px' }} />
                <div>暂无执行结果</div>
              </div>
            )}
          </Panel>
        </Collapse>
      </Card>

      {/* 参数详情 */}
      {Object.keys(parameters).length > 1 && (
        <Card size="small" title="执行参数">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            {Object.entries(parameters).map(([key, value]) => {
              if (key === 'command' || key === 'code') return null; // 已在上面显示
              return (
                <div key={key}>
                  <Text type="secondary" style={{ fontSize: '12px' }}>{key}</Text>
                  <div style={{ 
                    background: '#f5f5f5', 
                    padding: '4px 8px', 
                    borderRadius: '4px',
                    fontFamily: 'monospace',
                    fontSize: '12px',
                    wordBreak: 'break-all'
                  }}>
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
};

export default ExecuteViewer; 