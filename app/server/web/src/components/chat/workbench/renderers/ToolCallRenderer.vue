<template>
  <div class="tool-call-renderer h-full flex flex-col overflow-hidden">
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <component :is="toolIcon" class="w-4 h-4 text-primary flex-shrink-0" />
        <span class="text-sm font-medium truncate">{{ displayToolName }}</span>
        <Badge v-if="toolResultStatus" :variant="toolResultStatus.variant" class="text-xs flex-shrink-0">
          {{ toolResultStatus.text }}
        </Badge>
      </div>
      <Button
        variant="ghost"
        size="sm"
        class="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
        @click="showRawDataDialog = true"
      >
        <Code class="w-3 h-3 mr-1" />
        {{ t('workbench.tool.rawData') }}
      </Button>
    </div>

    <Dialog v-model:open="showRawDataDialog">
      <DialogContent class="max-w-4xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2">
            <Code class="w-4 h-4" />
            {{ t('workbench.tool.rawData') }} - {{ displayToolName }}
          </DialogTitle>
          <DialogDescription>
            {{ t('workbench.tool.arguments') }} & {{ t('workbench.tool.result') }}
          </DialogDescription>
        </DialogHeader>
        <div class="grid grid-cols-2 gap-4 flex-1 overflow-hidden">
          <div class="flex flex-col overflow-hidden">
            <div class="text-sm font-medium mb-2 flex items-center gap-2">
              <Settings class="w-4 h-4" />
              {{ t('workbench.tool.arguments') }}
            </div>
            <div class="flex-1 overflow-auto bg-muted rounded-lg p-4">
              <pre class="text-xs font-mono whitespace-pre-wrap">{{ formattedArguments }}</pre>
            </div>
          </div>
          <div class="flex flex-col overflow-hidden">
            <div class="text-sm font-medium mb-2 flex items-center gap-2">
              <CheckCircle class="w-4 h-4" />
              {{ t('workbench.tool.result') }}
            </div>
            <div class="flex-1 overflow-auto bg-muted rounded-lg p-4">
              <pre class="text-xs font-mono whitespace-pre-wrap">{{ formattedResult }}</pre>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button @click="showRawDataDialog = false">{{ t('workbench.tool.close') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <div class="flex-1 overflow-hidden">
      <template v-if="isShellCommand">
        <div class="shell-container bg-black text-green-400 font-mono text-sm p-4 h-full overflow-auto">
          <div class="shell-header text-gray-500 mb-2">$ {{ shellCommand }}</div>
          <div v-if="shellOutput" class="shell-output whitespace-pre-wrap break-all">{{ shellOutput }}</div>
          <div v-if="shellError" class="shell-error text-red-400 mt-2 whitespace-pre-wrap break-all">{{ shellError }}</div>
        </div>
      </template>

      <template v-else-if="isLoadSkill">
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

      <FileReadToolRenderer
        v-else-if="isFileRead"
        :tool-args="toolArgs"
        :tool-result="toolResult"
      />

      <template v-else-if="isFileWrite">
        <div class="h-full flex flex-col">
          <div class="file-header px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
            <FileText class="w-4 h-4" />
            <span class="font-medium text-sm">{{ writeFilePath }}</span>
            <Badge variant="secondary" class="text-xs">{{ writeFileType }}</Badge>
          </div>
          <div class="write-info px-4 py-2 text-sm text-muted-foreground flex-none border-b border-border">
            {{ t('workbench.tool.writtenBytes', { bytes: writeContentLength }) }}
          </div>
          <div class="file-content flex-1 overflow-auto p-4">
            <SyntaxHighlighter
              v-if="isCodeFile(writeFileType)"
              :code="writeContent"
              :language="writeFileType"
            />
            <MarkdownRenderer
              v-else-if="writeFileType === 'markdown'"
              :content="writeContent"
            />
            <pre v-else class="whitespace-pre-wrap text-sm">{{ writeContent }}</pre>
          </div>
        </div>
      </template>

      <FileUpdateToolRenderer
        v-else-if="isFileUpdate"
        :tool-args="toolArgs"
        :tool-result="toolResult"
        :formatted-arguments="formattedArguments"
        :display-tool-name="displayToolName"
        :has-arguments="hasArguments"
      />

      <template v-else-if="isTodoWrite">
        <div class="todo-write-container h-full overflow-auto p-4">
          <div v-if="todoSummary" class="mb-4 p-3 bg-muted/30 rounded-lg border border-border/50">
            <div class="flex items-center gap-2 text-sm">
              <ListTodo class="w-4 h-4 text-primary" />
              <span>{{ todoSummary }}</span>
            </div>
          </div>
          <div v-if="todoTasks.length > 0" class="space-y-2">
            <div
              v-for="task in todoTasks"
              :key="task.id"
              class="flex items-center gap-3 p-3 rounded-lg border transition-colors"
              :class="getTodoTaskClass(task.status)"
            >
              <div class="flex-shrink-0">
                <CheckCircle2 v-if="task.status === 'completed'" class="w-5 h-5 text-green-500" />
                <Circle v-else-if="task.status === 'pending'" class="w-5 h-5 text-muted-foreground" />
                <Loader2 v-else-if="task.status === 'in_progress'" class="w-5 h-5 text-blue-500 animate-spin" />
                <XCircle v-else-if="task.status === 'failed'" class="w-5 h-5 text-red-500" />
                <HelpCircle v-else class="w-5 h-5 text-muted-foreground" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-xs text-muted-foreground font-mono">#{{ task.index }}</span>
                  <span class="text-sm font-medium truncate">{{ task.name }}</span>
                </div>
                <div class="text-xs text-muted-foreground/70 mt-0.5">{{ task.id }}</div>
              </div>
              <Badge :variant="getTodoStatusVariant(task.status)" class="text-xs flex-shrink-0">
                {{ getTodoStatusLabel(task.status) }}
              </Badge>
            </div>
          </div>
          <div v-else class="flex items-center justify-center h-32 text-muted-foreground">
            <div class="text-center">
              <ListTodo class="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p class="text-sm">{{ t('workbench.tool.noTasks') }}</p>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isSysSpawnAgent">
        <div class="sys-spawn-agent-container h-full flex flex-col">
          <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span>{{ t('workbench.tool.creatingAgent') }}</span>
          </div>
          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-medium">{{ t('workbench.tool.createFailed') }}</p>
              <p class="text-sm opacity-80 mt-1">{{ spawnAgentError }}</p>
            </div>
          </div>
          <div v-else class="flex flex-col h-full">
            <div class="flex items-start gap-3 p-4 pb-3 border-b border-border/30">
              <img :src="spawnAgentAvatarUrl" :alt="spawnAgentName" class="w-10 h-10 rounded-lg bg-muted object-cover flex-shrink-0" />
              <div class="flex-1 min-w-0">
                <h4 class="font-medium text-sm text-foreground">{{ spawnAgentName || t('workbench.tool.untitledAgent') }}</h4>
                <p class="text-xs text-muted-foreground mt-0.5">{{ spawnAgentDescription || t('workbench.tool.noDescription') }}</p>
              </div>
              <Button variant="ghost" size="sm" class="h-7 text-xs" @click="openSpawnedAgentChat">
                <MessageSquare class="w-3.5 h-3.5 mr-1" />
                {{ t('workbench.tool.startChat') }}
              </Button>
            </div>
            <div v-if="spawnAgentSystemPrompt" class="flex-1 min-h-0 overflow-hidden">
              <div class="h-full overflow-auto custom-scrollbar p-4">
                <MarkdownRenderer :content="spawnAgentSystemPrompt" class="text-xs" />
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isSysDelegateTask">
        <div class="sys-delegate-task-container h-full flex flex-col">
          <div class="flex items-center justify-center gap-6 py-4 border-b border-border/30 bg-muted/20 flex-shrink-0">
            <div class="flex flex-col items-center gap-2 w-[100px]">
              <div class="relative">
                <img
                  :src="currentAgentAvatar"
                  :alt="currentAgentName"
                  class="w-12 h-12 rounded-xl bg-muted object-cover border-2 border-primary/30"
                />
                <div class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                  <User class="w-3 h-3 text-primary-foreground" />
                </div>
              </div>
              <span class="text-xs text-muted-foreground">{{ t('workbench.tool.delegator') }}</span>
            </div>

            <div class="flex flex-col items-center gap-1">
              <ArrowRight class="w-5 h-5 text-muted-foreground" />
              <span class="text-xs text-muted-foreground">{{ delegateTasks.length }} {{ t('workbench.tool.tasks') }}</span>
            </div>

            <div class="flex flex-col items-center gap-2 w-[100px]">
              <div class="flex -space-x-2">
                <img
                  v-for="(task, idx) in delegateTasks.slice(0, 3)"
                  :key="idx"
                  :src="getAgentAvatar(task.agent_id)"
                  :alt="task.agent_id"
                  class="w-10 h-10 rounded-xl bg-muted object-cover border-2 border-background"
                />
                <div v-if="delegateTasks.length > 3" class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center border-2 border-background text-xs font-medium">
                  +{{ delegateTasks.length - 3 }}
                </div>
              </div>
              <span class="text-sm font-medium truncate w-full text-center">{{ delegateTasks.length }} {{ t('workbench.tool.targetAgents') }}</span>
            </div>
          </div>

          <div class="flex-1 overflow-auto p-4 space-y-3 custom-scrollbar">
            <div
              v-for="(task, index) in delegateTasks"
              :key="index"
              class="border rounded-lg p-3 hover:bg-muted/30 transition-colors"
            >
              <div class="flex items-start gap-3">
                <img
                  :src="getAgentAvatar(task.agent_id)"
                  :alt="task.agent_id"
                  class="w-10 h-10 rounded-lg bg-muted object-cover flex-shrink-0"
                />
                <div class="flex-1 min-w-0">
                  <div class="flex items-center justify-between mb-1">
                    <p class="text-sm font-medium truncate">{{ task.task_name || task.original_task || t('workbench.tool.untitledTask') }}</p>
                    <Badge v-if="task.session_id" variant="outline" class="text-xs flex-shrink-0 ml-2">
                      {{ t('workbench.tool.hasSession') }}
                    </Badge>
                  </div>
                  <p class="text-xs text-muted-foreground truncate mb-2">{{ getAgentName(task.agent_id) }}</p>
                  <div class="bg-muted/30 rounded p-2 max-h-[150px] overflow-y-auto custom-scrollbar">
                    <pre class="text-xs whitespace-pre-wrap font-mono">{{ task.content }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="!toolResult" class="flex items-center justify-center p-4 border-t border-border/30 bg-muted/10">
            <Loader2 class="w-5 h-5 animate-spin mr-2 text-primary" />
            <span class="text-sm text-muted-foreground">{{ t('workbench.tool.delegatingTasks') }}</span>
          </div>

          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 border-t border-border/30 bg-destructive/5">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5 text-destructive" />
            <div>
              <p class="font-medium text-destructive">{{ t('workbench.tool.delegationFailed') }}</p>
              <p class="text-sm opacity-80 mt-1">{{ delegationError }}</p>
            </div>
          </div>

          <div v-else-if="delegationResult" class="border-t border-border/30 p-4 bg-green-500/5">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <CheckCircle class="w-4 h-4 text-green-600" />
                <span class="text-sm font-medium text-green-700">{{ t('workbench.tool.delegationCompleted') }}</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                class="h-6 text-xs gap-1"
                @click="showDelegationResult = !showDelegationResult"
              >
                <Eye v-if="!showDelegationResult" class="w-3.5 h-3.5" />
                <EyeOff v-else class="w-3.5 h-3.5" />
                {{ showDelegationResult ? t('workbench.tool.hideResult') : t('workbench.tool.viewResult') }}
              </Button>
            </div>
            <div v-if="showDelegationResult" class="max-h-[200px] overflow-auto custom-scrollbar bg-background rounded p-2">
              <MarkdownRenderer :content="delegationResult" class="text-xs" />
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isSysFinishTask">
        <div class="sys-finish-task-container h-full flex flex-col">
          <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span>{{ t('workbench.tool.finishingTask') }}</span>
          </div>
          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-medium">{{ t('workbench.tool.finishFailed') }}</p>
              <p class="text-sm opacity-80 mt-1">{{ finishTaskError }}</p>
            </div>
          </div>
          <div v-else class="flex flex-col h-full overflow-hidden">
            <div class="flex items-center gap-3 p-4 border-b border-border/30 bg-green-500/5 flex-shrink-0">
              <div class="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center">
                <CheckCircle class="w-5 h-5 text-green-600" />
              </div>
              <div>
                <p class="font-medium text-sm">{{ t('workbench.tool.taskCompleted') }}</p>
                <p class="text-xs text-muted-foreground">{{ finishTaskStatus }}</p>
              </div>
            </div>
            <div class="flex-1 overflow-hidden">
              <div class="h-full overflow-auto custom-scrollbar p-4">
                <MarkdownRenderer :content="finishTaskResult" class="text-sm" />
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isCodeExecution">
        <div class="ide-container h-full flex flex-col bg-[#1e1e1e] overflow-hidden">
          <div class="code-section flex-[3] min-h-0 overflow-auto">
            <SyntaxHighlighter
              :code="executedCode"
              :language="executionLanguage"
              :show-header="false"
              :show-copy-button="false"
              class="h-full !my-0 !rounded-none !border-0"
            />
          </div>
          <div v-if="executionResult" class="result-section flex-1 min-h-[80px] max-h-[150px] flex flex-col border-t border-border/30 bg-black/20 overflow-hidden">
            <div class="section-header px-3 py-1.5 bg-muted/30 text-[10px] text-muted-foreground flex items-center gap-1.5 flex-none">
              <Terminal class="w-3 h-3" />
              {{ t('workbench.tool.result') }}
            </div>
            <div class="result-content flex-1 overflow-auto px-3 py-2 font-mono text-xs">
              <div v-if="executionError" class="text-red-400">{{ executionError }}</div>
              <pre v-else class="whitespace-pre-wrap text-gray-300">{{ executionResult }}</pre>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isSearchWebPage">
        <div class="search-web-container h-full flex flex-col overflow-hidden">
          <div class="search-header px-4 py-3 border-b border-border/30 bg-muted/20 flex-none">
            <div class="flex items-center gap-2">
              <Search class="w-4 h-4 text-primary" />
              <span class="text-sm font-medium">{{ searchQuery }}</span>
              <Badge v-if="searchResults.length > 0" variant="secondary" class="text-xs">
                {{ searchResults.length }} {{ t('workbench.tool.results') }}
              </Badge>
            </div>
          </div>
          <div class="search-results flex-1 overflow-auto p-4 space-y-3">
            <div v-if="searchLoading" class="flex items-center justify-center h-full text-muted-foreground">
              <Loader2 class="w-5 h-5 animate-spin mr-2" />
              {{ t('workbench.tool.searching') }}
            </div>
            <div v-else-if="searchResults.length === 0" class="flex items-center justify-center h-full text-muted-foreground">
              <div class="text-center">
                <Search class="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p class="text-sm">{{ t('workbench.tool.noSearchResults') }}</p>
              </div>
            </div>
            <div
              v-for="(result, index) in searchResults"
              :key="index"
              class="search-result-item border rounded-lg p-3 hover:bg-muted/30 transition-colors cursor-pointer"
              @click="openSearchResult(result.url)"
            >
              <div class="flex items-start gap-3">
                <div class="flex-1 min-w-0">
                  <h4 class="text-sm font-medium text-primary truncate">{{ result.title }}</h4>
                  <p class="text-xs text-muted-foreground mt-1 line-clamp-2">{{ result.content }}</p>
                  <div class="flex items-center gap-2 mt-2">
                    <Globe class="w-3 h-3 text-muted-foreground" />
                    <span class="text-xs text-muted-foreground truncate">{{ result.url }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isSearchImageFromWeb">
        <div class="search-image-container h-full flex flex-col overflow-hidden">
          <div class="search-header px-4 py-3 border-b border-border/30 bg-muted/20 flex-none">
            <div class="flex items-center gap-2">
              <ImageIcon class="w-4 h-4 text-primary" />
              <span class="text-sm font-medium">{{ searchImageQuery }}</span>
              <Badge v-if="searchImageResults.length > 0" variant="secondary" class="text-xs">
                {{ searchImageResults.length }} {{ t('workbench.tool.images') }}
              </Badge>
            </div>
          </div>
          <div class="search-image-results flex-1 overflow-auto p-4">
            <div v-if="searchImageLoading" class="flex items-center justify-center h-full text-muted-foreground">
              <Loader2 class="w-5 h-5 animate-spin mr-2" />
              {{ t('workbench.tool.searchingImages') }}
            </div>
            <div v-else-if="searchImageResults.length === 0" class="flex items-center justify-center h-full text-muted-foreground">
              <div class="text-center">
                <ImageIcon class="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p class="text-sm">{{ t('workbench.tool.noImageResults') }}</p>
              </div>
            </div>
            <div v-else class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              <div
                v-for="(image, index) in searchImageResults"
                :key="index"
                class="search-image-item relative group aspect-square rounded-lg overflow-hidden border hover:border-primary transition-colors cursor-pointer"
                @click="openImagePreview(image.image_url || image.url)"
              >
                <img
                  :src="image.image_url || image.url"
                  :alt="image.title"
                  class="w-full h-full object-cover"
                  @error="handleImageError($event, index)"
                />
                <div class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2">
                  <p class="text-xs text-white truncate">{{ image.title }}</p>
                  <p class="text-[10px] text-white/70 truncate">{{ image.source }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="isSearchMemory">
        <MemoryToolRenderer
          :tool-call="item"
          :tool-result="toolResultData"
        />
      </template>

      <template v-else-if="isQuestionnaire">
        <div class="questionnaire-container h-full overflow-auto p-6">
          <QuestionnaireReadonly
            :tool-call="toolCall"
            :tool-result="toolResult"
          />
        </div>
      </template>

      <template v-else-if="isCompressHistory">
        <div class="compress-history-container h-full flex flex-col overflow-hidden">
          <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span>{{ t('workbench.tool.compressingHistory') }}</span>
          </div>
          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-medium">{{ t('workbench.tool.compressFailed') }}</p>
              <p class="text-sm opacity-80 mt-1">{{ compressHistoryError }}</p>
            </div>
          </div>
          <div v-else class="flex flex-col h-full overflow-hidden">
            <div class="flex items-center gap-3 p-4 border-b border-border/30 bg-blue-500/5 flex-shrink-0">
              <div class="w-10 h-10 rounded-full bg-blue-500/20 flex items-center justify-center">
                <Minimize2 class="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <p class="font-medium text-sm">{{ t('workbench.tool.historyCompressed') }}</p>
                <p class="text-xs text-muted-foreground">{{ compressHistoryStats }}</p>
              </div>
            </div>
            <div class="flex-1 overflow-hidden">
              <div class="h-full overflow-auto custom-scrollbar p-4">
                <MarkdownRenderer :content="compressHistoryResult" class="text-sm" />
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="p-4 h-full overflow-auto">
          <div v-if="hasArguments" class="mb-4">
            <div class="text-xs text-muted-foreground mb-2 flex items-center gap-1">
              <Settings class="w-3 h-3" />
              {{ t('workbench.tool.arguments') }}
            </div>
            <pre class="bg-muted p-3 rounded text-xs whitespace-pre-wrap break-all">{{ formattedArguments }}</pre>
          </div>

          <div v-if="hasResult">
            <div class="text-xs text-muted-foreground mb-2 flex items-center gap-1">
              <CheckCircle class="w-3 h-3" />
              {{ t('workbench.tool.result') }}
            </div>
            <div v-if="isErrorResult" class="bg-destructive/10 text-destructive p-3 rounded text-sm">
              {{ errorMessage }}
            </div>
            <pre v-else class="bg-muted p-3 rounded text-xs whitespace-pre-wrap break-all">{{ formattedResult }}</pre>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import {
  Terminal,
  FileText,
  Search,
  Code,
  Database,
  Globe,
  Settings,
  Zap,
  CheckCircle,
  ListTodo,
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
  HelpCircle,
  MessageSquare,
  ArrowRight,
  User,
  Eye,
  EyeOff,
  Image as ImageIcon,
  Brain,
  Minimize2
} from 'lucide-vue-next'
import SyntaxHighlighter from '../../SyntaxHighlighter.vue'
import MarkdownRenderer from '../../MarkdownRenderer.vue'
import { MemoryToolRenderer } from './toolcall'
import FileReadToolRenderer from './toolcall/FileReadToolRenderer.vue'
import FileUpdateToolRenderer from './toolcall/FileUpdateToolRenderer.vue'
import QuestionnaireReadonly from './toolcall/QuestionnaireReadonly.vue'
import { skillAPI } from '@/api/skill.js'
import { agentAPI } from '@/api/agent.js'
import { useLanguage } from '@/utils/i18n'
import { getToolLabel } from '@/utils/messageLabels.js'

const { t } = useLanguage()

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

const showRawDataDialog = ref(false)
const skillInfo = ref({ name: '', description: '', content: '' })
const skillLoading = ref(false)
const skillError = ref('')
const agentList = ref([])
const agentListLoaded = ref(false)
const showDelegationResult = ref(false)

const toolCall = computed(() => props.item.data?.toolCall || props.item.data || {})
const toolResult = computed(() => props.item.toolResult || props.item.data?.toolResult || null)

const toolResultData = computed(() => {
  if (!toolResult.value) return null
  let result = toolResult.value.content
  if (typeof result === 'string') {
    try {
      result = JSON.parse(result)
    } catch {
      return result
    }
  }
  return result
})

const toolName = computed(() => toolCall.value.function?.name || '')

watch(() => props.item.toolResult, (newVal, oldVal) => {
  console.log('[ToolCallRenderer] toolResult changed:', {
    toolName: toolName.value,
    hasNewVal: !!newVal,
    hasOldVal: !!oldVal,
    newValKeys: newVal ? Object.keys(newVal) : [],
    content: newVal?.content
  })
})

const toolArgs = computed(() => {
  try {
    const args = toolCall.value.function?.arguments
    if (typeof args === 'string') return JSON.parse(args)
    return args || {}
  } catch {
    return {}
  }
})

const isShellCommand = computed(() => toolName.value === 'execute_shell_command')
const isLoadSkill = computed(() => toolName.value === 'load_skill')
const isFileRead = computed(() => toolName.value === 'file_read')
const isFileWrite = computed(() => toolName.value === 'file_write')
const isFileUpdate = computed(() => toolName.value === 'file_update')
const isCodeExecution = computed(() => toolName.value === 'execute_python_code' || toolName.value === 'execute_javascript_code')
const isTodoWrite = computed(() => toolName.value === 'todo_write')
const isSysSpawnAgent = computed(() => toolName.value === 'sys_spawn_agent')
const isSysDelegateTask = computed(() => toolName.value === 'sys_delegate_task')
const isSysFinishTask = computed(() => toolName.value === 'sys_finish_task')
const isSearchWebPage = computed(() => toolName.value === 'search_web_page')
const isSearchImageFromWeb = computed(() => toolName.value === 'search_image_from_web')
const isSearchMemory = computed(() => toolName.value === 'search_memory' || toolName.value === 'memory_search')
const isQuestionnaire = computed(() => toolName.value === 'questionnaire')
const isCompressHistory = computed(() => toolName.value === 'compress_conversation_history')

const displayToolName = computed(() => getToolLabel(toolName.value, t))

const shellCommand = computed(() => toolArgs.value.command || '')
const shellOutput = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.stdout || parsed.output || content
    } catch {
      return content
    }
  }
  return content?.stdout || content?.output || JSON.stringify(content)
})
const shellError = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.stderr || parsed.error
    } catch {
      return ''
    }
  }
  return content?.stderr || content?.error
})

const skillName = computed(() => toolArgs.value.skill_name || '')

const fetchSkillInfo = async () => {
  if (!isLoadSkill.value || !skillName.value) return
  skillLoading.value = true
  skillError.value = ''
  try {
    const result = await skillAPI.getSkillContent(skillName.value)
    if (result) {
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
    }
  } catch (error) {
    console.error('[ToolCallRenderer] Failed to fetch skill info:', error)
    skillError.value = t('workbench.tool.loadingSkillError') + ': ' + (error.message || 'Unknown Error')
  } finally {
    skillLoading.value = false
  }
}

watch(isLoadSkill, (newVal) => {
  if (newVal && skillName.value && !skillInfo.value.description) fetchSkillInfo()
}, { immediate: true })

watch(skillName, (newVal, oldVal) => {
  if (newVal !== oldVal) {
    skillInfo.value = { name: '', description: '', content: '' }
    skillError.value = ''
    if (newVal && isLoadSkill.value) fetchSkillInfo()
  }
})

watch(() => props.item?.id, (newId, oldId) => {
  if (newId !== oldId) {
    skillInfo.value = { name: '', description: '', content: '' }
    skillError.value = ''
    agentListLoaded.value = false
    agentList.value = []
  }
})

const writeFilePath = computed(() => toolArgs.value.file_path || '')
const writeFileType = computed(() => {
  const ext = writeFilePath.value.split('.').pop()?.toLowerCase()
  const typeMap = {
    py: 'python',
    js: 'javascript',
    ts: 'typescript',
    vue: 'vue',
    html: 'html',
    css: 'css',
    json: 'json',
    md: 'markdown',
    txt: 'text',
    yml: 'yaml',
    yaml: 'yaml',
    sh: 'bash'
  }
  return typeMap[ext] || ext || 'text'
})
const writeContent = computed(() => toolArgs.value.content || '')
const writeContentLength = computed(() => writeContent.value ? new Blob([writeContent.value]).size : 0)

const executionLanguage = computed(() => {
  if (toolName.value === 'execute_python_code') return 'python'
  if (toolName.value === 'execute_javascript_code') return 'javascript'
  return 'text'
})
const executedCode = computed(() => toolArgs.value.code || '')
const executionResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.result || parsed.output || parsed.stdout || content
  } catch {
    return content
  }
})
const executionError = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.error || parsed.stderr
  } catch {
    return toolResult.value.is_error ? content : ''
  }
})

const compressHistoryResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  try {
    const parsed = JSON.parse(content)
    return parsed.message || parsed.content || content
  } catch {
    return content
  }
})
const compressHistoryStats = computed(() => {
  const result = compressHistoryResult.value
  if (!result) return ''
  const match = result.match(/(\d+)\s*tokens?\s*→\s*(\d+)\s*tokens?.*\((压缩率|compression):\s*([^)]+)\)/i)
  if (match) return `${match[1]} → ${match[2]} tokens (${match[4]})`
  return ''
})
const compressHistoryError = computed(() => {
  if (!toolResult.value?.content) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  try {
    const parsed = JSON.parse(content)
    return parsed.message || parsed.error || t('workbench.tool.unknownError')
  } catch {
    return String(content)
  }
})

const hasArguments = computed(() => Object.keys(toolArgs.value).length > 0)
const hasResult = computed(() => !!toolResult.value)
const isErrorResult = computed(() => toolResult.value?.is_error)
const errorMessage = computed(() => {
  const content = toolResult.value?.content
  if (typeof content === 'string') return content
  return JSON.stringify(content)
})

const toolResultStatus = computed(() => {
  if (!toolResult.value) return null
  if (toolResult.value.is_error) return { text: t('workbench.tool.statusError'), variant: 'destructive' }
  return { text: t('workbench.tool.statusCompleted'), variant: 'outline' }
})

const toolIcon = computed(() => {
  const name = toolName.value.toLowerCase()
  if (name.includes('terminal') || name.includes('command') || name.includes('shell')) return Terminal
  if (name.includes('file') || name.includes('read') || name.includes('write')) return FileText
  if (name === 'search_memory' || name.includes('memory')) return Brain
  if (name.includes('search')) return Search
  if (name.includes('code') || name.includes('python') || name.includes('javascript')) return Code
  if (name.includes('db') || name.includes('sql') || name.includes('query')) return Database
  if (name.includes('web') || name.includes('http') || name.includes('url')) return Globe
  if (name.includes('skill')) return Settings
  if (name.includes('compress')) return Minimize2
  return Zap
})

const isCodeFile = (type) => ['python', 'javascript', 'typescript', 'vue', 'html', 'css', 'json', 'bash', 'yaml'].includes(type)

const roleLabel = computed(() => {
  const roleMap = {
    assistant: t('workbench.tool.role.ai'),
    user: t('workbench.tool.role.user'),
    system: t('workbench.tool.role.system'),
    tool: t('workbench.tool.role.tool')
  }
  return roleMap[props.item?.role] || t('workbench.tool.role.ai')
})

const roleColor = computed(() => {
  const colorMap = {
    assistant: 'text-primary',
    user: 'text-muted-foreground',
    system: 'text-orange-500',
    tool: 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  let dateVal = timestamp
  const num = Number(timestamp)
  if (!isNaN(num)) dateVal = num < 10000000000 ? num * 1000 : num
  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

const formattedArguments = computed(() => JSON.stringify(toolArgs.value, null, 2))
const formattedResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'object') return JSON.stringify(content, null, 2)
  try {
    return JSON.stringify(JSON.parse(content), null, 2)
  } catch {
    return content
  }
})

const todoSummary = computed(() => {
  if (!toolResult.value) return ''
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    return parsed.summary || ''
  } catch {
    return ''
  }
})
const todoTasks = computed(() => {
  if (!toolResult.value) return []
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    return parsed.tasks || []
  } catch {
    return []
  }
})
const getTodoTaskClass = (status) => ({
  completed: 'bg-green-500/10 border-green-500/30',
  pending: 'bg-muted/30 border-border/50',
  in_progress: 'bg-blue-500/10 border-blue-500/30',
  failed: 'bg-red-500/10 border-red-500/30'
}[status] || 'bg-muted/30 border-border/50')
const getTodoStatusVariant = (status) => ({
  completed: 'success',
  pending: 'secondary',
  in_progress: 'default',
  failed: 'destructive'
}[status] || 'secondary')
const getTodoStatusLabel = (status) => ({
  completed: t('workbench.tool.statusCompleted'),
  pending: 'Pending',
  in_progress: 'In Progress',
  failed: 'Failed'
}[status] || status)

const delegateTasks = computed(() => toolArgs.value.tasks || [])
const generateAvatarUrl = (agentId) => agentId ? `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}` : ''
const getAgentNameById = (agentIdOrName) => {
  if (!agentIdOrName) return t('workbench.tool.unknownAgent')
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  if (!agent) agent = agentList.value.find(a => a.name === agentIdOrName)
  return agent?.name || agentIdOrName
}
const getAgentAvatarUrl = (agentIdOrName) => {
  if (!agentIdOrName) return ''
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  if (!agent) agent = agentList.value.find(a => a.name === agentIdOrName)
  if (agent?.avatar_url) return agent.avatar_url
  return generateAvatarUrl(agentIdOrName)
}
const currentAgentId = computed(() => props.item?.agent_id || props.item?.data?.agent_id || props.item?.data?.source_agent_id || '')
const currentAgentName = computed(() => props.item?.agent_name || props.item?.data?.agent_name || props.item?.data?.source_agent_name || props.item?.role || t('workbench.tool.delegator'))
const currentAgentAvatar = computed(() => getAgentAvatarUrl(currentAgentId.value || currentAgentName.value || 'current'))
const getAgentAvatar = (agentId) => getAgentAvatarUrl(agentId)
const getAgentName = (agentId) => getAgentNameById(agentId)
const loadAgentList = async () => {
  if (agentListLoaded.value) return
  try {
    const agents = await agentAPI.getAgents()
    agentList.value = agents || []
    agentListLoaded.value = true
  } catch (error) {
    console.error('[ToolCallRenderer] Failed to load agent list:', error)
  }
}
const delegationError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
})
const delegationResult = computed(() => {
  if (!toolResult.value || toolResult.value.is_error) return null
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content, null, 2)
})

const spawnAgentName = computed(() => toolArgs.value.name || '')
const spawnAgentDescription = computed(() => toolArgs.value.description || '')
const spawnAgentSystemPrompt = computed(() => toolArgs.value.system_prompt || '')
const spawnAgentId = computed(() => {
  if (!toolResult.value) return null
  const message = typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
  const match = message.match(/agent_[a-zA-Z0-9]+/)
  return match ? match[0] : null
})
const spawnAgentError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
})
const spawnAgentAvatarUrl = computed(() => {
  const seed = spawnAgentId.value || spawnAgentName.value || 'default'
  return `https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(seed)}&backgroundColor=b6e3f4,c0aede,d1d4f9`
})
const openSpawnedAgentChat = () => {
  if (!spawnAgentId.value) return
  localStorage.setItem('selectedAgentId', spawnAgentId.value)
  window.location.href = `/chat?agent=${spawnAgentId.value}`
}

const finishTaskStatus = computed(() => toolArgs.value.status || 'success')
const finishTaskResult = computed(() => {
  const resultFromArgs = toolArgs.value.result
  if (resultFromArgs) return typeof resultFromArgs === 'string' ? resultFromArgs : JSON.stringify(resultFromArgs, null, 2)
  if (!toolResult.value) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content, null, 2)
})
const finishTaskError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
})

const searchQuery = computed(() => toolArgs.value.query || '')
const searchLoading = computed(() => !toolResult.value)
const searchResults = computed(() => {
  if (!toolResult.value) return []
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    if (parsed.results && Array.isArray(parsed.results)) return parsed.results
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
})
const openSearchResult = (url) => {
  if (url) window.open(url, '_blank')
}

const searchImageQuery = computed(() => toolArgs.value.query || '')
const searchImageLoading = computed(() => !toolResult.value)
const searchImageResults = computed(() => {
  if (!toolResult.value) return []
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    if (parsed.images && Array.isArray(parsed.images)) return parsed.images
    if (parsed.results && Array.isArray(parsed.results)) return parsed.results
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
})
const openImagePreview = (url) => {
  if (url) window.open(url, '_blank')
}
const handleImageError = (event) => {
  event.target.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"%3E%3Crect width="100" height="100" fill="%23f3f4f6"/%3E%3Ctext x="50" y="50" font-family="Arial" font-size="12" fill="%239ca3af" text-anchor="middle" dy=".3em"%3EImage Error%3C/text%3E%3C/svg%3E'
}

onMounted(() => {
  nextTick(() => {
    if (isSysDelegateTask.value) loadAgentList()
    if (isLoadSkill.value && skillName.value) fetchSkillInfo()
  })
})
</script>

<style scoped>
.shell-container {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}

.shell-header {
  border-bottom: 1px solid #333;
  padding-bottom: 8px;
}

.ide-container {
  display: flex;
  flex-direction: column;
}

.code-section,
.result-section {
  flex: 1;
  overflow: hidden;
}

.section-header {
  border-bottom: 1px solid hsl(var(--border));
}
</style>
