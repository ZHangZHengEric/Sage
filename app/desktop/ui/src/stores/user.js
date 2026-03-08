import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

// 生成 Avataaars 风格头像 URL
const generateAvatarUrl = (seed) => {
  // 使用 dicebear 的 Avataaars 风格
  // 参考: https://www.dicebear.com/styles/avataaars/
  const params = new URLSearchParams({
    seed: seed,
    // 可以添加更多自定义参数
    backgroundColor: 'b6e3f4,c0aede,d1d4f9', // 柔和的背景色
  })
  return `https://api.dicebear.com/9.x/avataaars/svg?${params.toString()}`
}

export const useUserStore = defineStore('user', () => {
  // 从 localStorage 读取头像种子
  const avatarSeed = ref(localStorage.getItem('user_avatar_seed') || '')

  // 头像 URL
  const avatarUrl = computed(() => {
    if (avatarSeed.value) {
      return generateAvatarUrl(avatarSeed.value)
    }
    // 默认头像
    return '/sage_logo.svg'
  })

  // 设置头像种子
  const setAvatarSeed = (seed) => {
    avatarSeed.value = seed
    localStorage.setItem('user_avatar_seed', seed)
  }

  // 获取当前头像种子
  const getAvatarSeed = () => {
    return avatarSeed.value
  }

  return {
    avatarSeed,
    avatarUrl,
    setAvatarSeed,
    getAvatarSeed
  }
})
