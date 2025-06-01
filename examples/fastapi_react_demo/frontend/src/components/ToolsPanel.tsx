import React, { useState, useEffect } from 'react';
import { Card, List, Tag, Button, Space, Typography, Spin, Alert } from 'antd';
import { ToolOutlined, ReloadOutlined, InfoCircleOutlined } from '@ant-design/icons';
import axios from 'axios';

const { Text, Title } = Typography;

interface Tool {
  name: string;
  description: string;
  parameters: Record<string, any>;
}

const ToolsPanel: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/tools');
      setTools(response.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '获取工具列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  return (
    <div>
      <Card
        title={
          <Space>
            <ToolOutlined />
            <span>可用工具</span>
            <Tag color="blue">{tools.length} 个工具</Tag>
          </Space>
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={fetchTools}
            loading={loading}
          >
            刷新
          </Button>
        }
      >
        {error && (
          <Alert
            message="加载失败"
            description={error}
            type="error"
            style={{ marginBottom: 16 }}
          />
        )}

        <Spin spinning={loading}>
          {tools.length === 0 && !loading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
              <InfoCircleOutlined style={{ fontSize: '48px', marginBottom: '16px' }} />
              <div>暂无可用工具</div>
              <div>请检查系统配置或工具注册</div>
            </div>
          ) : (
            <List
              dataSource={tools}
              renderItem={(tool) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={<ToolOutlined style={{ fontSize: '20px', color: '#1890ff' }} />}
                    title={
                      <Space>
                        <Text strong>{tool.name}</Text>
                        <Tag color="green">可用</Tag>
                      </Space>
                    }
                    description={
                      <div>
                        <div style={{ marginBottom: 8 }}>
                          {tool.description}
                        </div>
                        {Object.keys(tool.parameters).length > 0 && (
                          <div>
                            <Text type="secondary" style={{ fontSize: '12px' }}>
                              参数: {Object.keys(tool.parameters).join(', ')}
                            </Text>
                          </div>
                        )}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Spin>
      </Card>
    </div>
  );
};

export default ToolsPanel; 