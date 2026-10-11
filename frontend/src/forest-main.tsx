// Standalone page for WS-A's 3D forest app (frontend/src/simulation/App.tsx), shown in the
// command center through an iframe so its page-wide CSS never touches the dashboard.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App as ForestApp } from "./simulation/App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ForestApp />
  </StrictMode>,
);
