import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/source-serif-4";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import App from "./App";
import { applyTheme, useTheme } from "./lib/theme";
import "./index.css";

const container = document.getElementById("root");

if (!container) {
  throw new Error("Root element #root was not found in index.html");
}

applyTheme(useTheme.getState().theme);

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);
