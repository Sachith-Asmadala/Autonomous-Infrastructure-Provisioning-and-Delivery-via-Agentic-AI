/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    container: { center: true, padding: '2rem', screens: { '2xl': '1400px' } },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        ink: {
          DEFAULT: 'hsl(var(--foreground))',
          muted: 'hsl(var(--ink-muted))',
          subtle: 'hsl(var(--ink-subtle))',
          faint: 'hsl(var(--ink-faint))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
          50: '#eefbf3', 100: '#d6f4e1', 200: '#b0e9c7', 300: '#7dd8a5', 400: '#48bf7e',
          500: '#25a461', 600: '#18844d', 700: '#14693f', 800: '#135434', 900: '#10452c', 950: '#072719',
        },
        secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
        popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
        surface: {
          950: 'hsl(var(--surface-950))', 900: 'hsl(var(--surface-900))', 800: 'hsl(var(--surface-800))',
          700: 'hsl(var(--surface-700))', 600: 'hsl(var(--surface-600))', 500: 'hsl(var(--surface-500))',
        },
      },
      borderRadius: { lg: 'var(--radius)', md: 'calc(var(--radius) - 2px)', sm: 'calc(var(--radius) - 4px)' },
      fontFamily: { mono: ['JetBrains Mono', 'Fira Code', 'monospace'], sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'] },
      boxShadow: { glow: '0 24px 80px hsl(var(--primary) / 0.18)', panel: '0 3px 16px hsl(var(--shadow) / 0.05)' },
      keyframes: {
        fadeIn: { '0%': { opacity: 0 }, '100%': { opacity: 1 } },
        slideUp: { '0%': { transform: 'translateY(10px)', opacity: 0 }, '100%': { transform: 'translateY(0)', opacity: 1 } },
        blink: { '0%, 100%': { opacity: 1 }, '50%': { opacity: 0 } },
      },
      animation: { 'fade-in': 'fadeIn 0.3s ease-in-out', 'slide-up': 'slideUp 0.3s ease-out', 'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite', blink: 'blink 1s step-end infinite' },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
