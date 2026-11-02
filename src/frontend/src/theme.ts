import { createTheme } from "@mui/material/styles";

declare module "@mui/material/styles" {
  interface Palette {
    brand: Palette["primary"];
  }
  interface PaletteOptions {
    brand?: PaletteOptions["primary"];
  }
}

export const theme = createTheme({
  cssVariables: {
    colorSchemeSelector: "data",
  },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "#0B3A5B" },
        secondary: { main: "#1F7A4D" },
        background: { default: "#F4F7FA", paper: "#FFFFFF" },
        brand: { main: "#0B3A5B", contrastText: "#FFFFFF" },
      },
    },
    dark: {
      palette: {
        primary: { main: "#8EC5E8" },
        secondary: { main: "#7DCEA0" },
        background: { default: "#0E141B", paper: "#17202A" },
        brand: { main: "#0B3A5B", contrastText: "#FFFFFF" },
      },
    },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: "Roboto, sans-serif",
  },
});
