import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/auth";
import { AppChrome } from "@/components/app-chrome";

export const metadata: Metadata = {
  title: "ESS Monitor",
  description: "Environmental sensing system — LoRa telemetry, alerts and fleet status",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-fg font-sans">
        <AuthProvider>
          <AppChrome>{children}</AppChrome>
        </AuthProvider>
      </body>
    </html>
  );
}
