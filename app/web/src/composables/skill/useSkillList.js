import { ref, computed, onMounted, watch } from 'vue'
import { skillAPI } from '../../api/skill.js'
import { getCurrentUser } from '../../utils/auth.js'
import { toast } from 'vue-sonner'

export function useSkillList(t) {
  // State
  const skills = ref([])
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
    user: skills.value.filter(s => s.dimension === 'user').length
  }))

  // Displayed skills with search filtering only (dimension filtering is done by backend)
  const displayedSkills = computed(() => {
    let result = skills.value

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
      default: return 'secondary'
    }
  }

  const getDimensionIcon = (dimension) => {
    switch (dimension) {
      case 'system': return 'Shield'
      case 'user': return 'User'
      default: return 'Box'
    }
  }

  const getDimensionLabel = (dimension) => {
    switch (dimension) {
      case 'system': return t('skills.system') || 'System'
      case 'user': return t('skills.user') || 'User'
      default: return dimension
    }
  }

  // Check if user can edit a skill
  const canEdit = (skill) => {
    if (skill.dimension === 'system') {
      return isAdmin.value // Only admin can edit system skills
    }
    return skill.owner_user_id === currentUser.value.userid
  }

  const canDelete = (skill) => {
    if (isAdmin.value) return true
    if (skill.dimension === 'system') return false
    return skill.owner_user_id === currentUser.value.userid
  }

  // API Methods
  const loadSkills = async () => {
    try {
      loading.value = true
      // Build query params - only include dimension if not 'all'
      const params = {}
      if (selectedDimension.value && selectedDimension.value !== 'all') {
        params.dimension = selectedDimension.value
      }
      const response = await skillAPI.getSkills(params)
      if (response.skills) {
        skills.value = response.skills
      }
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

  const confirmDelete = (skill) => {
    skillToDelete.value = skill
    showDeleteDialog.value = true
  }

  const executeDelete = async () => {
    if (!skillToDelete.value) return

    try {
      deleting.value = true
      await skillAPI.deleteSkill(skillToDelete.value.name)
      toast.success(t('skills.deleteSuccess') || 'Skill deleted successfully')
      showDeleteDialog.value = false
      await loadSkills()
    } catch (error) {
      toast.error(t('skills.deleteFailed') || 'Failed to delete skill')
    } finally {
      deleting.value = false
      skillToDelete.value = null
    }
  }

  // Watch for dimension changes and reload skills
  watch(selectedDimension, () => {
    loadSkills()
  })

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
