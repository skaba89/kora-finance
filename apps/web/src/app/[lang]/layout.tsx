import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import { lang } from "next/root-params";

import { ServiceWorkerRegistrar } from "@/components/service-worker";
import { LOCALES } from "@/lib/i18n/config";

import "../globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Kora Finance", template: "%s · Kora Finance" },
  description: "Gestion financière et comptable pour les PME guinéennes",
  applicationName: "Kora Finance",
  appleWebApp: { capable: true, title: "Kora Finance", statusBarStyle: "default" },
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: "#0f766e",
  width: "device-width",
  initialScale: 1,
};

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ lang: locale }));
}

export default async function RootLayout({ children }: LayoutProps<"/[lang]">) {
  return (
    <html lang={await lang()} className={`${geistSans.variable} h-full antialiased`}>
      <body className="bg-background text-foreground flex min-h-full flex-col">
        {children}
        <ServiceWorkerRegistrar />
      </body>
    </html>
  );
}
