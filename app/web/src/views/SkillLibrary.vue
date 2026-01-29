<template>
  <div class="skill-page">
    <div class="header-section">
      <div class="header-content">
        <h1 class="page-title">{{ t('skills.title') }}</h1>
        <p class="page-subtitle">{{ t('skills.subtitle') }}</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="showImportModal = true">
          <el-icon class="el-icon--left"><Plus /></el-icon>
          {{ t('skills.import') }}
        </el-button>
      </div>
    </div>

    <div class="list-content" v-loading="loading">
      <div class="filter-tabs-row">
        <div class="search-box">
          <el-input
            v-model="searchTerm"
            :placeholder="t('skills.search')"
            prefix-icon="Search"
            clearable
            class="search-input"
          />
        </div>
      </div>

      <div class="skills-section">
        <div v-if="filteredSkills.length > 0" class="skills-grid">
          <div v-for="skill in filteredSkills" :key="skill.name" class="skill-card-wrapper">
            <el-card class="skill-card" shadow="hover">
              <div class="skill-header">
                <div class="skill-icon">
                  <Box :size="24" />
                </div>
                <div class="skill-info">
                  <h3 class="skill-name">{{ skill.name }}</h3>
                  <el-tooltip
                    :content="skill.description || t('skills.noDescription')"
                    placement="top"
                    :show-after="500"
                  >
                    <p class="skill-description">
                      {{ skill.description || t('skills.noDescription') }}
                    </p>
                  </el-tooltip>
                </div>
              </div>
              
              <div class="skill-footer">
                <div class="skill-path" :title="skill.path">
                  <el-icon><Folder /></el-icon>
                  <span>{{ getFolderName(skill.path) }}</span>
                </div>
              </div>
            </el-card>
          </div>
        </div>

        <el-empty
          v-else
          :description="t('skills.noSkillsDesc')"
        >
          <template #image>
            <Box :size="60" style="color: var(--el-text-color-secondary)" />
          </template>
        </el-empty>
      </div>
    </div>

    <!-- Import Modal -->
    <el-dialog
      v-model="showImportModal"
      :title="t('skills.import')"
      width="500px"
      destroy-on-close
    >
      <el-tabs v-model="importMode" class="import-tabs">
        <el-tab-pane :label="t('skills.upload')" name="upload">
          <div class="upload-section">
            <el-upload
              class="upload-demo"
              drag
              action="#"
              :auto-upload="false"
              :on-change="handleFileChange"
              :limit="1"
              :show-file-list="true"
              accept=".zip"
              ref="uploadRef"
            >
              <el-icon class="el-icon--upload"><upload-filled /></el-icon>
              <div class="el-upload__text">
                Drop file here or <em>click to upload</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  Only .zip files are allowed
                </div>
              </template>
            </el-upload>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="t('skills.urlImport')" name="url">
          <div class="url-section">
            <el-input
              v-model="importUrl"
              :placeholder="t('skills.urlPlaceholder')"
              clearable
            >
              <template #prepend>HTTPS</template>
            </el-input>
          </div>
        </el-tab-pane>
      </el-tabs>

      <div v-if="importError" class="error-message">
        {{ importError }}
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showImportModal = false">{{ t('skills.cancel') }}</el-button>
          <el-button type="primary" @click="handleImport" :loading="importing" :disabled="isImportDisabled">
            {{ t('skills.confirm') }}
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Box } from 'lucide-vue-next'
import { Plus, Search, Folder, UploadFilled } from '@element-plus/icons-vue'
import { useLanguage } from '../utils/i18n.js'
import { skillAPI } from '../api/skill.js'
import { ElMessage } from 'element-plus'

const { t } = useLanguage()

const skills = ref([])
const loading = ref(false)
const searchTerm = ref('')
const showImportModal = ref(false)
const importMode = ref('upload') // 'upload' or 'url'
const selectedFile = ref(null)
const importUrl = ref('')
const importing = ref(false)
const importError = ref('')
const uploadRef = ref(null)

const filteredSkills = computed(() => {
  if (!searchTerm.value.trim()) return skills.value
  const query = searchTerm.value.toLowerCase()
  return skills.value.filter(skill => 
    skill.name.toLowerCase().includes(query) || 
    (skill.description && skill.description.toLowerCase().includes(query))
  )
})

const isImportDisabled = computed(() => {
  if (importMode.value === 'upload') {
    return !selectedFile.value
  } else {
    return !importUrl.value
  }
})

const loadSkills = async () => {
  try {
    loading.value = true
    const response = await skillAPI.getSkills()
    if (response.skills) {
      skills.value = response.skills
    }
  } catch (error) {
    console.error('Failed to load skills:', error)
    ElMessage.error(t('skills.loadError') || 'Failed to load skills')
  } finally {
    loading.value = false
  }
}

const getFolderName = (path) => {
  if (!path) return ''
  const parts = path.split(/[/\\]/)
  return parts[parts.length - 1]
}

const handleFileChange = (uploadFile) => {
  const file = uploadFile.raw
  if (file) {
    if (!file.name.endsWith('.zip')) {
      importError.value = 'Only ZIP files are supported'
      ElMessage.warning('Only ZIP files are supported')
      uploadRef.value.clearFiles()
      selectedFile.value = null
      return
    }
    selectedFile.value = file
    importError.value = ''
  }
}

const handleImport = async () => {
  importing.value = true
  importError.value = ''
  
  try {
    if (importMode.value === 'upload') {
      if (!selectedFile.value) return
      await skillAPI.uploadSkill(selectedFile.value)
    } else {
      if (!importUrl.value) return
      await skillAPI.importSkillFromUrl(importUrl.value)
    }
    
    // Success
    ElMessage.success(t('skills.importSuccess') || 'Skill imported successfully')
    showImportModal.value = false
    selectedFile.value = null
    importUrl.value = ''
    if (uploadRef.value) uploadRef.value.clearFiles()
    loadSkills() // Reload list
  } catch (error) {
    importError.value = error.message || 'Import failed'
    ElMessage.error(error.message || 'Import failed')
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadSkills()
})
</script>

<style scoped>
.skill-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 24px;
  overflow: hidden;
  background-color: var(--el-bg-color);
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0;
}

.page-subtitle {
  color: var(--el-text-color-secondary);
  margin: 4px 0 0;
  font-size: 14px;
}

.list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.filter-tabs-row {
  display: flex;
  margin-bottom: 20px;
}

.search-box {
  width: 300px;
}

.skills-section {
  flex: 1;
  overflow-y: auto;
}

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
  padding-bottom: 24px;
}

.skill-card-wrapper {
  height: 100%;
}

.skill-card {
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s;
  cursor: pointer;
}

.skill-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--el-box-shadow);
}

.skill-header {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.skill-icon {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.skill-info {
  flex: 1;
  min-width: 0;
}

.skill-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0 0 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-description {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}

.skill-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.skill-path {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.error-message {
  margin-top: 12px;
  color: var(--el-color-danger);
  font-size: 13px;
}

.upload-section, .url-section {
  padding: 10px 0;
}
</style>
