/** @type {import('tailwindcss').Config} */
// Design tokens from the "Teal Platina" system (see DESIGN.md). Spacing and type
// use Tailwind's default 4px scale; only the brand-specific axes are extended here.
module.exports = {
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html"],
  // State and award colours are composed from data (state='beaten' ->
  // text-state-beaten), so their utilities can't be found by scanning the markup.
  safelist: [
    { pattern: /(bg|text|border)-state-(locked|beaten|platinum|hardcore|softcore|progress)/ },
    { pattern: /(text|bg)-(brand|gold)/ },
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e13",
        surface: "#171c25",
        surface2: "#1e2531",
        elevated: "#27303d",
        line: "#29313d",
        line2: "#3b4657",
        txt: {
          DEFAULT: "#e6ecf3",
          muted: "#97a4b5",
          faint: "#5f6b7c",
        },
        brand: {
          DEFAULT: "#34dcc4",
          dim: "#1c5e56",
          ink: "#06201b",
          hi: "#7fe9db",
        },
        brand2: "#b09cff",
        gold: {
          DEFAULT: "#f2b84b",
          dim: "#8a6a2c",
          deep: "#c98d2e",
        },
        state: {
          locked: "#313b49",
          beaten: "#5cc48c",
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
        // Three tiers, from the rendered design mockup: containers, inner tiles,
        // then chips and bars. The mockup's 5px and 6px tiers both land on "chip".
        card: "0.1875rem",
        tile: "0.25rem",
        chip: "0.375rem",
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
        "rp-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: ".4" },
        },
      },
      animation: {
        "rp-shimmer": "rp-shimmer 3.2s linear infinite",
        "rp-pulse": "rp-pulse 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
