import { baseAPI } from './base.js'

export const knowledgeBaseAPI = {
  // 获取知识库列表
  getKnowledgeBases: async (params = {}) => {
    return await baseAPI.get('/api/knowledge-base/list', params)
  },

  // 添加知识库
  addKnowledgeBase: async ({ name, type, intro = '', language = '' }) => {
    return await baseAPI.post('/api/knowledge-base/add', { name, type, intro, language })
  },

  // 获取单个知识库详情
  getKnowledgeBase: async (id) => {
    return await baseAPI.get('/api/knowledge-base/info', { kdb_id: id })
  },

  // 更新知识库
  updateKnowledgeBase: async (id, { name = '', intro = '', kdb_setting = null } = {}) => {
    return await baseAPI.post('/api/knowledge-base/update', { kdb_id: id, name, intro, kdb_setting })
  },

  // 删除知识库
  deleteKnowledgeBase: async (id) => {
    return await baseAPI.delete(`/api/knowledge-base/delete/${id}`)
  },

  // 清空知识库文档
  clearKnowledgeBase: async (id) => {
    return await baseAPI.post('/api/knowledge-base/clear', { kdb_id: id })
  },

  // 重新处理所有文档
  redoAllDocuments: async (id) => {
    return await baseAPI.post('/api/knowledge-base/redo_all', { kdb_id: id })
  },

  // 文档列表
  getDocuments: async (params = {}) => {
    return await baseAPI.get('/api/knowledge-base/doc/list', params)
  },

  // 文档详情
  getDocument: async ({ kdb_id, data_id }) => {
    return await baseAPI.get('/api/knowledge-base/doc/info', { kdb_id, data_id })
  },

  addDocumentsByFiles: async ({ kdb_id, files, override = false }) => {
    const form = new FormData()
    form.append('kdb_id', kdb_id)
    form.append('override', override ? 'true' : 'false')
    ;(files || []).forEach(f => form.append('files', f))
    return await baseAPI.post('/api/knowledge-base/doc/add_by_files', form)
  },

  // 查询任务进度
  getTaskProcess: async ({ kdb_id, task_id }) => {
    return await baseAPI.get('/api/knowledge-base/doc/task_process', { kdb_id, task_id })
  },

  // 任务重做
  redoTask: async ({ kdb_id, task_id }) => {
    return await baseAPI.post('/api/knowledge-base/doc/task_redo', { kdb_id, task_id })
  },

  // 删除文档
  deleteDocument: async (doc_id) => {
    return await baseAPI.delete(`/api/knowledge-base/doc/delete/${doc_id}`)
  },

  // 文档重做
  redoDocument: async (doc_id) => {
    return await baseAPI.put(`/api/knowledge-base/doc/redo/${doc_id}`)
  },

  // 召回检索
  retrieve: async ({ kdb_id, query, top_k = 10 }) => {
    return await baseAPI.post('/api/knowledge-base/retrieve', { kdb_id, query, top_k })
  }
}
