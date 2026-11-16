import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Izuire Shop – Worldwide Online Shopping",
  description:
    "House Of Tife Collection — fashion, beauty, household, electronics and more. Local & abroad shipping.",
  icons: {
    icon: "/assets/mark-hotc-orange.svg",
    apple: "/assets/mark-hotc-orange.svg",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <head>
        <link rel="stylesheet" href="/assets/fonts-local.css" />
        <link rel="stylesheet" href="/assets/app-CXc2UZze.css" />
      </head>
      <body>{children}</body>
    </html>
  );
}
