import type { ApiProblem } from './errors';

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type TextPreset = 'text' | 'label';
export type ImagePreset = TextPreset | 'photo' | 'sticker';
export type RenderMethod = 'fs' | 'ordered' | 'th';
export type TextAlign = 'left' | 'center' | 'right';
export type TextDensity = 'light' | 'normal' | 'dark';
export type ImageRotate = 0 | 90 | 180 | 270;
export type ImageFit = 'width' | 'contain' | 'cover' | 'stretch' | 'none' | 'autofit';
export type CropAlign = 'top' | 'center' | 'bottom';
export type CropBox = [number, number, number, number];

export type JobType = 'text' | 'image';
export type JobStatus =
  | 'draft'
  | 'rendering'
  | 'rendered'
  | 'queued'
  | 'printing'
  | 'done'
  | 'failed'
  | 'canceled';

export type QueueStatus = 'queued' | 'printing' | 'done' | 'failed' | 'canceled';

export type CheckStatus = 'OK' | 'WARN' | 'FAIL';

export type ApiOk = {
  ok: true;
};

export type HealthResponse = ApiOk & {
  service: 'kotprinter';
  version: string;
};

export type VersionResponse = ApiOk & {
  name: 'kotPrinter';
  version: string;
};

export type CheckResult = {
  name: string;
  status: CheckStatus;
  message: string;
  action: string;
};

export type CheckResponse = {
  ok: boolean;
  results: CheckResult[];
};

export type DeviceConfig = {
  name: string;
  mac: string;
  channel: number;
  port: string;
  baudrate: number;
  rfcommService: string;
};

export type PrinterConfig = {
  width: number;
  feed: number;
  repeat: number;
};

export type TextConfig = {
  font: string;
  fontSize: number;
  padY: number;
  align: TextAlign;
  lineSpacing: number;
  density: TextDensity;
};

export type ImageConfig = {
  method: RenderMethod;
  brightness: number;
  contrast: number;
  gamma: number;
  rotate: ImageRotate;
  fit: ImageFit;
  height: number | null;
  cropAlign: CropAlign;
  invert: boolean;
  threshold: number | null;
};

export type HistoryConfig = {
  enabled: boolean;
  retentionDays: number | null;
  cleanupOnStart: boolean;
};

export type SettingsConfig = {
  schemaVersion: number;
  device: DeviceConfig;
  printer: PrinterConfig;
  text: TextConfig;
  image: ImageConfig;
  history: HistoryConfig;
};

export type RuntimeDeviceSettings = {
  name: string;
  mac: string;
  channel: number;
  port: string;
  baudrate: number;
  rfcomm_service: string;
};

export type RuntimePrinterSettings = {
  width: number;
  feed: number;
  repeat: number;
};

export type RuntimeRenderSettings = {
  method: RenderMethod;
  brightness: number;
  contrast: number;
  gamma: number;
};

export type RuntimeTextSettings = {
  font: string;
  font_size: number;
  pad_y: number;
  align: TextAlign;
  line_spacing: number;
  density: TextDensity;
};

export type RuntimeImageSettings = {
  rotate: ImageRotate;
  rotate_explicit: boolean;
  crop: CropBox | null;
  fit: ImageFit;
  height: number | null;
  crop_align: CropAlign;
  invert: boolean;
  threshold: number | null;
};

export type RuntimeSettings = {
  device: RuntimeDeviceSettings;
  printer: RuntimePrinterSettings;
  render: RuntimeRenderSettings;
  text: RuntimeTextSettings;
  image: RuntimeImageSettings;
  preview: boolean;
  preset: string | null;
};

export type SettingsResponse = ApiOk & {
  settings: SettingsConfig;
  configPath: string;
  loadedPath: string | null;
  configExists: boolean;
  warnings: string[];
};

export type SettingsUpdateResponse = ApiOk & {
  settings: SettingsConfig;
  configPath: string;
  loadedPath: string;
  warnings: string[];
};

export type ValidationIssue = {
  field: string;
  message: string;
};

export type SettingsValidationResponse = {
  ok: boolean;
  data: SettingsConfig | null;
  warnings: string[];
  errors: ValidationIssue[];
};

export type PrinterStatusResponse = ApiOk & {
  configured: boolean;
  configPath: string;
  rfcommBound: boolean;
  connectionState: string;
  lastJob: JobSummary | null;
  lastKnownBatteryPercent: number | null;
  queue: QueueSnapshot;
  note: string;
};

export type PrinterInfoResponse = ApiOk & {
  printer: {
    voltageMv: number;
    dpi: number;
    batteryPercent: number;
    serialNumber: string;
  };
  settings: RuntimeSettings;
};

export type CommonJobOptions = {
  method?: RenderMethod;
  brightness?: number;
  contrast?: number;
  gamma?: number;
  feed?: number;
  repeat?: number;
  preview?: boolean;
};

export type TextJobOptions = CommonJobOptions & {
  fontSize?: number;
  padY?: number;
  lineSpacing?: number;
  align?: TextAlign;
  textDensity?: TextDensity;
};

export type ImageJobOptions = CommonJobOptions & {
  rotate?: ImageRotate;
  crop?: CropBox;
  fit?: ImageFit;
  height?: number | null;
  cropAlign?: CropAlign;
  invert?: boolean;
  threshold?: number | null;
};

export type TextJobRequest = {
  text: string;
  preset?: TextPreset;
  render?: boolean;
  options?: TextJobOptions;
};

export type ImageJobRequest = {
  preset?: ImagePreset;
  render?: boolean;
  options?: ImageJobOptions;
};

export type JobOptionsSnapshot = {
  preview: boolean;
  feed: number;
  repeat: number;
  render: RuntimeRenderSettings;
  text: RuntimeTextSettings;
  image: RuntimeImageSettings;
};

export type JobArtifacts = {
  preview?: string;
  raster?: string;
  [key: string]: string | undefined;
};

export type JobPaths = {
  jobDir: string;
  source: string;
};

export type JobSummary = {
  jobId: string;
  type: JobType;
  status: JobStatus;
  createdAt: string;
  updatedAt: string;
  jobPath: string;
  previewPath: string | null;
  rasterPath: string | null;
  sourcePath: string;
};

export type JobRecord = {
  schemaVersion: number;
  jobId: string;
  type: JobType;
  status: JobStatus;
  createdAt: string;
  updatedAt: string;
  preset: string | null;
  options: JobOptionsSnapshot;
  settings: RuntimeSettings;
  paths: JobPaths;
  artifacts: JobArtifacts;
  warnings: string[];
  errors: ApiProblem[];
  text?: {
    length: number;
  };
  image?: {
    originalPath: string;
    storedSource: string;
  };
  renderMetadata?: JsonObject;
  jobMetadata?: JobMetadata;
};

export type JobMetadata = {
  upload?: {
    filename: string;
    contentType: string;
  };
  queue?: QueueEntry | Partial<QueueEntry>;
  cancelRequest?: QueueEntry | Partial<QueueEntry>;
  printError?: ApiProblem;
  printResult?: PrintResult;
  [key: string]: unknown;
};

export type JobsResponse = ApiOk & {
  jobs: JobSummary[];
  queue: QueueSnapshot;
};

export type JobResponse = ApiOk & {
  job: JobRecord;
};

export type JobDetailResponse = ApiOk & {
  job: JobRecord;
  queue: QueueEntry | null;
};

export type JobActionResponse = ApiOk & {
  job: JobRecord;
  queue?: QueueEntry;
  queued?: boolean;
  cancelRequested?: boolean;
  message?: string;
};

export type DeleteJobResponse = ApiOk & {
  deleted: {
    jobId: string;
    jobDir: string;
    remainingJobs: number;
  };
};

export type PrintResult = {
  bytesWritten: number;
  rasterBytesWritten: number;
  feedBytesWritten: number;
  warnings: string[];
  metadata: Record<string, unknown>;
  reprint: boolean;
  queueId: string;
};

export type QueueEntryResult = {
  jobId?: string;
  status?: JobStatus;
  printResult?: PrintResult;
  [key: string]: unknown;
};

export type QueueEntry = {
  queueId: string;
  jobId: string;
  action: string;
  status: QueueStatus;
  enqueuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  cancelRequestedAt: string | null;
  result: QueueEntryResult | null;
  error: ApiProblem | null;
};

export type QueueSnapshot = {
  activeCount: number;
  queuedCount: number;
  printingCount: number;
  entries: QueueEntry[];
};

export type QueueResponse = ApiOk & {
  queue: QueueSnapshot;
};

export type HistoryResponse = ApiOk & {
  history: JobSummary[];
  settings: HistoryConfig;
  queue: QueueSnapshot;
  startupCleanup: HistoryCleanupResult | StartupCleanupError | null;
};

export type HistoryCleanupRequest = {
  enabled?: boolean;
  retentionDays?: number | null;
};

export type HistoryCleanupResult = {
  enabled: boolean;
  retentionDays: number | null;
  cutoff?: string;
  removed: HistoryRemovedJob[];
  skipped: HistorySkippedJob[];
  errors: HistoryCleanupError[];
  rebuiltIndexCount: number;
};

export type HistoryRemovedJob = {
  jobId: string;
  jobDir: string;
  createdAt: string;
  status: JobStatus;
};

export type HistorySkippedJob = {
  jobId: string;
  reason: string;
  status?: JobStatus;
};

export type HistoryCleanupError = {
  jobPath?: string;
  message: string;
};

export type StartupCleanupError = {
  enabled: false;
  errors: HistoryCleanupError[];
};

export type HistoryCleanupResponse = {
  ok: boolean;
  cleanup: HistoryCleanupResult;
  settings: HistoryConfig;
};

export type InstallServicePlan = {
  kind: 'rfcomm' | 'server' | string;
  name: string;
  path: string;
  content: string;
};

export type InstallDryRunResponse = ApiOk & {
  dryRun: true;
  plan: {
    services: InstallServicePlan[];
    projectRoot: string;
    configPath: string | null;
    server: {
      host: string;
      port: number;
      service: string;
      user: string;
    };
    frontendBuilt: boolean;
    frontendIndex: string;
    warnings: string[];
    serviceName: string;
    servicePath: string;
    serviceContent: string;
    requiredGroup: string | null;
    commands: string[];
  };
};

export type JobArtifactUrls = {
  previewUrl: string;
  sourceUrl: string;
  rasterUrl: string;
};
