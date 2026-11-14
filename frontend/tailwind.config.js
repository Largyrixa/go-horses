import defaultTheme from "tailwindcss/defaultTheme";

/** Paleta herdada do secomp-web-xiv, com tons extras para estados de leilão. */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    colors: {
      current: "currentColor",
      transparent: "transparent",
      white: "#FFFFFF",
      black: "#0B0B0F",       // fundo
      surface: "#14141B",     // painéis
      edge: "#2A2A36",        // bordas discretas
      textColor: "#F2F0E8",
      gray: "#A0A0A0",
      primary: "#00FF66",     // verde: ação / em andamento
      secondary: "#1400FF",
      soft: "#7C8CFF",        // azul legível sobre preto: agendado
      danger: "#FF4D5E",      // cancelado / erro
    },
    screens: { xsm: "425px", ...defaultTheme.screens },
    extend: {
      fontFamily: {
        sans: ['"Glacial Indifference"', ...defaultTheme.fontFamily.sans],
        mono: ['"Roboto Mono"', ...defaultTheme.fontFamily.mono],
        display: ['"Big Shoulders Display"', ...defaultTheme.fontFamily.sans],
      },
    },
  },
  plugins: [],
};
