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
        },
        // Wordmark gradient stops: identity art, the one gradient the UI keeps.
        wordmark: {
          hi: "#f2f5fa",
          lo: "#aab8cd",
        },
        state: {
          locked: "#313b49",
          beaten: "#5cc48c",
          platinum: "#c2c9d8",
          hardcore: "#e0552f",
          softcore: "#7e93b1",
          progress: "#d8922f",
        },
        danger: "#e0552f",
      },
      fontFamily: {
        // Self-hosted from static/fonts (OFL); see the @font-face rules in input.css.
        display: ["Oxanium", "Arial", "sans-serif"],
        sans: ["'Atkinson Hyperlegible Next'", "Arial", "Helvetica", "sans-serif"],
        // Tabular figures so points, ranks and counts line up in columns.
        data: [["Oxanium", "Arial", "sans-serif"], { fontFeatureSettings: '"tnum"' }],
      },
      width: {
        // Accent strip on the left of a section heading.
        strip: "0.1875rem",
      },
      borderRadius: {
        card: "0.1875rem",
        tile: "0.25rem",
        chip: "0.375rem",
      },
      gridTemplateColumns: {
        // Desktop achievement grid: 20 icon cells per row.
        20: "repeat(20, minmax(0, 1fr))",
      },
      keyframes: {
        "rp-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: ".4" },
        },
      },
      animation: {
        "rp-pulse": "rp-pulse 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
