import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

export type AppTheme = 'catPrinterLight' | 'catPrinterDark';
export type ComposerMode = 'text' | 'image';
export type SnackbarTone = 'success' | 'info' | 'warning' | 'error';

export type AppSnackbar = {
  id: number;
  message: string;
  tone: SnackbarTone;
  timeout: number;
};

const THEME_STORAGE_KEY = 'catprinter.theme';
const COMPOSER_MODE_STORAGE_KEY = 'catprinter.composerMode';
let snackbarId = 0;

function readStoredTheme(): AppTheme {
  if (typeof window === 'undefined') {
    return 'catPrinterLight';
  }

  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (storedTheme === 'catPrinterDark' || storedTheme === 'catPrinterLight') {
    return storedTheme;
  }

  return window.matchMedia('(min-width: 960px)').matches
    ? 'catPrinterDark'
    : 'catPrinterLight';
}

function readStoredComposerMode(): ComposerMode {
  if (typeof window === 'undefined') {
    return 'text';
  }

  const storedMode = window.localStorage.getItem(COMPOSER_MODE_STORAGE_KEY);
  return storedMode === 'image' ? 'image' : 'text';
}

export const useUiStore = defineStore('ui', () => {
  const activeTheme = ref<AppTheme>(readStoredTheme());
  const composerMode = ref<ComposerMode>(readStoredComposerMode());
  const navRailCollapsed = ref(false);
  const snackbars = ref<AppSnackbar[]>([]);
  const isDark = computed(() => activeTheme.value === 'catPrinterDark');
  const activeSnackbar = computed(() => snackbars.value[0] ?? null);

  function setTheme(theme: AppTheme) {
    activeTheme.value = theme;

    if (typeof window !== 'undefined') {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'catPrinterLight' : 'catPrinterDark');
  }

  function setComposerMode(mode: ComposerMode) {
    composerMode.value = mode;

    if (typeof window !== 'undefined') {
      window.localStorage.setItem(COMPOSER_MODE_STORAGE_KEY, mode);
    }
  }

  function setNavRailCollapsed(value: boolean) {
    navRailCollapsed.value = value;
  }

  function showSnackbar(
    message: string,
    tone: SnackbarTone = 'info',
    timeout = 4500,
  ) {
    const snackbar = {
      id: ++snackbarId,
      message,
      tone,
      timeout,
    };
    snackbars.value.push(snackbar);
    return snackbar.id;
  }

  function dismissSnackbar(id: number) {
    snackbars.value = snackbars.value.filter((snackbar) => snackbar.id !== id);
  }

  return {
    activeTheme,
    composerMode,
    navRailCollapsed,
    snackbars,
    activeSnackbar,
    isDark,
    setTheme,
    toggleTheme,
    setComposerMode,
    setNavRailCollapsed,
    showSnackbar,
    dismissSnackbar,
  };
});
