import React, { useState } from 'react';
import { X, Search, Check, Plus, Trash2 } from 'lucide-react';
import './ToolSelectorModal.css';
import { useLanguage } from '../contexts/LanguageContext';

const ToolSelectorModal = ({ isOpen, onClose, tools, selectedTools, onToggle }) => {
  const { t } = useLanguage();
  const [query, setQuery] = useState('');

  if (!isOpen) return null;

  const filtered = tools.filter(
    (t) =>
      t.name.toLowerCase().includes(query.toLowerCase()) ||
      t.description?.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="tool-selector-overlay" onClick={onClose}>
      <div className="tool-selector-modal-root" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h4>选择工具</h4>
          <button className="close-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="modal-content">
          <div className="tool-search-input">
            <Search size={16} />
            <input
              type="text"
              placeholder="搜索工具..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="tool-selection-grid">
            {filtered.map((tool) => {
              const isSelected = selectedTools.includes(tool.name);
              return (
                <div
                  key={tool.name}
                  className={`tool-selection-item ${isSelected ? 'selected' : ''}`}
                  onClick={() => onToggle(tool.name)}
                >
                  <div className="tool-selection-checkbox">
                    {isSelected && <Check size={14} />}
                  </div>
                  <div className="tool-selection-info">
                    <span className="tool-selection-name">{tool.name}</span>
                    <span className="tool-selection-type">{tool.type}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-primary" onClick={onClose}>
            完成
          </button>
        </div>
      </div>
    </div>
  );
};

export default ToolSelectorModal;