import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import { apiClient, isAbortError, messageFromError } from '@/api';
import type {
  HealthResponse,
  PrinterInfoResponse,
  PrinterStatusResponse,
  VersionResponse,
} from '@/api';

const IDLE_STATUS_INTERVAL_MS = 12_000;
const ACTIVE_STATUS_INTERVAL_MS = 2_000;

export const usePrinterStore = defineStore('printer', () => {
  const health = ref<HealthResponse | null>(null);
  const version = ref<VersionResponse | null>(null);
  const status = ref<PrinterStatusResponse | null>(null);
  const printerInfo = ref<PrinterInfoResponse | null>(null);
  const isLoadingOverview = ref(false);
  const isLoadingInfo = ref(false);
  const overviewError = ref<string | null>(null);
  const infoError = ref<string | null>(null);
  const lastOverviewAt = ref<Date | null>(null);
  const lastInfoAt = ref<Date | null>(null);
  const isPolling = ref(false);

  let overviewController: AbortController | null = null;
  let infoController: AbortController | null = null;
  let pollTimer: number | undefined;
  let activeQueueSource: (() => boolean) | undefined;

  const isApiReachable = computed(() => health.value?.ok === true && !overviewError.value);
  const queueIsActive = computed(() => (status.value?.queue.activeCount ?? 0) > 0);
  const rfcommBound = computed(() => status.value?.rfcommBound ?? false);
  const connectionState = computed(() => status.value?.connectionState ?? 'unknown');
  const lastKnownBatteryPercent = computed(() => status.value?.lastKnownBatteryPercent ?? null);

  async function refreshOverview() {
    overviewController?.abort();
    overviewController = new AbortController();
    const { signal } = overviewController;

    isLoadingOverview.value = true;
    overviewError.value = null;

    try {
      const [healthResponse, versionResponse, statusResponse] = await Promise.all([
        apiClient.getHealth({ signal }),
        apiClient.getVersion({ signal }),
        apiClient.getPrinterStatus({ signal }),
      ]);

      health.value = healthResponse;
      version.value = versionResponse;
      status.value = statusResponse;
      lastOverviewAt.value = new Date();
    } catch (error) {
      if (!isAbortError(error)) {
        overviewError.value = messageFromError(error);
      }
    } finally {
      if (!signal.aborted) {
        isLoadingOverview.value = false;
      }
    }
  }

  async function fetchPrinterInfo() {
    infoController?.abort();
    infoController = new AbortController();
    const { signal } = infoController;

    isLoadingInfo.value = true;
    infoError.value = null;

    try {
      printerInfo.value = await apiClient.getPrinterInfo({ signal });
      lastInfoAt.value = new Date();
      return printerInfo.value;
    } catch (error) {
      if (!isAbortError(error)) {
        infoError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isLoadingInfo.value = false;
      }
    }
  }

  function startPolling(isQueueActive?: () => boolean) {
    activeQueueSource = isQueueActive;
    if (isPolling.value) {
      return;
    }

    isPolling.value = true;
    void pollOnce();
  }

  function stopPolling() {
    isPolling.value = false;
    if (pollTimer !== undefined) {
      window.clearTimeout(pollTimer);
      pollTimer = undefined;
    }
    overviewController?.abort();
    overviewController = null;
  }

  async function pollOnce() {
    if (!isPolling.value) {
      return;
    }

    await refreshOverview();

    if (!isPolling.value) {
      return;
    }

    const active = activeQueueSource?.() ?? queueIsActive.value;
    pollTimer = window.setTimeout(
      pollOnce,
      active ? ACTIVE_STATUS_INTERVAL_MS : IDLE_STATUS_INTERVAL_MS,
    );
  }

  return {
    health,
    version,
    status,
    printerInfo,
    isLoadingOverview,
    isLoadingInfo,
    overviewError,
    infoError,
    lastOverviewAt,
    lastInfoAt,
    isPolling,
    isApiReachable,
    queueIsActive,
    rfcommBound,
    connectionState,
    lastKnownBatteryPercent,
    refreshOverview,
    fetchPrinterInfo,
    startPolling,
    stopPolling,
  };
});
