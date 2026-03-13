<template>
  <div class="space-y-5">
    <!-- Tools -->
    <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
      <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl" @click="toggleSection('tools')">
        <div class="flex items-center gap-2">
          <Wrench class="h-5 w-5" />
          <CardTitle class="text-base">{{ t('agent.availableTools') }}</CardTitle>
          <span class="text-xs text-muted-foreground ml-2">({{ store.formData.availableTools.length }})</span>
        </div>
        <ChevronDown v-if="sections.tools" class="h-4 w-4" />
        <ChevronUp v-else class="h-4 w-4" />
      </CardHeader>
      <div v-show="!sections.tools" class="px-5 pb-5 pt-4 space-y-3">
        <div class="relative">
          <Search class="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input v-model="searchQueries.tools" placeholder="搜索工具..." class="pl-8" />
        </div>
        
        <!-- Split View for Tools -->
        <div class="flex flex-col md:flex-row h-[500px] md:h-[400px] border rounded-lg overflow-hidden bg-muted/10">
            <!-- Left: Source Groups -->
            <div class="w-full md:w-1/4 border-b md:border-b-0 md:border-r bg-background/50 flex flex-col shrink-0">
                <div class="md:h-full overflow-x-auto md:overflow-x-hidden md:overflow-y-auto">
                    <div class="flex flex-row md:flex-col p-2 gap-2 md:gap-0 md:space-y-1">
                        <button
                            v-for="group in groupedTools"
                            :key="group.source"
                            class="whitespace-nowrap md:whitespace-normal w-auto md:w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 shrink-0"
                            :class="selectedGroupSource === group.source ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted text-muted-foreground'"
                            @click="selectedGroupSource = group.source"
                        >
                            <component :is="getGroupIcon(group.source)" class="h-4 w-4 shrink-0" />
                            <span class="truncate max-w-[100px] md:max-w-none flex-1" :title="getToolSourceLabel(group.source)">{{ getToolSourceLabel(group.source) }}</span>
                            <span class="text-xs opacity-70">{{ group.tools.length }}</span>
                        </button>
                        
                        <div v-if="groupedTools.length === 0" class="text-xs text-muted-foreground text-center py-4 px-2 whitespace-nowrap">
                            无分组
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right: Tool List -->
            <div class="flex-1 bg-background/30 flex flex-col min-w-0 min-h-0">
                <ScrollArea class="h-full">
                    <div class="p-4 grid grid-cols-1 gap-3">
                        <div v-for="tool in displayedTools" :key="tool.name" class="flex items-start space-x-3 p-3 rounded-lg border bg-card hover:bg-accent/5 transition-colors">
                            <Checkbox 
                                :id="`tool-${tool.name}`" 
                                :checked="isRequiredTool(tool.name) || store.formData.availableTools.includes(tool.name)" 
                                :disabled="isRequiredTool(tool.name)"
                                @update:checked="() => !isRequiredTool(tool.name) && store.toggleTool(tool.name)" 
                                class="mt-1"
                            />
                            <div class="grid gap-1.5 leading-none flex-1">
                                <div class="flex items-center gap-2">
                                    <label :for="`tool-${tool.name}`" class="text-sm font-medium leading-none cursor-pointer" :class="{ 'opacity-50': isRequiredTool(tool.name) }">
                                        {{ tool.name }}
                                    </label>
                                    <Badge v-if="isRequiredTool(tool.name)" variant="secondary" class="text-[10px] px-1.5 py-0">
                                        技能必需
                                    </Badge>
                                </div>
                                <p v-if="tool.description" class="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                                    {{ tool.description }}
                                </p>
                            </div>
                        </div>
                         <div v-if="displayedTools.length === 0" class="text-sm text-muted-foreground text-center py-10">
                            {{ groupedTools.length === 0 ? (props.tools.length === 0 ? (t('tools.noTools') || '暂无可用工具') : '未找到匹配的工具') : '该分组下无工具' }}
                        </div>
                    </div>
                </ScrollArea>
            </div>
        </div>
      </div>
    </Card>

    <!-- Skills -->
    <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
      <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl" @click="toggleSection('skills')">
        <div class="flex items-center gap-2">
          <Bot class="h-5 w-5" />
          <CardTitle class="text-base">{{ t('agent.availableSkills') }}</CardTitle>
          <span class="text-xs text-muted-foreground ml-2">({{ store.formData.availableSkills ? store.formData.availableSkills.length : 0 }})</span>
        </div>
        <ChevronDown v-if="sections.skills" class="h-4 w-4" />
        <ChevronUp v-else class="h-4 w-4" />
      </CardHeader>
      <div v-show="!sections.skills" class="px-5 pb-5 pt-4 space-y-3">
         <div class="relative">
           <Search class="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
           <Input v-model="searchQueries.skills" placeholder="搜索技能..." class="pl-8" />
         </div>
         <div v-if="props.loadingSkills" class="flex items-center justify-center py-8">
           <Loader class="h-6 w-6 animate-spin text-primary" />
         </div>
         <ScrollArea v-else class="h-[300px] border rounded-lg p-4 bg-muted/10">
          <div class="space-y-4">
            <div v-for="skill in filteredSkills" :key="skill.name || skill" class="flex items-start space-x-2">
               <Checkbox :id="`skill-${skill.name || skill}`" :checked="store.formData.availableSkills ? store.formData.availableSkills.includes(skill.name || skill) : false" @update:checked="() => store.toggleSkill(skill.name || skill)" class="mt-1" />
               <div class="grid gap-1.5 leading-none flex-1">
                  <div class="flex items-center gap-2">
                    <label :for="`skill-${skill.name || skill}`" class="text-sm font-medium leading-none cursor-pointer">
                      {{ skill.name || skill }}
                    </label>
                    <Badge v-if="skill.source_dimension" :variant="getSkillSourceVariant(skill.source_dimension)" class="text-[10px] px-1.5 py-0">
                      {{ getSkillSourceLabel(skill.source_dimension) }}
                    </Badge>
                  </div>
                  <p v-if="skill.description" class="text-xs text-muted-foreground line-clamp-2">{{ skill.description }}</p>
               </div>
            </div>
            <div v-if="filteredSkills.length === 0" class="text-sm text-muted-foreground text-center py-4">
              {{ props.skills.length === 0 ? (t('skills.noSkills') || '暂无可用技能') : '未找到匹配的技能' }}
            </div>
          </div>
         </ScrollArea>
      </div>
    </Card>

    <!-- Knowledge Bases -->
    <Card class="transition-all hover:shadow-md rounded-xl border bg-background/80 backdrop-blur-sm">
      <CardHeader class="pb-3 pt-4 px-5 bg-muted/30 cursor-pointer flex flex-row items-center justify-between rounded-t-xl" @click="toggleSection('knowledgeBases')">
        <div class="flex items-center gap-2">
          <Database class="h-5 w-5" />
          <CardTitle class="text-base">{{ t('agent.availableKnowledgeBases') }}</CardTitle>
          <span class="text-xs text-muted-foreground ml-2">({{ store.formData.availableKnowledgeBases ? store.formData.availableKnowledgeBases.length : 0 }})</span>
        </div>
        <ChevronDown v-if="sections.knowledgeBases" class="h-4 w-4" />
        <ChevronUp v-else class="h-4 w-4" />
      </CardHeader>
      <div v-show="!sections.knowledgeBases" class="px-5 pb-5 pt-4 space-y-3">
         <div class="relative">
           <Search class="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
           <Input v-model="searchQueries.knowledgeBases" placeholder="搜索知识库..." class="pl-8" />
         </div>
         <ScrollArea class="h-[300px] border rounded-lg p-4 bg-muted/10">
          <div class="space-y-3">
            <div v-for="kb in filteredKnowledgeBases" :key="kb.id" class="flex items-center space-x-2">
              <Checkbox :id="`kb-${kb.id}`" :checked="store.formData.availableKnowledgeBases ? store.formData.availableKnowledgeBases.includes(kb.id) : false" @update:checked="() => store.toggleKnowledgeBase(kb.id)" />
              <label :for="`kb-${kb.id}`" class="text-sm font-medium leading-none cursor-pointer flex-1">
                {{ kb.name }}
                <p v-if="kb.intro" class="text-xs text-muted-foreground line-clamp-1 mt-1 font-normal">{{ kb.intro }}</p>
              </label>
            </div>
            <div v-if="filteredKnowledgeBases.length === 0" class="text-sm text-muted-foreground text-center py-4">
              {{ props.knowledgeBases.length === 0 ? (t('knowledgeBase.noKnowledgeBases') || '暂无可用知识库') : '未找到匹配的知识库' }}
            </div>
          </div>
         </ScrollArea>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'
import { useLanguage } from '../../utils/i18n.js'
import { Trash2, Plus, ChevronDown, ChevronUp, Bot, Wrench, Search, Database, Server, Code, Loader } from 'lucide-vue-next'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] },
  knowledgeBases: { type: Array, default: () => [] },
  loadingSkills: { type: Boolean, default: false }
})

const store = useAgentEditStore()
const { t } = useLanguage()

// Skills关联的必需工具
const REQUIRED_TOOLS_FOR_SKILLS = [
  'file_read',
  'execute_python_code',
  'execute_javascript_code',
  'execute_shell_command',
  'file_write',
  'file_update',
  'load_skill'
]

// 检查工具是否为必需工具（当skills有值时）
const isRequiredTool = (toolName) => {
  const hasSkills = store.formData.availableSkills && store.formData.availableSkills.length > 0
  return hasSkills && REQUIRED_TOOLS_FOR_SKILLS.includes(toolName)
}

// Collapsed state
const sections = reactive({
  tools: false,
  skills: false,
  knowledgeBases: false
})

const searchQueries = reactive({
  tools: '',
  skills: '',
  knowledgeBases: ''
})

const selectedGroupSource = ref('')

// Computed
const filteredTools = computed(() => {
  if (!searchQueries.tools) return props.tools
  const query = searchQueries.tools.toLowerCase()
  return props.tools.filter(tool => 
    tool.name.toLowerCase().includes(query) || 
    (tool.description && tool.description.toLowerCase().includes(query))
  )
})

const groupedTools = computed(() => {
  const groups = {}
  
  // Group tools by source
  filteredTools.value.forEach(tool => {
    const source = tool.source || '未知来源'
    if (!groups[source]) {
      groups[source] = {
        source,
        tools: []
      }
    }
    groups[source].tools.push(tool)
  })
  
  // Sort groups by source name
  return Object.values(groups).sort((a, b) => a.source.localeCompare(b.source))
})

const displayedTools = computed(() => {
   if (!selectedGroupSource.value) return []
   const group = groupedTools.value.find(g => g.source === selectedGroupSource.value)
   return group ? group.tools : []
})

// Watch to set initial selected group
watch(groupedTools, (newGroups) => {
  if (newGroups.length > 0) {
      if (!selectedGroupSource.value || !newGroups.find(g => g.source === selectedGroupSource.value)) {
           selectedGroupSource.value = newGroups[0].source
      }
  } else {
      selectedGroupSource.value = ''
  }
}, { immediate: true })

// Watch skills变化，自动添加必需工具
watch(() => store.formData.availableSkills, (newSkills) => {
  if (newSkills && newSkills.length > 0) {
    // 当skills有值时，自动添加必需工具
    REQUIRED_TOOLS_FOR_SKILLS.forEach(toolName => {
      if (!store.formData.availableTools.includes(toolName)) {
        store.formData.availableTools.push(toolName)
      }
    })
  }
}, { deep: true })

const filteredSkills = computed(() => {
  if (!searchQueries.skills) return props.skills
  const query = searchQueries.skills.toLowerCase()
  return props.skills.filter(skill => {
    const name = skill.name || skill
    const desc = skill.description || ''
    return name.toLowerCase().includes(query) || desc.toLowerCase().includes(query)
  })
})

const filteredKnowledgeBases = computed(() => {
  if (!searchQueries.knowledgeBases) return props.knowledgeBases
  const query = searchQueries.knowledgeBases.toLowerCase()
  return props.knowledgeBases.filter(kb => 
    kb.name.toLowerCase().includes(query) || 
    (kb.intro && kb.intro.toLowerCase().includes(query))
  )
})

const toggleSection = (key) => {
  sections[key] = !sections[key]
}

// Helpers
const getToolSourceLabel = (source) => {
  let displaySource = source
  if (source.startsWith('MCP Server: ')) {
    displaySource = source.replace('MCP Server: ', '')
  } else if (source.startsWith('内置MCP: ')) {
    displaySource = source.replace('内置MCP: ', '')
  }

  const sourceMapping = {
    '基础工具': 'tools.source.basic',
    '内置工具': 'tools.source.builtin',
    '系统工具': 'tools.source.system'
  }

  const translationKey = sourceMapping[displaySource]
  return translationKey ? t(translationKey) : displaySource
}

const getGroupIcon = (source) => {
    if (source.includes('MCP')) return Server
    if (['基础工具', '内置工具', '系统工具'].includes(source)) return Code
    return Wrench
}

const getSkillSourceVariant = (dimension) => {
    switch (dimension) {
        case 'system': return 'secondary'
        case 'user': return 'default'
        case 'agent': return 'outline'
        default: return 'secondary'
    }
}

const getSkillSourceLabel = (dimension) => {
    const labels = {
        'system': t('skills.system') || '系统',
        'user': t('skills.user') || '用户',
        'agent': t('skills.agent') || 'Agent'
    }
    return labels[dimension] || dimension
}
</script>
