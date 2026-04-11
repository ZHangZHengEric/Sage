<template>
  <div class="skill-content h-full overflow-auto p-6">
    <div v-if="skillLoading" class="flex items-center justify-center h-full text-muted-foreground">
      <div class="animate-spin mr-2">
        <Settings class="w-5 h-5" />
      </div>
      {{ t('workbench.tool.loadingSkill') }}
    </div>
    <div v-else-if="skillError" class="text-red-500">
      {{ skillError }}
    </div>
    <div v-else-if="skillInfo.description">
      <div class="text-lg font-semibold mb-4">{{ skillInfo.name }}</div>
      <div class="text-sm text-muted-foreground mb-6">{{ skillInfo.description }}</div>
      <div v-if="skillInfo.content" class="skill-markdown">
        <MarkdownRenderer :content="skillInfo.content" />
      </div>
    </div>
    <div v-else>
      <div class="text-sm text-muted-foreground">{{ t('workbench.tool.loadingSkillWait', { name: skillName }) }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { Settings } from 'lucide-vue-next'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { skillAPI } from '@/api/skill.js'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const skillName = computed(() => props.toolArgs.skill_name || '')
const skillInfo = ref({ name: '', description: '', content: '' })
const skillLoading = ref(false)
const skillError = ref('')

const fetchSkillInfo = async () => {
  if (!skillName.value) return
  skillLoading.value = true
  skillError.value = ''
  try {
    const result = await skillAPI.getSkillContent(skillName.value)
    if (!result) return
    let name = result.name || skillName.value
    let description = result.description || ''
    let content = result.content || ''
    if (content && !description) {
      const nameMatch = content.match(/^name:\s*(.+)$/m)
      const descMatch = content.match(/^description:\s*(.+)$/m)
      if (nameMatch) {
        name = nameMatch[1].trim()
        content = content.replace(/^name:\s*.+$/m, '').trim()
      }
      if (descMatch) {
        description = descMatch[1].trim()
        content = content.replace(/^description:\s*.+$/m, '').trim()
      }
    }
    skillInfo.value = { name, description, content }
  } catch (error) {
    skillError.value = t('workbench.tool.loadingSkillError') + ': ' + (error?.message || 'Unknown Error')
  } finally {
    skillLoading.value = false
  }
}

watch(skillName, (newVal, oldVal) => {
  if (newVal !== oldVal) {
    skillInfo.value = { name: '', description: '', content: '' }
    skillError.value = ''
    if (newVal) fetchSkillInfo()
  }
})

onMounted(() => {
  if (skillName.value) fetchSkillInfo()
})
</script>
