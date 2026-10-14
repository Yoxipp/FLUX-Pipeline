/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './app/src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        flux: {
          bg:      'var(--color-bg)',
          surface: 'var(--color-surface)',
          fg:      'var(--color-fg)',
          accent:  'var(--color-accent)',
        },
      },
      fontFamily: {
        // ADR 0050: one font everywhere (embedded Inter); see --sans / --mono / --code in globals.css.
        sans: ['Inter Variable', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['Inter Variable', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      borderRadius: {
        'flux-sm': '4px',
        'flux':    '6px',
        'flux-lg': '8px',
      },
      boxShadow: {
        'flux-xs': 'var(--shadow-xs)',
        'flux-sm': 'var(--shadow-sm)',
        'flux-md': 'var(--shadow-md)',
      },
    },
  },
  plugins: [],
}
