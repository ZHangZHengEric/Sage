/**
 * 路径转换工具
 * 将容器内的文件路径转换为可访问的alist URL
 */

// 配置常量
const ALIST_BASE_URL = 'http://36.133.44.114:20045/d/';
const CONTAINER_WORKSPACE_PATH = '/app/workspace';

/**
 * 将容器内的文件路径转换为alist URL
 * @param content 包含路径的内容
 * @returns 转换后的内容
 */
export function convertContainerPathsToAlistUrls(content: string): string {
  if (!content || typeof content !== 'string') {
    return content;
  }

  // 匹配容器内工作空间路径的正则表达式
  // 匹配格式: /app/workspace/20250630_025558_6c06b08f-a20c-473d-bb5d-ce7e74e6a40d/test_quick_sort.py
  const pattern = new RegExp(`${CONTAINER_WORKSPACE_PATH.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/([^"\\s]+)`, 'g');
  
  return content.replace(pattern, (match, filePath) => {
    // 构建alist URL
    const alistUrl = `${ALIST_BASE_URL}${filePath}`;
    return alistUrl;
  });
}

/**
 * 检查内容是否包含容器路径
 * @param content 要检查的内容
 * @returns 是否包含容器路径
 */
export function containsContainerPath(content: string): boolean {
  if (!content || typeof content !== 'string') {
    return false;
  }
  
  const pattern = new RegExp(`${CONTAINER_WORKSPACE_PATH.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/([^"\\s]+)`, 'g');
  return pattern.test(content);
}

/**
 * 提取内容中的所有容器路径
 * @param content 要提取的内容
 * @returns 路径数组
 */
export function extractContainerPaths(content: string): string[] {
  if (!content || typeof content !== 'string') {
    return [];
  }
  
  const pattern = new RegExp(`${CONTAINER_WORKSPACE_PATH.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/([^"\\s]+)`, 'g');
  const paths: string[] = [];
  let match;
  
  while ((match = pattern.exec(content)) !== null) {
    paths.push(match[0]);
  }
  
  return paths;
} 