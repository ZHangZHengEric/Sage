import React from 'react';
import './ConfigPanel.css';
import { useLanguage } from '../../contexts/LanguageContext';
import ThreeOptionSwitch from '../ThreeOptionSwitch';

const ConfigPanel = ({ config, onConfigChange, agents, selectedAgent, onAgentSelect }) => {
  const { t } = useLanguage();
  
  const handleConfigToggle = (key) => {
    const newValue = !config[key];
    console.log(`配置开关变更: ${key} = ${newValue}`);
    onConfigChange({ [key]: newValue });
  };

  const handleMaxLoopCountChange = (e) => {
    const value = parseInt(e.target.value, 10);
    if (!isNaN(value) && value > 0) {
      onConfigChange({ maxLoopCount: value });
    }
  };

  return (
    <div className="config-panel">
      <div className="panel-header">
        <h3>{t('config.title')}</h3>
      </div>
      
      <div className="config-content">
        {/* Agent选择 */}
        <div className="config-section">
          <label className="config-label">{t('config.selectAgent')}</label>
          <select 
            value={selectedAgent?.id || ''} 
            onChange={(e) => {
              const agent = agents.find(a => a.id === e.target.value);
              onAgentSelect(agent);
            }}
            className="agent-select"
          >
            {agents.map(agent => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </div>

        {/* 深度思考 */}
        <div className="config-section">
          <ThreeOptionSwitch
            value={config.deepThinking}
            onChange={(value) => onConfigChange({ deepThinking: value })}
            label={t('config.deepThinking')}
            description={t('config.deepThinkingDesc')}
          />
        </div>

        {/* 多智能体协作 */}
        <div className="config-section">
          <ThreeOptionSwitch
            value={config.multiAgent}
            onChange={(value) => onConfigChange({ multiAgent: value })}
            label={t('config.multiAgent')}
            description={t('config.multiAgentDesc')}
          />
        </div>

        {/* 更多建议 */}
        <div className="config-section">
          <label className="config-checkbox">
            <input
              type="checkbox"
              checked={config.moreSuggest}
              onChange={() => handleConfigToggle('moreSuggest')}
            />
            <span className="checkmark"></span>
            {t('config.moreSuggest')}
          </label>
          <small className="config-description">
            {t('config.moreSuggestDesc')}
          </small>
        </div>

        {/* 最大循环次数 */}
        <div className="config-section">
          <label className="config-label">{t('config.maxLoopCount')}</label>
          <input
            type="number"
            min="1"
            max="50"
            value={config.maxLoopCount}
            onChange={handleMaxLoopCountChange}
            className="config-input"
          />
          <small className="config-description">
            {t('config.maxLoopCountDesc')}
          </small>
        </div>
      </div>
    </div>
  );
};

export default ConfigPanel;