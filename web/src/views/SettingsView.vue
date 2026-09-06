<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import type {
  CropAlign,
  ImageFit,
  ImageRotate,
  RenderMethod,
  TextAlign,
  TextDensity,
} from '@/api';
import { useSettingsStore } from '@/stores/settings';
import { useUiStore } from '@/stores/ui';

type SelectItem<T extends string | number> = {
  title: string;
  value: T;
};

const settingsStore = useSettingsStore();
const uiStore = useUiStore();

const draft = computed(() => settingsStore.draft);
const loadedSettings = computed(() => settingsStore.settings);
const saveDialog = ref(false);

const darkTheme = computed({
  get: () => uiStore.isDark,
  set: (value: boolean) => {
    uiStore.setTheme(value ? 'catPrinterDark' : 'catPrinterLight');
  },
});
const imageHeightEnabled = computed({
  get: () => draft.value?.image.height !== null,
  set: (enabled: boolean) => {
    if (!draft.value) {
      return;
    }
    draft.value.image.height = enabled ? 384 : null;
  },
});
const imageThresholdEnabled = computed({
  get: () => draft.value?.image.threshold !== null,
  set: (enabled: boolean) => {
    if (!draft.value) {
      return;
    }
    draft.value.image.threshold = enabled ? 160 : null;
  },
});
const historyRetentionEnabled = computed({
  get: () => draft.value?.history.retentionDays !== null,
  set: (enabled: boolean) => {
    if (!draft.value) {
      return;
    }
    draft.value.history.retentionDays = enabled ? 30 : null;
  },
});
const hasDeviceChanges = computed(() => {
  if (!draft.value || !loadedSettings.value) {
    return false;
  }
  return !sameObject(draft.value.device, loadedSettings.value.device);
});
const changedSections = computed(() => {
  const current = draft.value;
  const loaded = loadedSettings.value;
  if (!current || !loaded) {
    return [];
  }

  return [
    ['Printer', current.printer, loaded.printer],
    ['Text', current.text, loaded.text],
    ['Image', current.image, loaded.image],
    ['History', current.history, loaded.history],
    ['Device', current.device, loaded.device],
  ]
    .filter(([, currentSection, loadedSection]) => !sameObject(currentSection, loadedSection))
    .map(([label]) => label as string);
});
const summaryTiles = computed(() => [
  {
    label: 'Width',
    value: `${draft.value?.printer.width ?? 384} dots`,
    icon: 'mdi-arrow-expand-horizontal',
  },
  {
    label: 'Feed',
    value: String(draft.value?.printer.feed ?? 5),
    icon: 'mdi-arrow-down-bold-outline',
  },
  {
    label: 'Changed',
    value: String(changedSections.value.length),
    icon: 'mdi-pencil-outline',
  },
]);
const validationWarnings = computed(() => settingsStore.validation?.warnings ?? []);
const responseWarnings = computed(() => settingsStore.response?.warnings ?? []);
const formError = computed(() => (
  settingsStore.loadError
  ?? settingsStore.validationError
  ?? settingsStore.saveError
));
const configPath = computed(() => settingsStore.response?.configPath ?? '-');
const loadedPath = computed(() => settingsStore.response?.loadedPath ?? '-');

const alignItems: SelectItem<TextAlign>[] = [
  { title: 'Left', value: 'left' },
  { title: 'Center', value: 'center' },
  { title: 'Right', value: 'right' },
];
const densityItems: SelectItem<TextDensity>[] = [
  { title: 'Light', value: 'light' },
  { title: 'Normal', value: 'normal' },
  { title: 'Dark', value: 'dark' },
];
const methodItems: SelectItem<RenderMethod>[] = [
  { title: 'Floyd-Steinberg', value: 'fs' },
  { title: 'Ordered', value: 'ordered' },
  { title: 'Threshold', value: 'th' },
];
const rotateItems: SelectItem<ImageRotate>[] = [
  { title: '0', value: 0 },
  { title: '90', value: 90 },
  { title: '180', value: 180 },
  { title: '270', value: 270 },
];
const fitItems: SelectItem<ImageFit>[] = [
  { title: 'Width', value: 'width' },
  { title: 'Contain', value: 'contain' },
  { title: 'Cover', value: 'cover' },
  { title: 'Stretch', value: 'stretch' },
  { title: 'None', value: 'none' },
  { title: 'Autofit', value: 'autofit' },
];
const cropAlignItems: SelectItem<CropAlign>[] = [
  { title: 'Top', value: 'top' },
  { title: 'Center', value: 'center' },
  { title: 'Bottom', value: 'bottom' },
];

onMounted(() => {
  void settingsStore.loadSettings();
});

async function validateSettings(showSuccess = true) {
  const validation = await settingsStore.validateDraft();

  if (!validation) {
    if (settingsStore.validationError) {
      uiStore.showSnackbar(settingsStore.validationError, 'error');
    }
    return null;
  }

  if (!validation.ok) {
    uiStore.showSnackbar('Fix settings validation errors', 'warning');
    return validation;
  }

  if (showSuccess) {
    uiStore.showSnackbar('Settings are valid', 'success');
  }
  return validation;
}

async function requestSave() {
  const validation = await validateSettings(false);
  if (!validation) {
    return;
  }

  if (!validation.ok) {
    uiStore.showSnackbar('Fix settings validation errors before saving', 'warning');
    return;
  }

  if (hasDeviceChanges.value) {
    saveDialog.value = true;
    return;
  }

  await saveSettings();
}

async function confirmSave() {
  saveDialog.value = false;
  await saveSettings();
}

async function saveSettings() {
  const saved = await settingsStore.saveDraft();
  if (saved) {
    uiStore.showSnackbar('Settings saved', 'success');
    return;
  }

  if (settingsStore.saveError) {
    uiStore.showSnackbar(settingsStore.saveError, 'error');
  }
}

function resetDraft() {
  settingsStore.resetDraft();
  uiStore.showSnackbar('Settings draft reset', 'info');
}

function fieldError(field: string): string[] {
  const message = settingsStore.fieldErrors.get(field);
  return message ? [message] : [];
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

function sameObject(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
</script>

<template>
  <section class="route-view settings-view">
    <header class="view-header">
      <div>
        <p class="section-kicker">Settings</p>
        <h1>Defaults</h1>
      </div>
      <div class="settings-toolbar">
        <v-btn
          :loading="settingsStore.isLoading"
          prepend-icon="mdi-refresh"
          variant="tonal"
          @click="settingsStore.loadSettings"
        >
          Reload
        </v-btn>
        <v-btn
          :disabled="!draft || !settingsStore.isDirty"
          prepend-icon="mdi-restore"
          variant="tonal"
          @click="resetDraft"
        >
          Reset
        </v-btn>
        <v-btn
          :disabled="!draft"
          :loading="settingsStore.isValidating"
          prepend-icon="mdi-check-decagram-outline"
          variant="tonal"
          @click="validateSettings"
        >
          Validate
        </v-btn>
        <v-btn
          color="primary"
          :disabled="!draft || !settingsStore.isDirty"
          :loading="settingsStore.isSaving"
          prepend-icon="mdi-content-save-outline"
          variant="tonal"
          @click="requestSave"
        >
          Save
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
      v-if="formError"
      density="comfortable"
      type="error"
      variant="tonal"
    >
      {{ formError }}
    </v-alert>

    <v-alert
      v-if="settingsStore.validation && !settingsStore.validation.ok"
      density="comfortable"
      type="warning"
      variant="tonal"
    >
      {{ settingsStore.validation.errors.length }} validation issue(s). Fields with errors are marked below.
    </v-alert>

    <div v-if="settingsStore.isLoading && !draft" class="settings-loading">
      <v-progress-circular color="primary" indeterminate size="28" />
      <span>Loading settings</span>
    </div>

    <template v-else-if="draft">
      <div class="settings-layout">
        <v-sheet class="tool-panel settings-panel" rounded="lg">
          <div class="panel-title">
            <v-icon icon="mdi-theme-light-dark" />
            <span>Appearance</span>
          </div>
          <div class="settings-form-grid is-two">
            <v-switch
              v-model="darkTheme"
              color="primary"
              density="compact"
              hide-details
              label="Dark theme"
            />
            <dl class="detail-list settings-meta-list">
              <div>
                <dt>Config</dt>
                <dd>{{ configPath }}</dd>
              </div>
              <div>
                <dt>Loaded</dt>
                <dd>{{ loadedPath }}</dd>
              </div>
              <div>
                <dt>Last read</dt>
                <dd>{{ formatDate(settingsStore.lastLoadedAt) }}</dd>
              </div>
              <div>
                <dt>Last save</dt>
                <dd>{{ formatDate(settingsStore.lastSavedAt) }}</dd>
              </div>
            </dl>
          </div>
        </v-sheet>

        <v-sheet class="tool-panel settings-panel" rounded="lg">
          <div class="panel-title">
            <v-icon icon="mdi-printer-settings" />
            <span>Printer Defaults</span>
          </div>
          <div class="settings-form-grid">
            <v-text-field
              v-model.number="draft.printer.width"
              density="compact"
              :error-messages="fieldError('printer.width')"
              label="Width"
              min="1"
              step="8"
              suffix="dots"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.printer.feed"
              density="compact"
              :error-messages="fieldError('printer.feed')"
              label="Feed"
              min="0"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.printer.repeat"
              density="compact"
              :error-messages="fieldError('printer.repeat')"
              label="Repeat"
              min="1"
              type="number"
              variant="outlined"
            />
          </div>
        </v-sheet>

        <v-sheet class="tool-panel settings-panel" rounded="lg">
          <div class="panel-title">
            <v-icon icon="mdi-text-box-outline" />
            <span>Text Defaults</span>
          </div>
          <div class="settings-form-grid">
            <v-text-field
              v-model="draft.text.font"
              class="settings-wide-field"
              density="compact"
              :error-messages="fieldError('text.font')"
              label="Font"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.text.fontSize"
              density="compact"
              :error-messages="fieldError('text.fontSize')"
              label="Font size"
              min="1"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.text.padY"
              density="compact"
              :error-messages="fieldError('text.padY')"
              label="Pad Y"
              min="0"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.text.lineSpacing"
              density="compact"
              :error-messages="fieldError('text.lineSpacing')"
              label="Line spacing"
              min="0"
              step="0.1"
              type="number"
              variant="outlined"
            />
            <v-select
              v-model="draft.text.align"
              density="compact"
              :error-messages="fieldError('text.align')"
              :items="alignItems"
              label="Align"
              variant="outlined"
            />
            <v-select
              v-model="draft.text.density"
              density="compact"
              :error-messages="fieldError('text.density')"
              :items="densityItems"
              label="Density"
              variant="outlined"
            />
          </div>
        </v-sheet>

        <v-sheet class="tool-panel settings-panel" rounded="lg">
          <div class="panel-title">
            <v-icon icon="mdi-image-outline" />
            <span>Image Defaults</span>
          </div>
          <div class="settings-form-grid">
            <v-select
              v-model="draft.image.method"
              density="compact"
              :error-messages="fieldError('image.method')"
              :items="methodItems"
              label="Method"
              variant="outlined"
            />
            <v-select
              v-model="draft.image.rotate"
              density="compact"
              :error-messages="fieldError('image.rotate')"
              :items="rotateItems"
              label="Rotate"
              variant="outlined"
            />
            <v-select
              v-model="draft.image.fit"
              density="compact"
              :error-messages="fieldError('image.fit')"
              :items="fitItems"
              label="Fit"
              variant="outlined"
            />
            <v-select
              v-model="draft.image.cropAlign"
              density="compact"
              :error-messages="fieldError('image.cropAlign')"
              :items="cropAlignItems"
              label="Crop align"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.image.brightness"
              density="compact"
              :error-messages="fieldError('image.brightness')"
              label="Brightness"
              min="0.1"
              step="0.05"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.image.contrast"
              density="compact"
              :error-messages="fieldError('image.contrast')"
              label="Contrast"
              min="0.1"
              step="0.05"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.image.gamma"
              density="compact"
              :error-messages="fieldError('image.gamma')"
              label="Gamma"
              min="0.1"
              step="0.05"
              type="number"
              variant="outlined"
            />
            <div class="settings-toggle-cell">
              <v-switch
                v-model="draft.image.invert"
                color="primary"
                density="compact"
                hide-details
                label="Invert"
              />
            </div>
            <div class="settings-toggle-cell">
              <v-switch
                v-model="imageHeightEnabled"
                color="primary"
                density="compact"
                hide-details
                label="Fixed height"
              />
            </div>
            <v-text-field
              v-model.number="draft.image.height"
              density="compact"
              :disabled="!imageHeightEnabled"
              :error-messages="fieldError('image.height')"
              label="Height"
              min="1"
              type="number"
              variant="outlined"
            />
            <div class="settings-toggle-cell">
              <v-switch
                v-model="imageThresholdEnabled"
                color="primary"
                density="compact"
                hide-details
                label="Threshold"
              />
            </div>
            <v-text-field
              v-model.number="draft.image.threshold"
              density="compact"
              :disabled="!imageThresholdEnabled"
              :error-messages="fieldError('image.threshold')"
              label="Threshold value"
              max="255"
              min="0"
              type="number"
              variant="outlined"
            />
          </div>
        </v-sheet>

        <v-sheet class="tool-panel settings-panel" rounded="lg">
          <div class="panel-title">
            <v-icon icon="mdi-history" />
            <span>History Behavior</span>
          </div>
          <div class="settings-form-grid">
            <div class="settings-toggle-cell">
              <v-switch
                v-model="draft.history.enabled"
                color="primary"
                density="compact"
                hide-details
                label="History enabled"
              />
            </div>
            <div class="settings-toggle-cell">
              <v-switch
                v-model="historyRetentionEnabled"
                color="primary"
                density="compact"
                hide-details
                label="Use retention"
              />
            </div>
            <v-text-field
              v-model.number="draft.history.retentionDays"
              density="compact"
              :disabled="!historyRetentionEnabled"
              :error-messages="fieldError('history.retentionDays')"
              label="Retention days"
              min="0"
              type="number"
              variant="outlined"
            />
            <div class="settings-toggle-cell">
              <v-switch
                v-model="draft.history.cleanupOnStart"
                color="primary"
                density="compact"
                hide-details
                label="Cleanup on start"
              />
            </div>
          </div>
        </v-sheet>

        <v-sheet class="tool-panel settings-panel settings-advanced-panel" rounded="lg">
          <div class="panel-title preview-title">
            <span>
              <v-icon icon="mdi-bluetooth-settings" />
              Advanced Device
            </span>
            <v-chip
              :color="hasDeviceChanges ? 'warning' : 'info'"
              size="small"
              variant="tonal"
            >
              {{ hasDeviceChanges ? 'Changed' : 'Stable' }}
            </v-chip>
          </div>
          <v-alert density="compact" type="warning" variant="tonal">
            Device changes can break printing until Bluetooth and RFCOMM are updated to match.
          </v-alert>
          <div class="settings-form-grid">
            <v-text-field
              v-model="draft.device.name"
              density="compact"
              :error-messages="fieldError('device.name')"
              label="Name"
              variant="outlined"
            />
            <v-text-field
              v-model="draft.device.mac"
              density="compact"
              :error-messages="fieldError('device.mac')"
              label="MAC"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.device.channel"
              density="compact"
              :error-messages="fieldError('device.channel')"
              label="RFCOMM channel"
              min="1"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model="draft.device.port"
              density="compact"
              :error-messages="fieldError('device.port')"
              label="Port"
              variant="outlined"
            />
            <v-text-field
              v-model.number="draft.device.baudrate"
              density="compact"
              :error-messages="fieldError('device.baudrate')"
              label="Baudrate"
              min="1"
              type="number"
              variant="outlined"
            />
            <v-text-field
              v-model="draft.device.rfcommService"
              density="compact"
              :error-messages="fieldError('device.rfcommService')"
              label="RFCOMM service"
              variant="outlined"
            />
          </div>
        </v-sheet>
      </div>

      <v-sheet class="tool-panel settings-status-panel" rounded="lg">
        <div class="panel-title preview-title">
          <span>
            <v-icon icon="mdi-clipboard-check-outline" />
            Validation
          </span>
          <v-chip
            :color="settingsStore.validation?.ok ? 'success' : settingsStore.hasValidationErrors ? 'warning' : 'info'"
            size="small"
            variant="tonal"
          >
            {{ settingsStore.validation?.ok ? 'Valid' : settingsStore.hasValidationErrors ? 'Needs fixes' : 'Not checked' }}
          </v-chip>
        </div>

        <div class="settings-chip-row">
          <v-chip
            v-for="section in changedSections"
            :key="section"
            color="warning"
            size="small"
            variant="tonal"
          >
            {{ section }}
          </v-chip>
          <v-chip v-if="changedSections.length === 0" color="success" size="small" variant="tonal">
            No draft changes
          </v-chip>
        </div>

        <v-alert
          v-for="warning in responseWarnings"
          :key="warning"
          density="compact"
          type="warning"
          variant="tonal"
        >
          {{ warning }}
        </v-alert>

        <v-alert
          v-for="warning in validationWarnings"
          :key="warning"
          density="compact"
          type="warning"
          variant="tonal"
        >
          {{ warning }}
        </v-alert>

        <div v-if="settingsStore.validation?.errors.length" class="settings-error-list">
          <div
            v-for="issue in settingsStore.validation.errors"
            :key="`${issue.field}-${issue.message}`"
            class="settings-error-row"
          >
            <strong>{{ issue.field }}</strong>
            <span>{{ issue.message }}</span>
          </div>
        </div>
      </v-sheet>
    </template>

    <v-alert
      v-else
      density="comfortable"
      type="warning"
      variant="tonal"
    >
      Settings are not loaded yet.
    </v-alert>

    <v-dialog v-model="saveDialog" max-width="460">
      <v-card rounded="lg">
        <v-card-title>Save device changes</v-card-title>
        <v-card-text>
          Device settings changed. Saving can affect Bluetooth binding, serial
          port access, and future print jobs.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="saveDialog = false">Cancel</v-btn>
          <v-btn
            color="warning"
            :loading="settingsStore.isSaving"
            variant="tonal"
            @click="confirmSave"
          >
            Save Anyway
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>
