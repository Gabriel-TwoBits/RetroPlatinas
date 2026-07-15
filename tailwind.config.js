/** @type {import('tailwindcss').Config} */
// Design tokens from the "Platina Quente" system (see DESIGN.md). Spacing and type
// use Tailwind's default 4px scale; only the brand-specific axes are extended here.
module.exports = {
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html"],
  // State colours are composed from data (state='beaten' -> text-state-beaten),
  // so their utilities can't be found by scanning the markup. Keep them all.
  safelist: [
    { pattern: /(bg|text|border)-state-(locked|beaten|platinum|hardcore|softcore|progress)/ },
  ],
  theme: {
    extend: {
      colors: {
        bg: "#100d09",
        surface: "#181510",
        surface2: "#1e1a13",
        elevated: "#252017",
        line: "#302a20",
        line2: "#463d2e",
        txt: {
          DEFAULT: "#ece5d6",
          muted: "#a89d87",
          faint: "#6d6353",
        },
        brand: {
          DEFAULT: "#6a67e0",
          dim: "#35356f",
          ink: "#f2f3ff",
        },
        brand2: "#ef7f2b",
        gold: {
          DEFAULT: "#f0c04a",
          dim: "#8a6a2c",
        },
        state: {
          locked: "#3a342a",
          beaten: "#93aa4e",
          platinum: "#c2c9d8",
          hardcore: "#e0552f",
          softcore: "#7e93b1",
          progress: "#d8922f",
        },
      },
      fontFamily: {
        display: ["'Arial Narrow'", "'Roboto Condensed'", "Arial", "sans-serif"],
        sans: ["Arial", "Helvetica", "sans-serif"],
        mono: ["'Courier New'", "Courier", "monospace"],
      },
      borderRadius: {
        card: "0.75rem",
        tile: "0.625rem",
      },
      gridTemplateColumns: {
        // Desktop achievement grid: one row of 20 icon cells.
        20: "repeat(20, minmax(0, 1fr))",
      },
      keyframes: {
        "rp-shimmer": {
          "0%": { backgroundPosition: "-120% 0" },
          "100%": { backgroundPosition: "220% 0" },
        },
        "rp-glow": {
          "0%, 100%": { boxShadow: "0 0 0 1px #c2c9d8, 0 0 12px -2px #c2c9d8" },
          "50%": { boxShadow: "0 0 0 1px #c2c9d8, 0 0 22px 1px #c2c9d8" },
        },
      },
      animation: {
        "rp-shimmer": "rp-shimmer 3.2s linear infinite",
        "rp-glow": "rp-glow 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
