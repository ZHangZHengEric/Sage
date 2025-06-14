import React from 'react';
import { Layout, Button, Space, Typography, Switch } from 'antd';
import { 
  MenuFoldOutlined, 
  MenuUnfoldOutlined,
  SunOutlined,
  MoonOutlined
} from '@ant-design/icons';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

interface HeaderProps {
  darkMode: boolean;
  setDarkMode: (dark: boolean) => void;
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

const Header: React.FC<HeaderProps> = ({ 
  darkMode, 
  setDarkMode, 
  collapsed, 
  setCollapsed 
}) => {
  return (
    <AntHeader
      style={{
        padding: '0 24px',
        background: '#ffffff',
        borderBottom: '1px solid #f0f0f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: '60px'
      }}
    >
      <Space align="center">
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={() => setCollapsed(!collapsed)}
          style={{
            fontSize: '16px',
            width: 40,
            height: 40,
            color: '#666666',
            borderRadius: '8px'
          }}
        />
        <Text style={{ 
          fontSize: '16px', 
          fontWeight: 500, 
          color: '#1f2937',
          marginLeft: '8px'
        }}>
          🧠 Zavix
        </Text>
      </Space>
      
      <Space align="center">
        <Switch
          checked={darkMode}
          onChange={setDarkMode}
          checkedChildren={<MoonOutlined />}
          unCheckedChildren={<SunOutlined />}
          style={{
            background: darkMode ? '#1890ff' : '#f5f5f5'
          }}
        />
      </Space>
    </AntHeader>
  );
};

export default Header; 