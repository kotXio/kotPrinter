import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

export type AppNavItem = {
  to: string;
  label: string;
  shortLabel: string;
  icon: string;
};

export const appNavItems: AppNavItem[] = [
  { to: '/print', label: 'Print', shortLabel: 'Print', icon: 'mdi-printer' },
  { to: '/jobs', label: 'Jobs', shortLabel: 'Jobs', icon: 'mdi-format-list-checks' },
  { to: '/history', label: 'History', shortLabel: 'History', icon: 'mdi-history' },
  { to: '/settings', label: 'Settings', shortLabel: 'Settings', icon: 'mdi-cog-outline' },
  { to: '/diagnostics', label: 'Diagnostics', shortLabel: 'Diag', icon: 'mdi-stethoscope' },
];

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/print',
  },
  {
    path: '/print',
    name: 'print',
    component: () => import('@/views/PrintView.vue'),
    meta: { title: 'Print', icon: 'mdi-printer' },
  },
  {
    path: '/jobs',
    name: 'jobs',
    component: () => import('@/views/JobsView.vue'),
    meta: { title: 'Jobs', icon: 'mdi-format-list-checks' },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { title: 'History', icon: 'mdi-history' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: 'Settings', icon: 'mdi-cog-outline' },
  },
  {
    path: '/diagnostics',
    name: 'diagnostics',
    component: () => import('@/views/DiagnosticsView.vue'),
    meta: { title: 'Diagnostics', icon: 'mdi-stethoscope' },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
