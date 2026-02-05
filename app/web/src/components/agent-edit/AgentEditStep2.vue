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
      <div v-show="!sections.tools" class="px-5 pb-5 pt-4">
        <ScrollArea class="h-[200px] border rounded-lg p-4 bg-muted/10">
          <div class="space-y-3">
            <div v-for="tool in props.tools" :key="tool.name" class="flex items-center space-x-2">
              <Checkbox :id="`tool-${tool.name}`" :checked="store.formData.availableTools.includes(tool.name)" @update:checked="() => store.toggleTool(tool.name)" />
              <label :for="`tool-${tool.name}`" class="text-sm font-medium leading-none cursor-pointer flex-1">
                {{ tool.name }}
                <p v-if="tool.description" class="text-xs text-muted-foreground line-clamp-1 mt-1 font-normal">{{ tool.description}}</p>
              </label>
            </div>
            <div v-if="props.tools.length === 0" class="text-sm text-muted-foreground text-center py-4">
              {{ t('tools.noTools') || '暂无可用工具' }}
            </div>
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
      <div v-show="!sections.skills" class="px-5 pb-5 pt-4">
         <ScrollArea class="h-[200px] border rounded-lg p-4 bg-muted/10">
          <div class="space-y-4">
            <div v-for="skill in props.skills" :key="skill.name || skill" class="flex items-start space-x-2">
               <Checkbox :id="`skill-${skill.name || skill}`" :checked="store.formData.availableSkills ? store.formData.availableSkills.includes(skill.name || skill) : false" @update:checked="() => store.toggleSkill(skill.name || skill)" class="mt-1" />
               <div class="grid gap-1.5 leading-none flex-1">
                  <label :for="`skill-${skill.name || skill}`" class="text-sm font-medium leading-none cursor-pointer">
                    {{ skill.name || skill }}
                  </label>
                  <p v-if="skill.description" class="text-xs text-muted-foreground line-clamp-2">{{ skill.description }}</p>
               </div>
            </div>
            <div v-if="props.skills.length === 0" class="text-sm text-muted-foreground text-center py-4">
              {{ t('skills.noSkills') || '暂无可用技能' }}
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
      <div v-show="!sections.knowledgeBases" class="px-5 pb-5 pt-4">
         <ScrollArea class="h-[200px] border rounded-lg p-4 bg-muted/10">
          <div class="space-y-3">
            <div v-for="kb in props.knowledgeBases" :key="kb.id" class="flex items-center space-x-2">
              <Checkbox :id="`kb-${kb.id}`" :checked="store.formData.availableKnowledgeBases ? store.formData.availableKnowledgeBases.includes(kb.id) : false" @update:checked="() => store.toggleKnowledgeBase(kb.id)" />
              <label :for="`kb-${kb.id}`" class="text-sm font-medium leading-none cursor-pointer flex-1">
                {{ kb.name }}
                <p v-if="kb.intro" class="text-xs text-muted-foreground line-clamp-1 mt-1 font-normal">{{ kb.intro }}</p>
              </label>
            </div>
            <div v-if="props.knowledgeBases.length === 0" class="text-sm text-muted-foreground text-center py-4">
              {{ t('knowledgeBase.noKnowledgeBases') || '暂无可用知识库' }}
            </div>
          </div>
         </ScrollArea>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useAgentEditStore } from '../../stores/agentEdit'
import { useLanguage } from '../../utils/i18n.js'
import { Trash2, Plus, ChevronDown, ChevronUp, Bot, Wrench } from 'lucide-vue-next'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'

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

const toggleSection = (key) => {
  sections[key] = !sections[key]
}
</script>
