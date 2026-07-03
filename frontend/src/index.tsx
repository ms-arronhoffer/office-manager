import React from 'react';
import ReactDOM from 'react-dom/client';
import '@cloudscape-design/global-styles/index.css';
import App from './App';
import { registerServiceWorker } from './serviceWorkerRegistration';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

registerServiceWorker();
