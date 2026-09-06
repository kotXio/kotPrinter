import { ref } from 'vue';
import { defineStore } from 'pinia';

import { apiClient, isAbortError, messageFromError } from '@/api';
import type {
  CheckResponse,
  HealthResponse,
  InstallDryRunResponse,
  PrinterInfoResponse,
  VersionResponse,
} from '@/api';

export const useDiagnosticsStore = defineStore('diagnostics', () => {
  const health = ref<HealthResponse | null>(null);
  const version = ref<VersionResponse | null>(null);
  const check = ref<CheckResponse | null>(null);
  const liveCheck = ref<CheckResponse | null>(null);
  const printerInfo = ref<PrinterInfoResponse | null>(null);
  const installDryRun = ref<InstallDryRunResponse | null>(null);
  const isLoadingHealth = ref(false);
  const isRunningCheck = ref(false);
  const isRunningLiveCheck = ref(false);
  const isLoadingPrinterInfo = ref(false);
  const isRunningInstallDryRun = ref(false);
  const healthError = ref<string | null>(null);
  const checkError = ref<string | null>(null);
  const liveCheckError = ref<string | null>(null);
  const printerInfoError = ref<string | null>(null);
  const installDryRunError = ref<string | null>(null);

  let healthController: AbortController | null = null;
  let checkController: AbortController | null = null;
  let liveCheckController: AbortController | null = null;
  let printerInfoController: AbortController | null = null;
  let installController: AbortController | null = null;

  async function refreshHealth() {
    healthController?.abort();
    healthController = new AbortController();
    const { signal } = healthController;

    isLoadingHealth.value = true;
    healthError.value = null;

    try {
      const [healthResponse, versionResponse] = await Promise.all([
        apiClient.getHealth({ signal }),
        apiClient.getVersion({ signal }),
      ]);
      health.value = healthResponse;
      version.value = versionResponse;
      return healthResponse;
    } catch (error) {
      if (!isAbortError(error)) {
        healthError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isLoadingHealth.value = false;
      }
    }
  }

  async function runCheck() {
    checkController?.abort();
    checkController = new AbortController();
    const { signal } = checkController;

    isRunningCheck.value = true;
    checkError.value = null;

    try {
      check.value = await apiClient.getCheck(false, { signal });
      return check.value;
    } catch (error) {
      if (!isAbortError(error)) {
        checkError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isRunningCheck.value = false;
      }
    }
  }

  async function runLiveCheck() {
    liveCheckController?.abort();
    liveCheckController = new AbortController();
    const { signal } = liveCheckController;

    isRunningLiveCheck.value = true;
    liveCheckError.value = null;

    try {
      liveCheck.value = await apiClient.getCheck(true, { signal });
      return liveCheck.value;
    } catch (error) {
      if (!isAbortError(error)) {
        liveCheckError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isRunningLiveCheck.value = false;
      }
    }
  }

  async function fetchPrinterInfo() {
    printerInfoController?.abort();
    printerInfoController = new AbortController();
    const { signal } = printerInfoController;

    isLoadingPrinterInfo.value = true;
    printerInfoError.value = null;

    try {
      printerInfo.value = await apiClient.getPrinterInfo({ signal });
      return printerInfo.value;
    } catch (error) {
      if (!isAbortError(error)) {
        printerInfoError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isLoadingPrinterInfo.value = false;
      }
    }
  }

  async function runInstallDryRun() {
    installController?.abort();
    installController = new AbortController();
    const { signal } = installController;

    isRunningInstallDryRun.value = true;
    installDryRunError.value = null;

    try {
      installDryRun.value = await apiClient.installDryRun({ signal });
      return installDryRun.value;
    } catch (error) {
      if (!isAbortError(error)) {
        installDryRunError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isRunningInstallDryRun.value = false;
      }
    }
  }

  function stopRequests() {
    healthController?.abort();
    checkController?.abort();
    liveCheckController?.abort();
    printerInfoController?.abort();
    installController?.abort();
  }

  return {
    health,
    version,
    check,
    liveCheck,
    printerInfo,
    installDryRun,
    isLoadingHealth,
    isRunningCheck,
    isRunningLiveCheck,
    isLoadingPrinterInfo,
    isRunningInstallDryRun,
    healthError,
    checkError,
    liveCheckError,
    printerInfoError,
    installDryRunError,
    refreshHealth,
    runCheck,
    runLiveCheck,
    fetchPrinterInfo,
    runInstallDryRun,
    stopRequests,
  };
});
