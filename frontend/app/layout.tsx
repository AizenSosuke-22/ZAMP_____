import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AP Workbench",
  description: "Invoice processing: upload, watch the checks run, read the decision.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-IN" className="h-full">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
