import React from 'react';
import { X, Code, Database, Globe, Cpu, Wrench } from 'lucide-react';
import './ToolDetail.css';
import { useLanguage } from '../contexts/LanguageContext';

const ToolDetail = ({ tool, onClose }) => {
  const { t } = useLanguage();
  if (!tool) return null;
  
  const getToolTypeLabel = (type) => {
    const typeKey = `tools.type.${type}`;
    return t(typeKey) !== typeKey ? t(typeKey) : type;
  };
  
  const getToolSourceLabel = (source) => {
    // 直接映射中文source到翻译key
    const sourceMapping = {
      '基础工具': 'tools.source.basic',
      '内置工具': 'tools.source.builtin',
      '系统工具': 'tools.source.system'
    };
    
    const translationKey = sourceMapping[source];
    return translationKey ? t(translationKey) : source;
  };

  const getToolIcon = (type) => {
    switch (type) {
      case 'basic':
        return <Code size={24} />;
      case 'mcp':
        return <Database size={24} />;
      case 'agent':
        return <Cpu size={24} />;
      default:
        return <Wrench size={24} />;
    }
  };
  
  const getToolTypeColor = (type) => {
    switch (type) {
      case 'basic':
        return '#4facfe';
      case 'mcp':
        return '#667eea';
      case 'agent':
        return '#ff6b6b';
      default:
        return '#4ade80';
    }
  };

  const formatParameters = (parameters) => {
    if (!parameters || typeof parameters !== 'object') {
      return [];
    }
    
    if (parameters.properties) {
      return Object.entries(parameters.properties).map(([key, value]) => ({
        name: key,
        type: value.type || 'unknown',
        description: value.description || 'No description',
        required: parameters.required?.includes(key) || false
      }));
    }
    
    return Object.entries(parameters).map(([key, value]) => {
      let type = 'unknown';
      let description = 'No description';
      
      if (typeof value === 'object' && value !== null) {
        if (value.type) {
          type = value.type;
        } else if (value.anyOf) {
          const types = value.anyOf.map(item => item.type).filter(t => t && t !== 'null');
          type = types.length > 0 ? types.join(' | ') : 'mixed';
        }
        
        if (value.title) {
          description = value.title;
        } else if (value.description) {
          description = value.description;
        } else {
          if (value.default !== undefined) {
            description = `默认值: ${JSON.stringify(value.default)}`;
          } else {
            description = '参数配置';
          }
        }
      } else {
        type = typeof value;
        description = String(value);
      }
      
      return {
        name: key,
        type: type,
        description: description,
        required: false
      };
    });
  };

  const formattedParams = formatParameters(tool.parameters);

  return (
    <div className="tool-detail">
      <div className="tool-detail-header">
        <div className="tool-detail-title">
          <div 
            className="tool-icon large"
            style={{ background: `linear-gradient(135deg, ${getToolTypeColor(tool.type)} 0%, ${getToolTypeColor(tool.type)}80 100%)` }}
          >
            {getToolIcon(tool.type)}
          </div>
          <div>
            <h2 className="tool-name">{tool.name}</h2>
            <span 
              className="tool-type-badge"
              style={{ background: getToolTypeColor(tool.type) }}
            >
              {getToolTypeLabel(tool.type)}
            </span>
          </div>
        </div>
        <button className="close-button" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      
      <div className="tool-detail-content">
        <div className="tool-section">
          <h3 className="section-title">{t('toolDetail.description')}</h3>
          <p className="tool-description">{tool.description}</p>
        </div>
        
        <div className="tool-section">
          <h3 className="section-title">{t('toolDetail.basicInfo')}</h3>
          <div className="info-grid">
            <div className="info-item">
              <span className="info-label">{t('toolDetail.toolName')}</span>
              <span className="info-value">{tool.name}</span>
            </div>
            <div className="info-item">
              <span className="info-label">{t('toolDetail.toolType')}</span>
              <span className="info-value">{getToolTypeLabel(tool.type)}</span>
            </div>
            <div className="info-item">
              <span className="info-label">{t('toolDetail.source')}</span>
              <span className="info-value">{getToolSourceLabel(tool.source)}</span>
            </div>
          </div>
        </div>
        
        {formattedParams.length > 0 && (
          <div className="tool-section">
            <h3 className="section-title">{t('toolDetail.parametersOverview')}</h3>
            <div className="parameters-overview">
              <div className="overview-stats">
                <div className="overview-stat">
                  <span className="stat-number">{formattedParams.length}</span>
                  <span className="stat-label">{t('toolDetail.totalParams')}</span>
                </div>
                <div className="overview-stat">
                  <span className="stat-number">{formattedParams.filter(p => p.required).length}</span>
                  <span className="stat-label">{t('toolDetail.requiredParams')}</span>
                </div>
                <div className="overview-stat">
                  <span className="stat-number">{formattedParams.filter(p => !p.required).length}</span>
                  <span className="stat-label">{t('toolDetail.optional')}</span>
                </div>
              </div>
              <div className="parameters-summary">
                {formattedParams.map((param, index) => (
                  <div key={index} className="parameter-summary-item">
                    <span className="param-summary-name">{param.name}</span>
                    <span className="param-summary-type">{param.type}</span>
                    {param.required && <span className="param-summary-required">{t('toolDetail.required')}</span>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
        
        <div className="tool-section">
          <h3 className="section-title">{t('toolDetail.parameterDetails')}</h3>
          {formattedParams.length > 0 ? (
            <table className="parameters-table">
              <thead>
                <tr>
                  <th>{t('toolDetail.paramName')}</th>
                  <th>{t('toolDetail.paramType')}</th>
                  <th>{t('toolDetail.required')}</th>
                  <th>{t('toolDetail.paramDescription')}</th>
                </tr>
              </thead>
              <tbody>
                {formattedParams.map((param, index) => (
                  <tr key={index}>
                    <td className="param-name-cell">{param.name}</td>
                    <td className="param-type-cell">{param.type}</td>
                    <td className="param-required-cell">
                      {param.required ? (
                        <span className="param-required-badge">{t('toolDetail.required')}</span>
                      ) : (
                        <span className="param-optional-badge">{t('toolDetail.optional')}</span>
                      )}
                    </td>
                    <td className="param-description-cell">{param.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="no-parameters">{t('toolDetail.noParameters')}</p>
          )}
        </div>
        
        <div className="tool-section">
          <h3 className="section-title">{t('toolDetail.rawConfig')}</h3>
          <pre className="json-display">
            {JSON.stringify(tool.parameters, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
};

export default ToolDetail;