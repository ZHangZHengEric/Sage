import { createPinia } from 'pinia'

// 创建pinia实例
const pinia = createPinia()

export default pinia

// 导出所有store
export { useAppStore } from './app'
export { useChatStore } from './chat'
export { useToolStore } from './tool'