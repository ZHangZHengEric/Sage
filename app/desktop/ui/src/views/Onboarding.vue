<template>
  <div class="min-h-screen bg-background flex flex-col items-center justify-center p-4">
    <div class="max-w-md w-full space-y-8 text-center">
      <div class="space-y-4">
        <h1 class="text-4xl font-bold tracking-tight">Welcome to Sage</h1>
        <p class="text-muted-foreground text-lg">
          Your personal AI assistant for better productivity.
        </p>
      </div>

      <div class="grid gap-4 mt-8">
        <Button size="lg" class="w-full" @click="handleLogin">
          Sign In
        </Button>
        <div class="relative">
          <div class="absolute inset-0 flex items-center">
            <span class="w-full border-t" />
          </div>
          <div class="relative flex justify-center text-xs uppercase">
            <span class="bg-background px-2 text-muted-foreground">
              Or
            </span>
          </div>
        </div>
        <Button variant="outline" size="lg" class="w-full" @click="handleDefaultLogin">
          Quick Start (Default)
        </Button>
      </div>
      
      <p class="text-xs text-muted-foreground mt-4">
        Quick Start will use the default local account.
      </p>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { loginAPI } from '@/utils/auth'
import { toast } from 'vue-sonner'

const router = useRouter()

const markOnboardingComplete = () => {
  localStorage.setItem('hasSeenOnboarding', 'true')
}

const handleLogin = () => {
  markOnboardingComplete()
  // Redirect to home, App.vue will detect not logged in and show LoginModal
  router.push('/')
}

const handleDefaultLogin = async () => {
  try {
    const res = await loginAPI('admin', 'admin')
    if (res.success) {
      markOnboardingComplete()
      toast.success('Welcome back!')
      router.push('/')
    } else {
      toast.error('Default login failed: ' + res.message)
    }
  } catch (e) {
    toast.error('Login failed')
  }
}
</script>
