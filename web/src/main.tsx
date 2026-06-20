import React from 'react';
import ReactDOM from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';
import App from './App';
import './styles/theme.css';

// PWA update reliability (v10.32): registerType is 'autoUpdate', but an open
// home-screen PWA never re-checks the service worker on its own — so a new
// deploy stays invisible until the app is fully quit ("10.30から変わらない").
// Poll for a new SW every 60s while the app is open; autoUpdate then installs
// + reloads it automatically.
registerSW({
  immediate: true,
  onRegisteredSW(_url, r) {
    if (r) setInterval(() => { r.update().catch(() => {}); }, 60_000);
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
