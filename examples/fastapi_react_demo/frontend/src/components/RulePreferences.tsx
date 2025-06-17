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
  Tooltip
} from 'antd';
import { 
  SettingOutlined, 
  PlusOutlined, 
  EditOutlined, 
  DeleteOutlined,
  InfoCircleOutlined
} from '@ant-design/icons';
import { useSystem, RulePreference } from '../context/SystemContext';

const { TextArea } = Input;
const { Text, Title } = Typography;

const RulePreferences: React.FC = () => {
  const { state, dispatch } = useSystem();
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingRule, setEditingRule] = useState<RulePreference | null>(null);

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

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <Card
        title={
          <Space>
            <SettingOutlined />
            规则偏好管理
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setIsModalVisible(true)}
          >
            添加规则
          </Button>
        }
      >
        <Alert
          message="规则偏好说明"
          description="规则偏好是您对AI助手行为的个性化配置，包括代码风格、响应语言、详细程度等。启用的规则会在每次对话时自动应用。"
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          style={{ marginBottom: 24 }}
        />

        {state.rulePreferences.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
            <SettingOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <div>暂无规则偏好</div>
            <div style={{ fontSize: 14, marginTop: 8 }}>
              点击"添加规则"开始配置您的个性化偏好
            </div>
          </div>
        ) : (
          <List
            dataSource={state.rulePreferences}
            renderItem={(rule) => (
              <List.Item
                key={rule.id}
                actions={[
                  <Tooltip title={rule.enabled ? '禁用' : '启用'}>
                    <Switch
                      checked={rule.enabled}
                      onChange={() => handleToggleRule(rule)}
                      size="small"
                    />
                  </Tooltip>,
                  <Tooltip title="编辑">
                    <Button
                      type="text"
                      icon={<EditOutlined />}
                      onClick={() => openEditModal(rule)}
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
                      />
                    </Tooltip>
                  </Popconfirm>
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Text strong style={{ color: rule.enabled ? '#1890ff' : '#999' }}>
                        {rule.name}
                      </Text>
                      {!rule.enabled && <Text type="secondary">(已禁用)</Text>}
                    </Space>
                  }
                  description={
                    <Text 
                      type="secondary" 
                      style={{ 
                        display: 'block',
                        maxWidth: '600px',
                        whiteSpace: 'pre-wrap',
                        opacity: rule.enabled ? 1 : 0.6
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
        )}

        {/* 添加规则模态框 */}
        <Modal
          title="添加规则偏好"
          open={isModalVisible}
          onCancel={() => {
            setIsModalVisible(false);
            form.resetFields();
          }}
          footer={null}
          width={600}
        >
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary">快速模板：</Text>
            <Space wrap style={{ marginTop: 8 }}>
              {ruleTemplates.map((template, index) => (
                <Button
                  key={index}
                  size="small"
                  onClick={() => insertTemplate(template)}
                >
                  {template.name}
                </Button>
              ))}
            </Space>
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
              <Input placeholder="为您的规则偏好起个名字" />
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
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
              <Space>
                <Button onClick={() => {
                  setIsModalVisible(false);
                  form.resetFields();
                }}>
                  取消
                </Button>
                <Button type="primary" htmlType="submit">
                  添加
                </Button>
              </Space>
            </Form.Item>
          </Form>
        </Modal>

        {/* 编辑规则模态框 */}
        <Modal
          title="编辑规则偏好"
          open={editModalVisible}
          onCancel={() => {
            setEditModalVisible(false);
            setEditingRule(null);
            editForm.resetFields();
          }}
          footer={null}
          width={600}
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
              <Input placeholder="为您的规则偏好起个名字" />
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
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
              <Space>
                <Button onClick={() => {
                  setEditModalVisible(false);
                  setEditingRule(null);
                  editForm.resetFields();
                }}>
                  取消
                </Button>
                <Button type="primary" htmlType="submit">
                  保存
                </Button>
              </Space>
            </Form.Item>
          </Form>
        </Modal>
      </Card>
    </div>
  );
};

export default RulePreferences; 