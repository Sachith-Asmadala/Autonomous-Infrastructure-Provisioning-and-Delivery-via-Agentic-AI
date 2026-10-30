import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { applyInitialTheme } from "@/store/themeStore";
import { setNonce } from "get-nonce";

const styleNonce = document.querySelector<HTMLMetaElement>('meta[name="csp-nonce"]')?.content;
if (styleNonce && styleNonce !== "__CSP_NONCE__") setNonce(styleNonce);

applyInitialTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
