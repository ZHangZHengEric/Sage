<template>
  <div class="flex justify-start px-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
    <div class="flex items-start gap-4 max-w-[80%]">
      <!-- Loading Bubble -->
      <div class="relative group">
        <div class="bg-card/80 backdrop-blur-sm border border-border/40 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm flex items-center gap-1.5">
          <div class="dot w-2 h-2 rounded-full bg-primary/60"></div>
          <div class="dot w-2 h-2 rounded-full bg-primary/60" style="animation-delay: 0.2s"></div>
          <div class="dot w-2 h-2 rounded-full bg-primary/60" style="animation-delay: 0.4s"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Loading animation component
</script>

<style scoped>
.dot {
  animation: wave 1.5s infinite ease-in-out;
}

@keyframes wave {
  0%, 100% {
    transform: translateY(0);
    opacity: 0.6;
  }
  50% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
