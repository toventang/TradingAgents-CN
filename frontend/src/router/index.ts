import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  {
    path: '/factors',
    name: 'FactorCatalog',
    component: () => import('../views/Factors/FactorCatalog.vue')
  },
  {
    path: '/factors/compute',
    name: 'FactorCompute',
    component: () => import('../views/Factors/FactorCompute.vue')
  },
  {
    path: '/strategies',
    name: 'StrategyCatalog',
    component: () => import('../views/Strategies/StrategyCatalog.vue')
  },
  {
    path: '/strategies/:id/versions',
    name: 'StrategyVersionHistory',
    component: () => import('../views/Strategies/StrategyVersionHistory.vue')
  },
  {
    path: '/strategies/:id/diff',
    name: 'StrategyDiff',
    component: () => import('../views/Strategies/StrategyDiff.vue')
  },
  {
    path: '/backtests/create',
    name: 'BacktestCreate',
    component: () => import('../views/Backtest/BacktestCreate.vue')
  },
  {
    path: '/backtests/compare',
    name: 'BacktestComparison',
    component: () => import('../views/Backtest/BacktestComparison.vue')
  },
  {
    path: '/backtests/:id',
    name: 'BacktestDetail',
    component: () => import('../views/Backtest/BacktestDetail.vue')
  },
  {
    path: '/settings/notifications',
    name: 'NotificationSettings',
    component: () => import('../views/Notifications/NotificationSettings.vue')
  },
  {
    path: '/settings/risk',
    name: 'RiskSettings',
    component: () => import('../views/Risk/RiskSettings.vue')
  },
  {
    path: '/risk/dashboard',
    name: 'RiskDashboard',
    component: () => import('../views/Risk/RiskDashboard.vue')
  },
  {
    path: '/risk/audit-logs',
    name: 'RiskAuditLogs',
    component: () => import('../views/Risk/RiskAuditLogs.vue')
  },
  {
    path: '/skills',
    name: 'SkillCatalog',
    component: () => import('../views/Skills/SkillCatalog.vue')
  },
  {
    path: '/skills/create',
    name: 'SkillEditor',
    component: () => import('../views/Skills/SkillEditor.vue')
  },
  {
    path: '/skills/:id/test',
    name: 'SkillTest',
    component: () => import('../views/Skills/SkillTest.vue')
  },
  {
    path: '/campaigns',
    name: 'CampaignList',
    component: () => import('../views/Campaigns/CampaignList.vue')
  },
  {
    path: '/campaigns/create',
    name: 'CampaignWizard',
    component: () => import('../views/Campaigns/CampaignWizard.vue')
  },
  {
    path: '/campaigns/:id',
    name: 'CampaignDetail',
    component: () => import('../views/Campaigns/CampaignDetail.vue')
  },
  {
    path: '/learning/trade-reviews/:id',
    name: 'TradeReviewDetail',
    component: () => import('../views/Learning/TradeReviewDetail.vue')
    path: '/factors',
    name: 'Factors',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '因子平台',
      icon: 'DataAnalysis',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'FactorCatalog',
        component: () => import('@/views/Factors/FactorCatalog.vue'),
        meta: { title: '因子目录', requiresAuth: true }
      },
      {
        path: 'compute',
        name: 'FactorCompute',
        component: () => import('@/views/Factors/FactorCompute.vue'),
        meta: { title: '因子计算', requiresAuth: true }
      },
      {
        path: 'snapshots/:id',
        name: 'FactorSnapshotDetail',
        component: () => import('@/views/Factors/FactorSnapshotDetail.vue'),
        meta: { title: '快照详情', requiresAuth: true, hideInMenu: true }
      }
    ]
  },
  {
    path: '/paper',
    name: 'PaperTrading',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '模拟交易',
      icon: 'CreditCard',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'PaperTradingHome',
        component: () => import('@/views/PaperTrading/index.vue'),
        meta: {
          title: '模拟交易',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/learning/proposals',
    name: 'LearningProposals',
    component: () => import('../views/Learning/LearningProposals.vue')
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;
