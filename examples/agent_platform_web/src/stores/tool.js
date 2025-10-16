import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { toolAPI } from '../api/index.js'

export const useToolStore = defineStore('tool', () => {
  // 状态
  const tools = ref([])
  const selectedTool = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const searchQuery = ref('')
  const selectedType = ref('all')
  const selectedSource = ref('all')
  
  // 计算属性
  const toolCount = computed(() => tools.value.length)
  const hasTools = computed(() => tools.value.length > 0)
  
  // 获取工具类型列表
  const toolTypes = computed(() => {
    const types = new Set()
    tools.value.forEach(tool => {
      if (tool.type) {
        types.add(tool.type)
      }
    })
    return Array.from(types).sort()
  })
  
  // 获取工具来源列表
  const toolSources = computed(() => {
    const sources = new Set()
    tools.value.forEach(tool => {
      if (tool.source) {
        sources.add(tool.source)
      }
    })
    return Array.from(sources).sort()
  })
  
  // 过滤后的工具列表
  const filteredTools = computed(() => {
    let filtered = tools.value
    
    // 按搜索查询过滤
    if (searchQuery.value.trim()) {
      const query = searchQuery.value.toLowerCase().trim()
      filtered = filtered.filter(tool => 
        tool.name?.toLowerCase().includes(query) ||
        tool.description?.toLowerCase().includes(query) ||
        tool.type?.toLowerCase().includes(query) ||
        tool.source?.toLowerCase().includes(query)
      )
    }
    
    // 按类型过滤
    if (selectedType.value && selectedType.value !== 'all') {
      filtered = filtered.filter(tool => tool.type === selectedType.value)
    }
    
    // 按来源过滤
    if (selectedSource.value && selectedSource.value !== 'all') {
      filtered = filtered.filter(tool => tool.source === selectedSource.value)
    }
    
    return filtered
  })
  
  // 工具统计
  const toolStats = computed(() => {
    const stats = {
      total: tools.value.length,
      types: toolTypes.value.length,
      byType: {},
      bySource: {}
    }
    
    // 按类型统计
    tools.value.forEach(tool => {
      const type = tool.type || 'unknown'
      stats.byType[type] = (stats.byType[type] || 0) + 1
    })
    
    // 按来源统计
    tools.value.forEach(tool => {
      const source = tool.source || 'unknown'
      stats.bySource[source] = (stats.bySource[source] || 0) + 1
    })
    
    return stats
  })
  
  // 方法
  const setTools = (toolList) => {
    tools.value = toolList
  }
  
  const addTool = (tool) => {
    tools.value.push(tool)
  }
  
  const updateTool = (updatedTool) => {
    const index = tools.value.findIndex(tool => tool.name === updatedTool.name)
    if (index !== -1) {
      tools.value[index] = updatedTool
    }
  }
  
  const deleteTool = (toolName) => {
    const index = tools.value.findIndex(tool => tool.name === toolName)
    if (index !== -1) {
      tools.value.splice(index, 1)
    }
  }
  
  const selectTool = (tool) => {
    selectedTool.value = tool
  }
  
  const getToolByName = (toolName) => {
    return tools.value.find(tool => tool.name === toolName)
  }
  
  const setLoading = (isLoading) => {
    loading.value = isLoading
  }
  
  const setError = (errorMessage) => {
    error.value = errorMessage
  }
  
  const clearError = () => {
    error.value = null
  }
  
  const setSearchQuery = (query) => {
    searchQuery.value = query
  }
  
  const setSelectedType = (type) => {
    selectedType.value = type
  }
  
  const setSelectedSource = (source) => {
    selectedSource.value = source
  }
  
  const clearFilters = () => {
    searchQuery.value = ''
    selectedType.value = 'all'
    selectedSource.value = 'all'
  }

  // 从API加载工具列表
  const loadTools = async () => {
    try {
      setLoading(true)
      clearError()
      
      const data = await toolAPI.getTools()
      setTools(data || [])
      
    } catch (err) {
      console.error('Failed to load tools:', err)
      setError('Failed to load tools')
    } finally {
      setLoading(false)
    }
  }
  
  // 搜索工具
  const searchTools = async (query, filters = {}) => {
    try {
      setLoading(true)
      clearError()
      
      const data = await toolAPI.searchTools({ keyword: query, ...filters })
      setTools(data || [])
      
    } catch (err) {
      console.error('Failed to search tools:', err)
      setError('Failed to search tools')
    } finally {
      setLoading(false)
    }
  }
  
  // 获取工具详情
  const getToolDetails = async (toolId) => {
    try {
      setLoading(true)
      clearError()
      
      const tool = await toolAPI.getToolDetail(toolId)
      selectTool(tool)
      return tool
    } catch (err) {
      console.error('Failed to get tool details:', err)
      setError('Failed to get tool details')
      throw err
    } finally {
      setLoading(false)
    }
  }
  
  // 初始化
  const initialize = async () => {
    await loadTools()
  }
  
  return {
    // 状态
    tools,
    selectedTool,
    loading,
    error,
    searchQuery,
    selectedType,
    selectedSource,
    
    // 计算属性
    toolCount,
    hasTools,
    toolTypes,
    toolSources,
    filteredTools,
    toolStats,
    
    // 方法
    setTools,
    addTool,
    updateTool,
    deleteTool,
    selectTool,
    getToolByName,
    setLoading,
    setError,
    clearError,
    setSearchQuery,
    setSelectedType,
    setSelectedSource,
    clearFilters,
    loadTools,
    searchTools,
    getToolDetails,
    initialize
  }
})