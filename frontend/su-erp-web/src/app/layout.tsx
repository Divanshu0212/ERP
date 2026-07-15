import type { Metadata } from "next";
import "./globals.css";
import { THEME_INIT_SCRIPT, ThemeProvider } from "@/lib/theme";

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
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Blocking: sets data-theme before first paint so there's no flash. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-canvas text-ink antialiased" suppressHydrationWarning>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
