import { useEffect } from "react";
import IconButton from "@mui/material/IconButton";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import { useColorScheme } from "@mui/material/styles";

export function ThemeToggle() {
  const { mode, setMode } = useColorScheme();
  const dark = mode === "dark";

  useEffect(() => {
    if (mode === "system") {
      setMode("light");
    }
  }, [mode, setMode]);

  return (
    <IconButton
      color="inherit"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setMode(dark ? "light" : "dark")}
    >
      {dark ? <LightModeIcon /> : <DarkModeIcon />}
    </IconButton>
  );
}
