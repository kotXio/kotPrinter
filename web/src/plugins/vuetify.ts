import '@mdi/font/css/materialdesignicons.css';
import 'vuetify/styles';

import { createVuetify } from 'vuetify';
import { aliases, mdi } from 'vuetify/iconsets/mdi';

const vuetify = createVuetify({
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi,
    },
  },
  theme: {
    defaultTheme: 'catPrinterLight',
    themes: {
      catPrinterLight: {
        dark: false,
        colors: {
          background: '#f6f7f2',
          surface: '#ffffff',
          'surface-bright': '#ffffff',
          'surface-variant': '#e4ebe5',
          primary: '#215c57',
          'on-primary': '#ffffff',
          secondary: '#f0a620',
          'on-secondary': '#1f1806',
          accent: '#4d7298',
          error: '#b3261e',
          info: '#3b6ea8',
          success: '#2e7d54',
          warning: '#b76e00',
        },
      },
      catPrinterDark: {
        dark: true,
        colors: {
          background: '#111518',
          surface: '#171d21',
          'surface-bright': '#222b30',
          'surface-variant': '#273239',
          primary: '#8fcfc3',
          'on-primary': '#08201d',
          secondary: '#f3c35a',
          'on-secondary': '#251a02',
          accent: '#9bb8d6',
          error: '#ffb4ab',
          info: '#a9c7ef',
          success: '#8dd9b2',
          warning: '#ffd48a',
        },
      },
    },
  },
});

export default vuetify;
