import type { Metadata } from "next";
import "./globals.css";

// System font stacks only — the app is built and shipped offline, so no
// next/font/google or remote font fetches. The stack is defined in globals.css
// and Tailwind's theme.

export const metadata: Metadata = {
  title: "SU-ERP",
  description: "Institutional ERP for student, hostel, finance and grievance operations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-canvas text-ink antialiased">{children}</body>
    </html>
  );
}
