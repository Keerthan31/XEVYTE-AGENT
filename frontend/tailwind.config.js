/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Wix Madefor Display"', 'sans-serif'],
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
      },
    },
  },
  plugins: [],
}
