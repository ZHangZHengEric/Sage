import React, { useState } from 'react';
import './TokenUsage.css';

const TokenUsage = ({ tokenUsage }) => {
  const [showDetails, setShowDetails] = useState(false);
  
  if (!tokenUsage || !tokenUsage.total_info) {
    return null;
  }

  const { total_info, per_step_info } = tokenUsage;
  
  // 提取输入和输出 token 数量
  const inputTokens = total_info.prompt_tokens || 0;
  const outputTokens = total_info.completion_tokens || 0;
  const totalTokens = total_info.total_tokens || (inputTokens + outputTokens);

  return (
    <div className="token-usage">
      {/* 简洁的一行显示 */}
      <div className="token-usage-compact">
        <span className="token-usage-icon">📊</span>
        <span className="token-usage-summary">
          Token 使用: 输入 <span className="token-value input-tokens">{inputTokens.toLocaleString()}</span>
          , 输出 <span className="token-value output-tokens">{outputTokens.toLocaleString()}</span>
          , 总计 <span className="token-value total-tokens">{totalTokens.toLocaleString()}</span>
        </span>
        {per_step_info && Array.isArray(per_step_info) && per_step_info.length > 0 && (
          <button 
            className="toggle-details-btn-compact"
            onClick={() => setShowDetails(!showDetails)}
          >
            {showDetails ? '收起' : '更多'}
          </button>
        )}
      </div>
      
      {/* 展开的详细信息 */}
      {showDetails && (
        <div className="token-usage-details">
          <div className="token-usage-content">
            <div className="token-item">
              <span className="token-label">输入 Token:</span>
              <span className="token-value input-tokens">{inputTokens.toLocaleString()}</span>
            </div>
            <div className="token-item">
              <span className="token-label">输出 Token:</span>
              <span className="token-value output-tokens">{outputTokens.toLocaleString()}</span>
            </div>
            <div className="token-item total">
              <span className="token-label">总计:</span>
              <span className="token-value total-tokens">{totalTokens.toLocaleString()}</span>
            </div>
            
            {/* 显示分步骤详情 */}
            {per_step_info && Array.isArray(per_step_info) && (
              <div className="step-details">
                <div className="step-details-title">分步骤统计:</div>
                {per_step_info.map((stepInfo, index) => (
                  <div key={index} className="step-item">
                    <div className="step-name">{stepInfo.step_name}:</div>
                    <div className="step-tokens">
                      <span className="step-token-item">
                        输入: {(stepInfo.usage?.prompt_tokens || 0).toLocaleString()}
                      </span>
                      <span className="step-token-item">
                        输出: {(stepInfo.usage?.completion_tokens || 0).toLocaleString()}
                      </span>
                      <span className="step-token-item total">
                        小计: {(stepInfo.usage?.total_tokens || 0).toLocaleString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default TokenUsage;