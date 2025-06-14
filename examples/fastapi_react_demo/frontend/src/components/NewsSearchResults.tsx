import React from 'react';
import { Card, Typography, Tag, Button, Divider, Space } from 'antd';
import { LinkOutlined, CalendarOutlined, GlobalOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

interface NewsArticle {
  title?: string;
  url?: string;
  description?: string;
  source?: string;
  published_date?: string;
  author?: string;
  // 支持更多可能的字段名
  headline?: string;
  link?: string;
  content?: string;
  summary?: string;
  snippet?: string;
  date?: string;
  publish_date?: string;
  publisher?: string;
}

interface NewsSearchResultsProps {
  query: string;
  results: NewsArticle[];
  count?: number;
  time_range?: string;
}

const NewsSearchResults: React.FC<NewsSearchResultsProps> = ({ 
  query, 
  results, 
  count, 
  time_range 
}) => {
  console.log('📰 NewsSearchResults 接收到的数据:', {
    query,
    results,
    count,
    time_range,
    resultsLength: results?.length
  });
  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
    } catch {
      return dateStr;
    }
  };

  const extractDomain = (url?: string) => {
    if (!url) return '';
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return url;
    }
  };

  // 标准化新闻数据，处理不同的字段名
  const normalizeArticle = (article: NewsArticle | null | undefined) => {
    if (!article || typeof article !== 'object') {
      return {
        title: '无标题',
        url: '#',
        description: '',
        source: '',
        published_date: '',
        author: ''
      };
    }
    
    return {
      title: article.title || article.headline || '无标题',
      url: article.url || article.link || '#',
      description: article.description || article.snippet || article.content || article.summary || '',
      source: article.source || article.publisher || '',
      published_date: article.published_date || article.date || article.publish_date || '',
      author: article.author || ''
    };
  };

  return (
    <div style={{ padding: '20px', background: '#fff' }}>
      {/* 搜索信息头部 */}
      <div style={{ marginBottom: '24px', paddingBottom: '16px', borderBottom: '1px solid #f0f0f0' }}>
        <Title level={4} style={{ margin: 0, color: '#1890ff', fontSize: '18px' }}>
          新闻搜索结果
        </Title>
        <div style={{ marginTop: '8px', fontSize: '14px', color: '#666' }}>
          <Space size="middle">
            <span>搜索词: <Text strong>"{query}"</Text></span>
            {count && <span>找到 <Text strong>{count}</Text> 条结果</span>}
            {time_range && <span>时间范围: <Text strong>{time_range}</Text></span>}
          </Space>
        </div>
      </div>

      {/* 搜索结果列表 */}
      <div style={{ maxHeight: '600px', overflow: 'auto' }}>
        {results.length > 0 ? (
          results
            .filter(article => article != null) // 过滤掉null和undefined
            .map((article, index) => {
            const normalizedArticle = normalizeArticle(article);
            return (
            <div 
              key={index} 
              style={{ 
                marginBottom: '20px',
                padding: '16px',
                border: '1px solid #f0f0f0',
                borderRadius: '8px',
                background: '#fafafa',
                transition: 'all 0.2s ease'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#f5f5f5';
                e.currentTarget.style.borderColor = '#d9d9d9';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#fafafa';
                e.currentTarget.style.borderColor = '#f0f0f0';
              }}
            >
              {/* 标题和链接 */}
              <div style={{ marginBottom: '8px' }}>
                <Title 
                  level={5} 
                  style={{ 
                    margin: 0, 
                    fontSize: '16px',
                    color: '#1890ff',
                    cursor: 'pointer',
                    lineHeight: '1.4'
                  }}
                  onClick={() => window.open(normalizedArticle.url, '_blank')}
                >
                  <LinkOutlined style={{ marginRight: '6px', fontSize: '14px' }} />
                  {normalizedArticle.title}
                </Title>
              </div>

              {/* 来源和日期 */}
              <div style={{ marginBottom: '8px' }}>
                <Space size="small">
                  {normalizedArticle.source && (
                    <Tag icon={<GlobalOutlined />} color="blue" style={{ fontSize: '12px' }}>
                      {normalizedArticle.source}
                    </Tag>
                  )}
                  {normalizedArticle.published_date && (
                    <Tag icon={<CalendarOutlined />} color="green" style={{ fontSize: '12px' }}>
                      {formatDate(normalizedArticle.published_date)}
                    </Tag>
                  )}
                  {normalizedArticle.author && (
                    <Tag color="orange" style={{ fontSize: '12px' }}>
                      {normalizedArticle.author}
                    </Tag>
                  )}
                </Space>
              </div>

              {/* URL显示 */}
              <div style={{ marginBottom: '8px' }}>
                <Text 
                  type="secondary" 
                  style={{ 
                    fontSize: '12px',
                    wordBreak: 'break-all'
                  }}
                >
                  {extractDomain(normalizedArticle.url)} • {normalizedArticle.url}
                </Text>
              </div>

              {/* 描述/摘要 */}
              {normalizedArticle.description && (
                <Paragraph 
                  style={{ 
                    margin: 0,
                    fontSize: '14px',
                    lineHeight: '1.6',
                    color: '#333'
                  }}
                  ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                >
                  {normalizedArticle.description}
                </Paragraph>
              )}

              {/* 操作按钮 */}
              <div style={{ marginTop: '12px', textAlign: 'right' }}>
                <Button 
                  type="link" 
                  size="small"
                  icon={<LinkOutlined />}
                  onClick={() => window.open(normalizedArticle.url, '_blank')}
                  style={{ padding: '0 8px', fontSize: '12px' }}
                >
                  访问原文
                </Button>
              </div>
            </div>
            );
          })
        ) : (
          <div style={{ 
            textAlign: 'center', 
            padding: '40px',
            color: '#999'
          }}>
            <div style={{ marginBottom: '16px', fontSize: '48px' }}>📰</div>
            <Text type="secondary" style={{ fontSize: '16px' }}>
              未找到相关新闻
            </Text>
            <div style={{ marginTop: '8px' }}>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                搜索词: "{query}" | 时间范围: {time_range || 'recent'}
              </Text>
            </div>
          </div>
        )}
      </div>

      {/* 底部统计 */}
      {results.length > 0 && (
        <div style={{ 
          marginTop: '20px', 
          paddingTop: '16px', 
          borderTop: '1px solid #f0f0f0',
          textAlign: 'center'
        }}>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            共显示 {results.length} 条新闻结果
          </Text>
        </div>
      )}
    </div>
  );
};

export default NewsSearchResults; 