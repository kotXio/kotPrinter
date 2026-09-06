<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { apiClient, isAbortError, messageFromError, previewUrl } from '@/api';
import type {
  HistoryCleanupResult,
  HistoryConfig,
  JobStatus,
  JobSummary,
  JobType,
  QueueSnapshot,
  StartupCleanupError,
} from '@/api';
import { useUiStore } from '@/stores/ui';

type Tone = 'success' | 'warning' | 'error' | 'info' | 'primary';

type StatusMeta = {
  label: string;
  icon: string;
  tone: Tone;
};

const uiStore = useUiStore();

const limitItems = [
  { title: '25', value: 25 },
  { title: '50', value: 50 },
  { title: '100', value: 100 },
];

const historyLimit = ref(25);
const history = ref<JobSummary[]>([]);
const queue = ref<QueueSnapshot | null>(null);
const settings = ref<HistoryConfig | null>(null);
const startupCleanup = ref<HistoryCleanupResult | StartupCleanupError | null>(null);
const cleanupResult = ref<HistoryCleanupResult | null>(null);
const cleanupDialog = ref(false);
const cleanupEnabled = ref(true);
const cleanupUseRetention = ref(true);
const cleanupRetentionDays = ref<number | null>(30);
const isLoading = ref(false);
const isCleaning = ref(false);
const isSaving = ref(false);
const loadError = ref<string | null>(null);
const cleanupError = ref<string | null>(null);
const saveError = ref<string | null>(null);

let loadController: AbortController | null = null;
let cleanupController: AbortController | null = null;

const historyNewestFirst = computed(() => (
  [...history.value].sort((left, right) => (
    new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime()
  ))
));
const activeHistoryJobs = computed(() => (
  history.value.filter((job) => job.status === 'queued' || job.status === 'printing')
));
const latestHistoryJob = computed(() => historyNewestFirst.value.at(0) ?? null);
const doneCount = computed(() => (
  history.value.filter((job) => job.status === 'done').length
));
const failureCount = computed(() => (
  history.value.filter((job) => job.status === 'failed' || job.status === 'canceled').length
));
const queueActiveCount = computed(() => queue.value?.activeCount ?? 0);
const retentionValue = computed(() => normalizedRetentionDays());
const cleanupWouldSkipRetention = computed(() => (
  !cleanupEnabled.value || retentionValue.value === null || retentionValue.value === 0
));
const historyHasChanges = computed(() => {
  if (!settings.value) {
    return false;
  }

  const activeRetention = cleanupUseRetention.value ? retentionValue.value : null;
  return settings.value.enabled !== cleanupEnabled.value
    || settings.value.retentionDays !== activeRetention;
});
const summaryTiles = computed(() => [
  {
    label: 'History',
    value: String(history.value.length),
    icon: 'mdi-history',
  },
  {
    label: 'Done',
    value: String(doneCount.value),
    icon: 'mdi-check-circle-outline',
  },
  {
    label: 'Issues',
    value: String(failureCount.value),
    icon: 'mdi-alert-circle-outline',
  },
]);
const cleanupSummary = computed(() => {
  const cleanup = cleanupResult.value;
  if (!cleanup) {
    return null;
  }

  return [
    { label: 'Removed', value: cleanup.removed.length, tone: 'success' as Tone },
    { label: 'Skipped', value: cleanup.skipped.length, tone: 'warning' as Tone },
    { label: 'Errors', value: cleanup.errors.length, tone: 'error' as Tone },
  ];
});

onMounted(() => {
  void loadHistory();
});

onBeforeUnmount(() => {
  loadController?.abort();
  cleanupController?.abort();
});

async function loadHistory(limit = historyLimit.value) {
  loadController?.abort();
  loadController = new AbortController();
  const { signal } = loadController;

  isLoading.value = true;
  loadError.value = null;

  try {
    const response = await apiClient.getHistory({ limit }, { signal });
    history.value = response.history;
    queue.value = response.queue;
    settings.value = response.settings;
    startupCleanup.value = response.startupCleanup;
    historyLimit.value = limit;
    syncCleanupControls(response.settings);
    return response;
  } catch (error) {
    if (!isAbortError(error)) {
      loadError.value = messageFromError(error);
    }
    return null;
  } finally {
    if (!signal.aborted) {
      isLoading.value = false;
    }
  }
}

async function refreshWithLimit(value: number) {
  await loadHistory(value);
}

async function runCleanup() {
  cleanupController?.abort();
  cleanupController = new AbortController();
  const { signal } = cleanupController;

  isCleaning.value = true;
  cleanupError.value = null;
  saveError.value = null;

  try {
    const response = await apiClient.cleanupHistory({
      enabled: cleanupEnabled.value,
      retentionDays: retentionValue.value,
    }, { signal });
    cleanupResult.value = response.cleanup;
    settings.value = response.settings;
    syncCleanupControls(response.settings);
    cleanupDialog.value = false;
    uiStore.showSnackbar(
      response.cleanup.errors.length > 0 ? 'History cleanup finished with errors' : 'History cleanup finished',
      response.cleanup.errors.length > 0 ? 'warning' : 'success',
    );
    await loadHistory(historyLimit.value);
    return response.cleanup;
  } catch (error) {
    if (!isAbortError(error)) {
      cleanupError.value = messageFromError(error);
      uiStore.showSnackbar(cleanupError.value, 'error');
    }
    return null;
  } finally {
    if (!signal.aborted) {
      isCleaning.value = false;
    }
  }
}

async function saveHistorySettings() {
  if (!settings.value || !historyHasChanges.value) {
    return;
  }

  isSaving.value = true;
  saveError.value = null;

  try {
    const response = await apiClient.updateSettings({
      history: {
        enabled: cleanupEnabled.value,
        retentionDays: cleanupUseRetention.value ? retentionValue.value : null,
        cleanupOnStart: settings.value.cleanupOnStart,
      },
    });
    const historySettings = response.settings.history;
    settings.value = historySettings;
    syncCleanupControls(historySettings);
    uiStore.showSnackbar('History settings saved', 'success');
  } catch (error) {
    saveError.value = messageFromError(error);
    uiStore.showSnackbar(saveError.value, 'error');
  } finally {
    isSaving.value = false;
  }
}

function syncCleanupControls(nextSettings: HistoryConfig) {
  cleanupEnabled.value = nextSettings.enabled;
  cleanupUseRetention.value = nextSettings.retentionDays !== null;
  cleanupRetentionDays.value = nextSettings.retentionDays ?? 30;
}

function normalizedRetentionDays(): number | null {
  if (!cleanupUseRetention.value) {
    return null;
  }

  const value = Number(cleanupRetentionDays.value);
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.floor(value));
}

function previewFor(job: JobSummary): string {
  return job.previewPath ? previewUrl(job.jobId) : '';
}

function jobStatusLabel(status: JobStatus): string {
  return statusMeta(status).label;
}

function statusMeta(status: JobStatus): StatusMeta {
  const map: Record<JobStatus, StatusMeta> = {
    draft: { label: 'Draft', icon: 'mdi-file-outline', tone: 'info' },
    rendering: { label: 'Rendering', icon: 'mdi-progress-clock', tone: 'info' },
    rendered: { label: 'Rendered', icon: 'mdi-receipt-text-check-outline', tone: 'success' },
    queued: { label: 'Queued', icon: 'mdi-tray-full', tone: 'warning' },
    printing: { label: 'Printing', icon: 'mdi-printer-pos-play-outline', tone: 'warning' },
    done: { label: 'Done', icon: 'mdi-check-circle-outline', tone: 'success' },
    failed: { label: 'Failed', icon: 'mdi-alert-circle-outline', tone: 'error' },
    canceled: { label: 'Canceled', icon: 'mdi-cancel', tone: 'error' },
  };
  return map[status];
}

function jobTypeIcon(type: JobType): string {
  return type === 'image' ? 'mdi-image-outline' : 'mdi-text-box-outline';
}

function jobTypeLabel(type: JobType): string {
  return type === 'image' ? 'Image' : 'Text';
}

function isCleanupResult(
  value: HistoryCleanupResult | StartupCleanupError,
): value is HistoryCleanupResult {
  return 'removed' in value;
}

function retentionLabel(value: number | null): string {
  if (value === null || value === 0) {
    return 'Off';
  }
  return `${value}d`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '-';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}...` : value;
}
</script>

<template>
  <section class="route-view history-view">
    <header class="view-header">
      <div>
        <p class="section-kicker">History</p>
        <h1>Print Log</h1>
      </div>
      <div class="history-toolbar">
        <v-select
          density="compact"
          hide-details
          :items="limitItems"
          label="Limit"
          :model-value="historyLimit"
          variant="outlined"
          @update:model-value="refreshWithLimit"
        />
        <v-btn
          color="primary"
          :loading="isLoading"
          prepend-icon="mdi-refresh"
          variant="tonal"
          @click="loadHistory()"
        >
          Refresh
        </v-btn>
      </div>
    </header>

    <div class="control-grid">
      <v-sheet v-for="tile in summaryTiles" :key="tile.label" class="metric-tile" rounded="lg">
        <v-icon :icon="tile.icon" size="22" />
        <span class="metric-label">{{ tile.label }}</span>
        <strong>{{ tile.value }}</strong>
      </v-sheet>
    </div>

    <v-alert
      v-if="loadError || cleanupError || saveError"
      density="comfortable"
      type="error"
      variant="tonal"
    >
      {{ loadError || cleanupError || saveError }}
    </v-alert>

    <v-alert
      v-if="activeHistoryJobs.length > 0 || queueActiveCount > 0"
      density="comfortable"
      type="warning"
      variant="tonal"
    >
      {{ activeHistoryJobs.length }} active history job(s) and {{ queueActiveCount }} active queue item(s) stay protected. Cleanup only asks the backend to remove retention-eligible inactive history.
    </v-alert>

    <div class="history-layout">
      <v-sheet class="tool-panel history-list-panel" rounded="lg">
        <div class="panel-title preview-title">
          <span>
            <v-icon icon="mdi-history" />
            History jobs
          </span>
          <v-chip size="small" variant="tonal">{{ history.length }}</v-chip>
        </div>

        <div v-if="isLoading && historyNewestFirst.length === 0" class="jobs-empty">
          <v-progress-circular color="primary" indeterminate size="28" />
          <span>Loading history</span>
        </div>

        <div v-else-if="historyNewestFirst.length === 0" class="jobs-empty">
          <v-icon icon="mdi-inbox-outline" size="30" />
          <span>No history yet</span>
        </div>

        <div v-else class="job-list">
          <div
            v-for="job in historyNewestFirst"
            :key="job.jobId"
            class="job-row history-job-row"
          >
            <div class="job-thumb" :class="{ 'has-image': previewFor(job) }">
              <img
                v-if="previewFor(job)"
                alt="History job preview"
                :src="previewFor(job)"
              >
              <v-icon v-else :icon="jobTypeIcon(job.type)" size="28" />
            </div>

            <div class="job-main">
              <div class="job-title-row">
                <strong>{{ shortId(job.jobId) }}</strong>
                <v-chip
                  :color="statusMeta(job.status).tone"
                  size="small"
                  variant="tonal"
                >
                  <v-icon :icon="statusMeta(job.status).icon" size="14" start />
                  {{ jobStatusLabel(job.status) }}
                </v-chip>
              </div>
              <div class="job-meta-row">
                <span>
                  <v-icon :icon="jobTypeIcon(job.type)" size="15" />
                  {{ jobTypeLabel(job.type) }}
                </span>
                <span>{{ formatDate(job.createdAt) }}</span>
                <span>Updated {{ formatDate(job.updatedAt) }}</span>
              </div>
            </div>

            <div class="history-job-actions">
              <v-tooltip text="Open preview">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :aria-label="`Open preview for ${job.jobId}`"
                    density="comfortable"
                    :disabled="!previewFor(job)"
                    :href="previewFor(job)"
                    icon="mdi-receipt-text-outline"
                    size="small"
                    target="_blank"
                    variant="text"
                  />
                </template>
              </v-tooltip>
            </div>
          </div>
        </div>
      </v-sheet>

      <div class="history-side-stack">
        <v-sheet class="tool-panel history-controls-panel" rounded="lg">
          <div class="panel-title">
            <v-icon icon="mdi-calendar-clock" />
            <span>Retention</span>
          </div>

          <div class="history-settings-form">
            <v-switch
              v-model="cleanupEnabled"
              color="primary"
              density="compact"
              hide-details
              label="History enabled"
            />
            <v-switch
              v-model="cleanupUseRetention"
              color="primary"
              density="compact"
              hide-details
              label="Use retention days"
            />
            <v-text-field
              v-model.number="cleanupRetentionDays"
              density="compact"
              :disabled="!cleanupUseRetention"
              hide-details
              label="Retention days"
              min="0"
              type="number"
              variant="outlined"
            />
          </div>

          <dl class="detail-list history-settings-list">
            <div>
              <dt>Loaded</dt>
              <dd>{{ settings ? (settings.enabled ? 'Enabled' : 'Disabled') : '-' }}</dd>
            </div>
            <div>
              <dt>Retention</dt>
              <dd>{{ settings ? retentionLabel(settings.retentionDays) : '-' }}</dd>
            </div>
            <div>
              <dt>Startup</dt>
              <dd>{{ settings ? (settings.cleanupOnStart ? 'Cleanup on start' : 'Manual only') : '-' }}</dd>
            </div>
            <div>
              <dt>Latest</dt>
              <dd>{{ latestHistoryJob ? formatDate(latestHistoryJob.createdAt) : '-' }}</dd>
            </div>
          </dl>

          <v-alert
            v-if="cleanupWouldSkipRetention"
            density="compact"
            type="info"
            variant="tonal"
          >
            Current cleanup overrides remove nothing.
          </v-alert>

          <v-btn
            color="error"
            :disabled="!settings || isLoading"
            :loading="isCleaning"
            prepend-icon="mdi-delete-clock-outline"
            variant="tonal"
            @click="cleanupDialog = true"
          >
            Cleanup History
          </v-btn>
          <v-btn
            color="primary"
            :disabled="!settings || isLoading || isCleaning || isSaving || !historyHasChanges"
            :loading="isSaving"
            prepend-icon="mdi-content-save"
            variant="tonal"
            @click="saveHistorySettings"
          >
            Save History
          </v-btn>
        </v-sheet>

        <v-sheet
          v-if="cleanupResult || startupCleanup"
          class="tool-panel history-result-panel"
          rounded="lg"
        >
          <div class="panel-title">
            <v-icon icon="mdi-clipboard-check-outline" />
            <span>Cleanup Result</span>
          </div>

          <div v-if="cleanupSummary" class="cleanup-summary">
            <v-chip
              v-for="item in cleanupSummary"
              :key="item.label"
              :color="item.tone"
              size="small"
              variant="tonal"
            >
              {{ item.label }} {{ item.value }}
            </v-chip>
          </div>

          <template v-if="cleanupResult">
            <section class="cleanup-section">
              <h2>Removed</h2>
              <div v-if="cleanupResult.removed.length === 0" class="cleanup-empty">
                No jobs removed
              </div>
              <div v-else class="cleanup-list">
                <div
                  v-for="job in cleanupResult.removed"
                  :key="job.jobId"
                  class="cleanup-row"
                >
                  <strong>{{ shortId(job.jobId) }}</strong>
                  <span>{{ formatDate(job.createdAt) }}</span>
                  <v-chip :color="statusMeta(job.status).tone" size="x-small" variant="tonal">
                    {{ jobStatusLabel(job.status) }}
                  </v-chip>
                </div>
              </div>
            </section>

            <section class="cleanup-section">
              <h2>Skipped</h2>
              <div v-if="cleanupResult.skipped.length === 0" class="cleanup-empty">
                No skipped jobs
              </div>
              <div v-else class="cleanup-list">
                <div
                  v-for="job in cleanupResult.skipped"
                  :key="`${job.jobId}-${job.reason}`"
                  class="cleanup-row"
                >
                  <strong>{{ shortId(job.jobId) }}</strong>
                  <span>{{ job.reason }}</span>
                  <v-chip
                    v-if="job.status"
                    :color="statusMeta(job.status).tone"
                    size="x-small"
                    variant="tonal"
                  >
                    {{ jobStatusLabel(job.status) }}
                  </v-chip>
                </div>
              </div>
            </section>

            <section v-if="cleanupResult.errors.length > 0" class="cleanup-section">
              <h2>Errors</h2>
              <v-alert
                v-for="(error, index) in cleanupResult.errors"
                :key="`${error.jobPath ?? 'cleanup'}-${error.message}-${index}`"
                density="compact"
                type="error"
                variant="tonal"
              >
                {{ error.message }}
              </v-alert>
            </section>
          </template>

          <v-alert
            v-if="startupCleanup"
            density="compact"
            :type="isCleanupResult(startupCleanup) && startupCleanup.errors.length === 0 ? 'info' : 'warning'"
            variant="tonal"
          >
            Startup cleanup:
            <template v-if="isCleanupResult(startupCleanup)">
              {{ startupCleanup.removed.length }} removed,
              {{ startupCleanup.skipped.length }} skipped,
              {{ startupCleanup.errors.length }} errors.
            </template>
            <template v-else>
              {{ startupCleanup.errors.length }} startup cleanup error(s).
            </template>
          </v-alert>
        </v-sheet>
      </div>
    </div>

    <v-dialog v-model="cleanupDialog" max-width="460">
      <v-card rounded="lg">
        <v-card-title>Cleanup history</v-card-title>
        <v-card-text>
          Run history cleanup with {{ cleanupEnabled ? 'history enabled' : 'history disabled' }}
          and retention {{ retentionLabel(retentionValue) }}?
          Queued or printing jobs are not presented as safe to remove.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="cleanupDialog = false">Cancel</v-btn>
          <v-btn
            color="error"
            :loading="isCleaning"
            variant="tonal"
            @click="runCleanup"
          >
            Cleanup
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>
