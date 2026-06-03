/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './App.{js,ts,tsx}',
    './components/**/*.{js,ts,tsx}',
    './src/**/*.{js,ts,tsx}',
  ],

  presets: [require('nativewind/preset')],
  theme: {
    extend: {
      colors: {
        'bg-dark': '#f4efe6',
        'bg-panel': '#ffffff',
        'bg-panel-hover': '#fcf9f3',
        primary: '#145374',
        'primary-hover': '#3a0ca3',
        secondary: '#0d3c52',
        danger: '#a43f24',
        success: '#1f7a58',
        'text-main': '#1f2933',
        'text-muted': '#5b6773',
        'border-glass': '#e0d8d0',
      },
      fontFamily: {
        sans: ['NunitoSans_400Regular'],
        semibold: ['NunitoSans_600SemiBold'],
        bold: ['NunitoSans_700Bold'],
      },
    },
  },
  plugins: [],
};
