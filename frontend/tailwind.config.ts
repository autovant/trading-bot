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
                background: "#050505",
                foreground: "#e0e0e0",
                card: {
                    DEFAULT: "#0a0a0a",
                    border: "#1f1f1f",
                    hover: "#141414",
                },
                brand: {
                    DEFAULT: "#0066FF", // Blue from the image
                    hover: "#0052cc",
                    glow: "rgba(0, 102, 255, 0.5)",
                },
                accent: {
                    cyan: "#00ff9d",
                    purple: "#9d00ff",
                },
                trade: {
                    long: "#00C853", // Green
                    short: "#FF3D00", // Red
                    neutral: "#B0BEC5",
                },
                gray: {
                    850: "#1a1a1a",
                    900: "#121212",
                    950: "#080808",
                }
            },
            fontFamily: {
                sans: ['Inter', 'sans-serif'],
                mono: ['JetBrains Mono', 'monospace'],
            },
            animation: {
                'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            }
        },
    },
    plugins: [],
} satisfies Config;
