import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api";
import { AuthProvider, RequireAuth } from "@/auth/AuthProvider";
import { Layout } from "@/components/layout/Layout";
import { ToastProvider } from "@/components/ui/Toast";
import { AlertsPage } from "@/pages/account/AlertsPage";
import { HistoryPage } from "@/pages/account/HistoryPage";
import { WishlistPage } from "@/pages/account/WishlistPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ProductPage } from "@/pages/ProductPage";
import { SearchPage } from "@/pages/SearchPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Don't retry client errors (404, 401, 422…); retry transient ones once.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 1,
    },
  },
});

const router = createBrowserRouter([
  {
    element: (
      <AuthProvider>
        <Layout />
      </AuthProvider>
    ),
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/products/:id", element: <ProductPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/wishlist", element: <RequireAuth><WishlistPage /></RequireAuth> },
      { path: "/alerts", element: <RequireAuth><AlertsPage /></RequireAuth> },
      { path: "/history", element: <RequireAuth><HistoryPage /></RequireAuth> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
