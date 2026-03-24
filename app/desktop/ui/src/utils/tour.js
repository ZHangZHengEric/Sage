import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import { useLanguage } from './i18n'

const STORAGE_KEYS = {
  SIDEBAR: 'sage_tour_sidebar_seen',
  AGENT_EDIT_STEP1: 'sage_tour_agent_edit_step1_seen',
  AGENT_EDIT_STEP2: 'sage_tour_agent_edit_step2_seen'
}

export const useTour = () => {
  const { t } = useLanguage()

  const createDriver = () => {
    return driver({
      showProgress: true,
      allowClose: true,
      animate: true,
      nextBtnText: t('tour.next'),
      prevBtnText: t('tour.prev'),
      doneBtnText: t('tour.done'),
      // driver.js popover class name for custom styling
      popoverClass: 'driver-popover-theme',
      steps: [],
      onDestroyStarted: () => {
         // verification or cleanup if needed
      }
    })
  }

  const startSidebarTour = (force = false) => {
    if (!force && localStorage.getItem(STORAGE_KEYS.SIDEBAR)) {
      return
    }

    const driverObj = driver({
      showProgress: true,
      allowClose: true,
      nextBtnText: t('tour.next'),
      prevBtnText: t('tour.prev'),
      doneBtnText: t('tour.done'),
      popoverClass: 'driver-popover-theme',
      steps: [
        {
          element: '#tour-sidebar-new-chat',
          popover: {
            title: t('tour.sidebar.newChat.title'),
            description: t('tour.sidebar.newChat.desc'),
            side: 'right',
            align: 'start'
          }
        },
        {
          element: '#tour-sidebar-history',
          popover: {
            title: t('tour.sidebar.history.title'),
            description: t('tour.sidebar.history.desc'),
            side: 'right',
            align: 'start'
          }
        },
        {
          element: '#tour-sidebar-agent-list',
          popover: {
            title: t('tour.sidebar.agentList.title'),
            description: t('tour.sidebar.agentList.desc'),
            side: 'right',
            align: 'start'
          }
        },
        {
          element: '#tour-sidebar-personal-center',
          popover: {
            title: t('tour.sidebar.personalCenter.title'),
            description: t('tour.sidebar.personalCenter.desc'),
            side: 'right',
            align: 'start'
          }
        },
        {
          element: '#tour-sidebar-system-settings',
          popover: {
            title: t('tour.sidebar.systemSettings.title'),
            description: t('tour.sidebar.systemSettings.desc'),
            side: 'right',
            align: 'start'
          }
        }
      ],
      onDestroyed: () => {
        localStorage.setItem(STORAGE_KEYS.SIDEBAR, 'true')
      }
    })

    driverObj.drive()
  }

  const startAgentEditStep1Tour = (force = false) => {
    if (!force && localStorage.getItem(STORAGE_KEYS.AGENT_EDIT_STEP1)) {
      return
    }

    const driverObj = driver({
      showProgress: true,
      allowClose: true,
      nextBtnText: t('tour.next'),
      prevBtnText: t('tour.prev'),
      doneBtnText: t('tour.done'),
      popoverClass: 'driver-popover-theme',
      steps: [
        {
          element: '#tour-agent-step1-basic',
          popover: {
            title: t('tour.agent.step1.basic.title'),
            description: t('tour.agent.step1.basic.desc'),
            side: 'left',
            align: 'start'
          }
        },
        {
          element: '#tour-agent-step1-strategy',
          popover: {
            title: t('tour.agent.step1.strategy.title'),
            description: t('tour.agent.step1.strategy.desc'),
            side: 'left',
            align: 'start'
          }
        },
        {
          element: '#tour-agent-step1-context',
          popover: {
            title: t('tour.agent.step1.context.title'),
            description: t('tour.agent.step1.context.desc'),
            side: 'left',
            align: 'start'
          }
        },
        {
          element: '#tour-agent-step1-workflows',
          popover: {
            title: t('tour.agent.step1.workflows.title'),
            description: t('tour.agent.step1.workflows.desc'),
            side: 'left',
            align: 'start'
          }
        }
      ],
      onDestroyed: () => {
        localStorage.setItem(STORAGE_KEYS.AGENT_EDIT_STEP1, 'true')
      }
    })

    driverObj.drive()
  }

  const startAgentEditStep2Tour = (force = false) => {
    if (!force && localStorage.getItem(STORAGE_KEYS.AGENT_EDIT_STEP2)) {
      return
    }

    const driverObj = driver({
      showProgress: true,
      allowClose: true,
      nextBtnText: t('tour.next'),
      prevBtnText: t('tour.prev'),
      doneBtnText: t('tour.done'),
      popoverClass: 'driver-popover-theme',
      steps: [
        {
          element: '#tour-agent-step2-tools',
          popover: {
            title: t('tour.agent.step2.tools.title'),
            description: t('tour.agent.step2.tools.desc'),
            side: 'left',
            align: 'start'
          }
        },
        {
          element: '#tour-agent-step2-skills',
          popover: {
            title: t('tour.agent.step2.skills.title'),
            description: t('tour.agent.step2.skills.desc'),
            side: 'left',
            align: 'start'
          }
        },
        {
          element: '#tour-agent-step2-paths',
          popover: {
            title: t('tour.agent.step2.paths.title'),
            description: t('tour.agent.step2.paths.desc'),
            side: 'left',
            align: 'start'
          }
        }
      ],
      onDestroyed: () => {
        localStorage.setItem(STORAGE_KEYS.AGENT_EDIT_STEP2, 'true')
      }
    })

    driverObj.drive()
  }

  return {
    startSidebarTour,
    startAgentEditStep1Tour,
    startAgentEditStep2Tour
  }
}
