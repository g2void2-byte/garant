import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        panel: "var(--panel)",
        "panel-2": "var(--panel-2)",
        secondary: "var(--secondary)",
        border: "var(--border)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",
        text: "var(--text)",
        "text-muted": "var(--text-muted)",
        "text-disabled": "var(--text-disabled)",
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
        button: "8px",
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
        "fade-in-down": {
          "0%": { opacity: "0", transform: "translateY(-6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in-scale": {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        "fade-in-logo": {
          "0%": { opacity: "0", transform: "scale(0.9)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        "slide-up": {
          "0%": { transform: "translateY(100%)" },
          "100%": { transform: "translateY(0)" },
        },
        "slide-down-banner": {
          "0%": { opacity: "0", transform: "translateY(-40px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pop-dot": {
          "0%": { transform: "scale(1.4)" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        breathe: "breathe 3s ease-in-out infinite",
        fadein: "fadein .25s ease-out both",
        "fade-in-down": "fade-in-down .2s ease-out both",
        "fade-in-scale": "fade-in-scale .2s ease-out both",
        "fade-in-logo": "fade-in-logo .3s ease-out both",
        "slide-up": "slide-up .3s cubic-bezier(.2,.8,.4,1) both",
        "slide-down-banner": "slide-down-banner .3s cubic-bezier(.2,.8,.4,1) both",
        "pop-dot": "pop-dot .18s ease-out",
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
