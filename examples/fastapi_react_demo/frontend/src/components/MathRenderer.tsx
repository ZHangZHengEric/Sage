import React, { useEffect, useRef } from 'react';
import katex from 'katex';

interface MathRendererProps {
  children: string;
  displayMode?: boolean;
}

const MathRenderer: React.FC<MathRendererProps> = ({ children, displayMode = false }) => {
  const mathRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (mathRef.current) {
      try {
        katex.render(children, mathRef.current, {
          displayMode,
          throwOnError: false,
          errorColor: '#cc0000',
          trust: false,
        });
      } catch (error) {
        console.error('KaTeX rendering error:', error);
        if (mathRef.current) {
          mathRef.current.textContent = children;
        }
      }
    }
  }, [children, displayMode]);

  return <span ref={mathRef} className={displayMode ? 'katex-display' : 'katex-inline'} />;
};

export default MathRenderer; 