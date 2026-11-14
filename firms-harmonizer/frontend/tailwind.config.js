/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0A0D13",
        surface: "#11151C",
        surface2: "#171C25",
        line: "rgba(255,255,255,0.08)",
        ink: "#E8EBF0",
        dim: "#98A1B0",
        ember: "#FF6B3D",
        heat: "#FFB454",
        info: "#5AA7E0",
        danger: "#E5484D",
        success: "#2FA97A",
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        panel:
          "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 24px 60px -24px rgba(0,0,0,0.85)",
        float: "0 18px 50px -18px rgba(0,0,0,0.9)",
      },
      letterSpacing: {
        tightest: "-0.03em",
      },
    },
  },
  plugins: [],
};
