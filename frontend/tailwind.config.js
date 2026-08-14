/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Wix Madefor Display"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SF Mono', 'Menlo', 'monospace'],
      },
      colors: {
        xevyte: {
          50:  '#e6f7f6',
          100: '#ccefed',
          500: '#19c2b4',
          600: '#00b3a4',
          700: '#009084',
          900: '#004a43',
        },
        agent: {
          void: '#f9fafb',   // Very light gray
          base: '#ffffff',   // White
          panel: '#f3f4f6',  // Panel background
          raised: '#ffffff', // Raised panel background
          inset: '#e5e7eb',  // Inset panel
          accent: '#009084', // Teal accent
          amber: '#d97706',  // Amber/yellow
          red: '#dc2626',    // Red for light mode
        },
      },
    },
  },
  plugins: [],
}
