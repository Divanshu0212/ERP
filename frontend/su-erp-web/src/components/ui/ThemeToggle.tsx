"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/cn";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      aria-pressed={isDark}
      className={cn(
        "relative inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        className,
      )}
    >
      <Sun
        aria-hidden
        className={cn(
          "absolute h-4 w-4 transition-all duration-200",
          isDark ? "scale-0 -rotate-90 opacity-0" : "scale-100 rotate-0 opacity-100",
        )}
      />
      <Moon
        aria-hidden
        className={cn(
          "absolute h-4 w-4 transition-all duration-200",
          isDark ? "scale-100 rotate-0 opacity-100" : "scale-0 rotate-90 opacity-0",
        )}
      />
    </button>
  );
}
