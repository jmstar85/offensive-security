/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        danger: '#dc2626',
        warning: '#ca8a04',
        success: '#16a34a',
      },
    },
  },
  plugins: [],
}
