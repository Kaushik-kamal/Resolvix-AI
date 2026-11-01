import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { AppLayout } from "./layout/AppLayout";
import LiveBoardPage from "./pages/live/LiveBoardPage";
import LoginPage from "./pages/login/LoginPage";
import NotFoundPage from "./pages/NotFoundPage";

// Page agents own these folders. The router only lazy-imports "./pages/<name>/index" (default export = the page).
const TicketsPage = lazy(() => import("./pages/tickets/index"));
const CallsPage = lazy(() => import("./pages/calls/index"));
const GapsPage = lazy(() => import("./pages/gaps/index"));
const KbPage = lazy(() => import("./pages/kb/index"));
const RulesPage = lazy(() => import("./pages/rules/index"));

/**
 * Route table. Page routes end in /* so a page may add its own nested <Routes> or read the splat
 * (useParams()["*"]); query-string deep links such as /tickets?ticket=EX-1001 work either way.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<LiveBoardPage />} />
        <Route path="tickets/*" element={<TicketsPage />} />
        <Route path="calls/*" element={<CallsPage />} />
        <Route path="gaps/*" element={<GapsPage />} />
        <Route path="kb/*" element={<KbPage />} />
        <Route path="rules/*" element={<RulesPage />} />
        <Route path="live" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
