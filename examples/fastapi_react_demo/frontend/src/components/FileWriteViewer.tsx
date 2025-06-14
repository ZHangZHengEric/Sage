import React, { useState, useEffect } from 'react';
import { Card, Button, Switch, Input, Typography, Space, Divider, message } from 'antd';
import { 
  DownloadOutlined, 
  EditOutlined, 
  EyeOutlined, 
  CopyOutlined,
  FileTextOutlined,
  SaveOutlined,
  UndoOutlined
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';

const { TextArea } = Input;
const { Title, Text } = Typography;

interface FileWriteViewerProps {
  filePath: string;
  content: string;
  mode?: string;
  encoding?: string;
  success?: boolean;
}

const FileWriteViewer: React.FC<FileWriteViewerProps> = ({
  filePath,
  content: originalContent,
  mode = 'overwrite',
  encoding = 'utf-8',
  success = true
}) => {
  const [content, setContent] = useState(originalContent);
  const [isEditing, setIsEditing] = useState(false);
  const [renderMarkdown, setRenderMarkdown] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // 检测文件类型
  const getFileType = (path: string) => {
    const ext = path.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'md':
      case 'markdown':
        return 'markdown';
      case 'js':
      case 'jsx':
        return 'javascript';
      case 'ts':
      case 'tsx':
        return 'typescript';
      case 'py':
        return 'python';
      case 'json':
        return 'json';
      case 'html':
        return 'html';
      case 'css':
        return 'css';
      case 'xml':
        return 'xml';
      case 'yaml':
      case 'yml':
        return 'yaml';
      default:
        return 'text';
    }
  };

  const fileType = getFileType(filePath);
  const fileName = filePath.split('/').pop() || 'file';

  // 自动检测是否应该渲染Markdown
  useEffect(() => {
    if (fileType === 'markdown') {
      setRenderMarkdown(true);
    }
  }, [fileType]);

  // 监听内容变化
  useEffect(() => {
    setHasChanges(content !== originalContent);
  }, [content, originalContent]);

  // 复制内容到剪贴板
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      message.success('内容已复制到剪贴板');
    } catch (error) {
      message.error('复制失败');
    }
  };

  // 下载文件
  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
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

  // 重置内容
  const handleReset = () => {
    setContent(originalContent);
    setHasChanges(false);
    message.info('内容已重置');
  };

  // 渲染代码高亮
  const renderCodeHighlight = (content: string, language: string) => {
    return (
      <SyntaxHighlighter
        language={language}
        style={tomorrow as any}
        customStyle={{
          margin: 0,
          borderRadius: '6px',
          fontSize: '13px',
          lineHeight: '1.4'
        }}
        showLineNumbers={content.split('\n').length > 10}
      >
        {content}
      </SyntaxHighlighter>
    );
  };

  // 渲染内容预览
  const renderContent = () => {
    if (isEditing) {
      return (
        <TextArea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          autoSize={{ minRows: 10, maxRows: 30 }}
          style={{ 
            fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace',
            fontSize: '13px',
            lineHeight: '1.4'
          }}
        />
      );
    }

    if (renderMarkdown && fileType === 'markdown') {
      return (
        <div style={{ 
          padding: '16px',
          background: '#fafafa',
          borderRadius: '6px',
          border: '1px solid #f0f0f0'
        }}>
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      );
    }

    // 代码高亮显示
    if (['javascript', 'typescript', 'python', 'json', 'html', 'css', 'xml', 'yaml'].includes(fileType)) {
      return renderCodeHighlight(content, fileType);
    }

    // 纯文本显示
    return (
      <div style={{
        background: '#fafafa',
        padding: '16px',
        borderRadius: '6px',
        border: '1px solid #f0f0f0',
        fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace',
        fontSize: '13px',
        lineHeight: '1.4',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        maxHeight: '500px',
        overflow: 'auto'
      }}>
        {content}
      </div>
    );
  };

  return (
    <div style={{ padding: '20px' }}>
      {/* 文件信息头部 */}
      <Card size="small" style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <FileTextOutlined style={{ color: '#1890ff', marginRight: '8px' }} />
            <div>
              <Title level={5} style={{ margin: 0, fontSize: '14px' }}>
                {fileName}
              </Title>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                {filePath} • {mode} • {encoding} • {content.length} 字符
              </Text>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {success ? (
              <Text type="success" style={{ fontSize: '12px' }}>✅ 写入成功</Text>
            ) : (
              <Text type="danger" style={{ fontSize: '12px' }}>❌ 写入失败</Text>
            )}
          </div>
        </div>
      </Card>

      {/* 控制按钮 */}
      <Card size="small" style={{ marginBottom: '16px' }}>
        <Space wrap>
          <Button
            icon={isEditing ? <EyeOutlined /> : <EditOutlined />}
            onClick={() => setIsEditing(!isEditing)}
            type={isEditing ? "default" : "primary"}
            size="small"
          >
            {isEditing ? '预览' : '编辑'}
          </Button>
          
          <Button
            icon={<CopyOutlined />}
            onClick={handleCopy}
            size="small"
          >
            复制
          </Button>
          
          <Button
            icon={<DownloadOutlined />}
            onClick={handleDownload}
            size="small"
          >
            下载{hasChanges ? '(已修改)' : ''}
          </Button>

          {hasChanges && (
            <Button
              icon={<UndoOutlined />}
              onClick={handleReset}
              size="small"
              danger
            >
              重置
            </Button>
          )}

          <Divider type="vertical" />

          {fileType === 'markdown' && (
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <Text style={{ marginRight: '8px', fontSize: '12px' }}>Markdown渲染:</Text>
              <Switch
                size="small"
                checked={renderMarkdown}
                onChange={setRenderMarkdown}
                disabled={isEditing}
              />
            </div>
          )}
        </Space>
      </Card>

      {/* 内容显示区域 */}
      <Card 
        size="small" 
        title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '14px' }}>
              {isEditing ? '编辑内容' : (renderMarkdown ? 'Markdown预览' : '文件内容')}
            </span>
            {hasChanges && (
              <Text type="warning" style={{ fontSize: '12px' }}>
                • 内容已修改
              </Text>
            )}
          </div>
        }
      >
        {renderContent()}
      </Card>

      {/* 统计信息 */}
      <Card size="small" style={{ marginTop: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#666' }}>
          <span>行数: {content.split('\n').length}</span>
          <span>字符数: {content.length}</span>
          <span>字节数: {new Blob([content]).size}</span>
          <span>文件类型: {fileType}</span>
        </div>
      </Card>
    </div>
  );
};

export default FileWriteViewer; 