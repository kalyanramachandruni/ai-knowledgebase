"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getUser, type StoredUser } from "@/lib/auth";

export function NavBar() {
  const router = useRouter();
  const [user, setUser] = useState<StoredUser | null>(null);

  useEffect(() => {
    setUser(getUser());
  }, []);

  return (
    <nav className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
      <div className="flex items-center gap-6">
        <Link href="/dashboard" className="font-semibold text-gray-900">
          Knowledge Product Studio
        </Link>
        <Link href="/dashboard" className="text-sm text-gray-600 hover:text-gray-900">
          Dashboard
        </Link>
        <Link href="/products" className="text-sm text-gray-600 hover:text-gray-900">
          Knowledge Products
        </Link>
        <Link href="/sources" className="text-sm text-gray-600 hover:text-gray-900">
          Sources
        </Link>
        <Link href="/docs" className="text-sm text-gray-600 hover:text-gray-900">
          Docs
        </Link>
      </div>
      {user && (
        <div className="flex items-center gap-3 text-sm text-gray-600">
          <span>
            {user.display_name} <span className="text-gray-400">({user.roles.join(", ")})</span>
          </span>
          <button
            onClick={() => {
              clearSession();
              router.push("/login");
            }}
            className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
          >
            Sign out
          </button>
        </div>
      )}
    </nav>
  );
}
