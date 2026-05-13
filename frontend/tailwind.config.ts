import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        panel: "var(--panel)",
        "panel-2": "var(--panel-2)",
        border: "var(--border)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",
        text: "var(--text)",
        "text-muted": "var(--text-muted)",
        success: "var(--success)",
        danger: "var(--danger)",
        warning: "var(--warning)",
      },
      fontFamily: {
        sans: [
          "'TT Hoves'",
          "var(--tg-theme-font-family, -apple-system)",
          "system-ui",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        pop: "0 8px 30px rgba(0,0,0,.35)",
        glow: "0 0 30px rgba(254,230,0,0.18)",
        navbar: "0 4px 42px rgba(5,5,5,.5)",
      },
      borderRadius: {
        card: "14px",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200px 0" },
          "100%": { backgroundPosition: "200px 0" },
        },
        breathe: {
          "0%,100%": { opacity: "0.85", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.02)" },
        },
        fadein: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        breathe: "breathe 3s ease-in-out infinite",
        fadein: "fadein .25s ease-out both",
      },
      maxWidth: {
        app: "500px",
      },
      height: {
        navbar: "62px",
      },
    },
  },
  plugins: [],
} satisfies Config;
