<template>
  <div class="flex justify-start px-4 animate-in fade-in duration-300">
    <div class="flex items-start gap-4 max-w-[80%]">
      <!-- Loading Bubble -->
      <div class="relative group">
        <div class="bg-background border border-border/40 rounded-2xl rounded-tl-sm px-5 py-3.5 shadow-sm flex items-center gap-3">
          <div class="flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce [animation-delay:-0.3s]"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce [animation-delay:-0.15s]"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce"></span>
          </div>
        </div>
        
        <!-- Decorative blur effect -->
        <div class="absolute -inset-1 bg-gradient-to-r from-primary/10 to-transparent blur-lg opacity-20 -z-10 group-hover:opacity-30 transition-opacity"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Loading animation component
</script>
