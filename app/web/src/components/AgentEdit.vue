<template>
  <div class="h-full flex flex-col bg-gradient-to-b from-background to-muted/20 border shadow-sm overflow-hidden">
    <!-- Header with Agent Name -->
    <div class="px-4 py-2.5 border-b bg-background/95 backdrop-blur flex items-center justify-between shrink-0">
      <div class="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          @click="handleReturn"
          class="text-muted-foreground hover:text-foreground h-7 w-7"
        >
          <ChevronLeft class="h-4 w-4" />
        </Button>
        <div class="flex items-center gap-2">
          <h1 class="text-sm font-medium">{{ isEditMode ? t('agent.editTitle') : t('agent.createTitle') }}</h1>
          <span class="text-xs text-muted-foreground/60">{{ store.formData.name || t('agent.unnamed') }}</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          @click="handleSave(false)"
          :disabled="saving || !store.isStep1Valid"
          class="h-7 text-xs px-3"
        >
          <Loader v-if="saving" class="mr-1.5 h-3 w-3 animate-spin" />
          <Save v-else class="mr-1.5 h-3 w-3" />
          {{ t('common.save') }}
        </Button>
        <Button
          @click="handleSave(true)"
          :disabled="saving || !store.isStep1Valid"
          size="sm"
          class="bg-primary hover:bg-primary/90 h-7 text-xs px-3"
        >
          <Loader v-if="saving" class="mr-1.5 h-3 w-3 animate-spin" />
          <Check v-else class="mr-1.5 h-3 w-3" />
          {{ t('common.saveAndExit') }}
        </Button>
      </div>
    </div>

    <!-- Main Content: Left Sidebar + Right Content -->
    <div class="flex-1 flex min-h-0">
      <!-- Left Sidebar - Navigation -->
      <div class="w-48 border-r bg-muted/20 flex flex-col shrink-0 overflow-y-auto">
        <nav class="py-3 px-2 space-y-0.5">
          <button
            v-for="section in sections"
            :key="section.id"
            @click="scrollToSection(section.id)"
            class="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-xs transition-all duration-200"
            :class="activeSection === section.id ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground/70 hover:bg-muted/60 hover:text-foreground'"
          >
            <component :is="section.icon" class="h-3.5 w-3.5 shrink-0" />
            <span class="truncate">{{ section.label }}</span>
          </button>
        </nav>
      </div>

      <!-- Right Content - Scrollable -->
      <div ref="contentRef" class="flex-1 overflow-y-auto scroll-smooth min-h-0 bg-background">
        <div class="max-w-3xl mx-auto py-8 px-8 space-y-10">
          <!-- Basic Info Section -->
          <section id="basic" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <User class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.basicInfo') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">设置Agent的名称、描述和系统提示词，这些是Agent的基本配置。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-2">
                <p class="text-xs text-muted-foreground">配置Agent的基本信息和系统提示词</p>
              </div>
            </div>
            <div class="space-y-5 pl-10">
              <FormItem :label="t('agent.name')" :error="store.errors.name" required>
                <Input
                  v-model="store.formData.name"
                  :placeholder="t('agent.namePlaceholder')"
                  :disabled="store.formData.id === 'default'"
                  class="h-10"
                />
              </FormItem>

              <FormItem :label="t('agent.description')" :error="store.errors.description">
                <Textarea
                  v-model="store.formData.description"
                  :rows="3"
                  :placeholder="t('agent.descriptionPlaceholder')"
                  class="resize-none"
                />
              </FormItem>

              <FormItem :error="store.errors.systemPrefix">
                <div class="flex justify-between items-center mb-2">
                  <Label :class="store.errors.systemPrefix ? 'text-destructive' : ''">{{ t('agent.systemPrefix') }}</Label>
                  <Button
                    size="sm"
                    variant="ghost"
                    class="flex items-center gap-1 text-foreground hover:bg-transparent h-7"
                    @click="showOptimizeModal = true"
                    :disabled="isOptimizing"
                  >
                    <Sparkles class="h-3.5 w-3.5 text-yellow-400" />
                    <span class="text-xs">AI优化</span>
                  </Button>
                </div>
                <Textarea
                  v-model="store.formData.systemPrefix"
                  :rows="10"
                  :placeholder="t('agent.systemPrefixPlaceholder')"
                  class="font-mono text-sm"
                />
              </FormItem>
            </div>
          </section>

          <!-- Strategy Section -->
          <section id="strategy" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Cpu class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.strategy') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">配置Agent的运行策略，包括记忆类型、工作模式、深度思考等行为设置。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            <div class="space-y-6 pl-10">
              <!-- Row 1: Memory Type & Agent Mode -->
              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <FormItem :label="t('agent.memoryType')">
                  <Select v-model="store.formData.memoryType">
                    <SelectTrigger class="h-10">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="session">{{ t('agent.sessionMemory') }}</SelectItem>
                      <SelectItem value="user">{{ t('agent.userMemory') }}</SelectItem>
                    </SelectContent>
                  </Select>
                </FormItem>

                <FormItem :label="t('agent.agentMode')">
                  <Select v-model="store.formData.agentMode">
                    <SelectTrigger class="h-10">
                      <SelectValue :placeholder="t('agent.modeAuto')" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="fibre">{{ t('agent.modeFibre') }}</SelectItem>
                      <SelectItem value="simple">{{ t('agent.modeSimple') }}</SelectItem>
                      <SelectItem value="multi">{{ t('agent.modeMulti') }}</SelectItem>
                    </SelectContent>
                  </Select>
                </FormItem>
              </div>

              <!-- Row 2: Deep Thinking, More Suggest, Max Loop -->
              <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <FormItem :label="t('agent.deepThinking')">
                  <Tabs :model-value="getSelectValue(store.formData.deepThinking)" @update:model-value="(v) => setSelectValue('deepThinking', v)">
                    <TabsList class="grid w-full grid-cols-3 h-10">
                      <TabsTrigger value="auto">{{ t('agent.auto') }}</TabsTrigger>
                      <TabsTrigger value="enabled">{{ t('agent.enabled') }}</TabsTrigger>
                      <TabsTrigger value="disabled">{{ t('agent.disabled') }}</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </FormItem>

                <FormItem :label="t('agent.moreSuggest')">
                  <div class="flex items-center h-10 gap-3 border rounded-md px-3 bg-background">
                    <Switch :checked="store.formData.moreSuggest" @update:checked="(v) => store.formData.moreSuggest = v" />
                    <span class="text-sm text-muted-foreground">{{ store.formData.moreSuggest ? t('agent.enabled') : t('agent.disabled') }}</span>
                  </div>
                </FormItem>

                <FormItem :label="t('agent.maxLoopCount')">
                  <Input type="number" v-model.number="store.formData.maxLoopCount" min="1" max="50" class="h-10" />
                </FormItem>
              </div>

              <!-- Row 3: Model Provider -->
              <FormItem :label="t('agent.modelProvider')">
                <Select v-model="llmProviderSelectValue">
                  <SelectTrigger class="h-10">
                    <SelectValue :placeholder="t('agent.selectModelProvider')" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="provider in providers" :key="provider.id" :value="provider.id">
                      <div class="flex items-center gap-2">
                        <span>{{ provider.name }} ({{ provider.model }})</span>
                        <div class="flex items-center gap-1 ml-2">
                          <!-- 文本输入图标 (默认) -->
                          <span class="inline-flex items-center justify-center w-4 h-4 text-[10px] font-medium bg-primary/10 text-primary rounded">T</span>
                          <!-- 多模态图像图标 -->
                          <ImageIcon v-if="provider.supports_multimodal" class="w-4 h-4 text-primary" />
                        </div>
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </FormItem>

              <!-- Row 3.5: Enable Multimodal -->
              <FormItem label="开启多模态">
                <div class="flex items-center h-10 gap-3 border rounded-md px-3 bg-background">
                  <Switch 
                    :checked="store.formData.enableMultimodal" 
                    @update:checked="(v) => store.formData.enableMultimodal = v"
                    :disabled="!selectedProviderSupportsMultimodal"
                  />
                  <span class="text-sm text-muted-foreground">
                    {{ store.formData.enableMultimodal ? '已开启' : '已关闭' }}
                    <span v-if="!selectedProviderSupportsMultimodal" class="text-xs text-destructive ml-2">(当前模型源不支持多模态)</span>
                  </span>
                </div>
              </FormItem>

              <!-- Row 4: Sub Agent Selection (Only for Fibre Mode) -->
              <FormItem v-if="store.formData.agentMode === 'fibre'" label="子智能体" class="pt-4 border-t">
                <div class="border rounded-lg overflow-hidden bg-background">
                  <div class="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
                    <span class="text-xs font-medium text-muted-foreground">可选子智能体 ({{ filteredAgents.length }})</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-7 text-xs px-2"
                      @click="selectAllSubAgents"
                      :disabled="filteredAgents.length === 0"
                    >
                      全选
                    </Button>
                  </div>
                  <ScrollArea class="h-[200px]">
                    <div class="p-3">
                      <div class="flex flex-wrap gap-2">
                        <button
                          v-for="agent in filteredAgents"
                          :key="agent.id"
                          type="button"
                          class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm transition-all duration-200 border"
                          :class="isSubAgentSelected(agent.id) 
                            ? 'bg-primary/10 border-primary/40 text-primary hover:bg-primary/20' 
                            : 'bg-muted/30 border-muted hover:bg-muted/50 hover:border-muted-foreground/30'"
                          @click="toggleSubAgent(agent.id, !isSubAgentSelected(agent.id))"
                        >
                          <span 
                            class="w-2 h-2 rounded-full"
                            :class="isSubAgentSelected(agent.id) ? 'bg-green-500' : 'bg-gray-400'"
                          ></span>
                          <span class="truncate max-w-[120px]">{{ agent.name }}</span>
                        </button>
                      </div>
                    </div>
                  </ScrollArea>
                </div>
              </FormItem>
            </div>
          </section>

          <!-- Tools Section -->
          <section id="tools" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Wrench class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.availableTools') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">选择Agent可以使用的工具，这些工具将增强Agent的能力。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-2">
                <p class="text-xs text-muted-foreground">选择Agent可以使用的工具</p>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <div class="flex flex-col md:flex-row h-[400px] border rounded-lg overflow-hidden bg-muted/5">
                <!-- Left: Source Groups -->
                <div class="w-full md:w-48 border-b md:border-b-0 md:border-r bg-muted/20 flex flex-col shrink-0">
                  <div class="p-2 space-y-1 overflow-y-auto">
                    <button
                      v-for="group in groupedTools"
                      :key="group.source"
                      class="w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2"
                      :class="selectedGroupSource === group.source ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted/50 text-muted-foreground/70'"
                      @click="selectedGroupSource = group.source"
                    >
                      <component :is="getGroupIcon(group.source)" class="h-3.5 w-3.5 shrink-0" />
                      <span class="truncate flex-1">{{ getToolSourceLabel(group.source) }}</span>
                      <span class="text-xs opacity-60">{{ group.tools.length }}</span>
                    </button>
                  </div>
                </div>

                <!-- Right: Tool List -->
                <div class="flex-1 bg-background flex flex-col min-w-0">
                  <div class="p-3 border-b flex items-center justify-between gap-3">
                    <div class="relative flex-1">
                      <Search class="absolute left-2 top-2 h-4 w-4 text-muted-foreground/70" />
                      <Input v-model="searchQueries.tools" placeholder="搜索工具..." class="pl-8 h-9" />
                    </div>
                    <div class="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-8 text-xs px-2"
                        @click="selectAllToolsInGroup"
                        :disabled="displayedTools.length === 0"
                      >
                        全选
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-8 text-xs px-2"
                        @click="deselectAllToolsInGroup"
                        :disabled="displayedTools.length === 0"
                      >
                        取消
                      </Button>
                    </div>
                  </div>
                  <ScrollArea class="flex-1">
                    <div class="p-4 space-y-2">
                      <div v-for="tool in displayedTools" :key="tool.name" class="flex items-start gap-3 p-3 rounded-lg border border-muted/50 hover:bg-accent/5 transition-colors">
                        <Checkbox 
                          :id="`tool-${tool.name}`" 
                          :checked="isRequiredTool(tool.name) || store.formData.availableTools.includes(tool.name)" 
                          :disabled="isRequiredTool(tool.name)"
                          @update:checked="() => !isRequiredTool(tool.name) && store.toggleTool(tool.name)" 
                          class="mt-0.5"
                        />
                        <div class="flex-1 min-w-0">
                          <div class="flex items-center gap-2">
                            <label :for="`tool-${tool.name}`" class="text-sm font-medium cursor-pointer" :class="{ 'opacity-50': isRequiredTool(tool.name) }">
                              {{ tool.name }}
                            </label>
                            <Badge v-if="isRequiredTool(tool.name)" variant="secondary" class="text-[10px] h-5 px-1.5">技能必需</Badge>
                          </div>
                          <p v-if="tool.description" class="text-xs text-muted-foreground line-clamp-2 mt-1">
                            {{ tool.description }}
                          </p>
                        </div>
                      </div>
                    </div>
                  </ScrollArea>
                </div>
              </div>
            </div>
          </section>

          <!-- Skills Section -->
          <section id="skills" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Bot class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.availableSkills') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">选择Agent可以使用的技能，技能是预定义的能力模块。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-auto flex items-center gap-2">
                <span class="text-xs text-muted-foreground">({{ store.formData.availableSkills?.length || 0 }})</span>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <!-- Selected Skills Tags -->
              <div v-if="selectedSkills.length > 0" class="flex flex-wrap gap-2 p-3 border rounded-lg bg-muted/5">
                <Badge
                  v-for="skill in selectedSkills"
                  :key="skill.name || skill"
                  variant="secondary"
                  class="text-xs px-2 py-1 h-auto cursor-pointer hover:bg-destructive/10 hover:text-destructive transition-colors"
                  @click="store.toggleSkill(skill.name || skill)"
                >
                  {{ skill.name || skill }}
                  <X class="h-3 w-3 ml-1" />
                </Badge>
              </div>
              
              <!-- Skills Selection Area -->
              <div class="h-[350px] border rounded-lg overflow-hidden bg-muted/5">
                <div class="p-3 border-b flex items-center justify-between gap-3">
                  <div class="relative flex-1">
                    <Search class="absolute left-2 top-2 h-4 w-4 text-muted-foreground/70" />
                    <Input v-model="searchQueries.skills" placeholder="搜索技能..." class="pl-8 h-9" />
                  </div>
                  <div class="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-8 text-xs px-2"
                      @click="selectAllSkills"
                      :disabled="filteredSkills.length === 0"
                    >
                      全选
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-8 text-xs px-2"
                      @click="deselectAllSkills"
                      :disabled="store.formData.availableSkills?.length === 0"
                    >
                      取消
                    </Button>
                  </div>
                </div>
                <ScrollArea class="h-[calc(350px-57px)]">
                  <div class="p-4 space-y-2">
                    <div v-for="skill in filteredSkills" :key="skill.name || skill" 
                      class="flex items-start gap-3 p-3 rounded-lg border border-muted/50 hover:bg-accent/5 transition-colors cursor-pointer"
                      @click="store.toggleSkill(skill.name || skill)"
                    >
                      <Checkbox 
                        :id="`skill-${skill.name || skill}`" 
                        :checked="store.formData.availableSkills?.includes(skill.name || skill)" 
                        @update:checked="() => store.toggleSkill(skill.name || skill)" 
                        class="mt-0.5 pointer-events-none"
                      />
                      <div class="flex-1 min-w-0">
                        <label :for="`skill-${skill.name || skill}`" class="text-sm font-medium cursor-pointer pointer-events-none">
                          {{ skill.name || skill }}
                        </label>
                        <p v-if="skill.description" class="text-xs text-muted-foreground line-clamp-2 mt-1">{{ skill.description }}</p>
                      </div>
                    </div>
                  </div>
                </ScrollArea>
              </div>
            </div>
          </section>

          <!-- Knowledge Bases Section -->
          <section id="knowledgeBases" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Database class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.availableKnowledgeBases') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">选择Agent可以访问的知识库，知识库提供额外的领域知识。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-auto flex items-center gap-2">
                <span class="text-xs text-muted-foreground">({{ store.formData.availableKnowledgeBases?.length || 0 }})</span>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <div class="h-[350px] border rounded-lg overflow-hidden bg-muted/5">
                <div class="p-3 border-b flex items-center justify-between gap-3">
                  <div class="relative flex-1">
                    <Search class="absolute left-2 top-2 h-4 w-4 text-muted-foreground/70" />
                    <Input v-model="searchQueries.knowledgeBases" placeholder="搜索知识库..." class="pl-8 h-9" />
                  </div>
                  <div class="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-8 text-xs px-2"
                      @click="selectAllKnowledgeBases"
                      :disabled="filteredKnowledgeBases.length === 0"
                    >
                      全选
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-8 text-xs px-2"
                      @click="deselectAllKnowledgeBases"
                      :disabled="store.formData.availableKnowledgeBases?.length === 0"
                    >
                      取消
                    </Button>
                  </div>
                </div>
                <ScrollArea class="h-[calc(350px-57px)]">
                  <div class="p-4 space-y-2">
                    <div v-for="kb in filteredKnowledgeBases" :key="kb.id" 
                      class="flex items-start gap-3 p-3 rounded-lg border border-muted/50 hover:bg-accent/5 transition-colors cursor-pointer"
                      @click="toggleKnowledgeBase(kb.id)"
                    >
                      <Checkbox 
                        :id="`kb-${kb.id}`" 
                        :checked="store.formData.availableKnowledgeBases?.includes(kb.id)" 
                        @update:checked="() => toggleKnowledgeBase(kb.id)" 
                        class="mt-0.5 pointer-events-none"
                      />
                      <div class="flex-1 min-w-0">
                        <label :for="`kb-${kb.id}`" class="text-sm font-medium cursor-pointer pointer-events-none">
                          {{ kb.name }}
                        </label>
                        <p v-if="kb.intro" class="text-xs text-muted-foreground line-clamp-2 mt-1">{{ kb.intro }}</p>
                      </div>
                    </div>
                  </div>
                </ScrollArea>
              </div>
            </div>
          </section>

          <!-- System Context Section -->
          <section id="context" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <FileText class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.systemContext') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">为Agent提供预设的静态知识或上下文信息，帮助Agent更好地理解任务和环境。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-auto flex items-center gap-2">
                <span class="text-xs text-muted-foreground">({{ store.systemContextPairs.filter(p => p.key).length }})</span>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <div v-for="(pair, index) in store.systemContextPairs" :key="index" class="flex items-center gap-3">
                <Input
                  :model-value="pair.key"
                  :placeholder="t('agent.contextKey')"
                  @input="store.updateSystemContextPair(index, 'key', $event.target.value)"
                  class="flex-1 h-9"
                />
                <Input
                  :model-value="pair.value"
                  :placeholder="t('agent.contextValue')"
                  @input="store.updateSystemContextPair(index, 'value', $event.target.value)"
                  class="flex-1 h-9"
                />
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-9 w-9 text-destructive hover:text-destructive hover:bg-destructive/10"
                  @click="store.removeSystemContextPair(index)"
                  :disabled="store.systemContextPairs.length === 1 && !pair.key && !pair.value"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </div>
              <Button variant="outline" size="sm" class="w-full border-dashed h-9" @click="store.addSystemContextPair">
                <Plus class="h-3.5 w-3.5 mr-2" /> {{ t('agent.addContext') }}
              </Button>
            </div>
          </section>

          <!-- Workflows Section -->
          <section id="workflows" class="scroll-mt-6 pb-8">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Workflow class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.workflows') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">定义结构化的任务流程，让Agent按步骤执行复杂任务，提高任务完成的一致性和可靠性。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-2">
                <p class="text-xs text-muted-foreground">定义结构化的任务流程，让Agent按步骤执行复杂任务</p>
                <span class="text-xs text-muted-foreground">({{ store.workflowPairs.filter(w => w.key).length }})</span>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <div v-for="(workflow, index) in store.workflowPairs" :key="workflow.id || index" class="border border-muted/50 rounded-lg p-4 bg-muted/5">
                <div class="flex items-center gap-2 mb-3">
                  <Button variant="ghost" size="sm" class="h-8 w-8 p-0" @click="toggleWorkflow(workflow.id)">
                    <ChevronDown v-if="isWorkflowExpanded(workflow.id)" class="h-4 w-4" />
                    <ChevronRight v-else class="h-4 w-4" />
                  </Button>
                  <Input
                    :model-value="workflow.key"
                    :placeholder="t('agent.workflowName')"
                    class="flex-1 h-9"
                    @input="store.updateWorkflowPair(index, 'key', $event.target.value)"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-destructive hover:text-destructive"
                    @click="store.removeWorkflowPair(index)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div v-show="isWorkflowExpanded(workflow.id)" class="pl-10 space-y-3">
                  <div v-for="(step, stepIndex) in workflow.steps" :key="stepIndex" class="flex items-start gap-2">
                    <Textarea
                      :model-value="step"
                      :placeholder="`${t('agent.step')} ${stepIndex + 1}`"
                      class="flex-1 min-h-[60px] resize-y"
                      @input="store.updateWorkflowStep(index, stepIndex, $event.target.value)"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-8 w-8 mt-1 text-destructive hover:text-destructive"
                      @click="store.removeWorkflowStep(index, stepIndex)"
                      :disabled="workflow.steps.length === 1"
                    >
                      <Trash2 class="h-3 w-3" />
                    </Button>
                  </div>
                  <Button variant="outline" size="sm" class="w-full border-dashed h-9" @click="store.addWorkflowStep(index)">
                    <Plus class="h-3 w-3 mr-2" /> {{ t('agent.addStep') }}
                  </Button>
                </div>
              </div>
              <Button variant="outline" size="sm" class="w-full border-dashed h-9" @click="handleAddWorkflow">
                <Plus class="h-3.5 w-3.5 mr-2" /> {{ t('agent.addWorkflow') }}
              </Button>
            </div>
          </section>
        </div>
      </div>
    </div>

    <!-- Optimize Modal -->
    <Dialog :open="showOptimizeModal" @update:open="v => !v && !isOptimizing && handleOptimizeCancel()">
      <DialogContent class="sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>优化系统提示词</DialogTitle>
          <DialogDescription>使用 AI 自动优化您的系统提示词，提高 Agent 的表现。</DialogDescription>
        </DialogHeader>
        <div class="space-y-4 py-4">
          <div class="space-y-2">
            <Label>优化目标 <span class="text-xs text-muted-foreground">(可选)</span></Label>
            <Textarea v-model="optimizationGoal" :rows="3" placeholder="例如：提高专业性和准确性，增强工具使用能力..." :disabled="isOptimizing || !!optimizedResult" />
          </div>
          <div v-if="optimizedResult" class="space-y-2">
            <Label>优化结果预览 <span class="text-xs text-muted-foreground">（可编辑）</span></Label>
            <Textarea v-model="optimizedResult" :rows="8" placeholder="优化结果将显示在这里..." />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="handleOptimizeCancel" :disabled="isOptimizing">取消</Button>
          <template v-if="optimizedResult">
            <Button variant="outline" @click="handleResetOptimization">重新优化</Button>
            <Button @click="handleApplyOptimization">应用优化</Button>
          </template>
          <template v-else>
            <Button @click="handleOptimizeStart" :disabled="isOptimizing">
              <Loader v-if="isOptimizing" class="mr-2 h-4 w-4 animate-spin" />
              开始优化
            </Button>
          </template>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { useAgentEditStore } from '../stores/agentEdit'
import { useLanguage } from '../utils/i18n.js'
import { agentAPI } from '../api/agent.js'
import { modelProviderAPI } from '@/api/modelProvider'
import { skillAPI } from '../api/skill.js'
import { 
  Loader, ChevronLeft, ChevronRight, ChevronDown, Save, Check, Plus, Trash2, 
  Sparkles, Bot, Wrench, Search, Server, Code, User, Cpu, Database, Workflow,
  FileText, X, Image as ImageIcon
} from 'lucide-vue-next'

// UI Components
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { FormItem } from '@/components/ui/form'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const props = defineProps({
  visible: { type: Boolean, default: false },
  agent: { type: Object, default: null },
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] },
  knowledgeBases: { type: Array, default: () => [] }
})

const emit = defineEmits(['update:visible', 'save'])
const store = useAgentEditStore()
const { t } = useLanguage()
const { listModelProviders } = modelProviderAPI

const saving = ref(false)
const contentRef = ref(null)
const activeSection = ref('basic')
const agentSkills = ref([])
const loadingAgentSkills = ref(false)

// Navigation sections
const sections = [
  { id: 'basic', label: t('agent.basicInfo'), icon: User },
  { id: 'strategy', label: t('agent.strategy'), icon: Cpu },
  { id: 'tools', label: t('agent.availableTools'), icon: Wrench },
  { id: 'skills', label: t('agent.availableSkills'), icon: Bot },
  { id: 'knowledgeBases', label: t('agent.availableKnowledgeBases'), icon: Database },
  { id: 'context', label: t('agent.systemContext'), icon: FileText },
  { id: 'workflows', label: t('agent.workflows'), icon: Workflow },
]

const isEditMode = computed(() => !!store.formData.id)

// Scroll to section
const scrollToSection = (sectionId) => {
  const element = document.getElementById(sectionId)
  if (element && contentRef.value) {
    const container = contentRef.value
    const elementTop = element.offsetTop - 24
    container.scrollTo({
      top: elementTop,
      behavior: 'smooth'
    })
  }
}

// Update active section on scroll
const handleScroll = () => {
  if (!contentRef.value) return
  
  const scrollTop = contentRef.value.scrollTop
  const sectionElements = sections.map(s => ({
    id: s.id,
    element: document.getElementById(s.id)
  })).filter(s => s.element)
  
  for (let i = sectionElements.length - 1; i >= 0; i--) {
    const section = sectionElements[i]
    if (section.element) {
      const offsetTop = section.element.offsetTop - 100
      if (scrollTop >= offsetTop) {
        activeSection.value = section.id
        break
      }
    }
  }
}

// 加载Agent可用技能列表
const loadAgentAvailableSkills = async (agentId) => {
  if (!agentId) {
    agentSkills.value = []
    return
  }
  try {
    loadingAgentSkills.value = true
    const response = await skillAPI.getAgentAvailableSkills(agentId)
    if (response.skills) {
      agentSkills.value = response.skills
    }
  } catch (error) {
    console.error('Failed to load agent available skills:', error)
    agentSkills.value = props.skills
  } finally {
    loadingAgentSkills.value = false
  }
}

// Initialize
onMounted(() => {
  store.initForm(props.agent)
  if (contentRef.value) {
    contentRef.value.addEventListener('scroll', handleScroll, { passive: true })
  }
  loadData()
  
  // 如果是编辑现有agent，加载agent可用技能列表
  if (props.agent && props.agent.id) {
    loadAgentAvailableSkills(props.agent.id)
  }
})

onBeforeUnmount(() => {
  if (contentRef.value) {
    contentRef.value.removeEventListener('scroll', handleScroll)
  }
})

// Watch agent changes
watch(() => props.agent, (newAgent) => {
  const isIdUpdate = newAgent && newAgent.id && store.formData.id === null && newAgent.name === store.formData.name
  const isSameAgent = newAgent && store.formData.id === newAgent.id
  
  if (isIdUpdate || isSameAgent) {
    store.initForm(newAgent, { preserveStep: true })
  } else {
    store.initForm(newAgent)
  }
  
  // 如果是编辑现有agent，加载agent可用技能列表
  if (newAgent && newAgent.id) {
    loadAgentAvailableSkills(newAgent.id)
  } else {
    agentSkills.value = []
  }
}, { immediate: true })

// Data loading
const providers = ref([])
const allAgents = ref([])

// Default provider option
const defaultProviderOption = '__default__'
const llmProviderSelectValue = computed({
  get: () => store.formData.llm_provider_id ?? defaultProviderOption,
  set: (val) => {
    store.formData.llm_provider_id = val === defaultProviderOption ? null : val
    // Reset multimodal when provider changes
    store.formData.enableMultimodal = false
  }
})

// Check if selected provider supports multimodal
const selectedProviderSupportsMultimodal = computed(() => {
  const providerId = store.formData.llm_provider_id
  if (!providerId) return false
  const provider = providers.value.find(p => p.id === providerId)
  return provider?.supports_multimodal === true
})

const loadData = async () => {
  try {
    const [providersRes, agentsRes] = await Promise.all([
      listModelProviders(),
      agentAPI.getAgents()
    ])
    providers.value = providersRes || []
    // 后端返回格式: [...]
    allAgents.value = agentsRes || []
  } catch (e) {
    console.error('Failed to load data', e)
  }
}

// Save handlers
const handleSave = async (shouldExit = true) => {
  saving.value = true
  try {
    store.prepareForSave()
    const plainData = JSON.parse(JSON.stringify(store.formData))
    await new Promise((resolve) => {
      emit('save', plainData, shouldExit, () => resolve())
    })
  } catch (e) {
    console.error('handleSave error', e)
  } finally {
    saving.value = false
  }
}

const handleReturn = () => {
  emit('update:visible', false)
}

// Helpers for Selects
const getSelectValue = (val) => {
  if (val === null) return 'auto'
  return val ? 'enabled' : 'disabled'
}

const setSelectValue = (field, val) => {
  if (val === 'auto') store.formData[field] = null
  else if (val === 'enabled') store.formData[field] = true
  else store.formData[field] = false
}

// Sub-agent Logic
const filteredAgents = computed(() => {
  return allAgents.value.filter(a => a.id !== store.formData.id)
})

const isSubAgentSelected = (id) => {
  return store.formData.availableSubAgentIds?.includes(id) || false
}

const toggleSubAgent = (id, checked) => {
  const currentIds = [...(store.formData.availableSubAgentIds || [])]
  if (checked) {
    if (!currentIds.includes(id)) currentIds.push(id)
  } else {
    const index = currentIds.indexOf(id)
    if (index > -1) currentIds.splice(index, 1)
  }
  store.formData.availableSubAgentIds = currentIds
}

const selectAllSubAgents = () => {
  const allAgentIds = filteredAgents.value.map(agent => agent.id)
  store.formData.availableSubAgentIds = [...new Set([...(store.formData.availableSubAgentIds || []), ...allAgentIds])]
}

// Workflow expansion
const expandedWorkflows = reactive(new Set())
const toggleWorkflow = (id) => {
  if (expandedWorkflows.has(id)) {
    expandedWorkflows.delete(id)
  } else {
    expandedWorkflows.add(id)
  }
}
const isWorkflowExpanded = (id) => expandedWorkflows.has(id)

const handleAddWorkflow = () => {
  store.addWorkflowPair()
  setTimeout(() => {
    const newWorkflow = store.workflowPairs[store.workflowPairs.length - 1]
    if (newWorkflow?.id) {
      expandedWorkflows.add(newWorkflow.id)
    }
  }, 0)
}

// Optimization
const showOptimizeModal = ref(false)
const isOptimizing = ref(false)
const optimizationGoal = ref('')
const optimizedResult = ref('')

const handleOptimizeStart = async () => {
  if (isOptimizing.value) return
  isOptimizing.value = true
  try {
    const result = await agentAPI.systemPromptOptimize({
      original_prompt: store.formData.systemPrefix,
      optimization_goal: optimizationGoal.value
    })
    if (result?.optimized_prompt) {
      optimizedResult.value = result.optimized_prompt
    }
  } catch (e) {
    console.error('Optimization failed:', e)
  } finally {
    isOptimizing.value = false
  }
}

const handleOptimizeCancel = () => {
  showOptimizeModal.value = false
  optimizationGoal.value = ''
  optimizedResult.value = ''
}

const handleResetOptimization = () => {
  optimizedResult.value = ''
}

const handleApplyOptimization = () => {
  if (optimizedResult.value) {
    store.formData.systemPrefix = optimizedResult.value
    handleOptimizeCancel()
  }
}

// Tools logic
const searchQueries = reactive({ tools: '', skills: '', knowledgeBases: '' })
const selectedGroupSource = ref('')

const REQUIRED_TOOLS_FOR_SKILLS = [
  'file_read', 'execute_python_code', 'execute_javascript_code', 
  'execute_shell_command', 'file_write', 'file_update', 'load_skill'
]

const isRequiredTool = (toolName) => {
  const hasSkills = store.formData.availableSkills?.length > 0
  return hasSkills && REQUIRED_TOOLS_FOR_SKILLS.includes(toolName)
}

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
  filteredTools.value.forEach(tool => {
    const source = tool.source || '未知来源'
    if (!groups[source]) {
      groups[source] = { source, tools: [] }
    }
    groups[source].tools.push(tool)
  })
  return Object.values(groups).sort((a, b) => a.source.localeCompare(b.source))
})

const displayedTools = computed(() => {
  if (!selectedGroupSource.value) return []
  const group = groupedTools.value.find(g => g.source === selectedGroupSource.value)
  return group ? group.tools : []
})

// Select/Deselect all tools in current group
const selectAllToolsInGroup = () => {
  const currentTools = displayedTools.value
  currentTools.forEach(tool => {
    if (!isRequiredTool(tool.name) && !store.formData.availableTools.includes(tool.name)) {
      store.formData.availableTools.push(tool.name)
    }
  })
}

const deselectAllToolsInGroup = () => {
  const currentTools = displayedTools.value
  currentTools.forEach(tool => {
    if (!isRequiredTool(tool.name)) {
      const index = store.formData.availableTools.indexOf(tool.name)
      if (index > -1) {
        store.formData.availableTools.splice(index, 1)
      }
    }
  })
}

watch(groupedTools, (newGroups) => {
  if (newGroups.length > 0) {
    if (!selectedGroupSource.value || !newGroups.find(g => g.source === selectedGroupSource.value)) {
      selectedGroupSource.value = newGroups[0].source
    }
  } else {
    selectedGroupSource.value = ''
  }
}, { immediate: true })

watch(() => store.formData.availableSkills, (newSkills) => {
  if (newSkills?.length > 0) {
    REQUIRED_TOOLS_FOR_SKILLS.forEach(toolName => {
      if (!store.formData.availableTools.includes(toolName)) {
        store.formData.availableTools.push(toolName)
      }
    })
  }
}, { deep: true })

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

// Skills logic
const skillsList = computed(() => {
  return agentSkills.value.length > 0 ? agentSkills.value : props.skills
})

const filteredSkills = computed(() => {
  if (!searchQueries.skills) return skillsList.value
  const query = searchQueries.skills.toLowerCase()
  return skillsList.value.filter(skill => {
    const name = skill.name || skill
    const desc = skill.description || ''
    return name.toLowerCase().includes(query) || desc.toLowerCase().includes(query)
  })
})

// Selected skills for display as tags
const selectedSkills = computed(() => {
  const selected = store.formData.availableSkills || []
  return selected.map(skillName => {
    const skill = skillsList.value.find(s => (s.name || s) === skillName)
    return skill || skillName
  })
})

// Select/Deselect all skills
const selectAllSkills = () => {
  filteredSkills.value.forEach(skill => {
    const skillName = skill.name || skill
    if (!store.formData.availableSkills?.includes(skillName)) {
      store.toggleSkill(skillName)
    }
  })
}

const deselectAllSkills = () => {
  const currentSkills = [...(store.formData.availableSkills || [])]
  currentSkills.forEach(skillName => {
    store.toggleSkill(skillName)
  })
}

// Knowledge Bases logic
const filteredKnowledgeBases = computed(() => {
  if (!searchQueries.knowledgeBases) return props.knowledgeBases
  const query = searchQueries.knowledgeBases.toLowerCase()
  return props.knowledgeBases.filter(kb => 
    kb.name.toLowerCase().includes(query) || 
    (kb.intro && kb.intro.toLowerCase().includes(query))
  )
})

const toggleKnowledgeBase = (id) => {
  if (!Array.isArray(store.formData.availableKnowledgeBases)) {
    store.formData.availableKnowledgeBases = []
  }
  const index = store.formData.availableKnowledgeBases.indexOf(id)
  if (index === -1) {
    store.formData.availableKnowledgeBases.push(id)
  } else {
    store.formData.availableKnowledgeBases.splice(index, 1)
  }
}

const selectAllKnowledgeBases = () => {
  filteredKnowledgeBases.value.forEach(kb => {
    if (!store.formData.availableKnowledgeBases?.includes(kb.id)) {
      toggleKnowledgeBase(kb.id)
    }
  })
}

const deselectAllKnowledgeBases = () => {
  const currentKBs = [...(store.formData.availableKnowledgeBases || [])]
  currentKBs.forEach(id => {
    toggleKnowledgeBase(id)
  })
}
</script>

<style scoped>
.scroll-mt-6 {
  scroll-margin-top: 1.5rem;
}
</style>
