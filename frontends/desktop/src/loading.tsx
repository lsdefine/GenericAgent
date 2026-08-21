import './platform';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './loading/bootstrap.css';
import { LoadingApp } from './loading/App';

const container = document.getElementById('loading-root');
if (container) {
  createRoot(container).render(
    <StrictMode>
      <LoadingApp />
    </StrictMode>
  );
}
