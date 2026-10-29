import "./i18n";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { persist } from "./offline/cache";
import * as queue from "./offline/queue";
import { finishPendingSignOut, SessionProvider } from "./session";

const queryClient = new QueryClient({
  // offlineFirst: screens show what the device holds and try the network when they can (FR-PW3).
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, networkMode: "offlineFirst" } },
});

async function start(): Promise<void> {
  await finishPendingSignOut();
  await persist(queryClient);
  // Whenever queued work reaches the server, refresh what is on screen.
  await queue.load(() => void queryClient.invalidateQueries());
  void queue.sync();
  window.addEventListener("online", () => void queue.sync());
  window.setInterval(() => navigator.onLine && void queue.sync(), 30_000);
}

void start().finally(() => createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SessionProvider>
          <App />
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
));

// Installable app shell (FR-PW1). Development builds skip it so changes show at once.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
  });
}
