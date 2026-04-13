/**@type {Import('tailwindcss').Config} */
module.exports = {
    content: [
        "./app/**/*.{js,ts,jsx,tsx,mdx}",
        "./components/**/*.{js,ts,jsx,tsx,mdx}",
        "./lib/**/*.{js,ts,jsx,tsx,mdx}",

    ],
    theme: {
        extend: {
            colors: {
                brand: {
                    50: "#f0fdf4ff",
                    100: "#dcfce7ff",
                    500: "rgb(127, 232, 165)",
                    600: "rgb(152, 218, 176)",
                    700: "#88d6a592",
                    900: "#156033"

                },
            },
            fontFamily: {
                sans: ["Inter", "system-ui", "sans-serif"],
                mono: ["JetBrains Mono", "monospace"],
            },
        },
    },
    plugins: [],
};