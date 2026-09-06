<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import type {
  CheckResponse,
  CheckResult,
  CheckStatus,
  InstallServicePlan,
  RuntimeSettings,
} from '@/api';
import { useDiagnosticsStore } from '@/stores/diagnostics';
import { useUiStore } from '@/stores/ui';

type Tone = 'success' | 'warning' | 'error' | 'info' | 'primary';

type StatusMeta = {
  label: string;
  icon: string;
  tone: Tone;
};

type DetailRow = {
  label: string;
  value: string;
};

const diagnosticsStore = useDiagnosticsStore();
const uiStore = useUiStore();

const safeCheckedAt = ref<Date | null>(null);
const liveCheckedAt = ref<Date | null>(null);
const printerInfoAt = ref<Date | null>(null);
const installDryRunAt = ref<Date | null>(null);

const isRefreshingSafe = computed(() => (
  diagnosticsStore.isLoadingHealth || diagnosticsStore.isRunningCheck
));
const normalResults = computed(() => diagnosticsStore.check?.results ?? []);
const liveResults = computed(() => diagnosticsStore.liveCheck?.results ?? []);
const apiTile = computed(() => {
  if (diagnosticsStore.healthError) {
    return {
      label: 'API',
      value: 'Offline',
      icon: 'mdi-cloud-off-outline',
      tone: 'error' as Tone,
    };
  }

  if (diagnosticsStore.health?.ok) {
    return {
      label: 'API',
      value: 'Online',
      icon: 'mdi-cloud-check-outline',
      tone: 'success' as Tone,
    };
  }

  return {
    label: 'API',
    value: 'Pending',
    icon: 'mdi-cloud-sync-outline',
    tone: 'info' as Tone,
  };
});
const checkTile = computed(() => ({
  label: 'Check',
  value: checkSummary(diagnosticsStore.check),
  icon: 'mdi-format-list-checks',
  tone: responseTone(diagnosticsStore.check),
}));
const summaryTiles = computed(() => [
  apiTile.value,
  {
    label: 'Version',
    value: diagnosticsStore.version?.version ?? diagnosticsStore.health?.version ?? '-',
    icon: 'mdi-tag-outline',
    tone: 'primary' as Tone,
  },
  checkTile.value,
]);
const healthRows = computed<DetailRow[]>(() => [
  { label: 'Service', value: diagnosticsStore.health?.service ?? '-' },
  { label: 'Health version', value: diagnosticsStore.health?.version ?? '-' },
  { label: 'Version name', value: diagnosticsStore.version?.name ?? '-' },
  { label: 'Version', value: diagnosticsStore.version?.version ?? '-' },
  { label: 'Refreshed', value: formatDate(safeCheckedAt.value) },
]);
const printerRows = computed<DetailRow[]>(() => {
  const info = diagnosticsStore.printerInfo;

  if (!info) {
    return [];
  }

  return [
    { label: 'Voltage', value: formatVoltage(info.printer.voltageMv) },
    { label: 'Battery', value: `${info.printer.batteryPercent}%` },
    { label: 'DPI', value: String(info.printer.dpi) },
    { label: 'Serial', value: info.printer.serialNumber || '-' },
    { label: 'Loaded', value: formatDate(printerInfoAt.value) },
  ];
});
const runtimeRows = computed<DetailRow[]>(() => runtimeSettingsRows(
  diagnosticsStore.printerInfo?.settings ?? null,
));
const installRows = computed<DetailRow[]>(() => {
  const plan = diagnosticsStore.installDryRun?.plan;

  if (!plan) {
    return [];
  }

  return [
    { label: 'Services', value: String(plan.services.length) },
    { label: 'Project root', value: plan.projectRoot },
    { label: 'Server', value: `${plan.server.host}:${plan.server.port}` },
    { label: 'Server unit', value: plan.server.service },
    { label: 'Frontend', value: plan.frontendBuilt ? 'Built' : 'Missing' },
    { label: 'Group', value: plan.requiredGroup ?? '-' },
    { label: 'Commands', value: String(plan.commands.length) },
    { label: 'Planned', value: formatDate(installDryRunAt.value) },
  ];
});
const pageErrors = computed(() => [
  diagnosticsStore.healthError,
  diagnosticsStore.checkError,
].filter(Boolean) as string[]);

onMounted(() => {
  void refreshSafeDiagnostics();
});

onBeforeUnmount(() => {
  diagnosticsStore.stopRequests();
});

async function refreshSafeDiagnostics() {
  const [health, check] = await Promise.all([
    diagnosticsStore.refreshHealth(),
    diagnosticsStore.runCheck(),
  ]);

  if (health || check) {
    safeCheckedAt.value = new Date();
  }

  const error = diagnosticsStore.healthError ?? diagnosticsStore.checkError;
  if (error) {
    uiStore.showSnackbar(error, 'error');
  }
}

async function runLiveCheck() {
  const response = await diagnosticsStore.runLiveCheck();

  if (response) {
    liveCheckedAt.value = new Date();
    uiStore.showSnackbar('Live check finished', response.ok ? 'success' : 'warning');
    return;
  }

  if (diagnosticsStore.liveCheckError) {
    uiStore.showSnackbar(diagnosticsStore.liveCheckError, 'error');
  }
}

async function fetchPrinterInfo() {
  const response = await diagnosticsStore.fetchPrinterInfo();

  if (response) {
    printerInfoAt.value = new Date();
    uiStore.showSnackbar('Printer info loaded', 'success');
    return;
  }

  if (diagnosticsStore.printerInfoError) {
    uiStore.showSnackbar(diagnosticsStore.printerInfoError, 'error');
  }
}

async function runInstallDryRun() {
  const response = await diagnosticsStore.runInstallDryRun();

  if (response) {
    installDryRunAt.value = new Date();
    uiStore.showSnackbar('Dry run ready', 'success');
    return;
  }

  if (diagnosticsStore.installDryRunError) {
    uiStore.showSnackbar(diagnosticsStore.installDryRunError, 'error');
  }
}

function runtimeSettingsRows(settings: RuntimeSettings | null): DetailRow[] {
  if (!settings) {
    return [];
  }

  return [
    { label: 'Device', value: settings.device.name },
    { label: 'Port', value: settings.device.port },
    { label: 'Baudrate', value: String(settings.device.baudrate) },
    { label: 'RFCOMM unit', value: settings.device.rfcomm_service },
    { label: 'Width', value: `${settings.printer.width} dots` },
    { label: 'Feed', value: String(settings.printer.feed) },
    { label: 'Repeat', value: `${settings.printer.repeat}x` },
    { label: 'Method', value: settings.render.method },
  ];
}

function installServiceRows(service: InstallServicePlan): DetailRow[] {
  return [
    { label: 'Kind', value: service.kind },
    { label: 'Service', value: service.name },
    { label: 'Path', value: service.path },
  ];
}

function responseTone(response: CheckResponse | null): Tone {
  if (!response) {
    return 'info';
  }

  if (response.results.some((result) => result.status === 'FAIL')) {
    return 'error';
  }

  if (response.results.some((result) => result.status === 'WARN')) {
    return 'warning';
  }

  return 'success';
}

function checkSummary(response: CheckResponse | null): string {
  if (!response) {
    return 'Pending';
  }

  const counts = checkCounts(response.results);
  return `${counts.OK} OK / ${counts.WARN} WARN / ${counts.FAIL} FAIL`;
}

function checkCounts(results: CheckResult[]) {
  return results.reduce(
    (counts, result) => {
      counts[result.status] += 1;
      return counts;
    },
    { OK: 0, WARN: 0, FAIL: 0 },
  );
}

function statusMeta(status: CheckStatus): StatusMeta {
  const map: Record<CheckStatus, StatusMeta> = {
    OK: { label: 'OK', icon: 'mdi-check-circle-outline', tone: 'success' },
    WARN: { label: 'WARN', icon: 'mdi-alert-outline', tone: 'warning' },
    FAIL: { label: 'FAIL', icon: 'mdi-alert-circle-outline', tone: 'error' },
  };
  return map[status];
}

function formatVoltage(value: number): string {
  return `${(value / 1000).toFixed(2)} V`;
}

function formatDate(value: Date | null): string {
  if (!value) {
    return '-';
  }

  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(value);
}
</script>

<template>
  <section class="route-view diagnostics-view">
    <header class="view-header">
      <div>
        <p class="section-kicker">Diagnostics</p>
        <h1>Device State</h1>
      </div>
      <div class="diagnostics-toolbar">
        <v-btn
          :loading="isRefreshingSafe"
          prepend-icon="mdi-refresh"
          variant="tonal"
          @click="refreshSafeDiagnostics"
        >
          Refresh
        </v-btn>
        <v-btn
          color="warning"
          :loading="diagnosticsStore.isRunningLiveCheck"
          prepend-icon="mdi-stethoscope"
          variant="tonal"
          @click="runLiveCheck"
        >
          Live Check
        </v-btn>
        <v-btn
          color="warning"
          :loading="diagnosticsStore.isLoadingPrinterInfo"
          prepend-icon="mdi-printer-search"
          variant="tonal"
          @click="fetchPrinterInfo"
        >
          Printer Info
        </v-btn>
        <v-btn
          :loading="diagnosticsStore.isRunningInstallDryRun"
          prepend-icon="mdi-clipboard-text-search-outline"
          variant="tonal"
          @click="runInstallDryRun"
        >
          Dry Run
        </v-btn>
      </div>
    </header>

    <div class="control-grid">
      <v-sheet v-for="tile in summaryTiles" :key="tile.label" class="metric-tile" rounded="lg">
        <v-icon :color="tile.tone" :icon="tile.icon" size="22" />
        <span class="metric-label">{{ tile.label }}</span>
        <strong>{{ tile.value }}</strong>
      </v-sheet>
    </div>

    <v-alert
      v-for="error in pageErrors"
      :key="error"
      density="comfortable"
      type="error"
      variant="tonal"
    >
      {{ error }}
    </v-alert>

    <div class="diagnostics-layout">
      <div class="diagnostics-stack">
        <v-sheet class="tool-panel diagnostics-panel" rounded="lg">
          <div class="panel-title diagnostics-panel-title">
            <span>
              <v-icon icon="mdi-cloud-check-outline" />
              <span>Health</span>
            </span>
            <v-chip :color="apiTile.tone" size="small" variant="tonal">
              {{ apiTile.value }}
            </v-chip>
          </div>
          <dl class="detail-list diagnostics-detail-list">
            <div v-for="row in healthRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </div>
          </dl>
        </v-sheet>

        <v-sheet class="tool-panel diagnostics-panel" rounded="lg">
          <div class="panel-title diagnostics-panel-title">
            <span>
              <v-icon icon="mdi-format-list-checks" />
              <span>Normal Check</span>
            </span>
            <v-chip :color="checkTile.tone" size="small" variant="tonal">
              {{ checkTile.value }}
            </v-chip>
          </div>
          <div v-if="normalResults.length" class="check-list">
            <article
              v-for="result in normalResults"
              :key="result.name"
              class="check-row"
            >
              <div class="check-row-main">
                <div class="check-row-title">
                  <strong>{{ result.name }}</strong>
                  <v-chip
                    :color="statusMeta(result.status).tone"
                    :prepend-icon="statusMeta(result.status).icon"
                    size="small"
                    variant="tonal"
                  >
                    {{ statusMeta(result.status).label }}
                  </v-chip>
                </div>
                <p class="check-message">{{ result.message || '-' }}</p>
                <span v-if="result.action" class="check-action">
                  <v-icon icon="mdi-arrow-right-circle-outline" size="16" />
                  {{ result.action }}
                </span>
              </div>
            </article>
          </div>
          <div v-else class="diagnostics-empty">
            <v-progress-circular
              v-if="diagnosticsStore.isRunningCheck"
              color="primary"
              indeterminate
              size="24"
            />
            <v-icon v-else icon="mdi-format-list-bulleted" size="24" />
            <span>Check pending</span>
          </div>
        </v-sheet>
      </div>

      <div class="diagnostics-stack">
        <v-sheet class="tool-panel diagnostics-panel live-diagnostics-panel" rounded="lg">
          <div class="panel-title diagnostics-panel-title">
            <span>
              <v-icon icon="mdi-bluetooth-connect" />
              <span>Live Check</span>
            </span>
            <v-chip color="warning" size="small" variant="tonal">
              Printer contact
            </v-chip>
          </div>
          <div v-if="liveResults.length" class="check-list">
            <article
              v-for="result in liveResults"
              :key="`live-${result.name}`"
              class="check-row"
            >
              <div class="check-row-main">
                <div class="check-row-title">
                  <strong>{{ result.name }}</strong>
                  <v-chip
                    :color="statusMeta(result.status).tone"
                    :prepend-icon="statusMeta(result.status).icon"
                    size="small"
                    variant="tonal"
                  >
                    {{ statusMeta(result.status).label }}
                  </v-chip>
                </div>
                <p class="check-message">{{ result.message || '-' }}</p>
                <span v-if="result.action" class="check-action">
                  <v-icon icon="mdi-arrow-right-circle-outline" size="16" />
                  {{ result.action }}
                </span>
              </div>
            </article>
          </div>
          <div v-else class="diagnostics-empty">
            <v-progress-circular
              v-if="diagnosticsStore.isRunningLiveCheck"
              color="warning"
              indeterminate
              size="24"
            />
            <v-icon v-else icon="mdi-stethoscope" size="24" />
            <span>Manual check pending</span>
          </div>
          <v-alert
            v-if="diagnosticsStore.liveCheckError"
            class="diagnostics-inline-alert"
            density="compact"
            type="error"
            variant="tonal"
          >
            {{ diagnosticsStore.liveCheckError }}
          </v-alert>
          <dl class="detail-list diagnostics-detail-list">
            <div>
              <dt>Last run</dt>
              <dd>{{ formatDate(liveCheckedAt) }}</dd>
            </div>
          </dl>
        </v-sheet>

        <v-sheet class="tool-panel diagnostics-panel live-diagnostics-panel" rounded="lg">
          <div class="panel-title diagnostics-panel-title">
            <span>
              <v-icon icon="mdi-printer-search" />
              <span>Printer Info</span>
            </span>
            <v-chip color="warning" size="small" variant="tonal">
              Printer contact
            </v-chip>
          </div>
          <v-alert
            v-if="diagnosticsStore.printerInfoError"
            density="compact"
            type="error"
            variant="tonal"
          >
            {{ diagnosticsStore.printerInfoError }}
          </v-alert>
          <template v-if="diagnosticsStore.printerInfo">
            <dl class="detail-list diagnostics-detail-list">
              <div v-for="row in printerRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
            <dl class="detail-list diagnostics-detail-list">
              <div v-for="row in runtimeRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
          </template>
          <div v-else class="diagnostics-empty">
            <v-progress-circular
              v-if="diagnosticsStore.isLoadingPrinterInfo"
              color="warning"
              indeterminate
              size="24"
            />
            <v-icon v-else icon="mdi-printer-pos-outline" size="24" />
            <span>Info pending</span>
          </div>
        </v-sheet>

        <v-sheet class="tool-panel diagnostics-panel" rounded="lg">
          <div class="panel-title diagnostics-panel-title">
            <span>
              <v-icon icon="mdi-clipboard-text-search-outline" />
              <span>Install Dry Run</span>
            </span>
            <v-chip color="info" size="small" variant="tonal">
              No apply
            </v-chip>
          </div>
          <v-alert
            v-if="diagnosticsStore.installDryRunError"
            density="compact"
            type="error"
            variant="tonal"
          >
            {{ diagnosticsStore.installDryRunError }}
          </v-alert>
          <template v-if="diagnosticsStore.installDryRun">
            <v-alert
              v-for="warning in diagnosticsStore.installDryRun.plan.warnings"
              :key="warning"
              density="compact"
              type="warning"
              variant="tonal"
            >
              {{ warning }}
            </v-alert>
            <dl class="detail-list diagnostics-detail-list">
              <div v-for="row in installRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
            <div class="dry-run-command-list">
              <code
                v-for="command in diagnosticsStore.installDryRun.plan.commands"
                :key="command"
                class="dry-run-command"
              >
                {{ command }}
              </code>
            </div>
            <div class="dry-run-service-list">
              <div
                v-for="service in diagnosticsStore.installDryRun.plan.services"
                :key="service.name"
                class="dry-run-service"
              >
                <dl class="detail-list diagnostics-detail-list">
                  <div v-for="row in installServiceRows(service)" :key="row.label">
                    <dt>{{ row.label }}</dt>
                    <dd>{{ row.value }}</dd>
                  </div>
                </dl>
                <pre class="service-content">{{ service.content }}</pre>
              </div>
            </div>
          </template>
          <div v-else class="diagnostics-empty">
            <v-progress-circular
              v-if="diagnosticsStore.isRunningInstallDryRun"
              color="primary"
              indeterminate
              size="24"
            />
            <v-icon v-else icon="mdi-file-cog-outline" size="24" />
            <span>Dry run pending</span>
          </div>
        </v-sheet>
      </div>
    </div>
  </section>
</template>
