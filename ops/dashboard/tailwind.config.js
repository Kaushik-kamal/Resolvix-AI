/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Resolvix palette (PRD section 6)
        header: "#5E4330",
        bg: "#F4EFEA",
        accent: { DEFAULT: "#7A5A40", sand: "#CBA982", amber: "#A97B49", slate: "#6F8592", graphite: "#525A63" },
        p1: "#B5603F",
        p2: "#A97B49",
        p3: "#6F8592",
        p4: "#9CA9B1",
        ink: { DEFAULT: "#2F2620", soft: "#5B5047", faint: "#8A7F75" },
        line: "#E1D7CC",
        surface: "#FFFFFF",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "-apple-system", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "ui-monospace", "monospace"],
      },
      keyframes: {
        flash: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(181,96,63,0)", backgroundColor: "#FFFFFF" },
          "25%, 75%": { boxShadow: "0 0 0 3px rgba(181,96,63,0.65)", backgroundColor: "#FBE6DD" },
        },
        slidein: { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        fadein: { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        flash: "flash 1.2s ease-in-out 5",
        slidein: "slidein 160ms ease-out",
        fadein: "fadein 120ms ease-out",
      },
    },
  },
  plugins: [],
};
