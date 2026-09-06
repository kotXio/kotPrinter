import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import { apiClient, isAbortError, isApiError, messageFromError } from '@/api';
import type {
  ApiFieldError,
  ImageJobRequest,
  JobRecord,
  JobSummary,
  QueueEntry,
  QueueSnapshot,
  TextJobRequest,
} from '@/api';

const IDLE_QUEUE_INTERVAL_MS = 12_000;
const ACTIVE_QUEUE_INTERVAL_MS = 2_000;
const DEFAULT_JOBS_LIMIT = 25;

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<JobSummary[]>([]);
  const queue = ref<QueueSnapshot | null>(null);
  const selectedJob = ref<JobRecord | null>(null);
  const selectedQueueEntry = ref<QueueEntry | null>(null);
  const jobsLimit = ref(DEFAULT_JOBS_LIMIT);
  const isLoadingJobs = ref(false);
  const isLoadingQueue = ref(false);
  const isLoadingDetail = ref(false);
  const isRunningAction = ref(false);
  const jobsError = ref<string | null>(null);
  const queueError = ref<string | null>(null);
  const detailError = ref<string | null>(null);
  const actionError = ref<string | null>(null);
  const actionFieldErrors = ref<ApiFieldError[]>([]);
  const lastJobsAt = ref<Date | null>(null);
  const lastQueueAt = ref<Date | null>(null);
  const isPollingQueue = ref(false);

  let jobsController: AbortController | null = null;
  let queueController: AbortController | null = null;
  let detailController: AbortController | null = null;
  let actionController: AbortController | null = null;
  let pollTimer: number | undefined;

  const hasActiveQueue = computed(() => (queue.value?.activeCount ?? 0) > 0);
  const queueCount = computed(() => queue.value?.activeCount ?? 0);
  const queuedCount = computed(() => queue.value?.queuedCount ?? 0);
  const printingCount = computed(() => queue.value?.printingCount ?? 0);
  const latestJob = computed(() => jobs.value.at(-1) ?? null);

  async function refreshJobs(limit = jobsLimit.value) {
    jobsController?.abort();
    jobsController = new AbortController();
    const { signal } = jobsController;

    isLoadingJobs.value = true;
    jobsError.value = null;

    try {
      const response = await apiClient.listJobs({ limit }, { signal });
      jobs.value = response.jobs;
      queue.value = response.queue;
      jobsLimit.value = limit;
      lastJobsAt.value = new Date();
      lastQueueAt.value = new Date();
      return response;
    } catch (error) {
      if (!isAbortError(error)) {
        jobsError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isLoadingJobs.value = false;
      }
    }
  }

  async function refreshQueue() {
    queueController?.abort();
    queueController = new AbortController();
    const { signal } = queueController;

    isLoadingQueue.value = true;
    queueError.value = null;

    try {
      const response = await apiClient.getQueue({ signal });
      queue.value = response.queue;
      lastQueueAt.value = new Date();
      return response.queue;
    } catch (error) {
      if (!isAbortError(error)) {
        queueError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isLoadingQueue.value = false;
      }
    }
  }

  async function refreshJobsAndQueue(limit = jobsLimit.value) {
    return refreshJobs(limit);
  }

  async function fetchJob(jobId: string) {
    detailController?.abort();
    detailController = new AbortController();
    const { signal } = detailController;

    isLoadingDetail.value = true;
    detailError.value = null;

    try {
      const response = await apiClient.getJob(jobId, { signal });
      selectedJob.value = response.job;
      selectedQueueEntry.value = response.queue;
      return response.job;
    } catch (error) {
      if (!isAbortError(error)) {
        detailError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isLoadingDetail.value = false;
      }
    }
  }

  async function createTextJob(payload: TextJobRequest) {
    return runJobAction(async (signal) => {
      const response = await apiClient.createTextJob(payload, { signal });
      selectedJob.value = response.job;
      await refreshJobsAndQueue();
      return response.job;
    });
  }

  async function createImageJob(file: File, payload: ImageJobRequest = {}) {
    return runJobAction(async (signal) => {
      const response = await apiClient.createImageJob(file, payload, { signal });
      selectedJob.value = response.job;
      await refreshJobsAndQueue();
      return response.job;
    });
  }

  async function printJob(jobId: string) {
    return runJobAction(async (signal) => {
      const response = await apiClient.printJob(jobId, { signal });
      selectedJob.value = response.job;
      selectedQueueEntry.value = response.queue ?? null;
      await refreshJobsAndQueue();
      return response.job;
    });
  }

  async function reprintJob(jobId: string) {
    return runJobAction(async (signal) => {
      const response = await apiClient.reprintJob(jobId, { signal });
      selectedJob.value = response.job;
      selectedQueueEntry.value = response.queue ?? null;
      await refreshJobsAndQueue();
      return response.job;
    });
  }

  async function cancelJob(jobId: string) {
    return runJobAction(async (signal) => {
      const response = await apiClient.cancelJob(jobId, { signal });
      selectedJob.value = response.job;
      selectedQueueEntry.value = response.queue ?? null;
      await refreshJobsAndQueue();
      return response.job;
    });
  }

  async function deleteJob(jobId: string) {
    return runJobAction(async (signal) => {
      const response = await apiClient.deleteJob(jobId, { signal });
      if (selectedJob.value?.jobId === jobId) {
        selectedJob.value = null;
        selectedQueueEntry.value = null;
      }
      await refreshJobsAndQueue();
      return response.deleted;
    });
  }

  function startQueuePolling() {
    if (isPollingQueue.value) {
      return;
    }

    isPollingQueue.value = true;
    void pollQueueOnce();
  }

  function stopQueuePolling() {
    isPollingQueue.value = false;
    if (pollTimer !== undefined) {
      window.clearTimeout(pollTimer);
      pollTimer = undefined;
    }
    jobsController?.abort();
    queueController?.abort();
    detailController?.abort();
    actionController?.abort();
  }

  async function pollQueueOnce() {
    if (!isPollingQueue.value) {
      return;
    }

    await refreshQueue();

    if (hasActiveQueue.value) {
      await refreshJobs();
    }

    if (!isPollingQueue.value) {
      return;
    }

    pollTimer = window.setTimeout(
      pollQueueOnce,
      hasActiveQueue.value ? ACTIVE_QUEUE_INTERVAL_MS : IDLE_QUEUE_INTERVAL_MS,
    );
  }

  async function runJobAction<T>(action: (signal: AbortSignal) => Promise<T>) {
    actionController?.abort();
    actionController = new AbortController();
    const { signal } = actionController;

    isRunningAction.value = true;
    actionError.value = null;
    actionFieldErrors.value = [];

    try {
      return await action(signal);
    } catch (error) {
      if (!isAbortError(error)) {
        actionError.value = messageFromError(error);
        actionFieldErrors.value = isApiError(error) ? error.fieldErrors : [];
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isRunningAction.value = false;
      }
    }
  }

  return {
    jobs,
    queue,
    selectedJob,
    selectedQueueEntry,
    jobsLimit,
    isLoadingJobs,
    isLoadingQueue,
    isLoadingDetail,
    isRunningAction,
    jobsError,
    queueError,
    detailError,
    actionError,
    actionFieldErrors,
    lastJobsAt,
    lastQueueAt,
    isPollingQueue,
    hasActiveQueue,
    queueCount,
    queuedCount,
    printingCount,
    latestJob,
    refreshJobs,
    refreshQueue,
    refreshJobsAndQueue,
    fetchJob,
    createTextJob,
    createImageJob,
    printJob,
    reprintJob,
    cancelJob,
    deleteJob,
    startQueuePolling,
    stopQueuePolling,
  };
});
