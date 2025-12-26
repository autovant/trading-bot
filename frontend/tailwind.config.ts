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
                background: "#020408", // Void Black
                foreground: "#E7ECF5",
                card: {
                    DEFAULT: "rgba(11, 16, 32, 0.7)",
                    border: "rgba(255, 255, 255, 0.08)",
                    hover: "rgba(255, 255, 255, 0.05)",
                },
                brand: {
                    DEFAULT: "#00FF9D", // Neon Mint
                    hover: "#00CC7D",
                    glow: "rgba(0, 255, 157, 0.4)",
                    secondary: "#00E0FF", // Neon Cyan
                },
                accent: {
                    cyan: "#00E0FF",
                    amber: "#FFB02E",
                    purple: "#9D00FF",
                    pink: "#FF007A"
                },
                trade: {
                    long: "#00FF9D",
                    short: "#FF3B30",
                    neutral: "#64748B",
                },
                gray: {
                    750: "#2D3748",
                    800: "#1A202C",
                    850: "#141927",
                    900: "#0E1320",
                    950: "#05070A",
                }
            },
            fontFamily: {
                sans: ['var(--font-sans)', 'Space Grotesk', 'Inter', 'system-ui', 'sans-serif'],
                mono: ['var(--font-mono)', 'JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
            },
            animation: {
                'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
                'glow': 'glow 3s ease-in-out infinite alternate',
                'slide-in': 'slide-in 0.3s ease-out',
            },
            keyframes: {
                glow: {
                    '0%': { boxShadow: '0 0 5px rgba(0, 255, 157, 0.1)' },
                    '100%': { boxShadow: '0 0 20px rgba(0, 255, 157, 0.4)' },
                },
                'slide-in': {
                    '0%': { transform: 'translateY(10px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                }
            }
        },
    },
    plugins: [],
} satisfies Config;
