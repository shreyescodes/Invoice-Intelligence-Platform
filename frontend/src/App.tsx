import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { type ReactNode } from "react";
import { createBrowserRouter, Link, Navigate, RouterProvider, useLocation } from "react-router-dom";
import { Toaster } from "sonner";

import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/ui/Feedback";
import { ApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { useAuth } from "@/lib/auth-context";
import { useTheme } from "@/lib/theme";
import { LoginPage } from "@/pages/LoginPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, lastSignOut } = useAuth();
  const location = useLocation();
  if (!user) {
    // Come back to the same page after re-authenticating, but not after an explicit sign-out.
    const state = lastSignOut === "user" ? null : { from: location.pathname + location.search };
    return <Navigate to="/login" replace state={state} />;
  }
  return children;
}

function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      action={
        <Link to="/" className="text-[13px] font-medium text-accent-ink hover:underline">
          Back to overview
        </Link>
      }
    >
      The page you were looking for doesn't exist.
    </EmptyState>
  );
}

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      // Each page is its own chunk; charts only load on the pages that draw them.
      { index: true, lazy: async () => ({ Component: (await import("@/pages/OverviewPage")).OverviewPage }) },
      { path: "invoices", lazy: async () => ({ Component: (await import("@/pages/InvoicesPage")).InvoicesPage }) },
      {
        path: "invoices/:id",
        lazy: async () => ({ Component: (await import("@/pages/InvoiceDetailPage")).InvoiceDetailPage }),
      },
      { path: "review", lazy: async () => ({ Component: (await import("@/pages/ReviewQueuePage")).ReviewQueuePage }) },
      { path: "vendors", lazy: async () => ({ Component: (await import("@/pages/VendorsPage")).VendorsPage }) },
      { path: "ask", lazy: async () => ({ Component: (await import("@/pages/AskPage")).AskPage }) },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

function ThemedToaster() {
  const [theme] = useTheme();
  return <Toaster theme={theme} position="bottom-right" richColors closeButton />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
        <ThemedToaster />
      </AuthProvider>
    </QueryClientProvider>
  );
}
