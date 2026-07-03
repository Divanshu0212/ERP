"use client";

import { useRouter } from "next/navigation";

import { clearToken } from "@/lib/auth";

/** Clears the session token and returns to the login page. */
export function LogoutButton() {
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-100 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
    >
      Log out
    </button>
  );
}
