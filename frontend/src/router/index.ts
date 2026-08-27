import { createRouter, createWebHistory } from 'vue-router';
import type { RouteRecordRaw } from 'vue-router';
import BasicLayout from '@/layouts/BasicLayout.vue';
import { useAuthStore } from '@/stores/auth';

// 不需要登录即可访问的路由
const publicRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Auth/Login.vue'),
    meta: { title: '登录', requiresAuth: false }
  }
];

// 需要登录后才能访问的路由（统一使用 BasicLayout 作为父级布局）
const appRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: { name: 'Dashboard' }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/Dashboard/index.vue'),
    meta: { title: '仪表板', icon: 'Odometer', requiresAuth: true }
  },

  // ============ 学习中心 ============
  {
    path: '/learning',
    name: 'Learning',
    component: () => import('../views/Learning/index.vue'),
    meta: { title: '学习中心', icon: 'Reading', requiresAuth: true }
  },
  {
    path: '/learning/proposals',
    name: 'LearningProposals',
    component: () => import('../views/Learning/LearningProposals.vue'),
    meta: { title: '学习建议', requiresAuth: true, hideInMenu: true }
  },
  {
    // 注意：此路由需在 /learning/:category 之前声明，Vue Router 会优先匹配静态段
    path: '/learning/article/:id',
    name: 'LearningArticle',
    component: () => import('../views/Learning/Article.vue'),
    meta: { title: '文章详情', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/learning/:category',
    name: 'LearningCategory',
    component: () => import('../views/Learning/Category.vue'),
    meta: { title: '学习分类', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/learning/trade-reviews/:id',
    name: 'TradeReviewDetail',
    component: () => import('../views/Learning/TradeReviewDetail.vue'), 
    meta: { title: '交易复盘', requiresAuth: true, hideInMenu: true }
  },

  // ============ 股票分析 ============
  {
    path: '/analysis/single',
    name: 'SingleAnalysis',
    component: () => import('../views/Analysis/SingleAnalysis.vue'),
    meta: { title: '单股分析', requiresAuth: true }
  },
  {
    path: '/analysis/batch',
    name: 'BatchAnalysis',
    component: () => import('../views/Analysis/BatchAnalysis.vue'),
    meta: { title: '批量分析', requiresAuth: true }
  },
  {
    path: '/analysis/history',
    name: 'AnalysisHistory',
    component: () => import('../views/Analysis/AnalysisHistory.vue'),
    meta: { title: '分析历史', requiresAuth: true, hideInMenu: true }
  },

  // ============ 任务中心 / 队列 ============
  // 侧边栏菜单使用 /tasks，仪表板与 404 页面会跳转到 /queue，两者均保留可用
  {
    path: '/tasks',
    name: 'TaskCenter',
    component: () => import('../views/Tasks/TaskCenter.vue'),
    meta: { title: '任务中心', icon: 'List', requiresAuth: true }
  },
  {
    path: '/queue',
    name: 'Queue',
    component: () => import('../views/Queue/index.vue'),
    meta: { title: '任务队列', requiresAuth: true, hideInMenu: true }
  },

  // ============ 股票筛选 / 自选股 / 详情 ============
  {
    path: '/screening',
    name: 'StockScreening',
    component: () => import('../views/Screening/index.vue'),
    meta: { title: '股票筛选', icon: 'Search', requiresAuth: true }
  },
  {
    path: '/favorites',
    name: 'Favorites',
    component: () => import('../views/Favorites/index.vue'),
    meta: { title: '我的自选股', icon: 'Star', requiresAuth: true }
  },
  {
    path: '/stocks/:code',
    name: 'StockDetail',
    component: () => import('../views/Stocks/Detail.vue'),
    meta: { title: '股票详情', requiresAuth: true, hideInMenu: true }
  },

  // ============ 分析报告 ============
  {
    path: '/reports',
    name: 'Reports',
    component: () => import('../views/Reports/index.vue'),
    meta: { title: '分析报告', requiresAuth: true }
  },
  {
    path: '/reports/view/:id',
    name: 'ReportDetail',
    component: () => import('../views/Reports/ReportDetail.vue'),
    meta: { title: '报告详情', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/reports/token-statistics',
    name: 'TokenStatistics',
    component: () => import('../views/Reports/TokenStatistics.vue'),
    meta: { title: 'Token 统计', requiresAuth: true, hideInMenu: true }
  },

  // ============ 因子平台 ============
  {
    path: '/factors',
    name: 'FactorCatalog',
    component: () => import('../views/Factors/FactorCatalog.vue'),
    meta: { title: '因子目录', icon: 'DataAnalysis', requiresAuth: true }
  },
  {
    path: '/factors/compute',
    name: 'FactorCompute',
    component: () => import('../views/Factors/FactorCompute.vue'),
    meta: { title: '因子计算', requiresAuth: true }
  },
  {
    path: '/factors/research',
    name: 'FactorResearch',
    component: () => import('../views/Factors/FactorResearch.vue'),
    meta: { title: '因子研究', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/factors/composite',
    name: 'CompositeEditor',
    component: () => import('../views/Factors/CompositeEditor.vue'),
    meta: { title: '复合因子编辑', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/factors/snapshots/:id',
    name: 'FactorSnapshotDetail',
    component: () => import('../views/Factors/FactorSnapshotDetail.vue'),
    meta: { title: '快照详情', requiresAuth: true, hideInMenu: true }
  },

  // ============ 策略 ============
  {
    path: '/strategies',
    name: 'StrategyCatalog',
    component: () => import('../views/Strategies/StrategyCatalog.vue'), 
    meta: { title: '策略目录', requiresAuth: true }
  },
  {
    path: '/strategies/:id/versions',
    name: 'StrategyVersionHistory',
    component: () => import('../views/Strategies/StrategyVersionHistory.vue'),    
    meta: { title: '策略版本历史', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/strategies/:id/diff',
    name: 'StrategyDiff',
    component: () => import('../views/Strategies/StrategyDiff.vue'),
    meta: { title: '策略差异对比', requiresAuth: true, hideInMenu: true }
  },

  // ============ 回测 ============
  {
    path: '/backtests/create',
    name: 'BacktestCreate',
    component: () => import('../views/Backtest/BacktestCreate.vue'),
    meta: { title: '创建回测', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/backtests/compare',
    name: 'BacktestComparison',
    component: () => import('../views/Backtest/BacktestComparison.vue'),
    meta: { title: '回测对比', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/backtests/:id',
    name: 'BacktestDetail',
    component: () => import('../views/Backtest/BacktestDetail.vue'),
    meta: { title: '回测详情', requiresAuth: true, hideInMenu: true }
  },

  // ============ 技能 ============
  {
    path: '/skills',
    name: 'SkillCatalog',
    component: () => import('../views/Skills/SkillCatalog.vue'),
    meta: { title: '技能目录', requiresAuth: true }
  },
  {
    path: '/skills/create',
    name: 'SkillEditor',
    component: () => import('../views/Skills/SkillEditor.vue'),
    meta: { title: '技能编辑', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/skills/:id/test',
    name: 'SkillTest',
    component: () => import('../views/Skills/SkillTest.vue'),
    meta: { title: '技能测试', requiresAuth: true, hideInMenu: true }
  },

  // ============ 营销活动 ============
  {
    path: '/campaigns',
    name: 'CampaignList',
    component: () => import('../views/Campaigns/CampaignList.vue'),
    meta: { title: '活动列表', requiresAuth: true }
  },
  {
    path: '/campaigns/create',
    name: 'CampaignWizard',
    component: () => import('../views/Campaigns/CampaignWizard.vue'),
    meta: { title: '创建活动', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/campaigns/:id',
    name: 'CampaignDetail',
    component: () => import('../views/Campaigns/CampaignDetail.vue'),
    meta: { title: '活动详情', requiresAuth: true, hideInMenu: true }
  },

  // ============ 风险 ============
  {
    path: '/risk/dashboard',
    name: 'RiskDashboard',
    component: () => import('../views/Risk/RiskDashboard.vue'),
    meta: { title: '风险仪表板', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/risk/audit-logs',
    name: 'RiskAuditLogs',
    component: () => import('../views/Risk/RiskAuditLogs.vue'), 
    meta: { title: '风险审计日志', requiresAuth: true, hideInMenu: true }
  },

  // ============ 模拟交易 ============
  {
    path: '/paper',
    name: 'PaperTradingHome',
    component: () => import('../views/PaperTrading/index.vue'),
    meta: { title: '模拟交易', icon: 'CreditCard', requiresAuth: true }
  },

  // ============ 设置（侧边栏菜单与 Settings/index.vue 跳转使用） ============
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings/index.vue'),
    meta: { title: '设置', icon: 'Setting', requiresAuth: true }
  },
  {
    path: '/settings/config',
    name: 'ConfigManagement',
    component: () => import('../views/Settings/ConfigManagement.vue'),
    meta: { title: '配置管理', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/cache',
    name: 'CacheManagement',
    component: () => import('../views/Settings/CacheManagement.vue'),
    meta: { title: '缓存管理', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/usage',
    name: 'UsageStatistics',
    component: () => import('../views/Settings/UsageStatistics.vue'),
    meta: { title: '使用统计', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/notifications',
    name: 'NotificationSettings',
    component: () => import('../views/Notifications/NotificationSettings.vue'),
    meta: { title: '通知设置', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/risk',
    name: 'RiskSettings',
    component: () => import('../views/Risk/RiskSettings.vue'),
    meta: { title: '风险设置', requiresAuth: true, hideInMenu: true }
  },

  // ============ 系统管理 ============
  {
    path: '/settings/database',
    name: 'DatabaseManagement',
    component: () => import('../views/System/DatabaseManagement.vue'),
    meta: { title: '数据库管理', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/logs',
    name: 'OperationLogs',
    component: () => import('../views/System/OperationLogs.vue'),
    meta: { title: '操作日志', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/system-logs',
    name: 'LogManagement',
    component: () => import('../views/System/LogManagement.vue'),
    meta: { title: '系统日志', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/sync',
    name: 'MultiSourceSync',
    component: () => import('../views/System/MultiSourceSync.vue'),
    meta: { title: '多数据源同步', requiresAuth: true, hideInMenu: true }
  },
  {
    path: '/settings/scheduler',
    name: 'SchedulerManagement',
    component: () => import('../views/System/SchedulerManagement.vue'),
    meta: { title: '定时任务', requiresAuth: true, hideInMenu: true }
  },

  // ============ 关于 ============
  {
    path: '/about',
    name: 'About',
    component: () => import('../views/About/index.vue'),
    meta: { title: '关于', icon: 'InfoFilled', requiresAuth: true }
  }
];

// 404 兜底
const notFoundRoute: RouteRecordRaw = {
  path: '/:pathMatch(.*)*',
  name: 'NotFound',
  component: () => import('../views/Error/404.vue'),
  meta: { title: '页面不存在', requiresAuth: false }
};

const routes: RouteRecordRaw[] = [
  // 公共路由（无 BasicLayout）
  ...publicRoutes,
  // 受保护路由统一挂载在 BasicLayout 下，使侧边栏 / 顶栏在所有页面保持一致
  {
    path: '/',
    component: BasicLayout,
    children: appRoutes
  },
  // 404 兜底（放在最后）
  notFoundRoute
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    // 后退/前进时恢复滚动位置，新导航回到顶部
    return savedPosition ?? { top: 0 }
  }
});

// 全局前置守卫：基于 meta.requiresAuth 做登录态校验
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  const requiresAuth = to.matched.some((r) => r.meta?.requiresAuth === true)

  // 设置页面标题
  if (to.meta?.title) {
    document.title = `${to.meta.title} - TradingAgents-CN`
  }

  if (requiresAuth && !authStore.isAuthenticated) {
    // 记录目标地址，登录后可回跳
    authStore.redirectPath = to.fullPath
    next({ name: 'Login' })
    return
  }

  // 已登录用户访问登录页，重定向到仪表板
  if (to.name === 'Login' && authStore.isAuthenticated) {
    next({ name: 'Dashboard' })
    return
  }

  next()
})

export default router;
