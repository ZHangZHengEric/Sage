import React, { useState } from 'react';
import { 
  Card, 
  Form, 
  Input, 
  Button, 
  List, 
  Switch, 
  Modal, 
  message, 
  Space, 
  Alert,
  Popconfirm,
  Typography,
  Tooltip,
  Tabs
} from 'antd';
import { 
  BulbOutlined, 
  PlusOutlined, 
  EditOutlined, 
  DeleteOutlined,
  InfoCircleOutlined,
  ForkOutlined,
  SettingOutlined
} from '@ant-design/icons';
import { useSystem, RulePreference } from '../context/SystemContext';
import WorkflowConfig from './WorkflowConfig';

const { TextArea } = Input;
const { Text, Title } = Typography;

const RulePreferences: React.FC = () => {
  const { state, dispatch } = useSystem();
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingRule, setEditingRule] = useState<RulePreference | null>(null);
  const [activeTab, setActiveTab] = useState('rules');

  // 添加新规则
  const handleAddRule = async (values: { name: string; content: string }) => {
    try {
      const newRule: RulePreference = {
        id: Date.now().toString(),
        name: values.name.trim(),
        content: values.content.trim(),
        enabled: true,
      };
      
      dispatch({ type: 'ADD_RULE_PREFERENCE', payload: newRule });
      form.resetFields();
      setIsModalVisible(false);
      message.success('规则偏好添加成功！');
    } catch (error) {
      message.error('添加规则偏好失败');
    }
  };

  // 编辑规则
  const handleEditRule = async (values: { name: string; content: string }) => {
    if (!editingRule) return;
    
    try {
      dispatch({
        type: 'UPDATE_RULE_PREFERENCE',
        payload: {
          id: editingRule.id,
          updates: {
            name: values.name.trim(),
            content: values.content.trim(),
          }
        }
      });
      
      editForm.resetFields();
      setEditModalVisible(false);
      setEditingRule(null);
      message.success('规则偏好更新成功！');
    } catch (error) {
      message.error('更新规则偏好失败');
    }
  };

  // 切换规则启用状态
  const handleToggleRule = (rule: RulePreference) => {
    dispatch({
      type: 'UPDATE_RULE_PREFERENCE',
      payload: {
        id: rule.id,
        updates: { enabled: !rule.enabled }
      }
    });
    message.success(`规则偏好已${!rule.enabled ? '启用' : '禁用'}`);
  };

  // 删除规则
  const handleDeleteRule = (ruleId: string) => {
    dispatch({ type: 'DELETE_RULE_PREFERENCE', payload: ruleId });
    message.success('规则偏好删除成功！');
  };

  // 打开编辑模态框
  const openEditModal = (rule: RulePreference) => {
    setEditingRule(rule);
    editForm.setFieldsValue({
      name: rule.name,
      content: rule.content,
    });
    setEditModalVisible(true);
  };

  // 预设规则模板
  const ruleTemplates = [
    {
      name: '代码风格偏好',
      content: '请使用简洁明了的代码风格，优先考虑可读性。变量命名使用camelCase，函数名清晰表达其功能。'
    },
    {
      name: '响应语言偏好',
      content: '请使用中文进行回复和解释，但代码注释可以使用英文。'
    },
    {
      name: '详细程度偏好',
      content: '提供详细的解释和示例，包括可能的替代方案和最佳实践建议。'
    }
  ];

  const insertTemplate = (template: { name: string; content: string }) => {
    form.setFieldsValue(template);
  };

  const tabItems = [
    {
      key: 'rules',
      label: (
        <Space>
          <BulbOutlined />
          规则偏好
        </Space>
      ),
      children: (
        <div style={{ padding: '24px 0' }}>
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center', 
            marginBottom: 24 
          }}>
            <div>
              <Title level={4} style={{ margin: 0, color: '#1890ff' }}>
                <BulbOutlined style={{ marginRight: 8 }} />
                规则偏好管理
              </Title>
              <Text type="secondary" style={{ fontSize: 14 }}>
                配置AI助手的个性化行为偏好
              </Text>
            </div>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setIsModalVisible(true)}
              size="large"
              style={{
                borderRadius: '8px',
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                border: 'none',
                boxShadow: '0 4px 12px rgba(102, 126, 234, 0.3)'
              }}
            >
              添加规则
            </Button>
          </div>

          <Alert
            message="规则偏好说明"
            description="规则偏好是您对AI助手行为的个性化配置，包括代码风格、响应语言、详细程度等。启用的规则会在每次对话时自动应用。"
            type="info"
            showIcon
            icon={<InfoCircleOutlined />}
            style={{ 
              marginBottom: 24,
              borderRadius: '12px',
              border: '1px solid #e6f7ff',
              background: 'linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%)'
            }}
          />

          {state.rulePreferences.length === 0 ? (
            <div style={{ 
              textAlign: 'center', 
              padding: '60px 0', 
              background: 'linear-gradient(135deg, #fafbfc 0%, #f5f7fa 100%)',
              borderRadius: '16px',
              border: '1px dashed #d9d9d9'
            }}>
              <BulbOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
              <div style={{ fontSize: 16, color: '#666', marginBottom: 8 }}>暂无规则偏好</div>
              <div style={{ fontSize: 14, color: '#999' }}>
                点击"添加规则"开始配置您的个性化偏好
              </div>
            </div>
          ) : (
            <div style={{ 
              background: '#fff',
              borderRadius: '16px',
              border: '1px solid #f0f0f0',
              overflow: 'hidden'
            }}>
              <List
                dataSource={state.rulePreferences}
                renderItem={(rule, index) => (
                  <List.Item
                    key={rule.id}
                    style={{
                      padding: '20px 24px',
                      borderBottom: index === state.rulePreferences.length - 1 ? 'none' : '1px solid #f5f5f5',
                      background: rule.enabled ? '#fff' : '#fafafa',
                      transition: 'all 0.3s ease'
                    }}
                    actions={[
                      <Tooltip title={rule.enabled ? '禁用' : '启用'}>
                        <Switch
                          checked={rule.enabled}
                          onChange={() => handleToggleRule(rule)}
                          style={{
                            background: rule.enabled ? '#52c41a' : '#d9d9d9'
                          }}
                        />
                      </Tooltip>,
                      <Tooltip title="编辑">
                        <Button
                          type="text"
                          icon={<EditOutlined />}
                          onClick={() => openEditModal(rule)}
                          style={{
                            color: '#1890ff',
                            borderRadius: '6px'
                          }}
                        />
                      </Tooltip>,
                      <Popconfirm
                        title="确认删除"
                        description="确定要删除这个规则偏好吗？"
                        onConfirm={() => handleDeleteRule(rule.id)}
                        okText="删除"
                        cancelText="取消"
                      >
                        <Tooltip title="删除">
                          <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            style={{
                              borderRadius: '6px'
                            }}
                          />
                        </Tooltip>
                      </Popconfirm>
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <Text strong style={{ 
                            color: rule.enabled ? '#1890ff' : '#999',
                            fontSize: 16
                          }}>
                            {rule.name}
                          </Text>
                          {!rule.enabled && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              (已禁用)
                            </Text>
                          )}
                        </Space>
                      }
                      description={
                        <Text 
                          type="secondary" 
                          style={{ 
                            display: 'block',
                            maxWidth: '600px',
                            whiteSpace: 'pre-wrap',
                            opacity: rule.enabled ? 1 : 0.6,
                            lineHeight: 1.6,
                            marginTop: 8
                          }}
                        >
                          {rule.content.length > 100 
                            ? `${rule.content.substring(0, 100)}...` 
                            : rule.content
                          }
                        </Text>
                      }
                    />
                  </List.Item>
                )}
              />
            </div>
          )}
        </div>
      )
    },
    {
      key: 'workflows',
      label: (
        <Space>
          <ForkOutlined />
          工作流配置
        </Space>
      ),
      children: <WorkflowConfig />
    }
  ];

  return (
    <div style={{ 
      height: '100%',
      background: 'linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)',
      minHeight: '100vh'
    }}>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        style={{ 
          height: '100%',
          padding: '0 24px'
        }}
        tabBarStyle={{
          background: 'rgba(255, 255, 255, 0.9)',
          backdropFilter: 'blur(10px)',
          borderRadius: '12px 12px 0 0',
          margin: '0 -24px 0 -24px',
          padding: '0 24px',
          borderBottom: '1px solid #f0f0f0'
        }}
      />

      {/* 添加规则模态框 */}
      <Modal
        title={
          <Space>
            <BulbOutlined style={{ color: '#1890ff' }} />
            <span style={{ color: '#1890ff', fontWeight: 600 }}>添加规则偏好</span>
          </Space>
        }
        open={isModalVisible}
        onCancel={() => {
          setIsModalVisible(false);
          form.resetFields();
        }}
        footer={null}
        width={700}
        style={{
          borderRadius: '16px'
        }}
      >
        <div style={{ marginBottom: 20 }}>
          <Text type="secondary">快速模板：</Text>
          <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {ruleTemplates.map((template, index) => (
              <Button
                key={index}
                size="small"
                onClick={() => insertTemplate(template)}
                style={{
                  borderRadius: '16px',
                  border: '1px solid #d9d9d9',
                  background: 'linear-gradient(135deg, #fff 0%, #f8f9fa 100%)'
                }}
              >
                {template.name}
              </Button>
            ))}
          </div>
        </div>
        
        <Form
          form={form}
          layout="vertical"
          onFinish={handleAddRule}
        >
          <Form.Item
            label="规则名称"
            name="name"
            rules={[
              { required: true, message: '请输入规则名称' },
              { max: 50, message: '规则名称不能超过50个字符' }
            ]}
          >
            <Input 
              placeholder="为您的规则偏好起个名字" 
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>

          <Form.Item
            label="规则内容"
            name="content"
            rules={[
              { required: true, message: '请输入规则内容' },
              { max: 1000, message: '规则内容不能超过1000个字符' }
            ]}
          >
            <TextArea
              rows={6}
              placeholder="详细描述您的偏好和要求，例如：代码风格、响应语言、详细程度等"
              showCount
              maxLength={1000}
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button 
                onClick={() => {
                  setIsModalVisible(false);
                  form.resetFields();
                }}
                style={{ borderRadius: '8px' }}
              >
                取消
              </Button>
              <Button 
                type="primary" 
                htmlType="submit"
                style={{
                  borderRadius: '8px',
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  border: 'none'
                }}
              >
                添加
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑规则模态框 */}
      <Modal
        title={
          <Space>
            <EditOutlined style={{ color: '#1890ff' }} />
            <span style={{ color: '#1890ff', fontWeight: 600 }}>编辑规则偏好</span>
          </Space>
        }
        open={editModalVisible}
        onCancel={() => {
          setEditModalVisible(false);
          setEditingRule(null);
          editForm.resetFields();
        }}
        footer={null}
        width={700}
        style={{
          borderRadius: '16px'
        }}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={handleEditRule}
        >
          <Form.Item
            label="规则名称"
            name="name"
            rules={[
              { required: true, message: '请输入规则名称' },
              { max: 50, message: '规则名称不能超过50个字符' }
            ]}
          >
            <Input 
              placeholder="为您的规则偏好起个名字" 
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>

          <Form.Item
            label="规则内容"
            name="content"
            rules={[
              { required: true, message: '请输入规则内容' },
              { max: 1000, message: '规则内容不能超过1000个字符' }
            ]}
          >
            <TextArea
              rows={6}
              placeholder="详细描述您的偏好和要求"
              showCount
              maxLength={1000}
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button 
                onClick={() => {
                  setEditModalVisible(false);
                  setEditingRule(null);
                  editForm.resetFields();
                }}
                style={{ borderRadius: '8px' }}
              >
                取消
              </Button>
              <Button 
                type="primary" 
                htmlType="submit"
                style={{
                  borderRadius: '8px',
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  border: 'none'
                }}
              >
                保存
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default RulePreferences; 