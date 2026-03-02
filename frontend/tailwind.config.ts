import type { Config } from "tailwindcss";

export default {
    content: [
        "./pages/**/*.{js,ts,jsx,tsx,mdx}",
        "./components/**/*.{js,ts,jsx,tsx,mdx}",
        "./app/**/*.{js,ts,jsx,tsx,mdx}",
    ],
    theme: {
        extend: {
            colors: {
                background: {
                    DEFAULT: "var(--background)",
                    primary: "var(--background)",
                    secondary: "#1C1C1E",
                    elevated: "#2C2C2E",
                },
                foreground: "var(--foreground)",
                text: {
                    primary: "#F5F5F7",
                    secondary: "#A1A1A6",
                    tertiary: "#6C6C70",
                },
                card: {
                    DEFAULT: "var(--card-bg)",
                    border: "var(--card-border)",
                    hover: "var(--card-hover)",
                },
                brand: {
                    DEFAULT: "var(--accent-primary)", // Apple Green
                    hover: "#30D158",
                    secondary: "var(--accent-secondary)", // Apple Blue
                },
                accent: {
                    primary: "var(--accent-primary)",
                    cyan: "var(--accent-secondary)",
                    danger: "var(--accent-danger)",
                    warning: "var(--accent-warning)",
                    success: "var(--accent-primary)",
                },
                trade: {
                    long: "var(--accent-primary)",
                    short: "var(--accent-danger)",
                    neutral: "#86868B", // Apple neutral gray
                },
                gray: {
                    50: "#F9FAFB",
                    100: "#F3F4F6",
                    200: "#E5E7EB",
                    300: "#D1D5DB",
                    400: "#9CA3AF",
                    500: "#6B7280",
                    600: "#4B5563",
                    700: "#374151",
                    750: "#2C2C2E",
                    800: "#1F2937",
                    850: "#1C1C1E",
                    900: "#111827",
                    950: "#0A0A0A",
                }
            },
            fontFamily: {
                sans: ['Inter', 'SF Pro Display', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
                mono: ['SF Mono', 'JetBrains Mono', 'ui-monospace', 'monospace'],
            },
            animation: {
                'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
                'pulse-subtle': 'pulse-subtle 3s ease-in-out infinite',
                'fade-in': 'fade-in 0.3s ease-out',
                'slide-up': 'slide-up 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
            },
            keyframes: {
                'fade-in': {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
                'slide-up': {
                    '0%': { transform: 'translateY(10px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                }
            }
        },
    },
    plugins: [],
} satisfies Config;
