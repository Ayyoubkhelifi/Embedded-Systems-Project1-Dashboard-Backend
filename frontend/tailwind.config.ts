import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        subtle: "var(--border-subtle)",
        fg: "var(--text-primary)",
        muted: "var(--text-secondary)",
        accent: "var(--accent)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        crit: "var(--crit)",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Cascadia Mono", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
