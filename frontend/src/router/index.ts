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
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;
