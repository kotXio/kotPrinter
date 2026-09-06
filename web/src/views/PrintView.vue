<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useDisplay } from 'vuetify';

import { previewUrl, sourceUrl } from '@/api';
import type {
  CropAlign,
  CropBox,
  ImageFit,
  ImageJobOptions,
  ImagePreset,
  ImageRotate,
  RenderMethod,
  TextAlign,
  TextDensity,
  TextJobOptions,
  TextPreset,
} from '@/api';
import { useJobsStore } from '@/stores/jobs';
import { useUiStore, type ComposerMode } from '@/stores/ui';

type TextForm = {
  text: string;
  preset: TextPreset;
  fontSize: number;
  align: TextAlign;
  padY: number;
  lineSpacing: number;
  textDensity: TextDensity;
  method: RenderMethod;
  brightness: number;
  contrast: number;
  gamma: number;
  feed: number;
  repeat: number;
};

type ImageForm = {
  preset: ImagePreset;
  rotate: ImageRotate;
  cropEnabled: boolean;
  cropLeft: number;
  cropTop: number;
  cropWidth: number;
  cropHeight: number;
  fit: ImageFit;
  heightEnabled: boolean;
  height: number;
  cropAlign: CropAlign;
  invert: boolean;
  thresholdEnabled: boolean;
  threshold: number;
  method: RenderMethod;
  brightness: number;
  contrast: number;
  gamma: number;
  feed: number;
  repeat: number;
};

type ImagePreviewMode = 'original' | 'thermal';

const jobsStore = useJobsStore();
const uiStore = useUiStore();
const display = useDisplay();

const mode = computed<ComposerMode>({
  get: () => uiStore.composerMode,
  set: (value) => uiStore.setComposerMode(value),
});
const isPhoneComposer = computed(() => display.width.value <= 520);
const isNarrowPhoneComposer = computed(() => display.width.value <= 380);
const isCompactComposer = computed(() => !display.lgAndUp.value);
const textOptionsPanel = ref<string | null>(display.mdAndUp.value ? 'options' : null);
const imageOptionsPanel = ref<string | null>(display.mdAndUp.value ? 'options' : null);
const imagePreviewMode = ref<ImagePreviewMode>('original');
const lastRenderedImageSignature = ref('');
const isImageDragging = ref(false);
const imageDragDepth = ref(0);

const textForm = reactive<TextForm>({
  text: '',
  preset: 'text',
  fontSize: 20,
  align: 'left',
  padY: 6,
  lineSpacing: 0.5,
  textDensity: 'normal',
  method: 'fs',
  brightness: 1,
  contrast: 1,
  gamma: 1,
  feed: 5,
  repeat: 1,
});

const imageForm = reactive<ImageForm>({
  preset: 'photo',
  rotate: 0,
  cropEnabled: false,
  cropLeft: 0,
  cropTop: 0,
  cropWidth: 384,
  cropHeight: 384,
  fit: 'autofit',
  heightEnabled: false,
  height: 384,
  cropAlign: 'center',
  invert: false,
  thresholdEnabled: false,
  threshold: 160,
  method: 'fs',
  brightness: 1,
  contrast: 1,
  gamma: 1,
  feed: 5,
  repeat: 1,
});

const imageFile = ref<File | null>(null);
const sourceObjectUrl = ref('');

const presetItems = [
  { title: 'Text', value: 'text' },
  { title: 'Label', value: 'label' },
];
const imagePresetItems = [
  { title: 'Text', value: 'text' },
  { title: 'Label', value: 'label' },
  { title: 'Photo', value: 'photo' },
  { title: 'Sticker', value: 'sticker' },
];
const alignItems = [
  { title: 'Left', value: 'left', icon: 'mdi-format-align-left' },
  { title: 'Center', value: 'center', icon: 'mdi-format-align-center' },
  { title: 'Right', value: 'right', icon: 'mdi-format-align-right' },
];
const densityItems = [
  { title: 'Light', value: 'light' },
  { title: 'Normal', value: 'normal' },
  { title: 'Dark', value: 'dark' },
];
const methodItems = [
  { title: 'Floyd-Steinberg', value: 'fs' },
  { title: 'Ordered', value: 'ordered' },
  { title: 'Threshold', value: 'th' },
];
const rotateItems = [
  { title: '0', value: 0 },
  { title: '90', value: 90 },
  { title: '180', value: 180 },
  { title: '270', value: 270 },
];
const fitItems = [
  { title: 'Width', value: 'width' },
  { title: 'Contain', value: 'contain' },
  { title: 'Cover', value: 'cover' },
  { title: 'Stretch', value: 'stretch' },
  { title: 'None', value: 'none' },
  { title: 'Autofit', value: 'autofit' },
];
const cropAlignItems = [
  { title: 'Top', value: 'top' },
  { title: 'Center', value: 'center' },
  { title: 'Bottom', value: 'bottom' },
];
const fieldAliases: Record<string, string[]> = {
  fontSize: ['fontSize', 'size'],
  padY: ['padY', 'pad_y'],
  lineSpacing: ['lineSpacing', 'line_spacing'],
  textDensity: ['textDensity', 'text_density'],
  cropAlign: ['cropAlign', 'crop_align'],
  file: ['file', 'image', 'source'],
};
const textOptionFields = [
  'preset',
  'method',
  'textDensity',
  'fontSize',
  'align',
  'brightness',
  'contrast',
  'gamma',
  'padY',
  'lineSpacing',
  'feed',
  'repeat',
];
const imageOptionFields = [
  'preset',
  'method',
  'fit',
  'cropAlign',
  'rotate',
  'height',
  'invert',
  'threshold',
  'brightness',
  'contrast',
  'gamma',
  'crop',
  'feed',
  'repeat',
];

const selectedTextJob = computed(() => (
  jobsStore.selectedJob?.type === 'text' ? jobsStore.selectedJob : null
));
const selectedImageJob = computed(() => (
  jobsStore.selectedJob?.type === 'image' ? jobsStore.selectedJob : null
));
const selectedPreviewJob = computed(() => (
  mode.value === 'text' ? selectedTextJob.value : selectedImageJob.value
));
const previewSource = computed(() => {
  const job = selectedPreviewJob.value;
  if (!job?.artifacts.preview) {
    return '';
  }
  return previewUrl(job.jobId);
});
const imageThermalPreviewSource = computed(() => {
  const job = selectedImageJob.value;
  if (!job?.artifacts.preview) {
    return '';
  }
  return previewUrl(job.jobId);
});
const sourcePreviewSource = computed(() => {
  if (sourceObjectUrl.value) {
    return sourceObjectUrl.value;
  }

  const job = selectedImageJob.value;
  if (!job?.paths.source) {
    return '';
  }
  return sourceUrl(job.jobId);
});
const sourcePreviewLabel = computed(() => {
  const file = imageFile.value;
  if (file) {
    return `${file.name} / ${fileSizeLabel(file.size)}`;
  }

  const upload = selectedImageJob.value?.jobMetadata?.upload;
  if (upload) {
    return `${upload.filename} / ${upload.contentType}`;
  }

  return 'No source selected';
});
const currentImageSignature = computed(() => JSON.stringify({
  file: imageFile.value
    ? {
        name: imageFile.value.name,
        size: imageFile.value.size,
        type: imageFile.value.type,
        lastModified: imageFile.value.lastModified,
      }
    : null,
  preset: imageForm.preset,
  options: imageOptions(),
}));
const canRenderText = computed(() => (
  mode.value === 'text'
  && textForm.text.trim().length > 0
  && !jobsStore.isRunningAction
));
const canRenderImage = computed(() => (
  mode.value === 'image'
  && imageFile.value !== null
  && !jobsStore.isRunningAction
));
const canPrintText = computed(() => {
  const job = selectedTextJob.value;
  return Boolean(
    mode.value === 'text'
    && job?.artifacts.raster
    && !['queued', 'printing'].includes(job.status)
    && !jobsStore.isRunningAction,
  );
});
const isThermalPreviewStale = computed(() => (
  mode.value === 'image'
  && Boolean(imageThermalPreviewSource.value)
  && lastRenderedImageSignature.value !== ''
  && currentImageSignature.value !== lastRenderedImageSignature.value
));
const canPrintImage = computed(() => {
  const job = selectedImageJob.value;
  return Boolean(
    mode.value === 'image'
    && job?.artifacts.raster
    && !isThermalPreviewStale.value
    && !['queued', 'printing'].includes(job.status)
    && !jobsStore.isRunningAction,
  );
});
const fieldErrorMap = computed(() => {
  const errors = new Map<string, string>();
  for (const error of jobsStore.actionFieldErrors) {
    errors.set(error.field, error.message);
  }
  return errors;
});
const jobStatusTone = computed(() => {
  switch (selectedPreviewJob.value?.status) {
    case 'rendered':
    case 'done':
      return 'success';
    case 'queued':
    case 'printing':
      return 'warning';
    case 'failed':
    case 'canceled':
      return 'error';
    default:
      return 'info';
  }
});
const jobStatusLabel = computed(() => selectedPreviewJob.value?.status ?? 'draft');
const renderWarnings = computed(() => selectedPreviewJob.value?.warnings ?? []);
const renderErrors = computed(() => selectedPreviewJob.value?.errors ?? []);
const metrics = computed(() => {
  if (mode.value === 'image') {
    return [
      {
        label: 'Width',
        value: `${selectedPreviewJob.value?.settings.printer.width ?? 384} dots`,
        shortValue: `${selectedPreviewJob.value?.settings.printer.width ?? 384}`,
        icon: 'mdi-arrow-expand-horizontal',
      },
      {
        label: 'Method',
        value: methodLabel(imageForm.method),
        shortValue: methodShortLabel(imageForm.method),
        icon: 'mdi-dots-grid',
      },
      {
        label: 'Fit',
        value: fitLabel(imageForm.fit),
        shortValue: fitLabel(imageForm.fit),
        icon: 'mdi-fit-to-page-outline',
      },
    ];
  }

  return [
    {
      label: 'Width',
      value: `${selectedPreviewJob.value?.settings.printer.width ?? 384} dots`,
      shortValue: `${selectedPreviewJob.value?.settings.printer.width ?? 384}`,
      icon: 'mdi-arrow-expand-horizontal',
    },
    {
      label: 'Method',
      value: methodLabel(textForm.method),
      shortValue: methodShortLabel(textForm.method),
      icon: 'mdi-dots-grid',
    },
    {
      label: 'Repeat',
      value: `${textForm.repeat}x`,
      shortValue: `${textForm.repeat}x`,
      icon: 'mdi-repeat',
    },
  ];
});
const emptyPreviewCaption = computed(() => (
  mode.value === 'image'
    ? 'No rendered image artifact yet.'
    : 'No rendered text artifact yet.'
));
const phoneThermalPreviewLabel = computed(() => (
  isThermalPreviewStale.value ? 'Last rendered' : 'Thermal preview'
));
const phoneImagePreviewCaption = computed(() => {
  if (imagePreviewMode.value === 'original') {
    return sourcePreviewLabel.value;
  }

  if (!imageThermalPreviewSource.value) {
    return 'No rendered image artifact yet.';
  }

  if (isThermalPreviewStale.value) {
    return 'Options changed. Render Preview again to update thermal view.';
  }

  return 'Exact rendered artifact that will be printed.';
});
const textOptionsSummary = computed(() => (
  `${presetLabel(textForm.preset)} · ${textForm.fontSize}px · ${methodLabel(textForm.method)}`
));
const imageOptionsSummary = computed(() => (
  `${imagePresetLabel(imageForm.preset)} · ${fitLabel(imageForm.fit)} · ${methodLabel(imageForm.method)}`
));
const previewActionLabel = computed(() => (
  isCompactComposer.value ? 'Preview' : 'Render preview'
));
const printActionLabel = computed(() => (
  isCompactComposer.value ? 'Print' : 'Print rendered job'
));

watch(
  () => textForm.preset,
  (preset) => {
    applyTextPresetDefaults(preset);
  },
  { immediate: true },
);

watch(
  () => imageForm.preset,
  (preset) => {
    applyImagePresetDefaults(preset);
  },
  { immediate: true },
);

watch(imageFile, (file) => {
  revokeSourceObjectUrl();
  imagePreviewMode.value = 'original';
  if (file) {
    sourceObjectUrl.value = URL.createObjectURL(file);
  }
});

watch(
  () => jobsStore.actionFieldErrors.map((error) => error.field).join('|'),
  () => {
    if (mode.value === 'text' && hasAnyFieldError(textOptionFields)) {
      textOptionsPanel.value = 'options';
    }

    if (mode.value === 'image' && hasAnyFieldError(imageOptionFields)) {
      imageOptionsPanel.value = 'options';
    }
  },
);

onBeforeUnmount(() => {
  revokeSourceObjectUrl();
});

async function renderTextJob() {
  const job = await jobsStore.createTextJob({
    text: textForm.text,
    preset: textForm.preset,
    render: true,
    options: textOptions(),
  });

  if (job) {
    uiStore.showSnackbar('Text preview rendered', 'success');
  } else if (jobsStore.actionError) {
    uiStore.showSnackbar(jobsStore.actionError, 'error');
  }
}

async function renderImageJob() {
  const file = imageFile.value;
  if (!file) {
    return;
  }

  const job = await jobsStore.createImageJob(file, {
    preset: imageForm.preset,
    render: true,
    options: imageOptions(),
  });

  if (job) {
    lastRenderedImageSignature.value = currentImageSignature.value;
    imagePreviewMode.value = 'thermal';
    uiStore.showSnackbar('Image preview rendered', 'success');
  } else if (jobsStore.actionError) {
    uiStore.showSnackbar(jobsStore.actionError, 'error');
  }
}

async function printTextJob() {
  const job = selectedTextJob.value;
  if (!job) {
    return;
  }

  const printed = await jobsStore.printJob(job.jobId);
  if (printed) {
    uiStore.showSnackbar('Text job queued for printing', 'success');
  } else if (jobsStore.actionError) {
    uiStore.showSnackbar(jobsStore.actionError, 'error');
  }
}

async function printImageJob() {
  const job = selectedImageJob.value;
  if (!job) {
    return;
  }

  const printed = await jobsStore.printJob(job.jobId);
  if (printed) {
    uiStore.showSnackbar('Image job queued for printing', 'success');
  } else if (jobsStore.actionError) {
    uiStore.showSnackbar(jobsStore.actionError, 'error');
  }
}

function textOptions(): TextJobOptions {
  return {
    fontSize: textForm.fontSize,
    padY: textForm.padY,
    lineSpacing: textForm.lineSpacing,
    align: textForm.align,
    textDensity: textForm.textDensity,
    method: textForm.method,
    brightness: textForm.brightness,
    contrast: textForm.contrast,
    gamma: textForm.gamma,
    feed: textForm.feed,
    repeat: textForm.repeat,
  };
}

function imageOptions(): ImageJobOptions {
  const options: ImageJobOptions = {
    rotate: imageForm.rotate,
    fit: imageForm.fit,
    height: imageForm.heightEnabled ? toInteger(imageForm.height, 384) : null,
    cropAlign: imageForm.cropAlign,
    invert: imageForm.invert,
    threshold: imageForm.thresholdEnabled ? toInteger(imageForm.threshold, 160) : null,
    method: imageForm.method,
    brightness: imageForm.brightness,
    contrast: imageForm.contrast,
    gamma: imageForm.gamma,
    feed: imageForm.feed,
    repeat: imageForm.repeat,
  };

  if (imageForm.cropEnabled) {
    options.crop = [
      toInteger(imageForm.cropLeft, 0),
      toInteger(imageForm.cropTop, 0),
      toInteger(imageForm.cropWidth, 384),
      toInteger(imageForm.cropHeight, 384),
    ] as CropBox;
  }

  return options;
}

function applyTextPresetDefaults(preset: TextPreset) {
  if (preset === 'label') {
    textForm.method = 'fs';
    textForm.contrast = 1.25;
    textForm.brightness = 1.05;
    textForm.gamma = 1;
    textForm.textDensity = 'dark';
    return;
  }

  textForm.method = 'th';
  textForm.contrast = 1.2;
  textForm.brightness = 1;
  textForm.gamma = 1;
  textForm.textDensity = 'normal';
}

function applyImagePresetDefaults(preset: ImagePreset) {
  imageForm.thresholdEnabled = false;

  if (preset === 'text') {
    imageForm.method = 'th';
    imageForm.thresholdEnabled = true;
    imageForm.threshold = 160;
    imageForm.contrast = 1.2;
    imageForm.brightness = 1;
    imageForm.gamma = 1;
    imageForm.fit = 'width';
    return;
  }

  if (preset === 'label') {
    imageForm.method = 'ordered';
    imageForm.contrast = 1.25;
    imageForm.brightness = 1.05;
    imageForm.gamma = 1;
    imageForm.fit = 'width';
    return;
  }

  if (preset === 'sticker') {
    imageForm.method = 'ordered';
    imageForm.contrast = 1.35;
    imageForm.brightness = 1.05;
    imageForm.gamma = 0.9;
    imageForm.fit = 'autofit';
    return;
  }

  imageForm.method = 'fs';
  imageForm.contrast = 1.1;
  imageForm.brightness = 1;
  imageForm.gamma = 0.95;
  imageForm.fit = 'autofit';
}

function setImageFile(value: unknown) {
  const file = normalizeFileInput(value);

  if (file && !isImageFile(file)) {
    imageFile.value = null;
    uiStore.showSnackbar('Choose an image file', 'error');
    return;
  }

  imageFile.value = file;
  imagePreviewMode.value = 'original';
}

function normalizeFileInput(value: unknown): File | null {
  if (value instanceof File) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.find((item): item is File => item instanceof File) ?? null;
  }

  return null;
}

function revokeSourceObjectUrl() {
  if (sourceObjectUrl.value) {
    URL.revokeObjectURL(sourceObjectUrl.value);
    sourceObjectUrl.value = '';
  }
}

function fieldError(field: string): string {
  const keys = fieldAliases[field] ?? [field];

  for (const key of keys) {
    const error = fieldErrorMap.value.get(key);
    if (error) {
      return error;
    }
  }

  return '';
}

function hasAnyFieldError(fields: string[]): boolean {
  return fields.some((field) => Boolean(fieldError(field)));
}

function onImageDragEnter(event: DragEvent) {
  if (!hasFileTransfer(event)) {
    return;
  }

  event.preventDefault();
  imageDragDepth.value += 1;
  isImageDragging.value = true;
}

function onImageDragOver(event: DragEvent) {
  if (!hasFileTransfer(event)) {
    return;
  }

  event.preventDefault();
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy';
  }
  isImageDragging.value = true;
}

function onImageDragLeave(event: DragEvent) {
  if (!hasFileTransfer(event)) {
    return;
  }

  event.preventDefault();
  imageDragDepth.value = Math.max(0, imageDragDepth.value - 1);
  if (imageDragDepth.value === 0) {
    isImageDragging.value = false;
  }
}

function onImageDrop(event: DragEvent) {
  if (!hasFileTransfer(event)) {
    return;
  }

  event.preventDefault();
  imageDragDepth.value = 0;
  isImageDragging.value = false;

  const files = Array.from(event.dataTransfer?.files ?? []);
  const file = files.find(isImageFile);
  if (!file) {
    imageFile.value = null;
    uiStore.showSnackbar('Drop an image file', 'error');
    return;
  }

  imageFile.value = file;
  imagePreviewMode.value = 'original';
}

function hasFileTransfer(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

function isImageFile(file: File): boolean {
  return (
    file.type.startsWith('image/')
    || /\.(avif|bmp|gif|jpe?g|png|tiff?|webp)$/i.test(file.name)
  );
}

function presetLabel(preset: TextPreset): string {
  return presetItems.find((item) => item.value === preset)?.title ?? preset;
}

function imagePresetLabel(preset: ImagePreset): string {
  return imagePresetItems.find((item) => item.value === preset)?.title ?? preset;
}

function methodLabel(method: RenderMethod): string {
  return methodItems.find((item) => item.value === method)?.title ?? method;
}

function methodShortLabel(method: RenderMethod): string {
  if (method === 'fs') {
    return 'FS';
  }

  return methodLabel(method);
}

function fitLabel(fit: ImageFit): string {
  return fitItems.find((item) => item.value === fit)?.title ?? fit;
}

function fileSizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${bytes} B`;
}

function toInteger(value: unknown, fallback: number): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.trunc(numeric);
}
</script>

<template>
  <section class="route-view print-view">
    <header class="view-header">
      <div class="workflow-toggle-row">
        <v-btn-toggle
          v-model="mode"
          class="mode-toggle"
          color="primary"
          density="comfortable"
          mandatory
          rounded="lg"
          variant="tonal"
        >
          <v-btn prepend-icon="mdi-text-box-outline" value="text">Text</v-btn>
          <v-btn prepend-icon="mdi-image-outline" value="image">Image</v-btn>
        </v-btn-toggle>
        <v-btn-toggle
          v-if="mode === 'image' && isPhoneComposer"
          v-model="imagePreviewMode"
          class="preview-mode-toggle"
          color="primary"
          density="compact"
          mandatory
          rounded="lg"
          variant="tonal"
        >
          <v-btn value="original">
            {{ isNarrowPhoneComposer ? 'Orig' : 'Original' }}
          </v-btn>
          <v-btn :disabled="!imageThermalPreviewSource" value="thermal">
            {{ isNarrowPhoneComposer ? 'Therm' : 'Thermal' }}
          </v-btn>
        </v-btn-toggle>
      </div>
    </header>

    <div class="studio-grid">
      <v-sheet class="tool-panel editor-panel" rounded="lg">
        <div class="panel-title composer-panel-title">
          <v-icon :icon="mode === 'text' ? 'mdi-pencil-outline' : 'mdi-image-edit-outline'" />
          <span>{{ mode === 'text' ? 'Text' : 'Image' }}</span>
        </div>

        <div v-if="mode === 'text'" class="text-composer">
          <v-textarea
            v-model="textForm.text"
            auto-grow
            bg-color="surface"
            counter
            density="comfortable"
            :error-messages="fieldError('text')"
            label="Content"
            rows="7"
            variant="outlined"
          />

          <v-expansion-panels
            v-model="textOptionsPanel"
            class="composer-option-panels"
            variant="accordion"
          >
            <v-expansion-panel value="options">
              <v-expansion-panel-title>
                <span class="option-panel-title">
                  <v-icon icon="mdi-tune-variant" size="20" />
                  Options
                </span>
                <span class="option-panel-summary">{{ textOptionsSummary }}</span>
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div class="option-panel-body">
                  <div class="option-grid">
                    <v-select
                      v-model="textForm.preset"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('preset')"
                      :items="presetItems"
                      label="Preset"
                      variant="outlined"
                    />
                    <v-select
                      v-model="textForm.method"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('method')"
                      :items="methodItems"
                      label="Method"
                      variant="outlined"
                    />
                    <v-select
                      v-model="textForm.textDensity"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('textDensity')"
                      :items="densityItems"
                      label="Text density"
                      variant="outlined"
                    />
                    <v-text-field
                      v-model.number="textForm.fontSize"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('fontSize')"
                      label="Font size"
                      min="1"
                      type="number"
                      variant="outlined"
                    />
                  </div>

                  <div class="toggle-row">
                    <span class="metric-label">Alignment</span>
                    <v-btn-toggle
                      v-model="textForm.align"
                      color="primary"
                      density="comfortable"
                      mandatory
                      rounded="lg"
                      variant="tonal"
                    >
                      <v-btn
                        v-for="item in alignItems"
                        :key="item.value"
                        :aria-label="item.title"
                        :icon="item.icon"
                        :value="item.value"
                      />
                    </v-btn-toggle>
                  </div>

                  <div class="slider-grid">
                    <div class="slider-field">
                      <v-slider
                        v-model="textForm.brightness"
                        color="primary"
                        density="compact"
                        hide-details
                        label="Brightness"
                        max="3"
                        min="0.1"
                        step="0.1"
                      />
                      <v-text-field
                        v-model.number="textForm.brightness"
                        bg-color="surface"
                        density="compact"
                        :error-messages="fieldError('brightness')"
                        hide-spin-buttons
                        label="Brightness"
                        max="3"
                        min="0.1"
                        step="0.1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                    <div class="slider-field">
                      <v-slider
                        v-model="textForm.contrast"
                        color="primary"
                        density="compact"
                        hide-details
                        label="Contrast"
                        max="3"
                        min="0.1"
                        step="0.1"
                      />
                      <v-text-field
                        v-model.number="textForm.contrast"
                        bg-color="surface"
                        density="compact"
                        :error-messages="fieldError('contrast')"
                        hide-spin-buttons
                        label="Contrast"
                        max="3"
                        min="0.1"
                        step="0.1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                    <div class="slider-field">
                      <v-slider
                        v-model="textForm.gamma"
                        color="primary"
                        density="compact"
                        hide-details
                        label="Gamma"
                        max="3"
                        min="0.1"
                        step="0.1"
                      />
                      <v-text-field
                        v-model.number="textForm.gamma"
                        bg-color="surface"
                        density="compact"
                        :error-messages="fieldError('gamma')"
                        hide-spin-buttons
                        label="Gamma"
                        max="3"
                        min="0.1"
                        step="0.1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                  </div>

                  <div class="option-grid is-compact">
                    <v-text-field
                      v-model.number="textForm.padY"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('padY')"
                      label="Pad Y"
                      min="0"
                      type="number"
                      variant="outlined"
                    />
                    <v-text-field
                      v-model.number="textForm.lineSpacing"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('lineSpacing')"
                      label="Line spacing"
                      min="0"
                      step="0.1"
                      type="number"
                      variant="outlined"
                    />
                    <v-text-field
                      v-model.number="textForm.feed"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('feed')"
                      label="Feed"
                      min="0"
                      type="number"
                      variant="outlined"
                    />
                    <v-text-field
                      v-model.number="textForm.repeat"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('repeat')"
                      label="Repeat"
                      min="1"
                      type="number"
                      variant="outlined"
                    />
                  </div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <v-alert
            v-if="jobsStore.actionError"
            density="comfortable"
            type="error"
            variant="tonal"
          >
            {{ jobsStore.actionError }}
          </v-alert>

          <div class="composer-actions">
            <v-btn
              color="primary"
              :disabled="!canRenderText"
              :loading="jobsStore.isRunningAction"
              prepend-icon="mdi-receipt-text-plus-outline"
              @click="renderTextJob"
            >
              {{ previewActionLabel }}
            </v-btn>
            <v-btn
              :disabled="!canPrintText"
              :loading="jobsStore.isRunningAction"
              prepend-icon="mdi-printer"
              variant="tonal"
              @click="printTextJob"
            >
              {{ printActionLabel }}
            </v-btn>
          </div>
        </div>

        <div v-else class="image-composer">
          <div class="source-grid">
            <div
              class="image-dropzone"
              :class="{ 'is-dragging': isImageDragging }"
              @dragenter="onImageDragEnter"
              @dragleave="onImageDragLeave"
              @dragover="onImageDragOver"
              @drop="onImageDrop"
            >
              <v-file-input
                accept="image/*"
                bg-color="surface"
                clearable
                density="comfortable"
                :error-messages="fieldError('file')"
                label="Image file"
                :model-value="imageFile"
                prepend-icon=""
                prepend-inner-icon="mdi-image-plus-outline"
                show-size
                variant="outlined"
                @update:model-value="setImageFile"
              />
              <div v-if="isImageDragging" class="dropzone-overlay">
                <v-icon icon="mdi-tray-arrow-down" size="28" />
                <span>Drop image</span>
              </div>
            </div>
            <div v-if="!isPhoneComposer" class="source-preview">
              <img
                v-if="sourcePreviewSource"
                :alt="sourcePreviewLabel"
                class="source-preview-image"
                :src="sourcePreviewSource"
              >
              <div v-else class="source-preview-empty">
                <v-icon icon="mdi-image-outline" size="30" />
                <span>Source preview</span>
              </div>
              <span class="source-preview-meta">{{ sourcePreviewLabel }}</span>
            </div>
          </div>

          <div
            v-if="isPhoneComposer"
            class="phone-preview-surface"
            :class="`is-${imagePreviewMode}`"
          >
            <template v-if="imagePreviewMode === 'original'">
              <div class="phone-preview-status-row">
                <span>
                  <v-icon icon="mdi-image-outline" size="18" />
                  Original
                </span>
              </div>
              <div class="source-preview">
                <img
                  v-if="sourcePreviewSource"
                  :alt="sourcePreviewLabel"
                  class="source-preview-image"
                  :src="sourcePreviewSource"
                >
                <div v-else class="source-preview-empty">
                  <v-icon icon="mdi-image-outline" size="30" />
                  <span>Source preview</span>
                </div>
                <span class="source-preview-meta">{{ phoneImagePreviewCaption }}</span>
              </div>
            </template>

            <template v-else>
              <div class="phone-preview-status-row">
                <span>
                  <v-icon icon="mdi-receipt-text-outline" size="18" />
                  {{ phoneThermalPreviewLabel }}
                </span>
                <v-chip
                  :color="isThermalPreviewStale ? 'warning' : jobStatusTone"
                  size="small"
                  variant="tonal"
                >
                  {{ isThermalPreviewStale ? 'stale' : jobStatusLabel }}
                </v-chip>
              </div>
              <div class="paper-preview" :class="{ 'has-image': imageThermalPreviewSource }">
                <img
                  v-if="imageThermalPreviewSource"
                  alt="Rendered thermal preview"
                  class="thermal-preview-image"
                  :src="imageThermalPreviewSource"
                >
                <template v-else>
                  <div class="paper-line is-wide" />
                  <div class="paper-line" />
                  <div class="paper-line is-short" />
                </template>
              </div>

              <div v-if="selectedImageJob" class="job-summary">
                <span>{{ selectedImageJob.jobId }}</span>
                <span>{{ selectedImageJob.createdAt }}</span>
              </div>

              <v-alert
                v-if="isThermalPreviewStale"
                density="compact"
                type="warning"
                variant="tonal"
              >
                {{ phoneImagePreviewCaption }}
              </v-alert>
              <v-alert
                v-for="warning in renderWarnings"
                :key="warning"
                density="compact"
                type="warning"
                variant="tonal"
              >
                {{ warning }}
              </v-alert>
              <v-alert
                v-for="error in renderErrors"
                :key="`${error.code}-${error.message}`"
                density="compact"
                type="error"
                variant="tonal"
              >
                {{ error.message }}
              </v-alert>
              <div v-if="!imageThermalPreviewSource" class="paper-preview-caption">
                {{ phoneImagePreviewCaption }}
              </div>
            </template>
          </div>

          <div v-if="isPhoneComposer" class="composer-actions">
            <v-btn
              color="primary"
              :disabled="!canRenderImage"
              :loading="jobsStore.isRunningAction"
              prepend-icon="mdi-image-filter-black-white"
              @click="renderImageJob"
            >
              {{ previewActionLabel }}
            </v-btn>
            <v-btn
              :disabled="!canPrintImage"
              :loading="jobsStore.isRunningAction"
              prepend-icon="mdi-printer"
              variant="tonal"
              @click="printImageJob"
            >
              {{ printActionLabel }}
            </v-btn>
          </div>

          <v-expansion-panels
            v-model="imageOptionsPanel"
            class="composer-option-panels"
            variant="accordion"
          >
            <v-expansion-panel value="options">
              <v-expansion-panel-title>
                <span class="option-panel-title">
                  <v-icon icon="mdi-tune-variant" size="20" />
                  Options
                </span>
                <span class="option-panel-summary">{{ imageOptionsSummary }}</span>
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div class="option-panel-body">
                  <div class="option-grid">
                    <v-select
                      v-model="imageForm.preset"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('preset')"
                      :items="imagePresetItems"
                      label="Preset"
                      variant="outlined"
                    />
                    <v-select
                      v-model="imageForm.method"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('method')"
                      :items="methodItems"
                      label="Method"
                      variant="outlined"
                    />
                    <v-select
                      v-model="imageForm.fit"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('fit')"
                      :items="fitItems"
                      label="Fit"
                      variant="outlined"
                    />
                    <v-select
                      v-model="imageForm.cropAlign"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('cropAlign')"
                      :items="cropAlignItems"
                      label="Crop align"
                      variant="outlined"
                    />
                  </div>

                  <div class="toggle-row">
                    <span class="metric-label">Rotate</span>
                    <v-btn-toggle
                      v-model="imageForm.rotate"
                      color="primary"
                      density="comfortable"
                      mandatory
                      rounded="lg"
                      variant="tonal"
                    >
                      <v-btn
                        v-for="item in rotateItems"
                        :key="item.value"
                        :value="item.value"
                      >
                        {{ item.title }}
                      </v-btn>
                    </v-btn-toggle>
                  </div>

                  <div class="option-grid is-compact">
                    <v-switch
                      v-model="imageForm.heightEnabled"
                      color="primary"
                      density="compact"
                      hide-details
                      inset
                      label="Height"
                    />
                    <v-text-field
                      v-model.number="imageForm.height"
                      bg-color="surface"
                      density="comfortable"
                      :disabled="!imageForm.heightEnabled"
                      :error-messages="fieldError('height')"
                      label="Height px"
                      min="1"
                      type="number"
                      variant="outlined"
                    />
                    <v-switch
                      v-model="imageForm.invert"
                      color="primary"
                      density="compact"
                      hide-details
                      inset
                      label="Invert"
                    />
                    <v-switch
                      v-model="imageForm.thresholdEnabled"
                      color="primary"
                      density="compact"
                      hide-details
                      inset
                      label="Threshold"
                    />
                  </div>

                  <div class="slider-grid">
                    <div class="slider-field">
                      <v-slider
                        v-model="imageForm.threshold"
                        color="primary"
                        density="compact"
                        :disabled="!imageForm.thresholdEnabled"
                        hide-details
                        label="Threshold"
                        max="255"
                        min="0"
                        step="1"
                      />
                      <v-text-field
                        v-model.number="imageForm.threshold"
                        bg-color="surface"
                        density="compact"
                        :disabled="!imageForm.thresholdEnabled"
                        :error-messages="fieldError('threshold')"
                        hide-spin-buttons
                        label="Threshold"
                        max="255"
                        min="0"
                        step="1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                    <div class="slider-field">
                      <v-slider
                        v-model="imageForm.brightness"
                        color="primary"
                        density="compact"
                        hide-details
                        label="Brightness"
                        max="3"
                        min="0.1"
                        step="0.1"
                      />
                      <v-text-field
                        v-model.number="imageForm.brightness"
                        bg-color="surface"
                        density="compact"
                        :error-messages="fieldError('brightness')"
                        hide-spin-buttons
                        label="Brightness"
                        max="3"
                        min="0.1"
                        step="0.1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                    <div class="slider-field">
                      <v-slider
                        v-model="imageForm.contrast"
                        color="primary"
                        density="compact"
                        hide-details
                        label="Contrast"
                        max="3"
                        min="0.1"
                        step="0.1"
                      />
                      <v-text-field
                        v-model.number="imageForm.contrast"
                        bg-color="surface"
                        density="compact"
                        :error-messages="fieldError('contrast')"
                        hide-spin-buttons
                        label="Contrast"
                        max="3"
                        min="0.1"
                        step="0.1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                    <div class="slider-field">
                      <v-slider
                        v-model="imageForm.gamma"
                        color="primary"
                        density="compact"
                        hide-details
                        label="Gamma"
                        max="3"
                        min="0.1"
                        step="0.1"
                      />
                      <v-text-field
                        v-model.number="imageForm.gamma"
                        bg-color="surface"
                        density="compact"
                        :error-messages="fieldError('gamma')"
                        hide-spin-buttons
                        label="Gamma"
                        max="3"
                        min="0.1"
                        step="0.1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                  </div>

                  <div class="crop-section">
                    <div class="toggle-row">
                      <span class="metric-label">Crop</span>
                      <v-switch
                        v-model="imageForm.cropEnabled"
                        color="primary"
                        density="compact"
                        hide-details
                        inset
                      />
                    </div>
                    <div class="crop-grid">
                      <v-text-field
                        v-model.number="imageForm.cropLeft"
                        bg-color="surface"
                        density="comfortable"
                        :disabled="!imageForm.cropEnabled"
                        :error-messages="fieldError('crop')"
                        label="Left"
                        min="0"
                        type="number"
                        variant="outlined"
                      />
                      <v-text-field
                        v-model.number="imageForm.cropTop"
                        bg-color="surface"
                        density="comfortable"
                        :disabled="!imageForm.cropEnabled"
                        :error-messages="fieldError('crop')"
                        label="Top"
                        min="0"
                        type="number"
                        variant="outlined"
                      />
                      <v-text-field
                        v-model.number="imageForm.cropWidth"
                        bg-color="surface"
                        density="comfortable"
                        :disabled="!imageForm.cropEnabled"
                        :error-messages="fieldError('crop')"
                        label="Width"
                        min="1"
                        type="number"
                        variant="outlined"
                      />
                      <v-text-field
                        v-model.number="imageForm.cropHeight"
                        bg-color="surface"
                        density="comfortable"
                        :disabled="!imageForm.cropEnabled"
                        :error-messages="fieldError('crop')"
                        label="Height"
                        min="1"
                        type="number"
                        variant="outlined"
                      />
                    </div>
                  </div>

                  <div class="option-grid is-compact">
                    <v-text-field
                      v-model.number="imageForm.feed"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('feed')"
                      label="Feed"
                      min="0"
                      type="number"
                      variant="outlined"
                    />
                    <v-text-field
                      v-model.number="imageForm.repeat"
                      bg-color="surface"
                      density="comfortable"
                      :error-messages="fieldError('repeat')"
                      label="Repeat"
                      min="1"
                      type="number"
                      variant="outlined"
                    />
                  </div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <v-alert
            v-if="jobsStore.actionError"
            density="comfortable"
            type="error"
            variant="tonal"
          >
            {{ jobsStore.actionError }}
          </v-alert>

          <div v-if="!isPhoneComposer" class="composer-actions">
            <v-btn
              color="primary"
              :disabled="!canRenderImage"
              :loading="jobsStore.isRunningAction"
              prepend-icon="mdi-image-filter-black-white"
              @click="renderImageJob"
            >
              {{ previewActionLabel }}
            </v-btn>
            <v-btn
              :disabled="!canPrintImage"
              :loading="jobsStore.isRunningAction"
              prepend-icon="mdi-printer"
              variant="tonal"
              @click="printImageJob"
            >
              {{ printActionLabel }}
            </v-btn>
          </div>
        </div>
      </v-sheet>

      <v-sheet
        v-if="!(mode === 'image' && isPhoneComposer)"
        class="tool-panel preview-panel"
        rounded="lg"
      >
        <div class="panel-title preview-title">
          <span>
            <v-icon icon="mdi-receipt-text-outline" />
            Thermal preview
          </span>
          <v-chip :color="jobStatusTone" size="small" variant="tonal">
            {{ jobStatusLabel }}
          </v-chip>
        </div>
        <div class="paper-preview" :class="{ 'has-image': previewSource }">
          <img
            v-if="previewSource"
            alt="Rendered thermal preview"
            class="thermal-preview-image"
            :src="previewSource"
          >
          <template v-else>
            <div class="paper-line is-wide" />
            <div class="paper-line" />
            <div class="paper-line is-short" />
          </template>
        </div>

        <div v-if="selectedPreviewJob" class="job-summary">
          <span>{{ selectedPreviewJob.jobId }}</span>
          <span>{{ selectedPreviewJob.createdAt }}</span>
        </div>

        <v-alert
          v-for="warning in renderWarnings"
          :key="warning"
          density="compact"
          type="warning"
          variant="tonal"
        >
          {{ warning }}
        </v-alert>
        <v-alert
          v-for="error in renderErrors"
          :key="`${error.code}-${error.message}`"
          density="compact"
          type="error"
          variant="tonal"
        >
          {{ error.message }}
        </v-alert>
        <div v-if="!previewSource" class="paper-preview-caption">
          {{ emptyPreviewCaption }}
        </div>
      </v-sheet>
    </div>

    <div class="control-grid">
      <v-sheet v-for="control in metrics" :key="control.label" class="metric-tile" rounded="lg">
        <v-icon :icon="control.icon" size="22" />
        <span class="metric-label">{{ control.label }}</span>
        <strong>{{ isPhoneComposer ? control.shortValue : control.value }}</strong>
      </v-sheet>
    </div>
  </section>
</template>
