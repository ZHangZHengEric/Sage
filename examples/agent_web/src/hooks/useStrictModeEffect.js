import { useEffect, useRef } from 'react';

/**
 * 自定义 Hook，用于在 React StrictMode 下防止副作用重复执行
 * @param {Function} effect - 要执行的副作用函数
 * @param {Array} deps - 依赖数组
 * @param {string} debugName - 调试名称，用于日志输出
 */
export function useStrictModeEffect(effect, deps, debugName = 'Effect') {
  const hasExecuted = useRef(false);
  const cleanupRef = useRef(null);

  useEffect(() => {
    // 在 StrictMode 下，如果已经执行过，跳过
    if (hasExecuted.current) {
      if (process.env.NODE_ENV === 'development') {
        console.log(`🔄 ${debugName}: 检测到重复执行，跳过...`);
      }
      return;
    }

    hasExecuted.current = true;
    
    if (process.env.NODE_ENV === 'development') {
      console.log(`🚀 ${debugName}: 开始执行...`);
    }

    // 执行副作用
    const cleanup = effect();
    
    // 保存清理函数
    if (typeof cleanup === 'function') {
      cleanupRef.current = cleanup;
    }

    // 返回清理函数
    return () => {
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
      hasExecuted.current = false;
    };
  }, deps);
}

export default useStrictModeEffect;