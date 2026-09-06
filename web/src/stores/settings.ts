import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import { apiClient, isAbortError, messageFromError } from '@/api';
import type {
  SettingsConfig,
  SettingsResponse,
  SettingsUpdateResponse,
  SettingsValidationResponse,
} from '@/api';

export const useSettingsStore = defineStore('settings', () => {
  const response = ref<SettingsResponse | null>(null);
  const settings = ref<SettingsConfig | null>(null);
  const draft = ref<SettingsConfig | null>(null);
  const validation = ref<SettingsValidationResponse | null>(null);
  const isLoading = ref(false);
  const isValidating = ref(false);
  const isSaving = ref(false);
  const loadError = ref<string | null>(null);
  const validationError = ref<string | null>(null);
  const saveError = ref<string | null>(null);
  const lastLoadedAt = ref<Date | null>(null);
  const lastSavedAt = ref<Date | null>(null);

  let loadController: AbortController | null = null;
  let validateController: AbortController | null = null;
  let saveController: AbortController | null = null;

  const fieldErrors = computed(() => {
    const errors = new Map<string, string>();
    for (const error of validation.value?.errors ?? []) {
      errors.set(error.field, error.message);
    }
    return errors;
  });

  const hasValidationErrors = computed(() => (validation.value?.errors.length ?? 0) > 0);
  const isDirty = computed(() => (
    settings.value !== null
    && draft.value !== null
    && JSON.stringify(settings.value) !== JSON.stringify(draft.value)
  ));

  async function loadSettings() {
    loadController?.abort();
    loadController = new AbortController();
    const { signal } = loadController;

    isLoading.value = true;
    loadError.value = null;

    try {
      const loaded = await apiClient.getSettings({ signal });
      response.value = loaded;
      settings.value = loaded.settings;
      draft.value = cloneSettings(loaded.settings);
      validation.value = null;
      lastLoadedAt.value = new Date();
      return loaded;
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

  async function validateDraft() {
    if (draft.value === null) {
      return null;
    }

    validateController?.abort();
    validateController = new AbortController();
    const { signal } = validateController;

    isValidating.value = true;
    validationError.value = null;

    try {
      validation.value = await apiClient.validateSettings(draft.value, { signal });
      return validation.value;
    } catch (error) {
      if (!isAbortError(error)) {
        validationError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isValidating.value = false;
      }
    }
  }

  async function saveDraft() {
    if (draft.value === null) {
      return null;
    }

    saveController?.abort();
    saveController = new AbortController();
    const { signal } = saveController;

    isSaving.value = true;
    saveError.value = null;

    try {
      const saved = await apiClient.updateSettings(draft.value, { signal });
      applySavedSettings(saved);
      return saved;
    } catch (error) {
      if (!isAbortError(error)) {
        saveError.value = messageFromError(error);
      }
      return null;
    } finally {
      if (!signal.aborted) {
        isSaving.value = false;
      }
    }
  }

  function resetDraft() {
    draft.value = settings.value === null ? null : cloneSettings(settings.value);
    validation.value = null;
    validationError.value = null;
    saveError.value = null;
  }

  function applySavedSettings(saved: SettingsUpdateResponse) {
    settings.value = saved.settings;
    draft.value = cloneSettings(saved.settings);
    response.value = {
      ok: true,
      settings: saved.settings,
      configPath: saved.configPath,
      loadedPath: saved.loadedPath,
      configExists: true,
      warnings: saved.warnings,
    };
    validation.value = null;
    lastSavedAt.value = new Date();
  }

  function stopRequests() {
    loadController?.abort();
    validateController?.abort();
    saveController?.abort();
  }

  return {
    response,
    settings,
    draft,
    validation,
    isLoading,
    isValidating,
    isSaving,
    loadError,
    validationError,
    saveError,
    lastLoadedAt,
    lastSavedAt,
    fieldErrors,
    hasValidationErrors,
    isDirty,
    loadSettings,
    validateDraft,
    saveDraft,
    resetDraft,
    stopRequests,
  };
});

function cloneSettings(settings: SettingsConfig): SettingsConfig {
  return JSON.parse(JSON.stringify(settings)) as SettingsConfig;
}
