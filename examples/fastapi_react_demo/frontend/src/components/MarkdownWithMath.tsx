import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import MathRenderer from './MathRenderer';
import { convertContainerPathsToAlistUrls } from '../utils/pathConverter';

interface MarkdownWithMathProps {
  children: string;
  className?: string;
  style?: React.CSSProperties;
  onFileClick?: (fileUrl: string, fileName: string) => void;
}

const MarkdownWithMath: React.FC<MarkdownWithMathProps> = ({ children, className, style, onFileClick }) => {
  const components: any = {
    code({ className, children, ...props }: { className?: string, children?: React.ReactNode }) {
      const match = /language-(\w+)/.exec(className || '');
      const isInline = !match;
      
      if (isInline) {
        return (
          <code 
            style={{
              background: '#f8fafc',
              color: '#475569',
              padding: '2px 6px',
              borderRadius: '4px',
              fontSize: '13px',
              fontFamily: 'SF Mono, Monaco, Consolas, monospace'
            }}
            {...props}
          >
            {children}
          </code>
        );
      }

      return (
        <SyntaxHighlighter
          style={tomorrow as any}
          language={match[1]}
          PreTag="div"
          customStyle={{
            background: '#1e293b',
            borderRadius: '8px',
            fontSize: '12px',
            margin: '8px 0'
          }}
          {...props}
        >
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      );
    },
    p: ({ children }: { children?: React.ReactNode }) => <p style={{ margin: '8px 0', lineHeight: '1.6' }}>{children}</p>,
    a: ({ node, ...props }: { node?: any, href?: string }) => {
      const href = props.href || '';
      // 检查是否是alist文件链接
      const isAlistFile = href.startsWith('http://36.133.44.114:20045/d/');
      
      if (isAlistFile && onFileClick) {
        // 提取文件名
        const fileName = href.split('/').pop() || 'unknown';
        
        return (
          <a
            {...props}
            onClick={(e) => {
              e.preventDefault();
              onFileClick(href, fileName);
            }}
            style={{
              color: '#1890ff',
              textDecoration: 'underline',
              cursor: 'pointer'
            }}
            title="点击在右侧分屏中查看文件内容"
          />
        );
      }
      
      // 普通链接
      return (
        <a
          {...props}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: '#1890ff',
            textDecoration: 'underline'
          }}
        />
      );
    }
  };

  // 解析数学公式的函数
  const parseMathContent = (text: string) => {
    // 转换容器路径为alist URL
    const convertedText = convertContainerPathsToAlistUrls(text);
    
    // 检查是否包含数学公式
    const hasMath = /\$.*\$/.test(convertedText);
    
    if (!hasMath) {
      // 如果没有数学公式，直接使用ReactMarkdown
      return (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={components}
        >
          {convertedText}
        </ReactMarkdown>
      );
    }

    // 如果有数学公式，使用复杂的解析逻辑
    const processText = (inputText: string): React.ReactNode[] => {
      const result: React.ReactNode[] = [];
      let remainingText = inputText;
      let currentKey = 0;

      const blockMathRegex = /\$\$([\s\S]*?)\$\$/;
      let blockMatch = remainingText.match(blockMathRegex);
      
      while (blockMatch) {
        const beforeMatch = remainingText.substring(0, blockMatch.index);
        const mathContent = blockMatch[1].trim();
        
        if (beforeMatch) {
          result.push(...processInlineText(beforeMatch, currentKey));
          currentKey += 10;
        }
        
        result.push(
          <MathRenderer 
            key={`block-math-${currentKey++}`} 
            displayMode={true}
          >
            {mathContent}
          </MathRenderer>
        );
        
        remainingText = remainingText.substring(blockMatch.index! + blockMatch[0].length);
        blockMatch = remainingText.match(blockMathRegex);
      }
      
      if (remainingText) {
        result.push(...processInlineText(remainingText, currentKey));
      }
      
      return result;
    };

    const processInlineText = (inputText: string, startKey: number): React.ReactNode[] => {
      const result: React.ReactNode[] = [];
      let remainingText = inputText;
      let currentKey = startKey;

      const inlineMathRegex = /\$([^$\n]+?)\$/;
      let inlineMatch = remainingText.match(inlineMathRegex);
      
      while (inlineMatch) {
        const beforeMatch = remainingText.substring(0, inlineMatch.index);
        const mathContent = inlineMatch[1].trim();
        
        if (beforeMatch) {
          result.push(
            <ReactMarkdown
              key={`text-${currentKey++}`}
              remarkPlugins={[remarkGfm]}
              components={components}
            >
              {beforeMatch}
            </ReactMarkdown>
          );
        }
        
        result.push(
          <MathRenderer 
            key={`inline-math-${currentKey++}`} 
            displayMode={false}
          >
            {mathContent}
          </MathRenderer>
        );
        
        remainingText = remainingText.substring(inlineMatch.index! + inlineMatch[0].length);
        inlineMatch = remainingText.match(inlineMathRegex);
      }
      
      if (remainingText) {
        result.push(
          <ReactMarkdown
            key={`text-${currentKey++}`}
            remarkPlugins={[remarkGfm]}
            components={components}
          >
            {remainingText}
          </ReactMarkdown>
        );
      }
      
      return result;
    };

    return <>{processText(convertedText)}</>;
  };

  return <div style={style} className={className}>{parseMathContent(children)}</div>;
};

export default MarkdownWithMath; 