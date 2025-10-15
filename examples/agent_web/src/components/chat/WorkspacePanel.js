import React from 'react';
import './WorkspacePanel.css';
import { useLanguage } from '../../contexts/LanguageContext';

const WorkspacePanel = ({ workspaceFiles, workspacePath, onDownloadFile }) => {
  const { t } = useLanguage();
  
  if (!workspaceFiles || workspaceFiles.length === 0) {
    return (
      <div className="workspace-panel">
        <div className="panel-header">
          <h3>{t('workspace.title')}</h3>
        </div>
        <div className="empty-workspace">
          <p>{t('workspace.noFiles')}</p>
        </div>
      </div>
    );
  }

  const renderFileTree = (files, basePath = '') => {
    const grouped = {};
    
    // 按目录分组文件
    files.forEach(file => {
      // 确保 file 是字符串，如果是对象则提取路径
      const filePath = typeof file === 'string' ? file : (file.path || file.name || String(file));
      const parts = filePath.split('/');
      let current = grouped;
      
      parts.forEach((part, index) => {
        if (index === parts.length - 1) {
          // 这是文件
          if (!current._files) current._files = [];
          current._files.push(filePath);
        } else {
          // 这是目录
          if (!current[part]) current[part] = {};
          current = current[part];
        }
      });
    });

    const renderNode = (node, name, path) => {
      if (name === '_files') {
        return node.map(file => (
          <div key={file} className="file-item">
            <span className="file-icon">📄</span>
            <span className="file-name">{file.split('/').pop()}</span>
            <button 
              className="download-btn"
              onClick={() => onDownloadFile(file)}
              title={t('workspace.download')}
            >
              ⬇️
            </button>
          </div>
        ));
      }

      const hasSubdirs = Object.keys(node).some(key => key !== '_files');
      const hasFiles = node._files && node._files.length > 0;

      return (
        <div key={name} className="directory-item">
          <div className="directory-header">
            <span className="directory-icon">📁</span>
            <span className="directory-name">{name}</span>
          </div>
          <div className="directory-content">
            {hasFiles && renderNode(node._files, '_files', path)}
            {hasSubdirs && Object.entries(node)
              .filter(([key]) => key !== '_files')
              .map(([key, value]) => renderNode(value, key, `${path}/${key}`))
            }
          </div>
        </div>
      );
    };

    return Object.entries(grouped).map(([key, value]) => 
      renderNode(value, key, key)
    );
  };

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <h3>{t('workspace.title')}</h3>
        {workspacePath && (
          <div className="workspace-path">
            <small>{t('workspace.path')} {workspacePath}</small>
          </div>
        )}
      </div>
      <div className="file-tree">
        {renderFileTree(workspaceFiles)}
      </div>
    </div>
  );
};

export default WorkspacePanel;