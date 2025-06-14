import React, { useState, useEffect } from 'react';
import { Card, Tag, Button, Space, Typography, Spin, Alert, Collapse, Input, Tooltip, Empty, Divider } from 'antd';
import { ToolOutlined, ReloadOutlined, SearchOutlined, ApiOutlined, RobotOutlined, FunctionOutlined, InfoCircleOutlined } from '@ant-design/icons';
import axios from 'axios';

const { Text, Title } = Typography;
const { Panel } = Collapse;
const { Search } = Input;

interface Tool {
  name: string;
  description: string;
  parameters: Record<string, any>;
  type: 'basic' | 'mcp' | 'agent'; // 工具类型（后端返回）
  source: string; // 工具来源（后端返回）
}

interface GroupedTools {
  basic: Tool[];
  mcp: Tool[];
  agent: Tool[];
}

const ToolsPanel: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/tools');
      // 直接使用后端返回的工具类型信息
      setTools(response.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '获取工具列表失败');
    } finally {
      setLoading(false);
    }
  };

  // 后端已经返回正确的工具类型和来源信息，无需前端推断

  // 过滤和分组工具
  const getFilteredAndGroupedTools = (): GroupedTools => {
    const filtered = tools.filter(tool => 
      tool.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      tool.description.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return {
      basic: filtered.filter(tool => tool.type === 'basic'),
      mcp: filtered.filter(tool => tool.type === 'mcp'),
      agent: filtered.filter(tool => tool.type === 'agent')
    };
  };

  // 获取工具类型图标和颜色
  const getToolTypeConfig = (type: 'basic' | 'mcp' | 'agent') => {
    switch (type) {
      case 'basic':
        return { icon: <FunctionOutlined />, color: '#52c41a', label: '基础工具' };
      case 'mcp':
        return { icon: <ApiOutlined />, color: '#1890ff', label: 'MCP工具' };
      case 'agent':
        return { icon: <RobotOutlined />, color: '#722ed1', label: '专业智能体' };
      default:
        return { icon: <ToolOutlined />, color: '#8c8c8c', label: '未知类型' };
    }
  };

  // 渲染工具项
  const renderToolItem = (tool: Tool) => {
    const typeConfig = getToolTypeConfig(tool.type);
    const paramCount = Object.keys(tool.parameters || {}).length;
    
    // 专业智能体使用更紧凑的显示样式
    const isAgent = tool.type === 'agent';
    const description = isAgent ? tool.description.split('\n')[0] : tool.description; // 只显示第一行
    
    return (
      <div 
        key={tool.name}
        style={{
          padding: isAgent ? '8px 16px' : '12px 16px', // 专业智能体减少padding
          background: '#ffffff',
          border: '1px solid #f0f0f0',
          borderRadius: '8px',
          marginBottom: '8px',
          transition: 'all 0.2s ease',
          cursor: 'pointer'
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.borderColor = '#1890ff';
          e.currentTarget.style.boxShadow = '0 2px 8px rgba(24, 144, 255, 0.1)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.borderColor = '#f0f0f0';
          e.currentTarget.style.boxShadow = 'none';
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: isAgent ? '4px' : '8px' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <span style={{ color: typeConfig.color, fontSize: '14px' }}>
                {typeConfig.icon}
              </span>
              <Text strong style={{ fontSize: '14px' }}>{tool.name}</Text>
              <Tag color={typeConfig.color}>
                {typeConfig.label}
              </Tag>
            </div>
            
            <Text 
              type="secondary" 
              style={{ 
                fontSize: '12px',
                display: 'block',
                lineHeight: isAgent ? '1.2' : '1.4', // 专业智能体使用更紧凑的行高
                marginBottom: isAgent ? '4px' : '6px'
              }}
            >
              {description}
            </Text>
            
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <Text type="secondary" style={{ fontSize: '11px' }}>
                来源: {tool.source}
              </Text>
              {paramCount > 0 && (
                                 <Tooltip title={`参数: ${Object.keys(tool.parameters).join(', ')}`}>
                   <Tag color="blue">
                     {paramCount} 个参数
                   </Tag>
                 </Tooltip>
              )}
            </div>
          </div>
          
          <Tag color="green">
            可用
          </Tag>
        </div>
      </div>
    );
  };

  // 渲染工具组
  const renderToolGroup = (tools: Tool[], type: 'basic' | 'mcp' | 'agent') => {
    if (tools.length === 0) return null;
    
    const typeConfig = getToolTypeConfig(type);
    
    return (
      <Panel 
        header={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ color: typeConfig.color, fontSize: '16px' }}>
              {typeConfig.icon}
            </span>
            <Text strong>{typeConfig.label}</Text>
                         <Tag color={typeConfig.color}>
               {tools.length} 个
             </Tag>
          </div>
        }
        key={type}
        style={{
          borderRadius: '8px',
          marginBottom: '8px'
        }}
      >
                 <div>
          {tools.map(renderToolItem)}
        </div>
      </Panel>
    );
  };

  useEffect(() => {
    fetchTools();
  }, []);

  const groupedTools = getFilteredAndGroupedTools();
  const totalTools = tools.length;
  const filteredCount = groupedTools.basic.length + groupedTools.mcp.length + groupedTools.agent.length;

      return (
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#f5f5f5' }}>
        {/* 标题栏 */}
        <Card 
          style={{ 
            borderRadius: '0',
            borderBottom: '1px solid #f0f0f0',
            flexShrink: 0,
            marginBottom: 0
          }}
          bodyStyle={{ padding: '16px 24px' }}
        >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <ToolOutlined style={{ fontSize: '20px', color: '#1890ff' }} />
            <Title level={4} style={{ margin: 0 }}>可用工具</Title>
            <Tag color="blue">{totalTools} 个工具</Tag>
          </div>
          
          <Button
            icon={<ReloadOutlined />}
            onClick={fetchTools}
            loading={loading}
            type="primary"
          >
            刷新
          </Button>
        </div>
        
        {/* 搜索栏 */}
        <div style={{ marginTop: '16px' }}>
          <Search
            placeholder="搜索工具名称或描述..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ maxWidth: '400px' }}
            prefix={<SearchOutlined />}
            allowClear
          />
          {searchTerm && (
            <Text type="secondary" style={{ marginLeft: '12px', fontSize: '12px' }}>
              找到 {filteredCount} 个匹配的工具
            </Text>
          )}
        </div>
      </Card>

              {/* 内容区域 */}
        <div style={{ 
          flex: 1, 
          overflow: 'hidden', 
          padding: '0',
          minHeight: 0,  // 确保flex子元素能正确收缩
          display: 'flex',
          flexDirection: 'column'
        }}>
          {error && (
            <div style={{ padding: '16px' }}>
              <Alert
                message="加载失败"
                description={error}
                type="error"
                showIcon
              />
            </div>
          )}

          <Spin spinning={loading} style={{ 
            flex: 1,
            width: '100%',
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column'
          }}>
            {totalTools === 0 && !loading ? (
              <div style={{ 
                height: '100%', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center' 
              }}>
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    <div>
                      <div>暂无可用工具</div>
                      <Text type="secondary" style={{ fontSize: '12px' }}>
                        请检查系统配置或工具注册
                      </Text>
                    </div>
                  }
                />
              </div>
            ) : (
              <div style={{ 
                height: 'calc(100vh - 114px)',  // 精确计算：总高度减去标题栏高度
                overflowY: 'auto',
                overflowX: 'hidden',
                padding: '16px 24px 24px 24px'
              }}
              className="custom-scrollbar main-tools-container"
              >
                <Collapse 
                  ghost
                  defaultActiveKey={['basic', 'mcp', 'agent']}  // 默认展开所有分组，便于查看
                  style={{
                    background: 'transparent'
                  }}
                  size="small"  // 使用小尺寸减少空间占用
                >
                  {renderToolGroup(groupedTools.basic, 'basic')}
                  {renderToolGroup(groupedTools.mcp, 'mcp')}
                  {renderToolGroup(groupedTools.agent, 'agent')}
                </Collapse>

                {searchTerm && filteredCount === 0 && (
                  <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        <div>
                          <div>没有找到匹配的工具</div>
                          <Text type="secondary" style={{ fontSize: '12px' }}>
                            尝试使用其他关键词搜索
                          </Text>
                        </div>
                      }
                    />
                  </div>
                )}
              </div>
            )}
          </Spin>
        </div>

      {/* 自定义滚动条样式 */}
      <style>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #d9d9d9;
          border-radius: 3px;
        }
        
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #bfbfbf;
        }
        
        .main-tools-container::-webkit-scrollbar {
          width: 4px;
        }
        
        .main-tools-container::-webkit-scrollbar-thumb {
          background: #d9d9d9;
          border-radius: 2px;
        }
        
        .main-tools-container::-webkit-scrollbar-thumb:hover {
          background: #bfbfbf;
        }
      `}</style>
    </div>
  );
};

export default ToolsPanel; 