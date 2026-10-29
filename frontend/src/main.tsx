import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@fontsource-variable/noto-sans-sc';
import { App } from './app/App';
import './styles/globals.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
