/** @type {import('tailwindcss').Config} */
// Design tokens from the "Platina Fria" system (see DESIGN.md). Spacing and type
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
        bg: "#0b0e13",
        surface: "#12161d",
        surface2: "#171c25",
        elevated: "#1e242f",
        line: "#262d39",
        line2: "#39434f",
        txt: {
          DEFAULT: "#e8ebf1",
          muted: "#98a2b3",
          faint: "#5c6675",
        },
        brand: {
          DEFAULT: "#34dcc4",
          dim: "#1c8f80",
          ink: "#05221e",
        },
        gold: "#f2b84b",
        state: {
          locked: "#3a434f",
          beaten: "#48c78e",
          platinum: "#b09cff",
          hardcore: "#ff6b57",
          softcore: "#8aa4c8",
          progress: "#eab04d",
        },
      },
      fontFamily: {
        display: ["Tahoma", "Verdana", "Geneva", "sans-serif"],
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
          "0%, 100%": { boxShadow: "0 0 0 1px #b09cff, 0 0 12px -2px #b09cff" },
          "50%": { boxShadow: "0 0 0 1px #b09cff, 0 0 22px 1px #b09cff" },
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
