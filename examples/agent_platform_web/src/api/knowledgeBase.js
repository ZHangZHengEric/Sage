import request from '../utils/request.js'

export const knowledgeBaseAPI = {
  // 获取知识库列表
  getKnowledgeBases: (params = {}) => {
    return request.get('/api/knowledge-base/list', params)
  },

  // 添加知识库
  addKnowledgeBase: ({ name, type, intro = '', language = '' }) => {
    return request.post('/api/knowledge-base/add', { name, type, intro, language })
  },

  // 获取单个知识库详情
  getKnowledgeBase: (id) => {
    return request.get('/api/knowledge-base/info', { kdb_id: id })
  },

  // 更新知识库
  updateKnowledgeBase: (id, { name = '', intro = '', kdb_setting = null } = {}) => {
    return request.post('/api/knowledge-base/update', { kdb_id: id, name, intro, kdb_setting })
  },

  // 删除知识库
  deleteKnowledgeBase: (id) => {
    return request.delete(`/api/knowledge-base/delete/${id}`)
  },

  // 清空知识库文档
  clearKnowledgeBase: (id) => {
    return request.post('/api/knowledge-base/clear', { kdb_id: id })
  },

  // 重新处理所有文档
  redoAllDocuments: (id) => {
    return request.post('/api/knowledge-base/redo_all', { kdb_id: id })
  },

  // 文档列表
  getDocuments: (params = {}) => {
    return request.get('/api/knowledge-base/doc/list', params)
  },

  // 文档详情
  getDocument: ({ kdb_id, data_id }) => {
    return request.get('/api/knowledge-base/doc/info', { kdb_id, data_id })
  },

  addDocumentsByFiles: ({ kdb_id, files, override = false }) => {
    const form = new FormData()
    form.append('kdb_id', kdb_id)
    form.append('override', override ? 'true' : 'false')
    ;(files || []).forEach(f => form.append('files', f))
    return request.post('/api/knowledge-base/doc/add_by_files', form)
  },

  // 查询任务进度
  getTaskProcess: ({ kdb_id, task_id }) => {
    return request.get('/api/knowledge-base/doc/task_process', { kdb_id, task_id })
  },

  // 任务重做
  redoTask: ({ kdb_id, task_id }) => {
    return request.post('/api/knowledge-base/doc/task_redo', { kdb_id, task_id })
  },

  // 删除文档
  deleteDocument: (doc_id) => {
    return request.delete(`/api/knowledge-base/doc/delete/${doc_id}`)
  },

  // 文档重做
  redoDocument: (doc_id) => {
    return request.put(`/api/knowledge-base/doc/redo/${doc_id}`)
  }
}