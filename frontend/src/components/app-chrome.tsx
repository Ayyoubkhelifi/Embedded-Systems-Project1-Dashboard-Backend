"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/auth";
import { Nav } from "./nav";

/** Hides the nav bar on the login screen until we know the user state. */
export function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, loading } = useAuth();
  const isLogin = pathname === "/login";
  const showNav = !isLogin && (loading || user !== null);
  return (
    <>
      {showNav && <Nav />}
      <main>{children}</main>
    </>
  );
}
