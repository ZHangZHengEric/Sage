import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Sage App 使用手册',
  description: 'Sage Desktop 使用文档',
  lang: 'zh-CN',
  base: '/',

  themeConfig: {
    logo: '/logo.svg',
    siteTitle: false,

    nav: [
      {
        text: 'GitHub',
        link: 'https://github.com/ZHangZHengEric/Sage',
        target: '_blank'
      }
    ],

    sidebar: [
      { text: '快速开始', link: '/guide/quickstart' },
      { text: '智能体', link: '/agent/' },
      { text: '聊天', link: '/chat/' },
      { text: '工具', link: '/tools/' },
      { text: '技能', link: '/skills/' },
      { text: '历史记录', link: '/history/' },
      { text: '任务调度', link: '/tasks/' },
      { text: '模型提供商', link: '/providers/' },
      { text: 'IM 渠道', link: '/im/' },
      { text: '系统设置', link: '/settings/' }
    ],

    search: {
      provider: 'local',
      options: {
        translations: {
          button: {
            buttonText: '搜索文档',
            buttonAriaLabel: '搜索文档'
          },
          modal: {
            noResultsText: '无法找到相关结果',
            resetButtonTitle: '清除查询条件',
            footer: {
              selectText: '选择',
              navigateText: '切换',
              closeText: '关闭'
            }
          }
        }
      }
    },

    outline: {
      level: [2, 3],
      label: '本页目录'
    },

    editLink: {
      pattern: 'https://github.com/ZHangZHengEric/Sage/edit/main/docs/:path',
      text: '在 GitHub 上编辑此页'
    },

    // Disabled to avoid "spawn git ENOENT" error in Docker build where .git is missing
    // lastUpdated: {
    //   text: '最后更新于',
    //   formatOptions: {
    //     dateStyle: 'short',
    //     timeStyle: 'short'
    //   }
    // },

    footer: {
      message: '基于 MIT 许可发布',
      copyright: 'Copyright © 2025 Sage AI'
    },

    docFooter: {
      prev: '上一页',
      next: '下一页'
    },

    returnToTopLabel: '返回顶部',
    sidebarMenuLabel: '菜单',
    darkModeSwitchLabel: '主题'
  }
})
