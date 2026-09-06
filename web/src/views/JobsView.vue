<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { previewUrl, rasterUrl, sourceUrl } from '@/api';
import type {
  ApiProblem,
  JobRecord,
  JobStatus,
  JobSummary,
  JobType,
  QueueEntry,
  QueueStatus,
} from '@/api';
import { useJobsStore } from '@/stores/jobs';
import { useUiStore } from '@/stores/ui';

type JobLike = Pick<JobSummary, 'jobId' | 'status' | 'type'> & {
  previewPath?: string | null;
  rasterPath?: string | null;
  artifacts?: JobRecord['artifacts'];
};

type Tone = 'success' | 'warning' | 'error' | 'info' | 'primary';

type StatusMeta = {
  label: string;
  icon: string;
  tone: Tone;
};

type QueueGroup = {
  key: string;
  title: string;
  icon: string;
  tone: Tone;
  entries: QueueEntry[];
};

const jobsStore = useJobsStore();
const uiStore = useUiStore();

const limitItems = [
  { title: '25', value: 25 },
  { title: '50', value: 50 },
  { title: '100', value: 100 },
];

const jobLimit = ref(jobsStore.jobsLimit);
const detailOpen = ref(false);
const deleteDialog = ref(false);
const pendingDelete = ref<JobLike | null>(null);

const jobsNewestFirst = computed(() => (
  [...jobsStore.jobs].sort((left, right) => (
    new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime()
  ))
));
const queueEntries = computed(() => jobsStore.queue?.entries ?? []);
const selectedJob = computed(() => jobsStore.selectedJob);
const selectedQueueEntry = computed(() => jobsStore.selectedQueueEntry);
const selectedJobPreview = computed(() => (
  selectedJob.value?.artifacts.preview ? previewUrl(selectedJob.value.jobId) : ''
));
const selectedJobSourceUrl = computed(() => (
  selectedJob.value ? sourceUrl(selectedJob.value.jobId) : ''
));
const selectedJobRasterUrl = computed(() => (
  selectedJob.value?.artifacts.raster ? rasterUrl(selectedJob.value.jobId) : ''
));
const summaryTiles = computed(() => [
  {
    label: 'Jobs',
    value: String(jobsStore.jobs.length),
    icon: 'mdi-format-list-bulleted',
  },
  {
    label: 'Printing',
    value: String(jobsStore.printingCount),
    icon: 'mdi-printer-pos-play-outline',
  },
  {
    label: 'Queued',
    value: String(jobsStore.queuedCount),
    icon: 'mdi-tray-full',
  },
]);
const queueGroups = computed<QueueGroup[]>(() => [
  {
    key: 'printing',
    title: 'Printing',
    icon: 'mdi-printer-pos-play-outline',
    tone: 'warning',
    entries: queueEntries.value.filter((entry) => entry.status === 'printing'),
  },
  {
    key: 'queued',
    title: 'Queued',
    icon: 'mdi-tray-full',
    tone: 'info',
    entries: queueEntries.value.filter((entry) => entry.status === 'queued'),
  },
  {
    key: 'done',
    title: 'Done',
    icon: 'mdi-check-circle-outline',
    tone: 'success',
    entries: queueEntries.value.filter((entry) => entry.status === 'done'),
  },
  {
    key: 'failed',
    title: 'Failed',
    icon: 'mdi-alert-circle-outline',
    tone: 'error',
    entries: queueEntries.value.filter((entry) => (
      entry.status === 'failed' || entry.status === 'canceled'
    )),
  },
]);
const detailRows = computed(() => {
  const job = selectedJob.value;
  if (!job) {
    return [];
  }

  return [
    { label: 'Type', value: jobTypeLabel(job.type) },
    { label: 'Status', value: statusMeta(job.status).label },
    { label: 'Preset', value: job.preset ?? '-' },
    { label: 'Width', value: `${job.settings.printer.width} dots` },
    { label: 'Method', value: job.settings.render.method },
    { label: 'Feed', value: String(job.settings.printer.feed) },
    { label: 'Repeat', value: `${job.settings.printer.repeat}x` },
    { label: 'Created', value: formatDate(job.createdAt) },
    { label: 'Updated', value: formatDate(job.updatedAt) },
  ];
});
const actionError = computed(() => jobsStore.actionError);

onMounted(() => {
  void refreshJobs();
});

async function refreshJobs() {
  await jobsStore.refreshJobsAndQueue(jobLimit.value);
}

async function refreshWithLimit(value: number) {
  jobLimit.value = value;
  await refreshJobs();
}

async function openJob(jobId: string) {
  detailOpen.value = true;
  const job = await jobsStore.fetchJob(jobId);
  if (!job && jobsStore.detailError) {
    uiStore.showSnackbar(jobsStore.detailError, 'error');
  }
}

async function printJob(job: JobLike) {
  const result = await jobsStore.printJob(job.jobId);
  showActionResult(result, 'Job queued for printing');
}

async function reprintJob(job: JobLike) {
  const result = await jobsStore.reprintJob(job.jobId);
  showActionResult(result, 'Job queued for reprint');
}

async function cancelJob(jobId: string) {
  const result = await jobsStore.cancelJob(jobId);
  showActionResult(result, 'Job cancellation requested');
}

function requestDelete(job: JobLike) {
  if (isActiveJob(job)) {
    return;
  }

  pendingDelete.value = job;
  deleteDialog.value = true;
}

async function confirmDelete() {
  const job = pendingDelete.value;
  if (!job) {
    return;
  }

  const deleted = await jobsStore.deleteJob(job.jobId);
  if (deleted) {
    uiStore.showSnackbar('Job deleted', 'success');
    deleteDialog.value = false;
    pendingDelete.value = null;
    if (selectedJob.value?.jobId === job.jobId) {
      detailOpen.value = false;
    }
    return;
  }

  showActionError();
}

function showActionResult(result: unknown, message: string) {
  if (result) {
    uiStore.showSnackbar(message, 'success');
    return;
  }

  showActionError();
}

function showActionError() {
  if (jobsStore.actionError) {
    uiStore.showSnackbar(jobsStore.actionError, 'error');
  }
}

function canPrintJob(job: JobLike): boolean {
  return (
    job.status === 'rendered'
    && hasRaster(job)
    && !isActiveJob(job)
    && !jobsStore.isRunningAction
  );
}

function canReprintJob(job: JobLike): boolean {
  return (
    (job.status === 'rendered' || job.status === 'done' || job.status === 'failed')
    && hasRaster(job)
    && !isActiveJob(job)
    && !jobsStore.isRunningAction
  );
}

function canCancelJob(job: JobLike): boolean {
  return (
    (job.status === 'queued' || job.status === 'printing')
    && !jobsStore.isRunningAction
  );
}

function canDeleteJob(job: JobLike): boolean {
  return !isActiveJob(job) && !jobsStore.isRunningAction;
}

function canCancelQueueEntry(entry: QueueEntry): boolean {
  return (
    (entry.status === 'queued' || entry.status === 'printing')
    && !jobsStore.isRunningAction
  );
}

function isActiveJob(job: JobLike): boolean {
  return job.status === 'queued' || job.status === 'printing';
}

function hasRaster(job: JobLike): boolean {
  if ('artifacts' in job && job.artifacts) {
    return Boolean(job.artifacts.raster);
  }
  return Boolean(job.rasterPath);
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

function queueStatusMeta(status: QueueStatus): StatusMeta {
  const map: Record<QueueStatus, StatusMeta> = {
    queued: { label: 'Queued', icon: 'mdi-tray-full', tone: 'info' },
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

function problemKey(problem: ApiProblem, index: number): string {
  return `${problem.code}-${problem.message}-${index}`;
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
  <section class="route-view jobs-view">
    <header class="view-header">
      <div>
        <p class="section-kicker">Jobs</p>
        <h1>Jobs And Queue</h1>
      </div>
      <div class="jobs-toolbar">
        <v-select
          density="compact"
          hide-details
          :items="limitItems"
          label="Limit"
          :model-value="jobLimit"
          variant="outlined"
          @update:model-value="refreshWithLimit"
        />
        <v-btn
          color="primary"
          :loading="jobsStore.isLoadingJobs || jobsStore.isLoadingQueue"
          prepend-icon="mdi-refresh"
          variant="tonal"
          @click="refreshJobs"
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
      v-if="jobsStore.jobsError || jobsStore.queueError || actionError"
      density="comfortable"
      type="error"
      variant="tonal"
    >
      {{ jobsStore.jobsError || jobsStore.queueError || actionError }}
    </v-alert>

    <div class="jobs-grid">
      <v-sheet class="tool-panel jobs-panel" rounded="lg">
        <div class="panel-title preview-title">
          <span>
            <v-icon icon="mdi-format-list-bulleted" />
            Recent jobs
          </span>
          <v-chip size="small" variant="tonal">{{ jobsStore.jobs.length }}</v-chip>
        </div>

        <div v-if="jobsStore.isLoadingJobs && jobsNewestFirst.length === 0" class="jobs-empty">
          <v-progress-circular color="primary" indeterminate size="28" />
          <span>Loading jobs</span>
        </div>

        <div v-else-if="jobsNewestFirst.length === 0" class="jobs-empty">
          <v-icon icon="mdi-inbox-outline" size="30" />
          <span>No jobs yet</span>
        </div>

        <div v-else class="job-list">
          <div
            v-for="job in jobsNewestFirst"
            :key="job.jobId"
            class="job-row"
            role="button"
            tabindex="0"
            @click="openJob(job.jobId)"
            @keydown.enter="openJob(job.jobId)"
          >
            <div class="job-thumb" :class="{ 'has-image': previewFor(job) }">
              <img
                v-if="previewFor(job)"
                alt="Job preview"
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

            <div class="job-actions">
              <v-tooltip text="Print">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :aria-label="`Print ${job.jobId}`"
                    density="comfortable"
                    :disabled="!canPrintJob(job)"
                    icon="mdi-printer"
                    size="small"
                    variant="text"
                    @click.stop="printJob(job)"
                  />
                </template>
              </v-tooltip>
              <v-tooltip text="Reprint">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :aria-label="`Reprint ${job.jobId}`"
                    density="comfortable"
                    :disabled="!canReprintJob(job)"
                    icon="mdi-printer-pos-refresh"
                    size="small"
                    variant="text"
                    @click.stop="reprintJob(job)"
                  />
                </template>
              </v-tooltip>
              <v-tooltip text="Cancel">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :aria-label="`Cancel ${job.jobId}`"
                    density="comfortable"
                    :disabled="!canCancelJob(job)"
                    icon="mdi-cancel"
                    size="small"
                    variant="text"
                    @click.stop="cancelJob(job.jobId)"
                  />
                </template>
              </v-tooltip>
              <v-tooltip text="Delete">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :aria-label="`Delete ${job.jobId}`"
                    density="comfortable"
                    :disabled="!canDeleteJob(job)"
                    icon="mdi-delete-outline"
                    size="small"
                    variant="text"
                    @click.stop="requestDelete(job)"
                  />
                </template>
              </v-tooltip>
            </div>
          </div>
        </div>
      </v-sheet>

      <v-sheet class="tool-panel queue-panel" rounded="lg">
        <div class="panel-title preview-title">
          <span>
            <v-icon icon="mdi-tray-full" />
            Queue
          </span>
          <v-chip
            :color="jobsStore.queueCount > 0 ? 'warning' : 'success'"
            size="small"
            variant="tonal"
          >
            {{ jobsStore.queueCount }} active
          </v-chip>
        </div>

        <div class="queue-summary">
          <span>{{ jobsStore.printingCount }} printing</span>
          <span>{{ jobsStore.queuedCount }} queued</span>
          <span>{{ queueEntries.length }} total</span>
        </div>

        <div class="queue-group-list">
          <section
            v-for="group in queueGroups"
            :key="group.key"
            class="queue-group"
          >
            <div class="queue-group-title">
              <span>
                <v-icon :icon="group.icon" size="18" />
                {{ group.title }}
              </span>
              <v-chip :color="group.tone" size="x-small" variant="tonal">
                {{ group.entries.length }}
              </v-chip>
            </div>

            <div v-if="group.entries.length === 0" class="queue-empty">
              No {{ group.title.toLowerCase() }} entries
            </div>

            <div v-else class="queue-entry-list">
              <div
                v-for="entry in group.entries"
                :key="entry.queueId"
                class="queue-entry"
              >
                <div class="queue-entry-main">
                  <div class="queue-entry-title">
                    <button type="button" @click="openJob(entry.jobId)">
                      {{ shortId(entry.jobId) }}
                    </button>
                    <v-chip
                      :color="queueStatusMeta(entry.status).tone"
                      size="x-small"
                      variant="tonal"
                    >
                      {{ queueStatusMeta(entry.status).label }}
                    </v-chip>
                  </div>
                  <div class="queue-entry-meta">
                    <span>{{ entry.action }}</span>
                    <span>{{ formatDate(entry.enqueuedAt) }}</span>
                    <span v-if="entry.startedAt">Started {{ formatDate(entry.startedAt) }}</span>
                    <span v-if="entry.finishedAt">Finished {{ formatDate(entry.finishedAt) }}</span>
                  </div>
                  <v-alert
                    v-if="entry.error"
                    density="compact"
                    type="error"
                    variant="tonal"
                  >
                    {{ entry.error.message }}
                  </v-alert>
                </div>

                <v-btn
                  :aria-label="`Cancel queue entry ${entry.queueId}`"
                  density="comfortable"
                  :disabled="!canCancelQueueEntry(entry)"
                  icon="mdi-cancel"
                  size="small"
                  variant="text"
                  @click="cancelJob(entry.jobId)"
                />
              </div>
            </div>
          </section>
        </div>
      </v-sheet>
    </div>

    <v-navigation-drawer
      v-model="detailOpen"
      class="job-detail-drawer"
      location="right"
      temporary
      width="430"
    >
      <div class="job-detail">
        <div class="detail-header">
          <div>
            <p class="section-kicker">Job detail</p>
            <h2>{{ selectedJob ? shortId(selectedJob.jobId) : 'Loading' }}</h2>
          </div>
          <v-btn
            aria-label="Close job detail"
            icon="mdi-close"
            size="small"
            variant="text"
            @click="detailOpen = false"
          />
        </div>

        <div v-if="jobsStore.isLoadingDetail" class="jobs-empty">
          <v-progress-circular color="primary" indeterminate size="28" />
          <span>Loading detail</span>
        </div>

        <template v-else-if="selectedJob">
          <div class="detail-preview" :class="{ 'has-image': selectedJobPreview }">
            <img
              v-if="selectedJobPreview"
              alt="Selected job thermal preview"
              :src="selectedJobPreview"
            >
            <v-icon v-else :icon="jobTypeIcon(selectedJob.type)" size="34" />
          </div>

          <div class="detail-actions">
            <v-btn
              :disabled="!canPrintJob(selectedJob)"
              prepend-icon="mdi-printer"
              size="small"
              variant="tonal"
              @click="printJob(selectedJob)"
            >
              Print
            </v-btn>
            <v-btn
              :disabled="!canReprintJob(selectedJob)"
              prepend-icon="mdi-printer-pos-refresh"
              size="small"
              variant="tonal"
              @click="reprintJob(selectedJob)"
            >
              Reprint
            </v-btn>
            <v-btn
              :disabled="!canCancelJob(selectedJob)"
              prepend-icon="mdi-cancel"
              size="small"
              variant="tonal"
              @click="cancelJob(selectedJob.jobId)"
            >
              Cancel
            </v-btn>
            <v-btn
              color="error"
              :disabled="!canDeleteJob(selectedJob)"
              prepend-icon="mdi-delete-outline"
              size="small"
              variant="tonal"
              @click="requestDelete(selectedJob)"
            >
              Delete
            </v-btn>
          </div>

          <dl class="detail-list">
            <div v-for="row in detailRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </div>
          </dl>

          <div class="artifact-links">
            <v-btn
              :disabled="!selectedJobSourceUrl"
              :href="selectedJobSourceUrl"
              prepend-icon="mdi-file-outline"
              size="small"
              target="_blank"
              variant="text"
            >
              Source
            </v-btn>
            <v-btn
              :disabled="!selectedJobPreview"
              :href="selectedJobPreview"
              prepend-icon="mdi-receipt-text-outline"
              size="small"
              target="_blank"
              variant="text"
            >
              Preview
            </v-btn>
            <v-btn
              :disabled="!selectedJobRasterUrl"
              :href="selectedJobRasterUrl"
              prepend-icon="mdi-file-image-outline"
              size="small"
              target="_blank"
              variant="text"
            >
              Raster
            </v-btn>
          </div>

          <v-alert
            v-for="(warning, index) in selectedJob.warnings"
            :key="`${warning}-${index}`"
            density="compact"
            type="warning"
            variant="tonal"
          >
            {{ warning }}
          </v-alert>

          <v-alert
            v-for="(error, index) in selectedJob.errors"
            :key="problemKey(error, index)"
            density="compact"
            type="error"
            variant="tonal"
          >
            {{ error.message }}
          </v-alert>

          <v-alert
            v-if="selectedQueueEntry?.error"
            density="compact"
            type="error"
            variant="tonal"
          >
            {{ selectedQueueEntry.error.message }}
          </v-alert>
        </template>

        <v-alert
          v-else-if="jobsStore.detailError"
          density="comfortable"
          type="error"
          variant="tonal"
        >
          {{ jobsStore.detailError }}
        </v-alert>
      </div>
    </v-navigation-drawer>

    <v-dialog v-model="deleteDialog" max-width="420">
      <v-card rounded="lg">
        <v-card-title>Delete job</v-card-title>
        <v-card-text>
          Delete {{ pendingDelete ? shortId(pendingDelete.jobId) : 'this job' }}?
          Active jobs stay protected and cannot be deleted from this action.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteDialog = false">Cancel</v-btn>
          <v-btn
            color="error"
            :loading="jobsStore.isRunningAction"
            variant="tonal"
            @click="confirmDelete"
          >
            Delete
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>
