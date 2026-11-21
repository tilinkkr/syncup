/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "Consolas", "monospace"],
      },
      keyframes: {
        rise: { "0%": { opacity: "0", transform: "translateY(10px)" }, "100%": { opacity: "1", transform: "none" } },
        flash: { "0%": { backgroundColor: "rgba(244,63,94,0.35)" }, "100%": { backgroundColor: "transparent" } },
        laser: { "0%": { top: "4%" }, "50%": { top: "92%" }, "100%": { top: "4%" } },
        radar: { "0%": { transform: "scale(0.7)", opacity: "0.75" }, "100%": { transform: "scale(2.1)", opacity: "0" } },
        eq: { "0%,100%": { transform: "scaleY(0.25)" }, "50%": { transform: "scaleY(1)" } },
      },
      animation: {
        rise: "rise 420ms cubic-bezier(.2,.8,.2,1) both",
        flash: "flash 1.6s ease-out",
        laser: "laser 0.6s ease-in-out",
        radar: "radar 2.2s ease-out infinite",
        eq: "eq 0.9s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
