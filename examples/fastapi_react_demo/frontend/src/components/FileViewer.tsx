import React, { useState, useEffect } from 'react';
import { Card, Button, Typography, Space, message, Spin } from 'antd';
import { 
  FileTextOutlined,
  DownloadOutlined,
  CopyOutlined,
  CloseOutlined,
  FileMarkdownOutlined,
  CodeOutlined
} from '@ant-design/icons';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import MarkdownWithMath from './MarkdownWithMath';

const { Text, Title } = Typography;

interface FileViewerProps {
  fileUrl: string;
  fileName: string;
  onClose: () => void;
}

interface FileContent {
  content: string;
  type: 'text' | 'markdown' | 'code';
  language?: string;
}

const FileViewer: React.FC<FileViewerProps> = ({
  fileUrl,
  fileName,
  onClose
}) => {
  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 获取文件扩展名
  const getFileExtension = (filename: string): string => {
    return filename.split('.').pop()?.toLowerCase() || '';
  };

  // 根据文件扩展名确定文件类型和语言
  const getFileType = (filename: string): { type: 'text' | 'markdown' | 'code'; language?: string } => {
    const ext = getFileExtension(filename);
    
    // Markdown文件
    if (ext === 'md' || ext === 'markdown') {
      return { type: 'markdown' };
    }
    
    // 代码文件
    const codeExtensions: { [key: string]: string } = {
      'py': 'python',
      'js': 'javascript',
      'ts': 'typescript',
      'jsx': 'javascript',
      'tsx': 'typescript',
      'html': 'html',
      'css': 'css',
      'scss': 'scss',
      'json': 'json',
      'xml': 'xml',
      'yaml': 'yaml',
      'yml': 'yaml',
      'sh': 'bash',
      'bash': 'bash',
      'sql': 'sql',
      'java': 'java',
      'cpp': 'cpp',
      'c': 'c',
      'go': 'go',
      'rs': 'rust',
      'php': 'php',
      'rb': 'ruby',
      'swift': 'swift',
      'kt': 'kotlin',
      'scala': 'scala'
    };
    
    if (codeExtensions[ext]) {
      return { type: 'code', language: codeExtensions[ext] };
    }
    
    // 默认为文本文件
    return { type: 'text' };
  };

  // 获取文件内容
  useEffect(() => {
    const fetchFileContent = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const proxyUrl = `/proxy-file?url=${encodeURIComponent(fileUrl)}`;
        const response = await fetch(proxyUrl);
        
        if (!response.ok) {
          // 尝试读取文本错误信息
          const errorText = await response.text();
          throw new Error(`代理请求失败 (状态码: ${response.status}): ${errorText}`);
        }
        
        const content = await response.text();
        const fileType = getFileType(fileName);
        
        setFileContent({
          content,
          type: fileType.type,
          language: fileType.language
        });
      } catch (err) {
        console.error('获取文件内容失败:', err);
        setError(err instanceof Error ? err.message : '获取文件内容失败');
      } finally {
        setLoading(false);
      }
    };

    fetchFileContent();
  }, [fileUrl, fileName]);

  // 复制内容到剪贴板
  const handleCopy = async () => {
    if (!fileContent) return;
    
    try {
      await navigator.clipboard.writeText(fileContent.content);
      message.success('文件内容已复制到剪贴板');
    } catch (error) {
      message.error('复制失败');
    }
  };

  // 下载文件
  const handleDownload = () => {
    if (!fileContent) return;
    
    const blob = new Blob([fileContent.content], { 
      type: fileContent.type === 'markdown' ? 'text/markdown' : 'text/plain;charset=utf-8' 
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    message.success('文件下载开始');
  };

  // 获取文件类型图标
  const getFileIcon = () => {
    if (fileContent?.type === 'markdown') {
      return <FileMarkdownOutlined style={{ color: '#1890ff' }} />;
    }
    if (fileContent?.type === 'code') {
      return <CodeOutlined style={{ color: '#722ed1' }} />;
    }
    return <FileTextOutlined style={{ color: '#52c41a' }} />;
  };

  // 渲染文件内容
  const renderFileContent = () => {
    if (!fileContent) return null;

    switch (fileContent.type) {
      case 'markdown':
        return (
          <div style={{ padding: '16px' }}>
            <MarkdownWithMath>
              {fileContent.content}
            </MarkdownWithMath>
          </div>
        );
      
      case 'code':
        return (
          <div style={{ padding: '16px' }}>
            <SyntaxHighlighter
              language={fileContent.language}
              style={tomorrow as any}
              customStyle={{
                margin: 0,
                borderRadius: '6px',
                fontSize: '13px',
                lineHeight: '1.4',
                maxHeight: 'none'
              }}
              showLineNumbers={fileContent.content.split('\n').length > 5}
            >
              {fileContent.content}
            </SyntaxHighlighter>
          </div>
        );
      
      default:
        return (
          <div style={{
            background: '#f5f5f5',
            padding: '16px',
            borderRadius: '6px',
            border: '1px solid #d9d9d9',
            fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace',
            fontSize: '13px',
            lineHeight: '1.4',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: 'none',
            overflow: 'auto'
          }}>
            {fileContent.content}
          </div>
        );
    }
  };

  return (
    <div style={{ 
      height: '100vh', 
      display: 'flex', 
      flexDirection: 'column',
      background: '#fff',
      borderLeft: '1px solid #f0f0f0'
    }}>
      {/* 头部 */}
      <Card 
        size="small" 
        style={{ 
          margin: '16px 16px 0 16px',
          borderBottom: '1px solid #f0f0f0'
        }}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0 }}>
            {getFileIcon()}
            <div style={{ marginLeft: '8px', flex: 1, minWidth: 0 }}>
              <Title level={5} style={{ margin: 0, fontSize: '14px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {fileName}
              </Title>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                {fileContent?.type === 'markdown' ? 'Markdown 文档' : 
                 fileContent?.type === 'code' ? `${fileContent.language} 代码` : '文本文件'}
              </Text>
            </div>
          </div>
          <Space>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={handleCopy}
              disabled={!fileContent}
            >
              复制
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={handleDownload}
              disabled={!fileContent}
            >
              下载
            </Button>
            <Button
              size="small"
              icon={<CloseOutlined />}
              onClick={onClose}
            >
              关闭
            </Button>
          </Space>
        </div>
      </Card>

      {/* 内容区域 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 16px 16px 16px' }}>
        {loading ? (
          <div style={{ 
            display: 'flex', 
            justifyContent: 'center', 
            alignItems: 'center', 
            height: '200px' 
          }}>
            <Spin size="large" />
            <Text style={{ marginLeft: '12px' }}>正在加载文件内容...</Text>
          </div>
        ) : error ? (
          <div style={{ 
            display: 'flex', 
            justifyContent: 'center', 
            alignItems: 'center', 
            height: '200px',
            flexDirection: 'column'
          }}>
            <Text type="danger" style={{ fontSize: '16px', marginBottom: '8px' }}>
              加载失败
            </Text>
            <Text type="secondary">{error}</Text>
          </div>
        ) : (
          renderFileContent()
        )}
      </div>
    </div>
  );
};

export default FileViewer; 