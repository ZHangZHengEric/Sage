import { ref, computed, onMounted } from 'vue'
import { skillAPI } from '../../api/skill.js'
import { agentAPI } from '../../api/agent.js'
import { getCurrentUser } from '../../utils/auth.js'
import { toast } from 'vue-sonner'

export function useSkillList(t) {
  // State
  const skills = ref([])
  const agents = ref([]) // Agent列表，用于获取agent名称
  const loading = ref(false)
  const searchTerm = ref('')
  const selectedDimension = ref('system')
  const currentUser = ref({ userid: '', role: 'user' })

  // Import dialog state
  const showImportModal = ref(false)
  const importMode = ref('upload')
  const importTargetDimension = ref('user')
  const selectedFile = ref(null)
  const importUrl = ref('')
  const importing = ref(false)
  const importError = ref('')
  const isDragging = ref(false)
  const fileInput = ref(null)

  // Edit dialog state
  const showEditModal = ref(false)
  const editingSkill = ref(null)
  const skillContent = ref('')
  const saving = ref(false)

  // Delete dialog state
  const showDeleteDialog = ref(false)
  const skillToDelete = ref(null)
  const deleting = ref(false)

  // Computed
  const isAdmin = computed(() => {
    return currentUser.value.role?.toLowerCase() === 'admin'
  })

  const counts = computed(() => ({
    system: skills.value.filter(s => s.dimension === 'system').length,
    user: skills.value.filter(s => s.dimension === 'user').length,
    agent: skills.value.filter(s => s.dimension === 'agent').length
  }))

  // Agent名称映射表
  const agentNameMap = computed(() => {
    const map = {}
    agents.value.forEach(agent => {
      map[agent.id] = agent.name
    })
    return map
  })

  // Group skills by agent for agent dimension view
  const groupedAgentSkills = computed(() => {
    const groups = {}
    skills.value
      .filter(s => s.dimension === 'agent')
      .filter(skill => {
        if (!searchTerm.value.trim()) return true
        const query = searchTerm.value.toLowerCase()
        return skill.name.toLowerCase().includes(query) ||
          (skill.description && skill.description.toLowerCase().includes(query))
      })
      .forEach(skill => {
        const agentId = skill.agent_id || 'unknown'
        // 优先使用agent列表中的名称，其次使用skill中的agent_name，最后使用agentId
        const agentName = agentNameMap.value[agentId] || skill.agent_name || agentId
        if (!groups[agentId]) {
          groups[agentId] = {
            agentId,
            agentName,
            skills: []
          }
        }
        groups[agentId].skills.push(skill)
      })
    return Object.values(groups)
  })

  // Displayed skills filtered by current dimension and search term.
  const displayedSkills = computed(() => {
    let result = skills.value

    if (selectedDimension.value && selectedDimension.value !== 'all') {
      result = result.filter(skill => skill.dimension === selectedDimension.value)
    }

    // Search filtering (client-side)
    if (searchTerm.value.trim()) {
      const query = searchTerm.value.toLowerCase()
      result = result.filter(skill =>
        skill.name.toLowerCase().includes(query) ||
        (skill.description && skill.description.toLowerCase().includes(query))
      )
    }

    return result
  })

  const isImportDisabled = computed(() => {
    // Upload mode requires file
    if (importMode.value === 'upload') {
      if (!selectedFile.value) return true
    }
    // URL mode requires URL
    if (importMode.value === 'url') {
      if (!importUrl.value) return true
    }
    // System dimension requires admin
    if (importTargetDimension.value === 'system') {
      if (!isAdmin.value) return true
    }
    return false
  })

  // Methods
  const getDimensionBadgeVariant = (dimension) => {
    switch (dimension) {
      case 'system': return 'default'
      case 'user': return 'secondary'
      case 'agent': return 'outline'
      default: return 'secondary'
    }
  }

  const getDimensionIcon = (dimension) => {
    switch (dimension) {
      case 'system': return 'Shield'
      case 'user': return 'User'
      case 'agent': return 'Bot'
      default: return 'Box'
    }
  }

  const getDimensionLabel = (dimension) => {
    switch (dimension) {
      case 'system': return t('skills.system') || 'System'
      case 'user': return t('skills.user') || 'User'
      case 'agent': return t('skills.agent') || 'Agent'
      default: return dimension
    }
  }

  // Check if user can edit a skill
  const canEdit = (skill) => {
    if (skill.dimension === 'system') {
      return isAdmin.value // Only admin can edit system skills
    }
    if (skill.dimension === 'agent') {
      // Agent skills can be edited by the owner
      return skill.owner_user_id === currentUser.value.userid
    }
    return skill.owner_user_id === currentUser.value.userid
  }

  const canDelete = (skill) => {
    if (isAdmin.value) return true
    if (skill.dimension === 'system') return false
    if (skill.dimension === 'agent') {
      return skill.owner_user_id === currentUser.value.userid
    }
    return skill.owner_user_id === currentUser.value.userid
  }

  // API Methods
  const loadSkills = async () => {
    try {
      loading.value = true

      // 并行请求skills和agents
      const [skillsResponse, agentsResponse] = await Promise.all([
        skillAPI.getSkills(),
        agentAPI.getAgents().catch(() => []) // 如果获取agents失败，返回空数组
      ])

      if (skillsResponse.skills) {
        skills.value = skillsResponse.skills
      }

      // 保存agent列表用于显示agent名称
      // 后端返回格式: [...]
      agents.value = agentsResponse || []
    } catch (error) {
      console.error('Failed to load skills:', error)
      toast.error(t('skills.loadFailed') || 'Failed to load skills')
    } finally {
      loading.value = false
    }
  }

  const openImportModal = () => {
    importTargetDimension.value = 'user'
    importMode.value = 'upload'
    selectedFile.value = null
    importUrl.value = ''
    importError.value = ''
    showImportModal.value = true
  }

  const handleFileChange = (event) => {
    const file = event.target.files[0]
    processFile(file)
  }

  const handleDrop = (event) => {
    isDragging.value = false
    const file = event.dataTransfer.files[0]
    processFile(file)
  }

  const processFile = (file) => {
    if (!file) return
    if (!file.name.endsWith('.zip')) {
      importError.value = t('skills.zipOnly') || 'Only ZIP files are supported'
      selectedFile.value = null
      if (fileInput.value) fileInput.value.value = ''
      return
    }
    selectedFile.value = file
    importError.value = ''
  }

  const handleImport = async () => {
    importing.value = true
    importError.value = ''

    try {
      const isSystemSkill = importTargetDimension.value === 'system'

      const importParams = {
        is_system: isSystemSkill,
        is_agent: false,
        agent_id: undefined
      }

      if (importMode.value === 'upload') {
        if (!selectedFile.value) return
        await skillAPI.uploadSkill(selectedFile.value, isSystemSkill, importParams)
      } else {
        if (!importUrl.value) return
        await skillAPI.importSkillFromUrl({
          url: importUrl.value,
          is_system: isSystemSkill,
          is_agent: false,
          agent_id: undefined
        })
      }

      await loadSkills()
      showImportModal.value = false
      selectedFile.value = null
      importUrl.value = ''
      if (fileInput.value) fileInput.value.value = ''
      toast.success(t('skills.importSuccess') || 'Skill imported successfully')
    } catch (error) {
      console.error('Import failed:', error)
      importError.value = error.message || t('skills.importFailed') || 'Import failed'
    } finally {
      importing.value = false
    }
  }

  const openEditModal = async (skill) => {
    // Check if can edit
    if (!canEdit(skill)) {
      toast.error(t('skills.noEditPermission') || 'You do not have permission to edit this skill')
      return
    }

    editingSkill.value = skill
    skillContent.value = ''
    showEditModal.value = true

    try {
      const response = await skillAPI.getSkillContent(skill.name)
      if (response.content) {
        skillContent.value = response.content
      }
    } catch (error) {
      toast.error(t('skills.loadContentFailed') || 'Failed to load skill content')
      showEditModal.value = false
    }
  }

  const saveSkillContent = async () => {
    if (!editingSkill.value) return

    try {
      saving.value = true
      await skillAPI.updateSkillContent(editingSkill.value.name, skillContent.value)
      toast.success(t('skills.updateSuccess') || 'Skill updated successfully')
      showEditModal.value = false
      loadSkills()
    } catch (error) {
      console.error('Failed to update skill:', error)
      toast.error(t('skills.updateFailed') || 'Failed to update skill')
    } finally {
      saving.value = false
    }
  }

  // 用于存储要删除的skill的agentId
  const skillToDeleteAgentId = ref(null)

  const confirmDelete = (skill, agentId = null) => {
    skillToDelete.value = skill
    skillToDeleteAgentId.value = agentId // 保存agentId用于删除
    showDeleteDialog.value = true
  }

  const executeDelete = async () => {
    if (!skillToDelete.value) return

    try {
      deleting.value = true
      // 如果是Agent维度的skill，传入agent_id
      const agentId = skillToDeleteAgentId.value
      await skillAPI.deleteSkill(skillToDelete.value.name, agentId)
      toast.success(t('skills.deleteSuccess') || 'Skill deleted successfully')
      showDeleteDialog.value = false
      skillToDelete.value = null
      skillToDeleteAgentId.value = null
      await loadSkills()
    } catch (error) {
      toast.error(t('skills.deleteFailed') || 'Failed to delete skill')
    } finally {
      deleting.value = false
    }
  }

  onMounted(async () => {
    const user = await getCurrentUser()
    if (user) {
      currentUser.value = user
    }
    loadSkills()
  })

  return {
    // State
    skills,
    loading,
    searchTerm,
    selectedDimension,
    currentUser,
    showImportModal,
    importMode,
    importTargetDimension,
    selectedFile,
    importUrl,
    importing,
    importError,
    isDragging,
    fileInput,
    showEditModal,
    editingSkill,
    skillContent,
    saving,
    showDeleteDialog,
    skillToDelete,
    deleting,

    // Computed
    isAdmin,
    counts,
    displayedSkills,
    isImportDisabled,
    groupedAgentSkills,

    // Methods
    getDimensionBadgeVariant,
    getDimensionIcon,
    getDimensionLabel,
    canEdit,
    canDelete,
    loadSkills,
    openImportModal,
    handleFileChange,
    handleDrop,
    processFile,
    handleImport,
    openEditModal,
    saveSkillContent,
    confirmDelete,
    executeDelete
  }
}
