import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";
import { isApiError } from "./api/client";
import { AuthProvider } from "./auth/AuthContext";
import { AppRoutes } from "./routes";

/** Shared QueryClient defaults: do not retry 4xx, keep data fresh for 10 s, no refetch on window focus (SSE does it). */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => !(isApiError(error) && error.status >= 400 && error.status < 500) && failureCount < 2,
      },
    },
  });
}

/** Providers shared by the app and by tests (tests pass their own QueryClient and router). */
export function AppProviders({ client, children }: { client?: QueryClient; children: ReactNode }) {
  const [fallback] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client ?? fallback}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppProviders>
        <AppRoutes />
      </AppProviders>
    </BrowserRouter>
  );
}
