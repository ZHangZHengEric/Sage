import React, { useEffect, useState } from 'react';
import { Card, Typography, Tag, Button, Divider } from 'antd';
import { CloseOutlined, CheckCircleOutlined, ExclamationCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { ToolCallData } from '../types/toolCall';
import NewsSearchResults from './NewsSearchResults';
import FileWriteViewer from './FileWriteViewer';
import ExecuteViewer from './ExecuteViewer';

const { Title, Text, Paragraph } = Typography;

interface ToolDetailPanelProps {
  toolCall: ToolCallData | null;
  onClose: () => void;
}

const ToolDetailPanel: React.FC<ToolDetailPanelProps> = ({ toolCall, onClose }) => {
  // 添加状态来强制重新渲染
  const [refreshKey, setRefreshKey] = useState(0);
  
  // 监听toolCall变化，自动更新内容
  useEffect(() => {
    if (toolCall) {
      console.log('🔄 工具详情面板更新:', toolCall.toolName, toolCall.id);
      setRefreshKey(prev => prev + 1);
    }
  }, [toolCall]);

  if (!toolCall) {
    return null;
  }

  const getStatusIcon = () => {
    switch (toolCall.status) {
      case 'success':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'error':
        return <ExclamationCircleOutlined style={{ color: '#f5222d' }} />;
      case 'running':
        return <ClockCircleOutlined style={{ color: '#1890ff' }} />;
      default:
        return null;
    }
  };

  const getStatusColor = () => {
    switch (toolCall.status) {
      case 'success':
        return 'success';
      case 'error':
        return 'error';
      case 'running':
        return 'processing';
      default:
        return 'default';
    }
  };

  const formatDuration = (duration?: number) => {
    if (!duration) return '-';
    if (duration < 1000) {
      return `${Math.round(duration)}ms`;
    }
    return `${(duration / 1000).toFixed(2)}s`;
  };

  // 解析执行工具结果
  const parseExecuteResult = () => {
    if (!['execute_shell_command', 'execute_python_code'].includes(toolCall.toolName)) {
      return null;
    }

    try {
      const success = toolCall.status === 'success';
      return {
        toolName: toolCall.toolName,
        parameters: toolCall.parameters,
        result: toolCall.result,
        success,
        duration: toolCall.duration,
        timestamp: toolCall.timestamp
      };
    } catch (error) {
      console.error('解析执行工具结果失败:', error);
      return null;
    }
  };

  // 解析文件写入结果
  const parseFileWriteResult = () => {
    if (toolCall.toolName !== 'file_write') {
      return null;
    }

    try {
      const filePath = toolCall.parameters.file_path || toolCall.parameters.path || '未知文件';
      const content = toolCall.parameters.content || toolCall.parameters.data || '';
      const mode = toolCall.parameters.mode || 'overwrite';
      const encoding = toolCall.parameters.encoding || 'utf-8';
      
      // 检查执行结果
      let success = toolCall.status === 'success';
      if (toolCall.result) {
        if (typeof toolCall.result === 'string') {
          success = !toolCall.result.toLowerCase().includes('error') && !toolCall.result.toLowerCase().includes('failed');
        } else if (typeof toolCall.result === 'object') {
          success = toolCall.result.success !== false;
        }
      }

      return {
        filePath,
        content,
        mode,
        encoding,
        success
      };
    } catch (error) {
      console.error('解析文件写入结果失败:', error);
      return null;
    }
  };

  // 解析搜索结果（支持新闻搜索和网页搜索）
  const parseSearchResult = () => {
    if (!['search_news_articles', 'search_web_page'].includes(toolCall.toolName)) {
      return null;
    }

    console.log('🔍 解析搜索结果:', {
      toolName: toolCall.toolName,
      parameters: toolCall.parameters,
      result: toolCall.result,
      resultType: typeof toolCall.result,
      resultLength: Array.isArray(toolCall.result) ? toolCall.result.length : 'not array'
    });

    try {
      // 检查toolCall.result是否存在
      if (!toolCall.result) {
        console.warn('工具调用结果为空');
        return {
          query: toolCall.parameters.query || '搜索查询',
          count: 0,
          time_range: toolCall.parameters.time_range || 'recent',
          results: []
        };
      }

      let parsedResult = toolCall.result;
      
      // 如果result是字符串，尝试解析JSON
      if (typeof toolCall.result === 'string') {
        try {
          // 第一层解析
          const firstParse = JSON.parse(toolCall.result);
          console.log('🔍 第一层解析结果:', firstParse);
          
          // 检查是否有content字段需要进一步解析
          if (firstParse.content && typeof firstParse.content === 'string') {
            console.log('🔍 发现content字段，进行第二层解析');
            parsedResult = JSON.parse(firstParse.content);
          } else {
            parsedResult = firstParse;
          }
        } catch (parseError) {
          console.warn('JSON解析失败，使用原始字符串:', parseError);
          console.warn('原始数据:', toolCall.result);
          // 如果JSON解析失败，可能是纯文本结果，创建一个假的搜索条目
          parsedResult = {
            results: [{
              title: '搜索结果',
              url: '#',
              snippet: typeof toolCall.result === 'string' ? toolCall.result : '无法解析的结果',
              source: '系统',
              date: new Date().toISOString()
            }]
          };
        }
      }

      console.log('🔍 最终解析结果:', parsedResult);

      // 处理可能的raw包装
      if (parsedResult && parsedResult.raw && typeof parsedResult.raw === 'object') {
        console.log('🔍 检测到raw包装，解包数据');
        parsedResult = parsedResult.raw;
      }

      // 提取搜索数据
      let searchResults = [];
      if (parsedResult && parsedResult.results && Array.isArray(parsedResult.results)) {
        searchResults = parsedResult.results;
      } else if (Array.isArray(parsedResult)) {
        searchResults = parsedResult;
      } else {
        console.warn('结果格式不符合预期，使用空数组. parsedResult:', parsedResult);
        searchResults = [];
      }

      // 标准化搜索结果格式，确保兼容NewsSearchResults组件
      const normalizedResults = searchResults.map((item: any) => ({
        title: item.title || item.headline || '无标题',
        url: item.url || item.link || '#',
        snippet: item.snippet || item.description || item.summary || '无描述',
        source: item.source || item.domain || '未知来源',
        date: item.date || item.published_date || item.time || new Date().toISOString(),
        image: item.image || item.thumbnail || undefined
      }));

      const searchData = {
        query: toolCall.parameters.query || (parsedResult && parsedResult.query) || '搜索查询',
        count: toolCall.parameters.count || (parsedResult && parsedResult.total_results) || normalizedResults.length,
        time_range: toolCall.parameters.time_range || 'recent',
        results: normalizedResults
      };

      console.log('✅ 解析后的搜索数据:', searchData);
      return searchData;
    } catch (error) {
      console.error('❌ 解析搜索结果失败:', error);
      // 即使解析失败，也返回一个基本结构，避免显示原始数据
      return {
        query: toolCall.parameters.query || '搜索查询',
        count: 0,
        time_range: toolCall.parameters.time_range || 'recent',
        results: []
      };
    }
  };

  const searchData = parseSearchResult();
  const fileWriteData = parseFileWriteResult();
  const executeData = parseExecuteResult();

  // 获取面板标题
  const getPanelTitle = () => {
    if (searchData) {
      return toolCall.toolName === 'search_news_articles' ? '新闻搜索结果' : '网页搜索结果';
    }
    if (fileWriteData) {
      return '文件写入详情';
    }
    if (executeData) {
      return executeData.toolName === 'execute_shell_command' ? 'Shell 命令执行' : 'Python 代码执行';
    }
    return '工具详情';
  };

  return (
    <div 
      key={`tool-panel-${toolCall.id}-${refreshKey}`}
      style={{
        width: '100%',
        height: '100vh',
        background: '#ffffff',
        borderLeft: '1px solid #f0f0f0',
        boxShadow: '-2px 0 8px rgba(0, 0, 0, 0.1)',
        overflow: 'hidden',
        transition: 'all 0.3s ease'
      }}>
      {/* 头部 */}
      <div style={{
        padding: '16px',
        borderBottom: '1px solid #f0f0f0',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: '#fafafa'
      }}>
        <Title level={4} style={{ margin: 0, fontSize: '16px' }}>
          {getPanelTitle()}
        </Title>
        <Button 
          type="text" 
          icon={<CloseOutlined />} 
          onClick={onClose}
          size="small"
        />
      </div>

      {/* 内容 */}
      <div style={{ padding: (searchData || fileWriteData || executeData) ? '0' : '20px' }}>
        {/* 如果是搜索结果，使用专门的组件 */}
        {searchData ? (
          <NewsSearchResults 
            query={searchData.query}
            results={searchData.results}
            count={searchData.count}
            time_range={searchData.time_range}
          />
        ) : fileWriteData ? (
          /* 如果是文件写入，使用专门的组件 */
          <FileWriteViewer
            filePath={fileWriteData.filePath}
            content={fileWriteData.content}
            mode={fileWriteData.mode}
            encoding={fileWriteData.encoding}
            success={fileWriteData.success}
          />
        ) : executeData ? (
          /* 如果是执行工具，使用专门的组件 */
          <ExecuteViewer
            toolName={executeData.toolName}
            parameters={executeData.parameters}
            result={executeData.result}
            success={executeData.success}
            duration={executeData.duration}
            timestamp={executeData.timestamp}
          />
        ) : (
          <>
            {/* 工具基本信息 */}
            <Card size="small" style={{ marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px' }}>
                {getStatusIcon()}
                <Title level={5} style={{ margin: '0 0 0 8px', fontSize: '14px' }}>
                  {toolCall.toolName}
                </Title>
                <Tag color={getStatusColor()} style={{ marginLeft: 'auto' }}>
                  {toolCall.status}
                </Tag>
              </div>
              
              <div style={{ fontSize: '12px', color: '#666' }}>
                <div>执行时间: {formatDuration(toolCall.duration)}</div>
                <div>时间戳: {toolCall.timestamp.toLocaleString('zh-CN')}</div>
              </div>
            </Card>

            {/* 参数 */}
            <Card size="small" title="输入参数" style={{ marginBottom: '16px' }}>
              {Object.keys(toolCall.parameters).length > 0 ? (
                <div style={{ fontSize: '12px' }}>
                  {Object.entries(toolCall.parameters).map(([key, value]) => (
                    <div key={key} style={{ marginBottom: '8px' }}>
                      <Text strong>{key}:</Text>
                      <div style={{ 
                        background: '#f5f5f5', 
                        padding: '8px', 
                        borderRadius: '4px', 
                        marginTop: '4px',
                        wordBreak: 'break-all'
                      }}>
                        <Text code>{JSON.stringify(value, null, 2)}</Text>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <Text type="secondary">无参数</Text>
              )}
            </Card>

            {/* 结果 */}
            <Card size="small" title="执行结果" style={{ marginBottom: '16px' }}>
              {toolCall.result ? (
                <div style={{ 
                  background: '#f5f5f5', 
                  padding: '12px', 
                  borderRadius: '4px',
                  maxHeight: '300px',
                  overflow: 'auto'
                }}>
                  <Text code style={{ fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                    {typeof toolCall.result === 'string' 
                      ? toolCall.result 
                      : JSON.stringify(toolCall.result, null, 2)
                    }
                  </Text>
                </div>
              ) : (
                <Text type="secondary">无结果</Text>
              )}
            </Card>

            {/* 错误信息 */}
            {toolCall.error && (
              <Card size="small" title="错误信息" style={{ marginBottom: '16px' }}>
                <div style={{ 
                  background: '#fff2f0', 
                  padding: '12px', 
                  borderRadius: '4px',
                  border: '1px solid #ffccc7'
                }}>
                  <Text type="danger" style={{ fontSize: '12px' }}>
                    {toolCall.error}
                  </Text>
                </div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default ToolDetailPanel; 