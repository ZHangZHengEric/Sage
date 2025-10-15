import React from 'react';
import './ThreeOptionSwitch.css';
import { useLanguage } from '../contexts/LanguageContext';

const ThreeOptionSwitch = ({ value, onChange, disabled = false, label, description }) => {
  const { t } = useLanguage();

  // 将值转换为选项
  const getOptionFromValue = (val) => {
    if (val === null || val === undefined) return 'auto';
    return val ? 'on' : 'off';
  };

  // 将选项转换为值
  const getValueFromOption = (option) => {
    switch (option) {
      case 'on': return true;
      case 'off': return false;
      case 'auto': return null;
      default: return null;
    }
  };

  const currentOption = getOptionFromValue(value);

  const handleOptionChange = (option) => {
    if (disabled) return;
    const newValue = getValueFromOption(option);
    onChange(newValue);
  };

  return (
    <div className="three-option-switch">
      <div className="switch-label-container">
        <span className="switch-label">{label}</span>
        {description && (
          <small className="switch-description">{description}</small>
        )}
      </div>
      <div className="option-buttons">
        <button
          type="button"
          className={`option-button ${currentOption === 'off' ? 'active' : ''}`}
          onClick={() => handleOptionChange('off')}
          disabled={disabled}
        >
          {t('common.off')}
        </button>
        <button
          type="button"
          className={`option-button ${currentOption === 'auto' ? 'active' : ''}`}
          onClick={() => handleOptionChange('auto')}
          disabled={disabled}
        >
          {t('common.auto')}
        </button>
        <button
          type="button"
          className={`option-button ${currentOption === 'on' ? 'active' : ''}`}
          onClick={() => handleOptionChange('on')}
          disabled={disabled}
        >
          {t('common.on')}
        </button>
      </div>
    </div>
  );
};

export default ThreeOptionSwitch;