import React, { useState } from 'react';
import { Card, Form, Input, Button, InputNumber, message, Space, Alert } from 'antd';
import { ApiOutlined, SettingOutlined } from '@ant-design/icons';
import { useSystem } from '../context/SystemContext';
import axios from 'axios';

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
      maxWidth: 1000, 
      margin: '0 auto',
      padding: '24px'
    }}>
      <Card
        title={
          <Space>
            <SettingOutlined />
            系统配置
          </Space>
        }
        style={{
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
          borderRadius: '12px'
        }}
      >
        <Alert
          message="配置说明"
          description="请配置您的API密钥和模型参数。配置成功后即可开始使用多智能体对话功能。"
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />

        <Form
          form={form}
          layout="vertical"
          initialValues={state.config}
          onFinish={handleSubmit}
          style={{ maxWidth: 600 }}
        >
          <Form.Item
            label="API 密钥"
            name="apiKey"
            rules={[{ required: true, message: '请输入API密钥' }]}
          >
            <Input.Password
              placeholder="请输入您的API密钥"
              prefix={<ApiOutlined />}
              size="large"
            />
          </Form.Item>

          <Form.Item
            label="模型名称"
            name="modelName"
            rules={[{ required: true, message: '请输入模型名称' }]}
          >
            <Input 
              placeholder="例如: deepseek-chat, gpt-4o" 
              size="large"
            />
          </Form.Item>

          <Form.Item
            label="API 基础URL"
            name="baseUrl"
            rules={[{ required: true, message: '请输入API基础URL' }]}
          >
            <Input 
              placeholder="例如: https://api.deepseek.com/v1" 
              size="large"
            />
          </Form.Item>

          <Form.Item
            label="最大Token数"
            name="maxTokens"
            rules={[{ required: true, message: '请输入最大Token数' }]}
          >
            <InputNumber
              min={1}
              max={8192}
              style={{ width: '100%' }}
              placeholder="4096"
              size="large"
            />
          </Form.Item>

          <Form.Item
            label="温度参数"
            name="temperature"
            rules={[{ required: true, message: '请输入温度参数' }]}
          >
            <InputNumber
              min={0}
              max={2}
              step={0.1}
              style={{ width: '100%' }}
              placeholder="0.7"
              size="large"
            />
          </Form.Item>

          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              size="large"
              block
              style={{
                height: '48px',
                fontSize: '16px',
                borderRadius: '8px'
              }}
            >
              保存配置
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default SystemConfig; 