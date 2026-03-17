<template>
  <div class="memory-search-item w-full mb-3" @click="handleClick">
    <!-- Memory Card with organic feel -->
    <div class="memory-card relative overflow-hidden rounded-2xl border border-amber-200/30 dark:border-amber-800/30 bg-gradient-to-br from-amber-50/80 via-orange-50/60 to-yellow-50/80 dark:from-amber-950/40 dark:via-orange-950/30 dark:to-yellow-950/40 backdrop-blur-sm transition-all duration-500 hover:shadow-lg hover:shadow-amber-500/10 hover:border-amber-300/50 dark:hover:border-amber-700/50 cursor-pointer group">
      
      <!-- Decorative memory particles -->
      <div class="absolute inset-0 overflow-hidden pointer-events-none">
        <div v-for="i in 6" :key="i" class="memory-particle absolute w-1 h-1 rounded-full bg-amber-400/40 dark:bg-amber-500/30"
          :style="{
            left: `${10 + i * 15}%`,
            top: `${20 + (i % 3) * 25}%`,
            animationDelay: `${i * 0.5}s`
          }">
        </div>
      </div>

      <!-- Header -->
      <div class="relative px-4 py-3 border-b border-amber-200/20 dark:border-amber-800/20">
        <div class="flex items-center gap-3">
          <!-- Memory Icon -->
          <div class="flex-none w-8 h-8 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 dark:from-amber-500 dark:to-orange-600 flex items-center justify-center shadow-lg shadow-amber-500/20">
            <Brain class="w-4 h-4 text-white" />
          </div>
          
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium text-amber-900 dark:text-amber-100">记忆搜索</span>
              <span class="text-xs text-amber-600/70 dark:text-amber-400/70">"{{ query }}"</span>
            </div>
            <div class="flex items-center gap-2 mt-0.5">
              <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300">
                {{ fileCount }} 个文件
              </span>
              <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-300">
                {{ historyCount }} 条对话
              </span>
            </div>
          </div>

          <!-- Expand Icon -->
          <ChevronRight class="h-4 w-4 text-amber-400/70 transition-transform