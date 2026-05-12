/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0b0b0e",
          soft: "#15151b",
          card: "#1c1c24",
          input: "#2a2a35",
        },
        brand: {
          DEFAULT: "#ffa724",
          50: "#fff6e5",
          100: "#ffe6b8",
          200: "#ffd07a",
          300: "#ffba3d",
          400: "#ffa724",
          500: "#f29100",
          600: "#cc7700",
          700: "#a35e00",
          800: "#7a4500",
          900: "#522e00",
        },
        success: "#22c55e",
        danger: "#ef4444",
      },
      boxShadow: {
        glow: "0 0 40px -10px rgba(255, 167, 36, 0.7)",
        card: "0 14px 60px -30px rgba(255, 167, 36, 0.25)",
      },
      backgroundImage: {
        grid:
          "linear-gradient(to right, rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.04) 1px, transparent 1px)",
      },
      fontFamily: {
        display: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        glow: {
          "0%,100%": { boxShadow: "0 0 30px -10px rgba(255,167,36,0.4)" },
          "50%": { boxShadow: "0 0 50px -10px rgba(255,167,36,0.8)" },
        },
        pop: {
          "0%": { transform: "scale(0.96)", opacity: "0" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
      },
      animation: {
        shimmer: "shimmer 2.4s linear infinite",
        glow: "glow 2.6s ease-in-out infinite",
        pop: "pop 0.18s ease-out",
      },
    },
  },
  plugins: [],
};
