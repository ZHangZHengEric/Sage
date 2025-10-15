import React, { useState } from 'react';
import { Wrench, Search, Code, Database, Globe, Cpu } from 'lucide-react';
import ToolDetail from '../components/ToolDetail';
import './ToolsPage.css';
import { useLanguage } from '../contexts/LanguageContext';

const ToolsPage = ({ tools }) => {
  const { t } = useLanguage();
  const [selectedTool, setSelectedTool] = useState(null);
  
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
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('all');
  const [showToolDetail, setShowToolDetail] = useState(false);
  
  const getToolIcon = (type) => {
    switch (type) {
      case 'basic':
        return <Code size={20} />;
      case 'mcp':
        return <Database size={20} />;
      case 'agent':
        return <Cpu size={20} />;
      default:
        return <Wrench size={20} />;
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
  
  const filteredTools = tools.filter(tool => {
    const matchesSearch = tool.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         tool.description.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesType = filterType === 'all' || tool.type === filterType;
    return matchesSearch && matchesType;
  });
  
  const toolTypes = ['all', ...new Set(tools.map(tool => tool.type))];
  
  const formatParameters = (parameters) => {
    if (!parameters || typeof parameters !== 'object') {
      return t('tools.noParameters');
    }
    
    if (parameters.properties) {
      return Object.entries(parameters.properties).map(([key, value]) => ({
          name: key,
          type: value.type || 'unknown',
          description: value.description || t('tools.noDescription'),
          required: parameters.required?.includes(key) || false
        }));
    }
    
    return Object.entries(parameters).map(([key, value]) => {
      let type = 'unknown';
      let description = t('tools.noDescription');
      
      if (typeof value === 'object' && value !== null) {
        // 处理复杂的参数类型
        if (value.type) {
          type = value.type;
        } else if (value.anyOf) {
          // 处理 anyOf 类型，提取主要类型
          const types = value.anyOf.map(item => item.type).filter(t => t && t !== 'null');
          type = types.length > 0 ? types.join(' | ') : 'mixed';
        }
        
        // 优先使用 title 作为描述，然后是 description
        if (value.title) {
          description = value.title;
        } else if (value.description) {
          description = value.description;
        } else {
          // 如果没有合适的描述，显示简化的类型信息
          if (value.default !== undefined) {
            description = `${t('tools.defaultValue')}: ${JSON.stringify(value.default)}`;
          } else {
            description = t('tools.paramConfig');
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
  
  return (
    <div className="tools-page">
      <div className="page-header">
        <div className="page-title">
          <h2>{t('tools.title')}</h2>
          <p>{t('tools.subtitle')}</p>
        </div>
        
        <div className="tools-stats">
          <div className="stat-item">
            <span className="stat-number">{tools.length}</span>
            <span className="stat-label">{t('tools.totalCount')}</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{toolTypes.length - 1}</span>
            <span className="stat-label">{t('tools.typeCount')}</span>
          </div>
        </div>
      </div>
      
      <div className="tools-filters">
        <div className="search-box">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input search-input"
            placeholder={t('tools.search')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        
        <div className="filter-tabs">
          {toolTypes.map(type => (
            <button
              key={type}
              className={`filter-tab ${filterType === type ? 'active' : ''}`}
              onClick={() => setFilterType(type)}
            >
              {type === 'all' ? t('tools.all') : getToolTypeLabel(type)}
            </button>
          ))}
        </div>
      </div>
      
      <div className="tools-grid">
        {filteredTools.map(tool => (
          <div 
            key={tool.name} 
            className="tool-card"
            onClick={() => {
              setSelectedTool(tool);
              setShowToolDetail(true);
            }}
          >
            <div className="tool-header">
              <div 
                className="tool-icon"
                style={{ background: `linear-gradient(135deg, ${getToolTypeColor(tool.type)} 0%, ${getToolTypeColor(tool.type)}80 100%)` }}
              >
                {getToolIcon(tool.type)}
              </div>
              <div className="tool-info">
                <h3 className="tool-name">{tool.name}</h3>
                <span 
                  className="tool-type-badge"
                  style={{ background: getToolTypeColor(tool.type) }}
                >
                  {tool.type}
                </span>
              </div>
            </div>
            
            <div className="tool-meta">
              <div className="meta-item">
                <span className="meta-label">{t('tools.source')}:</span>
                <span className="meta-value">{getToolSourceLabel(tool.source)}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">{t('tools.params')}:</span>
                <span className="meta-value">
                  {formatParameters(tool.parameters).length} {t('tools.paramsCount')}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
      
      {filteredTools.length === 0 && (
        <div className="empty-state">
          <Wrench size={48} className="empty-icon" />
          <h3>{t('tools.noTools')}</h3>
          <p>{t('tools.noToolsDesc')}</p>
        </div>
      )}
      
      {showToolDetail && selectedTool && (
        <ToolDetail 
          tool={selectedTool} 
          onClose={() => {
            setShowToolDetail(false);
            setSelectedTool(null);
          }} 
        />
      )}
    </div>
  );
};

export default ToolsPage;