"use client";
/**
 * components/NavBar.tsx - Top navigation bar.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_LINKS = [
  { href: "/",          label: "Dashboard", icon: "📊" },
  { href: "/map",       label: "Map",       icon: "🗺️" },
  { href: "/graph",     label: "Graph",     icon: "🕸️" },
  { href: "/chat",      label: "Ask AI",    icon: "💬" },
  { href: "/pipeline",  label: "Pipeline",  icon: "⚙️" },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <header className="border-b border-gray-800 bg-gray-900 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 font-bold text-lg text-brand-500">
            <span className="text-2xl">🌱</span>
            <span className="hidden sm:block">EcoGraph</span>
          </Link>

          {/* Nav links */}
          <nav className="flex items-center gap-1">
            {NAV_LINKS.map(({ href, label, icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  pathname === href
                    ? "bg-brand-600 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800"
                )}
              >
                <span>{icon}</span>
                <span className="hidden md:block">{label}</span>
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}