import React, { useState } from 'react';
import { Form, Input, Button, InputNumber, message, Space, Alert, Typography, Row, Col, Divider, Tooltip } from 'antd';
import { ApiOutlined, SettingOutlined, InfoCircleOutlined, RocketOutlined, ThunderboltOutlined, CloudOutlined, KeyOutlined, DatabaseOutlined } from '@ant-design/icons';
import { useSystem } from '../context/SystemContext';
import axios from 'axios';

const { Title, Text, Paragraph } = Typography;

const SystemConfig: React.FC = () => {
  const { state, dispatch } = useSystem();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (values: any) => {
    setLoading(true);
    try {
      const configData = {
        api_key: values.apiKey,
        model_name: values.modelName,
        base_url: values.baseUrl,
        max_tokens: values.maxTokens,
        temperature: values.temperature
      };
      
      await axios.post('/api/configure', configData);
      
      dispatch({ type: 'SET_CONFIG', payload: values });
      message.success('配置更新成功！');
      
    } catch (error: any) {
      message.error(`配置失败: ${error.response?.data?.detail || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ 
      height: '100%',
      background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 50%, #f0f9ff 100%)',
      backdropFilter: 'blur(10px)',
      padding: '32px',
      overflow: 'auto'
    }}>
      {/* 页面头部 */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
          <div style={{
            width: '56px',
            height: '56px',
            borderRadius: '16px',
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginRight: 16,
            boxShadow: '0 8px 24px rgba(102, 126, 234, 0.3)'
          }}>
            <SettingOutlined style={{ fontSize: 24, color: '#fff' }} />
          </div>
          <div>
            <Title level={2} style={{ margin: 0, color: '#1e293b', fontWeight: 700 }}>
              系统配置
            </Title>
            <Text style={{ color: '#64748b', fontSize: 16 }}>
              配置AI模型参数，开启智能对话体验
            </Text>
          </div>
        </div>
        
        <Alert
          message={
            <Space>
              <RocketOutlined style={{ color: '#1890ff' }} />
              <Text strong style={{ color: '#1890ff' }}>配置说明</Text>
            </Space>
          }
          description={
            <div style={{ marginTop: 8 }}>
              <Paragraph style={{ margin: 0, color: '#64748b', lineHeight: 1.6 }}>
                请配置您的API密钥和模型参数。配置成功后即可开始使用多智能体对话功能。
                支持OpenAI、DeepSeek、Claude等主流AI模型。
              </Paragraph>
            </div>
          }
          type="info"
          showIcon={false}
          style={{
            background: 'rgba(255, 255, 255, 0.8)',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(24, 144, 255, 0.2)',
            borderRadius: '16px',
            padding: '20px'
          }}
        />
      </div>

      {/* 配置表单 */}
      <div style={{
        background: 'rgba(255, 255, 255, 0.9)',
        backdropFilter: 'blur(20px)',
        borderRadius: '24px',
        padding: '32px',
        border: '1px solid rgba(255, 255, 255, 0.2)',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1)'
      }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={state.config}
          onFinish={handleSubmit}
          size="large"
        >
          <Row gutter={[32, 24]}>
            {/* API 配置区域 */}
            <Col span={24}>
              <div style={{ marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
                  <KeyOutlined style={{ 
                    fontSize: 20, 
                    color: '#667eea',
                    marginRight: 12,
                    padding: '8px',
                    background: 'linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%)',
                    borderRadius: '8px'
                  }} />
                  <Title level={4} style={{ margin: 0, color: '#1e293b' }}>
                    API 认证配置
                  </Title>
                </div>
                <Text type="secondary" style={{ fontSize: 14 }}>
                  配置您的AI模型API访问凭证
                </Text>
              </div>
            </Col>

            <Col xs={24} lg={12}>
              <Form.Item
                label={
                  <Space>
                    <Text strong>API 密钥</Text>
                    <Tooltip title="您的AI模型API密钥，用于身份验证">
                      <InfoCircleOutlined style={{ color: '#64748b' }} />
                    </Tooltip>
                  </Space>
                }
                name="apiKey"
                rules={[{ required: true, message: '请输入API密钥' }]}
              >
                <Input.Password
                  placeholder="请输入您的API密钥"
                  prefix={<ApiOutlined style={{ color: '#667eea' }} />}
                  style={{
                    borderRadius: '12px',
                    height: '48px',
                    border: '2px solid #e2e8f0',
                    fontSize: '16px'
                  }}
                />
              </Form.Item>
            </Col>

            <Col xs={24} lg={12}>
              <Form.Item
                label={
                  <Space>
                    <Text strong>API 基础URL</Text>
                    <Tooltip title="AI模型API的基础访问地址">
                      <InfoCircleOutlined style={{ color: '#64748b' }} />
                    </Tooltip>
                  </Space>
                }
                name="baseUrl"
                rules={[{ required: true, message: '请输入API基础URL' }]}
              >
                <Input 
                  placeholder="例如: https://api.deepseek.com/v1"
                  prefix={<CloudOutlined style={{ color: '#667eea' }} />}
                  style={{
                    borderRadius: '12px',
                    height: '48px',
                    border: '2px solid #e2e8f0',
                    fontSize: '16px'
                  }}
                />
              </Form.Item>
            </Col>

            <Col span={24}>
              <Divider style={{ margin: '32px 0', borderColor: '#e2e8f0' }} />
            </Col>

            {/* 模型配置区域 */}
            <Col span={24}>
              <div style={{ marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
                  <DatabaseOutlined style={{ 
                    fontSize: 20, 
                    color: '#667eea',
                    marginRight: 12,
                    padding: '8px',
                    background: 'linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%)',
                    borderRadius: '8px'
                  }} />
                  <Title level={4} style={{ margin: 0, color: '#1e293b' }}>
                    模型参数配置
                  </Title>
                </div>
                <Text type="secondary" style={{ fontSize: 14 }}>
                  调整AI模型的行为和性能参数
                </Text>
              </div>
            </Col>

            <Col xs={24} lg={12}>
              <Form.Item
                label={
                  <Space>
                    <Text strong>模型名称</Text>
                    <Tooltip title="选择要使用的AI模型">
                      <InfoCircleOutlined style={{ color: '#64748b' }} />
                    </Tooltip>
                  </Space>
                }
                name="modelName"
                rules={[{ required: true, message: '请输入模型名称' }]}
              >
                <Input 
                  placeholder="例如: deepseek-chat, gpt-4o"
                  prefix={<RocketOutlined style={{ color: '#667eea' }} />}
                  style={{
                    borderRadius: '12px',
                    height: '48px',
                    border: '2px solid #e2e8f0',
                    fontSize: '16px'
                  }}
                />
              </Form.Item>
            </Col>

            <Col xs={24} lg={12}>
              <Form.Item
                label={
                  <Space>
                    <Text strong>最大Token数</Text>
                    <Tooltip title="单次对话的最大token限制，影响回复长度">
                      <InfoCircleOutlined style={{ color: '#64748b' }} />
                    </Tooltip>
                  </Space>
                }
                name="maxTokens"
                rules={[{ required: true, message: '请输入最大Token数' }]}
              >
                <InputNumber
                  min={1}
                  max={8192}
                  style={{ 
                    width: '100%',
                    borderRadius: '12px',
                    height: '48px',
                    border: '2px solid #e2e8f0',
                    fontSize: '16px'
                  }}
                  placeholder="4096"
                  prefix={<ThunderboltOutlined style={{ color: '#667eea' }} />}
                />
              </Form.Item>
            </Col>

            <Col xs={24} lg={12}>
              <Form.Item
                label={
                  <Space>
                    <Text strong>温度参数</Text>
                    <Tooltip title="控制AI回复的创造性，0-2之间，越高越有创意">
                      <InfoCircleOutlined style={{ color: '#64748b' }} />
                    </Tooltip>
                  </Space>
                }
                name="temperature"
                rules={[{ required: true, message: '请输入温度参数' }]}
              >
                <InputNumber
                  min={0}
                  max={2}
                  step={0.1}
                  style={{ 
                    width: '100%',
                    borderRadius: '12px',
                    height: '48px',
                    border: '2px solid #e2e8f0',
                    fontSize: '16px'
                  }}
                  placeholder="0.7"
                />
              </Form.Item>
            </Col>

            <Col span={24}>
              <Divider style={{ margin: '32px 0', borderColor: '#e2e8f0' }} />
            </Col>

            {/* 保存按钮 */}
            <Col span={24}>
              <div style={{ textAlign: 'center' }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  size="large"
                  style={{
                    height: '56px',
                    fontSize: '18px',
                    fontWeight: 600,
                    borderRadius: '16px',
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    border: 'none',
                    boxShadow: '0 8px 24px rgba(102, 126, 234, 0.3)',
                    paddingLeft: '48px',
                    paddingRight: '48px',
                    minWidth: '200px'
                  }}
                  icon={<SettingOutlined />}
                >
                  保存配置
                </Button>
              </div>
            </Col>
          </Row>
        </Form>
      </div>

      {/* 配置提示 */}
      <div style={{
        marginTop: 32,
        background: 'rgba(255, 255, 255, 0.7)',
        backdropFilter: 'blur(10px)',
        borderRadius: '16px',
        padding: '24px',
        border: '1px solid rgba(255, 255, 255, 0.2)'
      }}>
        <Title level={5} style={{ color: '#1e293b', marginBottom: 16 }}>
          💡 配置建议
        </Title>
        <Row gutter={[24, 16]}>
          <Col xs={24} md={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '12px',
                background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px',
                boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)'
              }}>
                <RocketOutlined style={{ fontSize: 20, color: '#fff' }} />
              </div>
              <Text strong style={{ display: 'block', marginBottom: 8, color: '#1e293b' }}>
                DeepSeek推荐
              </Text>
              <Text type="secondary" style={{ fontSize: 13, lineHeight: 1.5 }}>
                模型：deepseek-chat<br/>
                温度：0.7<br/>
                Token：4096
              </Text>
            </div>
          </Col>
          <Col xs={24} md={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '12px',
                background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px',
                boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)'
              }}>
                <ThunderboltOutlined style={{ fontSize: 20, color: '#fff' }} />
              </div>
              <Text strong style={{ display: 'block', marginBottom: 8, color: '#1e293b' }}>
                OpenAI推荐
              </Text>
              <Text type="secondary" style={{ fontSize: 13, lineHeight: 1.5 }}>
                模型：gpt-4o<br/>
                温度：0.8<br/>
                Token：8192
              </Text>
            </div>
          </Col>
          <Col xs={24} md={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: '12px',
                background: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px',
                boxShadow: '0 4px 12px rgba(139, 92, 246, 0.3)'
              }}>
                <CloudOutlined style={{ fontSize: 20, color: '#fff' }} />
              </div>
              <Text strong style={{ display: 'block', marginBottom: 8, color: '#1e293b' }}>
                Claude推荐
              </Text>
              <Text type="secondary" style={{ fontSize: 13, lineHeight: 1.5 }}>
                模型：claude-3-sonnet<br/>
                温度：0.6<br/>
                Token：4096
              </Text>
            </div>
          </Col>
        </Row>
      </div>
    </div>
  );
};

export default SystemConfig; 