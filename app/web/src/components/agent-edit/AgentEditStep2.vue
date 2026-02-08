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
        <ScrollArea class="h-[300px] border rounded-lg p-4 bg-muted/10">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div v-for="tool in filteredTools" :key="tool.name" class="flex items-center space-x-2">
              <Checkbox :id="`tool-${tool.name}`" :checked="store.formData.availableTools.includes(tool.name)" @update:checked="() => store.toggleTool(tool.name)" />
              <label :for="`tool-${tool.name}`" class="text-sm font-medium leading-none cursor-pointer flex-1">
                {{ tool.name }}
                <p v-if="tool.description" class="text-xs text-muted-foreground line-clamp-1 mt-1 font-normal">{{ tool.description}}</p>
              </label>
            </div>
          </div>
          <div v-if="filteredTools.length === 0" class="text-sm text-muted-foreground text-center py-4">
            {{ props.tools.length === 0 ? (t('tools.noTools') || '暂无可用工具') : '未找到匹配的工具' }}
          </div>
        </ScrollArea>
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
import { ref, reactive, computed } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'
import { useLanguage } from '../../utils/i18n.js'
import { Trash2, Plus, ChevronDown, ChevronUp, Bot, Wrench, Search, Database } from 'lucide-vue-next'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'

const props = defineProps({
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] },
  knowledgeBases: { type: Array, default: () => [] }
})

const store = useAgentEditStore()
const { t } = useLanguage()

// Collapsed state (true = collapsed, false = open)
// Default to open for visibility, or closed if too many?
// Requirement says "collapsible cards", implying they can be toggled.
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

const filteredTools = computed(() => {
  if (!searchQueries.tools) return props.tools
  const query = searchQueries.tools.toLowerCase()
  return props.tools.filter(tool => 
    tool.name.toLowerCase().includes(query) || 
    (tool.description && tool.description.toLowerCase().includes(query))
  )
})

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
</script>
