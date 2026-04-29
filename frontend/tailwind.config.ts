import type { Config } from "tailwindcss";

/**
 * Tailwind-Konfiguration auf Basis der Design-Strategie 2.0.1.
 *
 * Alle Farben, Radien, Shadows, Spacing-Tokens kommen aus CSS-Variablen
 * in globals.css. Hier nur das Mapping CSS-Variable -> Tailwind-Utility.
 *
 * FLAT-Mapping fuer Surface- und Border-Tokens:
 *   bg-surface         => var(--color-surface)
 *   bg-surface-alt     => var(--color-surface-alt)
 *   border-border      => var(--color-border)
 *   border-border-strong => var(--color-border-strong)
 *
 * NESTED-Mapping fuer Text- und Brand-/Semantik-Farben (mit Sub-Tokens):
 *   text-text-primary  => var(--color-text-primary)
 *   bg-primary         => var(--color-primary)
 *   bg-primary-soft    => var(--color-primary-soft)
 *   text-primary       => var(--color-primary)
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
      // Schriftgroessen via Tokens. Aenderung von --font-size-base
      // skaliert die ganze App proportional.
      fontSize: {
        xs: "var(--font-size-xs)",
        sm: "var(--font-size-sm)",
        base: "var(--font-size-base)",
        lg: "var(--font-size-lg)",
        xl: "var(--font-size-xl)",
        "2xl": "var(--font-size-2xl)",
        "3xl": "var(--font-size-3xl)",
      },
      colors: {
        // Brand: Rosé
        primary: {
          DEFAULT: "var(--color-primary)",
          hover: "var(--color-primary-hover)",
          active: "var(--color-primary-active)",
          soft: "var(--color-primary-soft)",
          "on-primary": "var(--color-on-primary)",
        },
        // Text — nested, damit `text-text-primary` semantisch klar ist.
        text: {
          primary: "var(--color-text-primary)",
          secondary: "var(--color-text-secondary)",
          tertiary: "var(--color-text-tertiary)",
          inverse: "var(--color-text-inverse)",
        },
        // Surfaces — flach, damit `bg-surface`, `bg-surface-alt` direkt greifen.
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        "surface-alt": "var(--color-surface-alt)",
        overlay: "var(--color-overlay)",
        // Borders — flach, damit `border-border`, `border-border-strong` greifen.
        border: "var(--color-border)",
        "border-strong": "var(--color-border-strong)",
        "border-focus": "var(--color-border-focus)",
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
      maxWidth: {
        content: "var(--layout-content-max)",
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
