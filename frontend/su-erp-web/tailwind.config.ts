import type { Config } from "tailwindcss";

// Colors are wired to CSS variables (see globals.css) so a single set of
// utilities serves both light and dark themes. Distinctiveness lives in the
// palette + layout, not in exotic fonts — the font stacks are system-only.

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        line: "var(--border)",
        primary: {
          DEFAULT: "var(--primary)",
          hover: "var(--primary-hover)",
          fg: "var(--primary-fg)",
        },
        gold: "var(--accent-gold)",
        success: "var(--success)",
        warn: "var(--warn)",
        danger: "var(--danger)",
      },
      borderColor: {
        DEFAULT: "var(--border)",
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        md: "6px",
      },
      boxShadow: {
        subtle: "0 1px 2px rgba(0, 0, 0, 0.04)",
        card: "0 1px 2px rgba(0, 0, 0, 0.04)",
      },
      fontSize: {
        eyebrow: ["11px", { lineHeight: "1", letterSpacing: "0.08em" }],
        data: ["13px", { lineHeight: "1.45" }],
      },
    },
  },
  plugins: [],
};
export default config;
