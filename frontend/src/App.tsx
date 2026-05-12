import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";

import BottomNav from "@/components/BottomNav";
import { useUser } from "@/store";

import Home from "@/pages/Home";
import Deals from "@/pages/Deals";
import DealDetail from "@/pages/DealDetail";
import CreateDeal from "@/pages/CreateDeal";
import Balance from "@/pages/Balance";
import Profile from "@/pages/Profile";
import AdminLayout from "@/pages/admin/AdminLayout";
import AdminDashboard from "@/pages/admin/Dashboard";
import AdminUsers from "@/pages/admin/Users";
import AdminDeals from "@/pages/admin/Deals";
import AdminSettings from "@/pages/admin/Settings";

function ErrorView({ message }: { message: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <div className="text-5xl">⚠️</div>
      <div className="text-xl font-semibold">Не удалось подключиться</div>
      <div className="max-w-sm text-sm text-white/60">{message}</div>
    </div>
  );
}

function Loading() {
  return (
    <div className="flex h-full items-center justify-center">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
        className="h-12 w-12 rounded-full border-2 border-brand/30 border-t-brand"
      />
    </div>
  );
}

export default function App() {
  const { user, loading, error, refresh } = useUser();

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading && !user) return <Loading />;
  if (error && !user) return <ErrorView message={error} />;
  if (!user) return <Loading />;

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col pb-28">
      <AnimatePresence mode="wait">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/deals" element={<Deals />} />
          <Route path="/deals/new" element={<CreateDeal />} />
          <Route path="/deals/:id" element={<DealDetail />} />
          <Route path="/balance" element={<Balance />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/search" element={<Home initialTab="search" />} />
          <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
          <Route path="/admin/*" element={<AdminLayout />}>
            <Route path="dashboard" element={<AdminDashboard />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="deals" element={<AdminDeals />} />
            <Route path="settings" element={<AdminSettings />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AnimatePresence>
      <BottomNav />
    </div>
  );
}
