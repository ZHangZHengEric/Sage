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
                                :checked="store.formData.availableTools.includes(tool.name)" 
                                @update:checked="() => store.toggleTool(tool.name)" 
                                class="mt-1"
                            />
                            <div class="grid gap-1.5 leading-none flex-1">
                                <label :for="`tool-${tool.name}`" class="text-sm font-medium leading-none cursor-pointer">
                                    {{ tool.name }}
                                </label>
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
         <ScrollArea class="h-[300px] border rounded-lg p-4 bg-muted/10">
          <div class="space-y-4">
            <div v-for="skill in filteredSkills" :key="skill.name || skill" class="flex items-start space-x-2">
               <Checkbox :id="`skill-${skill.name || skill}`" :checked="store.formData.availableSkills ? store.formData.availableSkills.includes(skill.name || skill) : false" @update:checked="() => store.toggleSkill(skill.name || skill)" class="mt-1" />
               <div class="grid gap-1.5 leading-none flex-1">
                  <label :for="`skill-${skill.name || skill}`" class="text-sm font-medium leading-none cursor-pointer">
                    {{ skill.name || skill }}
                  </label>
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
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'
import { useLanguage } from '../../utils/i18n.js'
import { Trash2, Plus, ChevronDown, ChevronUp, Bot, Wrench, Search, Server, Code } from 'lucide-vue-next'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'

const props = defineProps({
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] }
})

const store = useAgentEditStore()
const { t } = useLanguage()

// Collapsed state
const sections = reactive({
  tools: false,
  skills: false
})

const searchQueries = reactive({
  tools: '',
  skills: ''
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

const filteredSkills = computed(() => {
  if (!searchQueries.skills) return props.skills
  const query = searchQueries.skills.toLowerCase()
  return props.skills.filter(skill => {
    const name = skill.name || skill
    const desc = skill.description || ''
    return name.toLowerCase().includes(query) || desc.toLowerCase().includes(query)
  })
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
</script>
