import type { Config } from "tailwindcss";

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
      fontSize: {
        xs: "var(--font-size-xs)",
        sm: "var(--font-size-sm)",
        base: "var(--font-size-base)",
        lg: "var(--font-size-lg)",
        xl: "var(--font-size-xl)",
        "2xl": "var(--font-size-2xl)",
        "3xl": "var(--font-size-3xl)",
        "4xl": "var(--font-size-4xl)",
      },
      colors: {
        primary: {
          DEFAULT: "var(--color-primary)",
          hover: "var(--color-primary-hover)",
          active: "var(--color-primary-active)",
          soft: "var(--color-primary-soft)",
          "on-primary": "var(--color-on-primary)",
        },
        add: {
          DEFAULT: "var(--color-add)",
          hover: "var(--color-add-hover)",
          "on-add": "var(--color-on-add)",
        },
        "on-primary": "var(--color-on-primary)",
        "on-add": "var(--color-on-add)",
        text: {
          primary: "var(--color-text-primary)",
          secondary: "var(--color-text-secondary)",
          tertiary: "var(--color-text-tertiary)",
          inverse: "var(--color-text-inverse)",
        },
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        "surface-alt": "var(--color-surface-alt)",
        overlay: "var(--color-overlay)",
        border: "var(--color-border)",
        "border-strong": "var(--color-border-strong)",
        "border-focus": "var(--color-border-focus)",
        success: {
          DEFAULT: "var(--color-success)",
          soft: "var(--color-success-soft)",
        },
        warning: {
          DEFAULT: "var(--color-warning)",
          soft: "var(--color-warning-soft)",
        },
        error: {
          DEFAULT: "var(--color-error)",
          soft: "var(--color-error-soft)",
        },
        danger: {
          DEFAULT: "var(--color-danger)",
          soft: "var(--color-danger-soft)",
        },
        info: {
          DEFAULT: "var(--color-info)",
          soft: "var(--color-info-soft)",
        },
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