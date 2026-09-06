<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue';
import { useRoute } from 'vue-router';
import { useDisplay, useTheme } from 'vuetify';

import { appNavItems } from '@/router';
import { useJobsStore } from '@/stores/jobs';
import { usePrinterStore } from '@/stores/printer';
import { useSettingsStore } from '@/stores/settings';
import { useUiStore } from '@/stores/ui';

const route = useRoute();
const display = useDisplay();
const theme = useTheme();
const uiStore = useUiStore();
const printerStore = usePrinterStore();
const jobsStore = useJobsStore();
const settingsStore = useSettingsStore();
const now = ref(new Date());
let clockTimer: number | undefined;

const isMobile = computed(() => !display.mdAndUp.value);
const showContextPanel = computed(() => display.lgAndUp.value);
const railWidth = computed(() => 184);
const activeTitle = computed(() => String(route.meta.title ?? 'Print'));
const activeIcon = computed(() => String(route.meta.icon ?? 'mdi-printer'));
const formattedTime = computed(() =>
  new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(now.value),
);

const settings = computed(() => settingsStore.settings);
const deviceName = computed(() => settings.value?.device.name ?? 'YHK-D0D0');
const devicePort = computed(() => settings.value?.device.port ?? '/dev/rfcomm0');
const printerWidth = computed(() => settings.value?.printer.width ?? 384);
const activeQueueCount = computed(() => jobsStore.queue?.activeCount ?? 0);
const queuedCount = computed(() => jobsStore.queue?.queuedCount ?? 0);
const printingCount = computed(() => jobsStore.queue?.printingCount ?? 0);
const isRefreshing = computed(() => (
  printerStore.isLoadingOverview
  || jobsStore.isLoadingJobs
  || jobsStore.isLoadingQueue
  || settingsStore.isLoading
));
const apiStatusChip = computed(() => {
  if (printerStore.overviewError) {
    return {
      label: 'API offline',
      icon: 'mdi-cloud-off-outline',
      tone: 'error',
    };
  }

  if (printerStore.health?.ok) {
    return {
      label: 'API online',
      icon: 'mdi-cloud-check-outline',
      tone: 'success',
    };
  }

  return {
    label: 'API pending',
    icon: 'mdi-cloud-sync-outline',
    tone: 'info',
  };
});
const printerStatusChip = computed(() => {
  if (printerStore.rfcommBound) {
    return {
      label: printingCount.value > 0 ? 'Printing' : 'Idle',
      icon: printingCount.value > 0 ? 'mdi-printer-pos-play-outline' : 'mdi-printer-pos-outline',
      tone: printingCount.value > 0 ? 'warning' : 'success',
    };
  }

  if (printerStore.status) {
    return {
      label: 'RFCOMM missing',
      icon: 'mdi-bluetooth-off',
      tone: 'warning',
    };
  }

  return {
    label: 'Printer unknown',
    icon: 'mdi-printer-alert-outline',
    tone: 'info',
  };
});
const queueStatusChip = computed(() => ({
  label: `Queue ${activeQueueCount.value}`,
  icon: activeQueueCount.value > 0 ? 'mdi-tray-full' : 'mdi-tray',
  tone: activeQueueCount.value > 0 ? 'warning' : 'info',
}));
const statusChips = computed(() => [
  apiStatusChip.value,
  printerStatusChip.value,
  queueStatusChip.value,
]);
const mobileStatusChips = computed(() => [
  apiStatusChip.value,
  printerStatusChip.value,
  {
    ...queueStatusChip.value,
    label: `Q ${activeQueueCount.value}`,
  },
]);
const queueContext = computed(() => {
  if (activeQueueCount.value > 0) {
    return {
      title: `${activeQueueCount.value} active`,
      subtitle: `${printingCount.value} printing, ${queuedCount.value} queued`,
      icon: 'mdi-progress-clock',
    };
  }

  return {
    title: 'No active jobs',
    subtitle: jobsStore.lastQueueAt ? 'Queue is empty' : 'Queue not loaded',
    icon: 'mdi-check-circle-outline',
  };
});
const contextRows = computed(() => [
  queueContext.value,
  {
    title: 'Printer width',
    subtitle: `${printerWidth.value} dots`,
    icon: 'mdi-arrow-expand-horizontal',
  },
  {
    title: 'Device',
    subtitle: `${deviceName.value} ${devicePort.value}`,
    icon: 'mdi-serial-port',
  },
]);
const contextTone = computed(() => {
  if (printerStore.overviewError) {
    return 'error';
  }
  return activeQueueCount.value > 0 ? 'warning' : 'success';
});
const contextLabel = computed(() => {
  if (printerStore.overviewError) {
    return 'API';
  }
  return activeQueueCount.value > 0 ? 'Busy' : 'OK';
});

watchEffect(() => {
  theme.change(uiStore.activeTheme);
});

async function refreshAppState() {
  await Promise.all([
    printerStore.refreshOverview(),
    jobsStore.refreshJobsAndQueue(),
    settingsStore.settings === null ? settingsStore.loadSettings() : Promise.resolve(null),
  ]);

  const refreshError = (
    printerStore.overviewError
    ?? jobsStore.jobsError
    ?? jobsStore.queueError
    ?? settingsStore.loadError
  );

  if (refreshError) {
    uiStore.showSnackbar(refreshError, 'error');
  }
}

onMounted(() => {
  clockTimer = window.setInterval(() => {
    now.value = new Date();
  }, 1000);

  void settingsStore.loadSettings();
  printerStore.startPolling(() => jobsStore.hasActiveQueue);
  jobsStore.startQueuePolling();
});

onBeforeUnmount(() => {
  if (clockTimer !== undefined) {
    window.clearInterval(clockTimer);
  }
  printerStore.stopPolling();
  jobsStore.stopQueuePolling();
  settingsStore.stopRequests();
});
</script>

<template>
  <v-app>
    <v-app-bar class="app-topbar" density="comfortable" elevation="0" height="64">
      <v-btn
        v-if="!isMobile"
        aria-label="Navigation"
        class="top-icon"
        icon="mdi-menu"
        variant="text"
      />

      <v-app-bar-title class="app-title" :class="{ 'is-mobile': isMobile }">
        <div class="brand-lockup">
          <span class="brand-mark">
            <v-icon icon="mdi-paw" size="24" />
          </span>
          <span v-if="!isMobile" class="brand-copy">
            <span class="brand-name">KotPrinter</span>
            <span class="brand-context">
              <v-icon :icon="activeIcon" size="16" />
              {{ activeTitle }}
            </span>
          </span>
        </div>
      </v-app-bar-title>

      <div v-if="!isMobile" class="status-strip" aria-label="Printer status">
        <v-chip
          v-for="chip in statusChips"
          :key="chip.label"
          :color="chip.tone"
          :prepend-icon="chip.icon"
          size="small"
          variant="tonal"
        >
          {{ chip.label }}
        </v-chip>
        <v-chip color="accent" prepend-icon="mdi-chip" size="small" variant="tonal">
          {{ deviceName }}
        </v-chip>
        <v-chip color="accent" prepend-icon="mdi-serial-port" size="small" variant="tonal">
          {{ devicePort }}
        </v-chip>
      </div>

      <div v-if="isMobile" class="mobile-header-status" aria-label="Printer status">
        <v-chip
          v-for="chip in mobileStatusChips"
          :key="chip.label"
          :color="chip.tone"
          :prepend-icon="chip.icon"
          size="x-small"
          variant="tonal"
        >
          {{ chip.label }}
        </v-chip>
      </div>

      <v-btn
        aria-label="Refresh"
        class="top-icon"
        icon
        :loading="isRefreshing"
        variant="text"
        @click="refreshAppState"
      >
        <v-icon icon="mdi-refresh" />
        <v-tooltip activator="parent" location="bottom">Refresh</v-tooltip>
      </v-btn>

      <v-btn
        v-if="!isMobile"
        class="theme-toggle"
        :aria-label="uiStore.isDark ? 'Use light theme' : 'Use dark theme'"
        icon
        variant="text"
        @click="uiStore.toggleTheme"
      >
        <v-icon :icon="uiStore.isDark ? 'mdi-weather-sunny' : 'mdi-weather-night'" />
        <v-tooltip activator="parent" location="bottom">
          {{ uiStore.isDark ? 'Light theme' : 'Dark theme' }}
        </v-tooltip>
      </v-btn>

      <v-menu location="bottom end">
        <template #activator="{ props }">
          <v-btn
            aria-label="More actions"
            class="top-icon"
            icon="mdi-dots-vertical"
            v-bind="props"
            variant="text"
          />
        </template>
        <v-list density="compact" min-width="188">
          <v-list-item
            prepend-icon="mdi-information-outline"
            title="Printer info"
            to="/diagnostics"
          />
          <v-list-item prepend-icon="mdi-stethoscope" title="Run checks" to="/diagnostics" />
          <v-list-item prepend-icon="mdi-cog-outline" title="Settings" to="/settings" />
          <template v-if="isMobile">
            <v-divider />
            <v-list-item
              :prepend-icon="uiStore.isDark ? 'mdi-weather-sunny' : 'mdi-weather-night'"
              :title="uiStore.isDark ? 'Light theme' : 'Dark theme'"
              @click="uiStore.toggleTheme"
            />
          </template>
        </v-list>
      </v-menu>
    </v-app-bar>

    <v-navigation-drawer
      v-if="display.mdAndUp.value"
      class="app-rail"
      color="surface"
      permanent
      :width="railWidth"
    >
      <v-list class="rail-list" density="compact" nav>
        <v-list-item
          v-for="item in appNavItems"
          :key="item.to"
          class="rail-item"
          :to="item.to"
          :title="item.label"
          rounded="lg"
        >
          <template #prepend>
            <v-icon :icon="item.icon" />
          </template>
        </v-list-item>
      </v-list>

      <template #append>
        <div class="rail-footer">
          <span>v0.4</span>
          <span>Local API</span>
        </div>
      </template>
    </v-navigation-drawer>

    <v-navigation-drawer
      v-if="showContextPanel"
      class="context-panel"
      location="right"
      permanent
      width="320"
    >
      <section class="context-section">
        <header class="context-header">
          <div>
            <p class="section-kicker">Queue</p>
            <h2>Printer Context</h2>
          </div>
          <v-chip :color="contextTone" prepend-icon="mdi-check" size="small" variant="tonal">
            {{ contextLabel }}
          </v-chip>
        </header>

        <v-list class="context-list" density="compact" lines="two">
          <v-list-item
            v-for="row in contextRows"
            :key="row.title"
            :prepend-icon="row.icon"
            :subtitle="row.subtitle"
            :title="row.title"
            rounded="lg"
          />
        </v-list>

        <div class="context-actions">
          <v-btn color="primary" prepend-icon="mdi-printer" to="/print" variant="tonal">Print</v-btn>
          <v-btn color="warning" prepend-icon="mdi-alert-outline" to="/diagnostics" variant="tonal">
            Live check
          </v-btn>
        </div>
      </section>
    </v-navigation-drawer>

    <v-main class="app-main">
      <div class="app-content">
        <RouterView />
      </div>
    </v-main>

    <v-footer v-if="display.mdAndUp.value" app class="app-footer" height="44">
      <span>Server: same-origin /api</span>
      <span>Printer width: {{ printerWidth }} dots</span>
      <span>Device: {{ deviceName }}</span>
      <strong>{{ formattedTime }}</strong>
    </v-footer>

    <v-bottom-navigation
      v-if="isMobile"
      class="mobile-nav"
      :model-value="route.path"
      grow
      height="72"
      mandatory
    >
      <v-btn
        v-for="item in appNavItems"
        :key="item.to"
        :to="item.to"
        :value="item.to"
        stacked
      >
        <v-icon :icon="item.icon" />
        <span>{{ item.shortLabel }}</span>
      </v-btn>
    </v-bottom-navigation>

    <v-snackbar
      v-if="uiStore.activeSnackbar"
      :color="uiStore.activeSnackbar.tone"
      location="bottom right"
      :model-value="true"
      :timeout="uiStore.activeSnackbar.timeout"
      @update:model-value="(value) => {
        if (!value && uiStore.activeSnackbar) {
          uiStore.dismissSnackbar(uiStore.activeSnackbar.id);
        }
      }"
    >
      {{ uiStore.activeSnackbar.message }}
    </v-snackbar>
  </v-app>
</template>
