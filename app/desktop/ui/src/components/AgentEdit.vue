<template>
  <div class="h-full flex flex-col bg-gradient-to-b from-background to-muted/20 border shadow-sm overflow-hidden">
    <!-- Header with Agent Name -->
    <div class="px-4 py-2.5 border-b bg-background/95 backdrop-blur flex items-center justify-between shrink-0">
      <div class="flex items-center gap-2">
        <Button
          v-if="!isSetup"
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
              <!-- Row 1: Memory Type, Agent Mode, Enable Multimodal -->
              <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
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
                      <!-- <SelectItem value="multi">{{ t('agent.modeMulti') }}</SelectItem> -->
                    </SelectContent>
                  </Select>
                </FormItem>

                <!-- Enable Multimodal -->
                <FormItem label="开启多模态">
                  <div class="flex items-center h-10 gap-3 border rounded-md px-3 bg-background">
                    <Switch 
                      :checked="store.formData.enableMultimodal" 
                      @update:checked="(v) => {
                        userManuallySetMultimodal.value = true
                        store.formData.enableMultimodal = v
                      }"
                      :disabled="!selectedProviderSupportsMultimodal"
                    />
                    <span class="text-sm text-muted-foreground">
                      {{ store.formData.enableMultimodal ? '已开启' : '已关闭' }}
                    </span>
                  </div>
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
                  <Input
                    type="number"
                    v-model.number="store.formData.maxLoopCount"
                    min="1"
                    max="100"
                    class="h-10"
                    @blur="validateMaxLoopCount"
                  />
                  <p v-if="maxLoopCountError" class="text-xs text-destructive mt-1">{{ maxLoopCountError }}</p>
                </FormItem>
              </div>

            </div>
          </section>

          <!-- Model Provider Section -->
          <section id="model" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Server class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">{{ t('agent.modelProvider') }}</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">选择Agent使用的语言模型提供商，不同的模型具有不同的能力和特性。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            <div class="pl-10">
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
            </div>
          </section>

          <!-- Sub Agent Section -->
          <section id="subAgents" class="scroll-mt-6" v-if="store.formData.agentMode === 'fibre'">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Bot class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">子智能体</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">选择当前Agent可以调用的子智能体，仅在Fibre模式下有效。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            <div class="pl-10">
              <FormItem label="子智能体">
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

          <!-- External Paths Section -->
          <section id="paths" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <FolderOpen class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">可访问文件夹</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">设置Agent可以访问的文件夹路径，Agent将能够读取和处理这些文件夹中的文件。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-auto flex items-center gap-2">
                <span class="text-xs text-muted-foreground">({{ store.formData.externalPaths?.length || 0 }})</span>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <div class="flex items-center gap-3">
                <Button variant="outline" size="sm" class="h-9 px-4" @click="selectExternalPath">
                  <Plus class="h-3.5 w-3.5 mr-2" />
                  添加文件夹
                </Button>
                <span class="text-sm text-muted-foreground">允许 Agent 访问这些文件夹中的文件</span>
              </div>
              <div v-if="store.formData.externalPaths?.length > 0" class="space-y-2">
                <div v-for="(path, index) in store.formData.externalPaths" :key="index" class="flex items-center justify-between p-3 rounded-lg border border-muted/50 bg-muted/5 hover:bg-muted/10 transition-colors">
                  <span class="text-sm truncate flex-1" :title="path">{{ path }}</span>
                  <Button variant="ghost" size="icon" class="h-8 w-8" @click="store.removeExternalPath(index)">
                    <Trash2 class="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              </div>
            </div>
          </section>

          <!-- IM Channels Section -->
          <section id="im" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <MessageSquare class="h-4 w-4 text-primary" />
              </div>
              <div class="flex items-center gap-2">
                <h2 class="text-base font-semibold">IM 频道</h2>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="w-5 h-5 rounded-full bg-muted flex items-center justify-center text-xs hover:bg-muted/80 transition-colors">
                        ?
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p class="text-xs">配置Agent的即时通讯频道，支持企业微信、钉钉、飞书等平台。配置后Agent可以通过这些渠道与用户交互。</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div class="ml-auto flex items-center gap-2">
                <span class="text-xs text-muted-foreground">({{ enabledIMChannelsCount }})</span>
              </div>
            </div>
            <div class="pl-10 space-y-4">
              <!-- IM Provider Tabs -->
              <div class="flex space-x-1 border-b">
                <button
                  v-for="provider in imProviders"
                  :key="provider.key"
                  class="flex-1 py-2 px-3 text-sm transition-colors relative"
                  :class="[
                    activeIMProvider === provider.key
                      ? 'text-primary font-medium'
                      : 'text-muted-foreground hover:text-foreground'
                  ]"
                  @click="activeIMProvider = provider.key"
                >
                  <div class="flex items-center justify-center gap-2">
                    <span>{{ provider.label }}</span>
                    <span
                      v-if="imConfig[provider.key]?.enabled"
                      class="w-2 h-2 rounded-full bg-green-500"
                    />
                  </div>
                  <div
                    v-if="activeIMProvider === provider.key"
                    class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"
                  />
                </button>
              </div>

              <!-- IM Provider Config -->
              <div v-for="provider in imProviders" :key="provider.key">
                <div v-if="activeIMProvider === provider.key" class="space-y-4">
                  <!-- Test & Enable Row (for wechat_personal: test first, then enable) -->
                  <div class="flex items-center justify-between p-4 bg-card rounded-lg border">
                    <div class="space-y-1">
                      <Label class="text-base">启用 {{ provider.label }}</Label>
                      <p class="text-sm text-muted-foreground">
                        <span v-if="provider.key === 'imessage' && !isDefaultAgent" class="text-yellow-600">iMessage 只能配置在默认智能体上</span>
                        <span v-else-if="provider.key === 'wechat_personal'" class="text-yellow-600">⚠️ 先点击测试连接，测试成功后再启动</span>
                        <span v-else-if="imTestStatus[provider.key]?.tested && !imTestStatus[provider.key]?.passed" class="text-red-600">测试失败，请检查配置后重新测试</span>
                        <span v-else-if="!imTestStatus[provider.key]?.passed" class="text-yellow-600">请先填写配置并通过测试连接后才能启用</span>
                        <span v-else>允许Agent通过{{ provider.label }}与用户交互</span>
                      </p>
                    </div>
                    <div class="flex items-center gap-3">
                      <!-- Test Button -->
                      <Button 
                        variant="outline" 
                        size="sm"
                        @click="testIMConnection(provider.key)"
                        :disabled="testingIM[provider.key] || (!imEditMode[provider.key] && imTestStatus[provider.key]?.passed)"
                      >
                        <Loader v-if="testingIM[provider.key]" class="mr-2 h-4 w-4 animate-spin" />
                        <Play v-else class="mr-2 h-4 w-4" />
                        {{ imTestStatus[provider.key]?.passed && !imEditMode[provider.key] ? '已测试' : '测试连接' }}
                      </Button>
                      <!-- Enable Switch -->
                      <Switch 
                        :checked="imConfig[provider.key]?.enabled"
                        @update:checked="(val) => handleEnableSwitch(provider.key, val)"
                        :disabled="provider.key === 'imessage' ? !isDefaultAgent : !imTestStatus[provider.key]?.passed"
                      />
                    </div>
                  </div>

                  <!-- Config Fields (always visible, editable only in edit mode or when not frozen) -->
                  <div class="space-y-4">
                    <!-- Status Bar -->
                    <div class="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                      <div class="flex items-center gap-2">
                        <div 
                          class="w-2 h-2 rounded-full"
                          :class="{
                            'bg-green-500': imTestStatus[provider.key]?.passed && !imEditMode[provider.key],
                            'bg-yellow-500': imEditMode[provider.key],
                            'bg-red-500': imTestStatus[provider.key]?.tested && !imTestStatus[provider.key]?.passed && !imEditMode[provider.key],
                            'bg-gray-400': !imTestStatus[provider.key]?.tested && !imEditMode[provider.key]
                          }"
                        />
                        <span class="text-sm">
                          <span v-if="imTestStatus[provider.key]?.passed && !imEditMode[provider.key]" class="text-green-600">配置已冻结（测试通过）</span>
                          <span v-else-if="imEditMode[provider.key]" class="text-yellow-600">编辑模式 - 请修改配置并测试</span>
                          <span v-else-if="imTestStatus[provider.key]?.tested && !imTestStatus[provider.key]?.passed" class="text-red-600">测试失败 - 请检查配置后重试</span>
                          <span v-else>未测试 - 请填写配置并测试</span>
                        </span>
                      </div>
                      <Button
                        v-if="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        variant="outline"
                        size="sm"
                        @click="handleUpdateIMConfig(provider.key)"
                      >
                        <Edit class="mr-2 h-3.5 w-3.5" />
                        更新配置
                      </Button>
                      <Button
                        v-else-if="imEditMode[provider.key]"
                        variant="outline"
                        size="sm"
                        @click="handleFinishIMEdit(provider.key)"
                      >
                        <Check class="mr-2 h-3.5 w-3.5" />
                        完成编辑
                      </Button>
                    </div>

                    <!-- WeChat Work -->
                    <template v-if="provider.key === 'wechat_work'">
                      <div class="space-y-2">
                        <Label>Bot ID <span class="text-red-500">*</span></Label>
                        <Input
                          v-model="imConfig.wechat_work.config.bot_id"
                          placeholder="输入企业微信 Bot ID"
                          :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        />
                      </div>
                      <div class="space-y-2">
                        <Label>Secret <span class="text-red-500">*</span></Label>
                        <Input
                          v-model="imConfig.wechat_work.config.secret"
                          type="password"
                          placeholder="输入 Secret"
                          :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        />
                      </div>
                    </template>

                    <!-- WeChat Personal (微信个人号) -->
                    <template v-if="provider.key === 'wechat_personal'">
                      <div class="space-y-4">
                        <div class="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                          <p class="text-sm text-green-800 dark:text-green-200">
                            微信个人号通过 iLink Bot API 接入。首次使用需要扫码登录获取 Bot Token。
                          </p>
                        </div>
                        
                        <!-- 扫码登录区域 -->
                        <div class="space-y-3 p-4 border rounded-lg bg-muted/30">
                          <div class="flex items-center justify-between">
                            <div class="flex items-center gap-2">
                              <Button 
                                variant="outline" 
                                size="sm"
                                @click="startWeChatPersonalLogin(provider.key)"
                                :disabled="wechatPersonalLogin.loading"
                              >
                                <Loader v-if="wechatPersonalLogin.loading" class="mr-2 h-4 w-4 animate-spin" />
                                <QrCode v-else class="mr-2 h-4 w-4" />
                                {{ wechatPersonalLogin.loading ? '获取中...' : '扫码获取 Token' }}
                              </Button>
                              <span v-if="wechatPersonalLogin.status === 'scaned'" class="text-sm text-yellow-600">已扫码，等待确认...</span>
                              <span v-if="wechatPersonalLogin.status === 'confirmed'" class="text-sm text-green-600">登录成功！</span>
                              <span v-if="wechatPersonalLogin.status === 'expired'" class="text-sm text-red-600">二维码已过期</span>
                            </div>
                          </div>
                          
                          <!-- 二维码显示 -->
                          <div v-if="wechatPersonalLogin.qrCodeUrl" class="border rounded-lg p-4 bg-white space-y-3">
                            <div class="flex justify-center">
                              <img 
                                :src="wechatPersonalLogin.qrCodeUrl" 
                                alt="微信扫码登录" 
                                class="w-48 h-48 object-contain bg-white border"
                                style="image-rendering: pixelated; min-height: 192px; min-width: 192px;"
                              />
                            </div>
                            <div class="text-sm space-y-2">
                              <p class="font-medium text-center">使用步骤：</p>
                              <ol class="list-decimal list-inside text-xs text-muted-foreground space-y-1">
                                <li>使用微信扫描上方二维码</li>
                                <li>微信连接后自动填充Bot token</li>
                              </ol>
                            </div>
                            <!-- 备用链接 -->
                            <div v-if="wechatPersonalLogin.qrUrl" class="text-center space-y-2 pt-2 border-t">
                              <p class="text-xs text-gray-500">扫码无效？可复制链接到微信打开：</p>
                              <div class="flex gap-2 justify-center">
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  @click="copyWeChatPersonalUrl"
                                >
                                  复制链接
                                </Button>
                              </div>
                            </div>
                          </div>
                        </div>
                        
                        <div class="space-y-2">
                          <Label>Bot Token <span class="text-red-500">*</span></Label>
                          <p class="text-xs text-muted-foreground">
                            通过微信扫码登录获取，或使用已有 Bot Token
                          </p>
                          <Textarea
                            v-model="imConfig.wechat_personal.config.bot_token"
                            placeholder="输入 Bot Token"
                            rows="3"
                            :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                          />
                        </div>
                        
                        <div class="space-y-2">
                          <Label>Bot ID <span class="text-red-500">*</span></Label>
                          <p class="text-xs text-muted-foreground">
                            登录成功后自动获取，或手动输入
                          </p>
                          <Input
                            v-model="imConfig.wechat_personal.config.bot_id"
                            placeholder="输入 Bot ID"
                            :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                          />
                        </div>
                      </div>
                    </template>

                    <!-- DingTalk -->
                    <template v-if="provider.key === 'dingtalk'">
                      <div class="space-y-2">
                        <Label>Client ID <span class="text-red-500">*</span></Label>
                        <Input
                          v-model="imConfig.dingtalk.config.client_id"
                          placeholder="输入钉钉 Client ID"
                          :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        />
                      </div>
                      <div class="space-y-2">
                        <Label>Client Secret <span class="text-red-500">*</span></Label>
                        <Input
                          v-model="imConfig.dingtalk.config.client_secret"
                          type="password"
                          placeholder="输入 Client Secret"
                          :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        />
                      </div>
                    </template>

                    <!-- Feishu -->
                    <template v-if="provider.key === 'feishu'">
                      <div class="space-y-2">
                        <Label>App ID <span class="text-red-500">*</span></Label>
                        <Input
                          v-model="imConfig.feishu.config.app_id"
                          placeholder="输入飞书 App ID"
                          :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        />
                      </div>
                      <div class="space-y-2">
                        <Label>App Secret <span class="text-red-500">*</span></Label>
                        <Input
                          v-model="imConfig.feishu.config.app_secret"
                          type="password"
                          placeholder="输入 App Secret"
                          :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                        />
                      </div>
                    </template>

                    <!-- iMessage -->
                    <template v-if="provider.key === 'imessage'">
                      <div class="space-y-4">
                        <div class="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                          <p class="text-sm text-blue-800 dark:bg-blue-200">
                            iMessage 使用本地数据库轮询模式。需要授予完全磁盘访问权限才能读取 Messages 数据库。
                          </p>
                        </div>
                        <div class="space-y-2">
                          <Label>监听发送者 <span class="text-red-500">*</span></Label>
                          <p class="text-xs text-muted-foreground">每行输入一个手机号（+86 开头或纯号码），只有这些发送者的消息会被处理</p>
                          <Textarea
                            v-model="imConfig.imessage.config.allowed_senders_text"
                            placeholder="+86138xxxxxxxx&#10;+86139xxxxxxxx"
                            rows="4"
                            :disabled="!imEditMode[provider.key] && imTestStatus[provider.key]?.passed"
                          />
                        </div>
                      </div>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- System Context Section -->
          <section id="context" class="scroll-mt-6">
            <div class="flex items-center gap-2 mb-5">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <Database class="h-4 w-4 text-primary" />
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
              <Button variant="outline" size="sm" class="w-full border-dashed h-9">
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
                  <Button variant="outline" size="sm" class="w-full border-dashed h-9">
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
import request from '@/utils/request.js'
import { 
  Loader, ChevronLeft, ChevronRight, ChevronDown, Save, Check, Plus, Trash2, 
  Sparkles, Bot, Wrench, Search, Server, Code, FolderOpen, User, Cpu, Database, Workflow,
  GripVertical, X, Image as ImageIcon, AlertCircle, MessageSquare, Play
} from 'lucide-vue-next'
import Sortable from 'sortablejs'

// UI Components
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { FormItem } from '@/components/ui/form'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenuRoot as DropdownMenu,
  DropdownMenuContent,
  DropdownMenuPortal,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
} from 'reka-ui'

const props = defineProps({
  visible: { type: Boolean, default: false },
  agent: { type: Object, default: null },
  tools: { type: Array, default: () => [] },
  skills: { type: Array, default: () => [] },
  isSetup: { type: Boolean, default: false },
})

const emit = defineEmits(['update:visible', 'save'])
const store = useAgentEditStore()
const { t } = useLanguage()
const { listModelProviders } = modelProviderAPI

const saving = ref(false)
const contentRef = ref(null)
const activeSection = ref('basic')
const maxLoopCountError = ref('')

const validateMaxLoopCount = () => {
  const value = store.formData.maxLoopCount
  if (value > 100) {
    store.formData.maxLoopCount = 100
    maxLoopCountError.value = '最大循环次数不能超过 100'
  } else if (value < 1) {
    store.formData.maxLoopCount = 1
    maxLoopCountError.value = '最大循环次数不能小于 1'
  } else {
    maxLoopCountError.value = ''
  }
}

// ============================================================================
// IM Channel Configuration
// ============================================================================

const activeIMProvider = ref('wechat_work')
const testingIM = ref({})

// WeChat Personal (iLink) login state
const wechatPersonalLogin = ref({
  loading: false,
  qrCodeUrl: '',      // 二维码图片 data URL
  qrUrl: '',          // 微信扫码后打开的 URL
  qrcode: '',         // 二维码字符串（用于状态查询）
  status: '',         // wait, scaned, confirmed, expired
  polling: false
})

const isDefaultAgent = computed(() => store.formData.is_default === true)

const imProviders = [
  { key: 'wechat_work', label: '企业微信' },
  { key: 'wechat_personal', label: '微信' },
  { key: 'dingtalk', label: '钉钉' },
  { key: 'feishu', label: '飞书' },
  { key: 'imessage', label: 'iMessage' }
]

const imConfig = ref({
  wechat_work: { enabled: false, config: { bot_id: '', secret: '' } },
  wechat_personal: { enabled: false, config: { bot_token: '', bot_id: '' } },
  dingtalk: { enabled: false, config: { client_id: '', client_secret: '' } },
  feishu: { enabled: false, config: { app_id: '', app_secret: '' } },
  imessage: { enabled: false, config: { allowed_senders_text: '' } }
})

const enabledIMChannelsCount = computed(() => {
  return Object.values(imConfig.value).filter(c => c.enabled).length
})

// 记录各渠道的测试连接状态
const imTestStatus = ref({
  wechat_work: { tested: false, passed: false },
  dingtalk: { tested: false, passed: false },
  feishu: { tested: false, passed: false },
  imessage: { tested: false, passed: false }
})

// 记录各渠道测试通过时的配置快照（冻结配置）
const imFrozenConfig = ref({
  wechat_work: null,
  dingtalk: null,
  feishu: null,
  imessage: null
})

// 记录各渠道是否处于编辑模式
const imEditMode = ref({
  wechat_work: false,
  dingtalk: false,
  feishu: false,
  imessage: false
})

// Default empty IM config
const getDefaultIMConfig = () => ({
  wechat_work: { enabled: false, config: { bot_id: '', secret: '' } },
  wechat_personal: { enabled: false, config: { bot_token: '', bot_id: '' } },
  dingtalk: { enabled: false, config: { client_id: '', client_secret: '' } },
  feishu: { enabled: false, config: { app_id: '', app_secret: '' } },
  imessage: { enabled: false, config: { allowed_senders_text: '' } }
})

// Load IM config when agent changes
const loadIMConfig = async () => {
  const agentId = store.formData.id
  console.log(`[AgentEdit] loadIMConfig called for agent: ${agentId}`)
  
  if (!agentId) {
    console.log('[AgentEdit] No agent ID, resetting IM config')
    imConfig.value = getDefaultIMConfig()
    return
  }
  
  // Always reset first to prevent showing stale config
  console.log('[AgentEdit] Resetting IM config before loading')
  imConfig.value = getDefaultIMConfig()
  
  // Note: Don't reset test status here to preserve test results
  // Only reset edit mode
  imEditMode.value = {
    wechat_work: false,
    dingtalk: false,
    feishu: false,
    imessage: false
  }
  
  try {
    console.log(`[AgentEdit] Fetching IM config for agent: ${agentId}`)
    const result = await request.get(`/api/im/agent/${agentId}/im_channels`)
    
    // Double-check that we're still on the same agent (user might have switched while fetching)
    if (store.formData.id !== agentId) {
      console.log(`[AgentEdit] Agent changed during fetch, discarding results (was: ${agentId}, now: ${store.formData.id})`)
      return
    }
    
    // Check again after request (in case of async delay)
    if (store.formData.id !== agentId) {
      console.log(`[AgentEdit] Agent changed after fetch, discarding results (was: ${agentId}, now: ${store.formData.id})`)
      return
    }
    
    console.log(`[AgentEdit] IM config response:`, result)
    
    // request.get returns response.data directly, so result is {agent_id, is_default, channels}
    if (result.channels) {
      console.log(`[AgentEdit] Loaded channels:`, Object.keys(result.channels))
      // Merge loaded config with default structure
      for (const [provider, data] of Object.entries(result.channels)) {
        if (imConfig.value[provider]) {
          console.log(`[AgentEdit] Setting ${provider} config:`, data)
          const updatedConfig = { ...imConfig.value[provider].config, ...data.config }
          
          // Convert allowed_senders array to text for iMessage
          if (provider === 'imessage' && data.config?.allowed_senders) {
            updatedConfig.allowed_senders_text = data.config.allowed_senders.join('\n')
          }
          
          imConfig.value = {
            ...imConfig.value,
            [provider]: {
              ...imConfig.value[provider],
              enabled: data.enabled || false,
              config: updatedConfig
            }
          }
          
          // Auto-mark as passed if config has actual values (not just empty strings)
          // This allows users to enable/disable without re-testing
          const configValues = Object.values(data.config || {})
          const hasRealConfig = configValues.some(v => v && v.toString().trim() !== '')
          if (hasRealConfig) {
            imTestStatus.value = {
              ...imTestStatus.value,
              [provider]: { tested: true, passed: true }
            }
            // Freeze the loaded config so enable switch works
            imFrozenConfig.value = {
              ...imFrozenConfig.value,
              [provider]: JSON.parse(JSON.stringify(updatedConfig))
            }
            console.log(`[AgentEdit] Auto-marked ${provider} as tested (has real config)`)
          } else {
            console.log(`[AgentEdit] Not marking ${provider} as tested (config is empty)`)
          }
        }
      }
    } else {
      console.log(`[AgentEdit] No channels in response (result:`, result, '), keeping default empty config')
    }
    
    console.log(`[AgentEdit] Final imConfig:`, JSON.parse(JSON.stringify(imConfig.value)))
  } catch (e) {
    console.error('[AgentEdit] Failed to load IM config:', e)
    // On error, ensure config is reset to default
    imConfig.value = getDefaultIMConfig()
  }
}

const updateIMConfig = (provider, key, value) => {
  if (!imConfig.value[provider]) return
  imConfig.value = {
    ...imConfig.value,
    [provider]: {
      ...imConfig.value[provider],
      [key]: value
    }
  }
  // 如果配置被修改，退出编辑模式时会检查
}

// 检查当前配置是否与冻结配置一致
const isConfigFrozen = (provider) => {
  const frozen = imFrozenConfig.value[provider]
  if (!frozen) return false  // 没有冻结配置，视为未冻结
  
  const current = imConfig.value[provider]?.config
  if (!current) return false
  
  // 对比关键字段
  return JSON.stringify(frozen) === JSON.stringify(current)
}

// 处理启用开关切换
const handleEnableSwitch = (provider, value) => {
  if (value) {
    // 尝试启用，检查测试状态和配置是否被修改
    if (!imTestStatus.value[provider]?.passed) {
      alert('请先通过测试连接后再启用')
      return
    }
    
    // 检查配置是否被修改过（与冻结配置不一致）
    if (!isConfigFrozen(provider)) {
      alert('配置已修改，请重新测试连接后再启用')
      // 重置测试状态
      imTestStatus.value = {
        ...imTestStatus.value,
        [provider]: { tested: false, passed: false }
      }
      return
    }
  }
  // 关闭开关不需要检查
  imConfig.value = {
    ...imConfig.value,
    [provider]: {
      ...imConfig.value[provider],
      enabled: value
    }
  }
}

// 处理更新配置（进入编辑模式）
const handleUpdateIMConfig = (provider) => {
  // 如果当前已启用，先禁用
  if (imConfig.value[provider]?.enabled) {
    imConfig.value = {
      ...imConfig.value,
      [provider]: {
        ...imConfig.value[provider],
        enabled: false
      }
    }
  }
  // 进入编辑模式
  imEditMode.value = {
    ...imEditMode.value,
    [provider]: true
  }
  // 重置测试状态
  imTestStatus.value = {
    ...imTestStatus.value,
    [provider]: { tested: false, passed: false }
  }
}

// 处理完成编辑（退出编辑模式）
const handleFinishIMEdit = (provider) => {
  imEditMode.value = {
    ...imEditMode.value,
    [provider]: false
  }
}

// ============================================================================
// WeChat Personal (iLink) Login Functions
// ============================================================================

const startWeChatPersonalLogin = async (provider) => {
  if (!store.formData.id) return
  
  wechatPersonalLogin.value = {
    loading: true,
    qrCodeUrl: '',
    qrUrl: '',
    qrcode: '',
    status: '',
    polling: false
  }
  
  try {
    // 1. 获取二维码
    const result = await request.post(`/api/im/agent/${store.formData.id}/im_channels/wechat_personal/qrcode`, {})
    
    console.log('[AgentEdit] WeChat Personal QR code response:', result)
    
    if (!result.qrcode || !result.qrcode_url) {
      alert('获取二维码失败：响应数据不完整')
      return
    }
    
    // 使用 qrcode 库生成二维码图片
    // 优先使用 qrcode_url（微信授权页面URL），如果不存在则使用 qrcode（标识符）
    const qrData = result.qrcode_url || result.qrcode
    const qrId = result.qrcode
    
    let qrCodeUrl = ''
    try {
      // 动态导入 qrcode 库
      const QRCode = await import('qrcode')
      qrCodeUrl = await QRCode.toDataURL(qrData, {
        width: 400,
        margin: 2,
        color: {
          dark: '#000000',
          light: '#ffffff'
        }
      })
    } catch (qrError) {
      console.error('[AgentEdit] Failed to generate QR code:', qrError)
      // 如果生成失败，显示原始字符串
      qrCodeUrl = ''
    }
    
    wechatPersonalLogin.value = {
      loading: false,
      qrCodeUrl: qrCodeUrl,
      qrUrl: result.qrcode_url,
      qrcode: result.qrcode,
      status: 'wait',
      polling: true
    }
    
    // 开始轮询扫码状态
    pollWeChatPersonalStatus(provider)
    
  } catch (e) {
    console.error('[AgentEdit] Failed to get QR code:', e)
    alert('获取二维码失败: ' + e.message)
    wechatPersonalLogin.value.loading = false
  }
}

const pollWeChatPersonalStatus = async (provider) => {
  // 后端使用长轮询（35秒），前端设置40秒超时
  // 10次尝试 = 最长350秒（约6分钟）
  const maxAttempts = 10
  let attempts = 0
  
  console.log('[AgentEdit] Starting QR status polling')
  
  while (wechatPersonalLogin.value.polling && attempts < maxAttempts) {
    try {
      console.log(`[AgentEdit] Polling attempt ${attempts + 1}/${maxAttempts}`)
      
      // 使用40秒超时，因为后端长轮询35秒
      const result = await request.post(
        `/api/im/agent/${store.formData.id}/im_channels/wechat_personal/qrcode/status`,
        { qrcode: wechatPersonalLogin.value.qrcode },
        { timeout: 40000 }  // 40秒超时
      )
      
      console.log('[AgentEdit] QR status response:', result)
      
      const status = result.status
      wechatPersonalLogin.value.status = status
      
      if (status === 'confirmed') {
        // 登录成功，保存 token
        wechatPersonalLogin.value.polling = false
        imConfig.value = {
          ...imConfig.value,
          wechat_personal: {
            ...imConfig.value.wechat_personal,
            config: {
              ...imConfig.value.wechat_personal.config,
              bot_token: result.bot_token,
              bot_id: result.bot_id
            }
          }
        }
        alert('登录成功！Bot Token 和 Bot ID 已自动填充')
        return
      } else if (status === 'expired') {
        wechatPersonalLogin.value.polling = false
        alert('二维码已过期，请重新获取')
        return
      } else if (status === 'scaned') {
        console.log('[AgentEdit] QR code scanned, waiting for confirm...')
      }
      
      // 长轮询返回 wait，立即发起下一次请求
      attempts++
      
    } catch (e) {
      console.error('[AgentEdit] Failed to check QR status:', e)
      // 出错后等待2秒再试
      await new Promise(resolve => setTimeout(resolve, 2000))
      attempts++
    }
  }
  
  // 超时
  if (attempts >= maxAttempts) {
    wechatPersonalLogin.value.polling = false
    wechatPersonalLogin.value.status = 'expired'
    alert('扫码超时，请重新获取二维码')
  }
}

const copyWeChatPersonalUrl = async () => {
  try {
    if (wechatPersonalLogin.value.qrUrl) {
      await navigator.clipboard.writeText(wechatPersonalLogin.value.qrUrl)
      alert('链接已复制到剪贴板，请在微信中打开')
    }
  } catch (err) {
    console.error('Failed to copy:', err)
    alert('复制失败，请手动复制')
  }
}

// ============================================================================
// Test Connection
// ============================================================================

const testIMConnection = async (provider) => {
  if (!store.formData.id) return
  
  testingIM.value = {
    ...testingIM.value,
    [provider]: true
  }
  try {
    // Get current config from form
    const currentConfig = imConfig.value[provider]?.config || {}
    
    // iMessage 手机号格式验证
    if (provider === 'imessage') {
      const sendersText = currentConfig.allowed_senders_text || ''
      const senders = sendersText.split('\n').map(s => s.trim()).filter(s => s)
      
      if (senders.length === 0) {
        throw new Error('请至少输入一个监听手机号')
      }
      
      // 验证手机号格式：+86 开头或纯 11 位号码
      const phoneRegex = /^(\+86)?\d{11}$/
      const invalidPhones = senders.filter(phone => !phoneRegex.test(phone))
      
      if (invalidPhones.length > 0) {
        throw new Error(`手机号格式错误: ${invalidPhones.join(', ')}\n请输入 +86 开头或 11 位纯号码`)
      }
    }
    
    const result = await request.post(`/api/im/agent/${store.formData.id}/im_channels/${provider}/test`, {
      config: currentConfig
    })
    console.log(`[AgentEdit] Test result for ${provider}:`, result)
    if (result.success) {
      // 更新测试状态为通过 - 使用 Vue.set 方式确保响应式
      imTestStatus.value = {
        ...imTestStatus.value,
        [provider]: { tested: true, passed: true }
      }
      console.log(`[AgentEdit] Test passed, imTestStatus:`, imTestStatus.value)
      // 冻结当前配置
      imFrozenConfig.value = {
        ...imFrozenConfig.value,
        [provider]: JSON.parse(JSON.stringify(currentConfig))
      }
      // 退出编辑模式
      imEditMode.value = {
        ...imEditMode.value,
        [provider]: false
      }
      alert(result.data?.message || '连接测试成功，现在可以启用该渠道')
    } else {
      // 更新测试状态为失败
      imTestStatus.value = {
        ...imTestStatus.value,
        [provider]: { tested: true, passed: false }
      }
      console.log(`[AgentEdit] Test failed, imTestStatus:`, imTestStatus.value)
      alert('连接测试失败: ' + result.message)
    }
  } catch (e) {
    console.error('[AgentEdit] Failed to test IM connection:', e)
    // 更新测试状态为失败
    imTestStatus.value = {
      ...imTestStatus.value,
      [provider]: { tested: true, passed: false }
    }
    console.log(`[AgentEdit] Test exception, imTestStatus:`, imTestStatus.value)
    alert('测试失败: ' + e.message)
  } finally {
    testingIM.value = {
      ...testingIM.value,
      [provider]: false
    }
  }
}

// Watch for agent changes to load IM config
watch(() => store.formData.id, (newId) => {
  if (newId) {
    loadIMConfig()
  }
}, { immediate: true })

// Debug: Watch imTestStatus changes
watch(() => imTestStatus.value, (newVal, oldVal) => {
  console.log('[AgentEdit] imTestStatus changed:', JSON.parse(JSON.stringify(newVal)))
}, { deep: true })

// 监听工具列表更新事件，重新过滤已选中的工具
const handleToolsUpdated = async () => {
  // 等待 props.tools 更新（使用 nextTick）
  await nextTick()

  // 获取当前可用的工具名称
  const availableToolNames = new Set(props.tools.map(t => t.name))
  const currentTools = store.formData.availableTools || []

  // 过滤掉已不存在的工具（保留必需的技能工具）
  const filteredTools = currentTools.filter(toolName => {
    if (isRequiredTool(toolName)) return true
    return availableToolNames.has(toolName)
  })

  // 如果有变化，更新表单
  if (filteredTools.length !== currentTools.length) {
    store.formData.availableTools = filteredTools
  }
}

// Navigation sections
const sections = computed(() => {
  const baseSections = [
    { id: 'basic', label: t('agent.basicInfo'), icon: User },
    { id: 'strategy', label: t('agent.strategy'), icon: Cpu },
    { id: 'model', label: t('agent.modelProvider'), icon: Server },
    { id: 'tools', label: t('agent.availableTools'), icon: Wrench },
    { id: 'skills', label: t('agent.availableSkills'), icon: Bot },
    { id: 'paths', label: '可访问文件夹', icon: FolderOpen },
    { id: 'im', label: 'IM 频道', icon: MessageSquare },
    { id: 'context', label: t('agent.systemContext'), icon: Database },
    { id: 'workflows', label: t('agent.workflows'), icon: Workflow },
  ]
  
  // 仅在Fibre模式下显示子智能体导航
  if (store.formData.agentMode === 'fibre') {
    const subAgentSection = { id: 'subAgents', label: '子智能体', icon: Bot }
    // 在model之后插入subAgents
    const modelIndex = baseSections.findIndex(s => s.id === 'model')
    baseSections.splice(modelIndex + 1, 0, subAgentSection)
  }
  
  return baseSections
})

const isEditMode = computed(() => !!store.formData.id)

// Scroll to section
const scrollToSection = (sectionId) => {
  const element = document.getElementById(sectionId)
  if (element && contentRef.value) {
    const container = contentRef.value
    const elementTop = element.offsetTop - 24 // 24px padding offset
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
  const sectionElements = sections.value.map(s => ({
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

// Initialize
onMounted(() => {
  console.log('[AgentEdit] Component mounted, agent:', props.agent?.id)
  
  // Always reset IM config on mount (component might be reused)
  console.log('[AgentEdit] Resetting IM config on mount')
  imConfig.value = getDefaultIMConfig()
  
  // Only reset edit mode, preserve test status
  imEditMode.value = {
    wechat_work: false,
    dingtalk: false,
    feishu: false,
    imessage: false
  }
  
  store.initForm(props.agent)
  if (contentRef.value) {
    contentRef.value.addEventListener('scroll', handleScroll, { passive: true })
  }
  loadData()
  
  // Explicitly load IM config on mount (watch might not trigger if id hasn't changed)
  if (props.agent?.id || store.formData.id) {
    loadIMConfig()
  }
  
  window.addEventListener('tools-updated', handleToolsUpdated)
})

onBeforeUnmount(() => {
  if (contentRef.value) {
    contentRef.value.removeEventListener('scroll', handleScroll)
  }
  window.removeEventListener('tools-updated', handleToolsUpdated)
})

// Watch agent changes
watch(() => props.agent, (newAgent) => {
  console.log('[AgentEdit] Agent changed:', newAgent?.id)
  
  // Always reset IM config when agent changes
  console.log('[AgentEdit] Resetting IM config on agent change')
  imConfig.value = getDefaultIMConfig()
  
  // Only reset edit mode, preserve test status
  imEditMode.value = {
    wechat_work: false,
    dingtalk: false,
    feishu: false,
    imessage: false
  }
  
  const isIdUpdate = newAgent && newAgent.id && store.formData.id === null && newAgent.name === store.formData.name
  const isSameAgent = newAgent && store.formData.id === newAgent.id
  
  if (isIdUpdate || isSameAgent) {
    store.initForm(newAgent, { preserveStep: true })
  } else {
    store.initForm(newAgent)
  }
  
  // Reload IM config when agent changes (even for same agent, to get latest saved config)
  if (newAgent?.id) {
    console.log('[AgentEdit] Reloading IM config for agent:', newAgent.id)
    loadIMConfig()
  }
})

// Data loading
const providers = ref([])
const allAgents = ref([])

const loadData = async () => {
  try {
    const [providersRes, agentsRes] = await Promise.all([
      listModelProviders(),
      agentAPI.getAgents()
    ])
    providers.value = providersRes || []
    allAgents.value = agentsRes?.agents || agentsRes || []
  } catch (e) {
    console.error('Failed to load data', e)
  }
}

// Default provider option
const defaultProviderOption = '__default__'
// Track if user has manually set multimodal
const userManuallySetMultimodal = ref(false)

const llmProviderSelectValue = computed({
  get: () => store.formData.llm_provider_id ?? defaultProviderOption,
  set: (val) => {
    store.formData.llm_provider_id = val === defaultProviderOption ? null : val
    // Reset manual flag when provider changes
    userManuallySetMultimodal.value = false
    // Auto-enable multimodal if new provider supports it
    const newProvider = providers.value.find(p => p.id === val)
    if (newProvider?.supports_multimodal) {
      store.formData.enableMultimodal = true
    } else {
      store.formData.enableMultimodal = false
    }
  }
})

// Check if selected provider supports multimodal
const selectedProviderSupportsMultimodal = computed(() => {
  const providerId = store.formData.llm_provider_id
  if (!providerId) return false
  const provider = providers.value.find(p => p.id === providerId)
  return provider?.supports_multimodal === true
})

// Watch for provider changes and auto-enable multimodal
watch(selectedProviderSupportsMultimodal, (supportsMultimodal) => {
  // Only auto-enable if user hasn't manually set it and provider supports it
  if (supportsMultimodal && !userManuallySetMultimodal.value) {
    store.formData.enableMultimodal = true
  } else if (!supportsMultimodal) {
    store.formData.enableMultimodal = false
  }
}, { immediate: true })

// Save handlers
const handleSave = async (shouldExit = true) => {
  saving.value = true
  try {
    // Check all enabled channels have passed test
    for (const [provider, data] of Object.entries(imConfig.value)) {
      if (data.enabled) {
        // iMessage has its own validation
        if (provider === 'imessage') {
          const sendersText = data.config?.allowed_senders_text || ''
          const senders = sendersText.split('\n').map(s => s.trim()).filter(s => s)
          if (senders.length === 0) {
            alert('iMessage 必须配置至少一个监听发送者')
            saving.value = false
            return
          }
        } else {
          // Other channels must pass test before saving
          if (!imTestStatus.value[provider]?.passed) {
            alert(`${imProviders.find(p => p.key === provider)?.label} 未通过测试连接，请先测试通过后再保存`)
            saving.value = false
            return
          }
        }
      }
    }
    
    // Prepare IM channels config
    const imChannels = {}
    for (const [provider, data] of Object.entries(imConfig.value)) {
      let config = { ...data.config }
      
      // Convert allowed_senders_text to array for iMessage
      if (provider === 'imessage' && config.allowed_senders_text) {
        config.allowed_senders = config.allowed_senders_text
          .split('\n')
          .map(s => s.trim())
          .filter(s => s)
        delete config.allowed_senders_text
      }
      
      imChannels[provider] = {
        enabled: data.enabled,
        config: config
      }
    }
    
    // Add IM channels to formData
    store.formData.im_channels = imChannels
    
    console.log('[AgentEdit] Saving IM channels:', JSON.parse(JSON.stringify(imChannels)))
    
    // 保存前验证 maxLoopCount
    validateMaxLoopCount()
    store.prepareForSave()
    const plainData = JSON.parse(JSON.stringify(store.formData))
    
    console.log('[AgentEdit] Plain data to save:', { 
      id: plainData.id, 
      im_channels: plainData.im_channels 
    })
    
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

const selectedSubAgents = computed(() => {
  const ids = store.formData.availableSubAgentIds || []
  if (ids.length === 0) return []
  return ids
    .map(id => allAgents.value.find(agent => agent.id === id))
    .filter(Boolean)
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

const deselectAllSubAgents = () => {
  store.formData.availableSubAgentIds = []
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
const searchQueries = reactive({ tools: '', skills: '' })
const selectedGroupSource = ref('')

const REQUIRED_TOOLS_FOR_SKILLS = [
  'file_read', 'execute_python_code', 'execute_javascript_code',
  'execute_shell_command', 'file_write', 'file_update', 'load_skill'
]

// 记忆类型为用户时必需的工具
const REQUIRED_TOOLS_FOR_USER_MEMORY = ['search_memory']

// Fibre 策略必需的工具
const REQUIRED_TOOLS_FOR_FIBRE = ['sys_spawn_agent', 'sys_delegate_task', 'sys_finish_task']

const isRequiredTool = (toolName) => {
  // 检查是否是技能必需的工具
  const hasSkills = store.formData.availableSkills?.length > 0
  if (hasSkills && REQUIRED_TOOLS_FOR_SKILLS.includes(toolName)) {
    return true
  }

  // 检查是否是用户记忆类型必需的工具
  const memoryType = store.formData.memoryType
  if (memoryType === 'user' && REQUIRED_TOOLS_FOR_USER_MEMORY.includes(toolName)) {
    return true
  }

  // 检查是否是 Fibre 策略必需的工具
  const agentMode = store.formData.agentMode
  if (agentMode === 'fibre' && REQUIRED_TOOLS_FOR_FIBRE.includes(toolName)) {
    return true
  }

  return false
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

// 监听记忆类型变化，自动添加 search_memory 工具
watch(() => store.formData.memoryType, (newMemoryType) => {
  if (newMemoryType === 'user') {
    REQUIRED_TOOLS_FOR_USER_MEMORY.forEach(toolName => {
      if (!store.formData.availableTools.includes(toolName)) {
        store.formData.availableTools.push(toolName)
      }
    })
  }
})

// 监听 Agent 模式变化，自动添加 Fibre 必需工具
watch(() => store.formData.agentMode, (newAgentMode) => {
  if (newAgentMode === 'fibre') {
    REQUIRED_TOOLS_FOR_FIBRE.forEach(toolName => {
      if (!store.formData.availableTools.includes(toolName)) {
        store.formData.availableTools.push(toolName)
      }
    })
  }
})

// 监听工具列表变化，自动清理已不存在（被禁用）的工具
watch(() => props.tools, (newTools) => {
  console.log('[AgentEdit] props.tools changed:', newTools?.length, 'tools')
  if (!newTools || newTools.length === 0) return
  
  const availableToolNames = new Set(newTools.map(t => t.name))
  const currentTools = store.formData.availableTools || []
  
  console.log('[AgentEdit] Current selected tools:', currentTools)
  console.log('[AgentEdit] Available tool names:', Array.from(availableToolNames))
  
  // 过滤掉已不存在的工具（保留必需的技能工具）
  const filteredTools = currentTools.filter(toolName => {
    // 如果是必需的技能工具，保留
    if (isRequiredTool(toolName)) return true
    // 如果工具仍然存在于可用列表中，保留
    return availableToolNames.has(toolName)
  })
  
  // 如果有变化，更新表单
  if (filteredTools.length !== currentTools.length) {
    console.log('[AgentEdit] Removing unavailable tools:', currentTools.filter(t => !filteredTools.includes(t)))
    store.formData.availableTools = filteredTools
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
const filteredSkills = computed(() => {
  if (!searchQueries.skills) return props.skills
  const query = searchQueries.skills.toLowerCase()
  return props.skills.filter(skill => {
    const name = skill.name || skill
    const desc = skill.description || ''
    return name.toLowerCase().includes(query) || desc.toLowerCase().includes(query)
  })
})

// Selected skills for display as tags
const selectedSkills = computed(() => {
  const selected = store.formData.availableSkills || []
  return selected.map(skillName => {
    const skill = props.skills.find(s => (s.name || s) === skillName)
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

// External paths
const selectExternalPath = async () => {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      directory: true,
      multiple: false,
      title: '选择可访问文件夹'
    })
    if (selected) {
      store.addExternalPath(selected)
    }
  } catch (error) {
    console.error('选择文件夹失败:', error)
    const path = prompt('请输入文件夹路径:')
    if (path) {
      store.addExternalPath(path)
    }
  }
}
</script>

<style scoped>
.scroll-mt-6 {
  scroll-margin-top: 1.5rem;
}
</style>
