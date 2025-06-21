import React from 'react';
import { RobotOutlined, ThunderboltOutlined, BranchesOutlined } from '@ant-design/icons';
import MarkdownWithMath from './MarkdownWithMath';

interface WelcomeScreenProps {
  onExampleClick: (example: string) => void;
}

const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ onExampleClick }) => {
  const examples = [
    {
      title: "数学公式",
      example: "解释二次公式：$$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$",
      icon: "📊"
    },
    {
      title: "代码编程", 
      example: "用 Python 写一个快速排序算法",
      icon: "💻"
    },
    {
      title: "文档写作",
      example: "帮我写一份项目总结报告的大纲",
      icon: "📝"
    },
    {
      title: "数据分析",
      example: "分析这组销售数据的趋势和特点，计算平均值：$\\bar{x} = \\frac{1}{n}\\sum_{i=1}^{n} x_i$",
      icon: "🔢"
    }
  ];

  return (
    <div style={{ 
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      textAlign: 'center',
      color: '#6b7280',
      padding: '60px 20px',
      minHeight: '400px'
    }}>
      <div style={{
        width: '64px',
        height: '64px',
        borderRadius: '16px',
        background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: '20px',
        boxShadow: '0 4px 12px rgba(99, 102, 241, 0.2)'
      }}>
        <RobotOutlined style={{ fontSize: '28px', color: '#ffffff' }} />
      </div>
      
      <div style={{ fontSize: '18px', fontWeight: 600, marginBottom: '8px', color: '#1f2937' }}>
        您好，我是 Zavix 助手
      </div>
      <div style={{ fontSize: '13px', marginBottom: '12px', color: '#6b7280', fontStyle: 'italic' }}>
        <span style={{ fontWeight: 'bold', color: '#6366f1' }}>Z</span>enith <span style={{ fontWeight: 'bold', color: '#8b5cf6' }}>A</span>I <span style={{ fontWeight: 'bold', color: '#a855f7' }}>V</span>irtual <span style={{ fontWeight: 'bold', color: '#c084fc' }}>I</span>ntelligence e<span style={{ fontWeight: 'bold', color: '#d8b4fe' }}>X</span>pert
      </div>
      <div style={{ fontSize: '14px', lineHeight: '1.5', marginBottom: '24px', maxWidth: '320px' }}>
        我是您的多智能体协作助手，可以运用深度思考为您解决各种复杂问题。
      </div>
      
      {/* 功能特色 */}
      <div style={{ 
        display: 'flex', 
        gap: '12px',
        flexWrap: 'wrap',
        justifyContent: 'center',
        marginBottom: '32px'
      }}>
        <div style={{
          padding: '12px 16px',
          background: '#ffffff',
          borderRadius: '8px',
          border: '1px solid #f1f5f9',
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <ThunderboltOutlined style={{ fontSize: '16px', color: '#f59e0b' }} />
          <span style={{ fontSize: '13px', fontWeight: 500, color: '#374151' }}>
            深度思考
          </span>
        </div>
        
        <div style={{
          padding: '12px 16px',
          background: '#ffffff',
          borderRadius: '8px',
          border: '1px solid #f1f5f9',
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <BranchesOutlined style={{ fontSize: '16px', color: '#10b981' }} />
          <span style={{ fontSize: '13px', fontWeight: 500, color: '#374151' }}>
            多智能体协作
          </span>
        </div>
      </div>

      {/* 使用示例 */}
      <div style={{ 
        width: '100%',
        maxWidth: '600px'
      }}>
        <div style={{ 
          fontSize: '16px', 
          fontWeight: 600, 
          color: '#1f2937', 
          marginBottom: '16px' 
        }}>
          试试这些示例
        </div>
        
        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', 
          gap: '12px'
        }}>
          {examples.map((item, index) => (
            <div
              key={index}
              style={{
                padding: '16px',
                background: '#ffffff',
                borderRadius: '12px',
                border: '1px solid #f1f5f9',
                boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                textAlign: 'left'
              }}
              onClick={() => onExampleClick(item.example)}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#e0e7ff';
                e.currentTarget.style.boxShadow = '0 4px 12px rgba(99, 102, 241, 0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#f1f5f9';
                e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.05)';
              }}
            >
              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: '8px', 
                marginBottom: '8px' 
              }}>
                <span style={{ fontSize: '18px' }}>{item.icon}</span>
                <span style={{ 
                  fontSize: '14px', 
                  fontWeight: 600, 
                  color: '#1f2937' 
                }}>
                  {item.title}
                </span>
              </div>
              <div style={{ 
                fontSize: '13px', 
                color: '#6b7280', 
                lineHeight: '1.4' 
              }}>
                <MarkdownWithMath>
                  {item.example}
                </MarkdownWithMath>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default WelcomeScreen; 