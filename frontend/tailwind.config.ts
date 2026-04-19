import type { Config } from "tailwindcss";

/**
 * Tailwind-Konfiguration auf Basis der Design-Strategie 2.0.
 *
 * Alle Farb- und Layout-Tokens werden per CSS-Variable aus globals.css gezogen,
 * damit Theme-Wechsel (z. B. Dark-Mode) später ohne Rebuild funktionieren.
 */
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-admin)", "system-ui", "sans-serif"],
      },
      colors: {
        // Primärfarbe (Rosé)
        primary: {
          DEFAULT: "var(--color-primary)",
          hover: "var(--color-primary-hover)",
          active: "var(--color-primary-active)",
          soft: "var(--color-primary-soft)",
          "on-primary": "var(--color-on-primary)",
        },
        // Textfarben
        text: {
          primary: "var(--color-text-primary)",
          secondary: "var(--color-text-secondary)",
          tertiary: "var(--color-text-tertiary)",
          inverse: "var(--color-text-inverse)",
        },
        // Hintergründe
        bg: {
          DEFAULT: "var(--color-bg)",
          surface: "var(--color-surface)",
          "surface-alt": "var(--color-surface-alt)",
          overlay: "var(--color-overlay)",
        },
        // Border
        border: {
          DEFAULT: "var(--color-border)",
          strong: "var(--color-border-strong)",
          focus: "var(--color-border-focus)",
        },
        // Semantik
        success: {
          DEFAULT: "var(--color-success)",
          soft: "var(--color-success-soft)",
        },
        warning: {
          DEFAULT: "var(--color-warning)",
          soft: "var(--color-warning-soft)",
        },
        danger: {
          DEFAULT: "var(--color-danger)",
          soft: "var(--color-danger-soft)",
        },
        info: {
          DEFAULT: "var(--color-info)",
          soft: "var(--color-info-soft)",
        },
        // Domain-Farben für Heizung
        heating: {
          on: "var(--color-heating-on)",
          off: "var(--color-heating-off)",
          preheat: "var(--color-heating-preheat)",
          frost: "var(--color-heating-frost)",
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        DEFAULT: "var(--radius-md)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
        full: "var(--radius-full)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        DEFAULT: "var(--shadow-md)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        focus: "var(--shadow-focus)",
      },
      spacing: {
        sidebar: "var(--layout-sidebar-width)",
        header: "var(--layout-header-height)",
      },
      transitionDuration: {
        fast: "var(--motion-fast)",
        DEFAULT: "var(--motion-medium)",
        medium: "var(--motion-medium)",
        slow: "var(--motion-slow)",
      },
      transitionTimingFunction: {
        standard: "var(--motion-ease-standard)",
      },
    },
  },
  plugins: [],
};

export default config;
