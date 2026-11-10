import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiError } from "./api/client";
import { ToastHost } from "./ds/ai";
import { router } from "./router";
import { UiProvider } from "./state/ui";

// A dropped connection or a restarting server (a deploy) is tried again twice; a refusal is not.
const transient = (failures: number, error: unknown) =>
  failures < 2 && error instanceof ApiError && (error.status === 0 || error.status >= 500);
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: transient } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <UiProvider>
        <RouterProvider router={router} />
        <ToastHost />
      </UiProvider>
    </QueryClientProvider>
  </StrictMode>,
);
