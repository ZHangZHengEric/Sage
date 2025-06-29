import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import MathRenderer from './MathRenderer';

interface MarkdownWithMathProps {
  children: string;
  className?: string;
  style?: React.CSSProperties;
}

const MarkdownWithMath: React.FC<MarkdownWithMathProps> = ({ children, className, style }) => {
  // 解析数学公式的函数
  const parseMathContent = (text: string) => {
    const parts: React.ReactNode[] = [];
    let key = 0;

    // 简单的数学公式解析策略
    // 1. 先处理块级公式 $$...$$
    // 2. 然后处理行内公式 $...$
    
    const processText = (inputText: string): React.ReactNode[] => {
      const result: React.ReactNode[] = [];
      let remainingText = inputText;
      let currentKey = 0;

      // 处理块级公式 $$...$$
      const blockMathRegex = /\$\$([\s\S]*?)\$\$/;
      let blockMatch = remainingText.match(blockMathRegex);
      
      while (blockMatch) {
        const beforeMatch = remainingText.substring(0, blockMatch.index);
        const mathContent = blockMatch[1].trim();
        
        // 添加前面的文本（可能包含行内公式）
        if (beforeMatch) {
          result.push(...processInlineText(beforeMatch, currentKey));
          currentKey += 10; // 预留key空间
        }
        
        // 添加块级数学公式
        result.push(
          <MathRenderer 
            key={`block-math-${currentKey++}`} 
            displayMode={true}
          >
            {mathContent}
          </MathRenderer>
        );
        
        // 继续处理剩余文本
        remainingText = remainingText.substring(blockMatch.index! + blockMatch[0].length);
        blockMatch = remainingText.match(blockMathRegex);
      }
      
      // 处理最后剩余的文本（可能包含行内公式）
      if (remainingText) {
        result.push(...processInlineText(remainingText, currentKey));
      }
      
      return result;
    };

    // 处理行内公式的函数
    const processInlineText = (inputText: string, startKey: number): React.ReactNode[] => {
      const result: React.ReactNode[] = [];
      let remainingText = inputText;
      let currentKey = startKey;

      // 简单的行内公式匹配：单个$包围的内容，且不包含$$
      const inlineMathRegex = /\$([^$\n]+?)\$/;
      let inlineMatch = remainingText.match(inlineMathRegex);
      
      while (inlineMatch) {
        const beforeMatch = remainingText.substring(0, inlineMatch.index);
        const mathContent = inlineMatch[1].trim();
        
        // 添加前面的普通文本
        if (beforeMatch) {
          result.push(
            <ReactMarkdown
              key={`text-${currentKey++}`}
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children, ...props }) {
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
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  );
                },
                p: ({ children }) => <p style={{ margin: '8px 0', lineHeight: '1.6' }}>{children}</p>
              }}
            >
              {beforeMatch}
            </ReactMarkdown>
          );
        }
        
        // 添加行内数学公式
        result.push(
          <MathRenderer 
            key={`inline-math-${currentKey++}`} 
            displayMode={false}
          >
            {mathContent}
          </MathRenderer>
        );
        
        // 继续处理剩余文本
        remainingText = remainingText.substring(inlineMatch.index! + inlineMatch[0].length);
        inlineMatch = remainingText.match(inlineMathRegex);
      }
      
      // 处理最后剩余的普通文本
      if (remainingText) {
        result.push(
          <ReactMarkdown
            key={`final-text-${currentKey++}`}
            remarkPlugins={[remarkGfm]}
            components={{
              code({ className, children, ...props }) {
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
                  >
                    {String(children).replace(/\n$/, '')}
                  </SyntaxHighlighter>
                );
              },
              p: ({ children }) => <p style={{ margin: '8px 0', lineHeight: '1.6' }}>{children}</p>
            }}
          >
            {remainingText}
          </ReactMarkdown>
        );
      }
      
      return result;
    };

    // 开始处理文本
    const processedParts = processText(children);
    
    // 如果没有找到任何数学公式，则使用普通的ReactMarkdown
    return processedParts.length > 0 ? processedParts : [
      <ReactMarkdown key="fallback" remarkPlugins={[remarkGfm]}>
        {children}
      </ReactMarkdown>
    ];
  };

  return (
    <div className={className} style={style}>
      {parseMathContent(children)}
    </div>
  );
};

export default MarkdownWithMath; 