"use client";

import { Identity } from "@/lib/identity";

const PRODUCTS = [
  // Featured in the refund-compliance demo: receipt total is 2 × $349.99
  // = $699.98, so the storefront price has to match the seeded order.
  { name: "Sony WH-1000XM5 Headphones", price: 349.99, tag: "Featured", emoji: "🎧" },
  { name: "Wireless Earbuds", price: 89, tag: "Best seller", emoji: "🎵" },
  { name: "Mechanical Keyboard RGB", price: 149, tag: "New", emoji: "⌨️" },
  { name: "Wireless Gaming Mouse", price: 69, tag: null, emoji: "🖱️" },
  { name: "Smart Air Purifier", price: 229, tag: null, emoji: "🌬️" },
  { name: "Smart Coffee Maker", price: 179, tag: "Limited", emoji: "☕" },
  { name: "Robot Vacuum Cleaner", price: 399, tag: null, emoji: "🤖" },
  { name: "Fitness Smartwatch", price: 199, tag: null, emoji: "⌚" },
  { name: "10-inch Android Tablet", price: 249, tag: null, emoji: "📱" },
];

export function Storefront({ me }: { me: Identity }) {
  return (
    <>
      <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 grid place-items-center text-white text-xs font-bold">
              V
            </div>
            <span className="font-semibold tracking-tight">Voltway</span>
            <span className="hidden sm:inline text-xs text-zinc-500 ml-2">
              Electronics, delivered fast.
            </span>
          </div>
          <nav className="hidden md:flex items-center gap-5 text-sm text-zinc-600 dark:text-zinc-400">
            <a className="hover:text-zinc-900 dark:hover:text-zinc-100">Shop</a>
            <a className="hover:text-zinc-900 dark:hover:text-zinc-100">Deals</a>
            <a className="hover:text-zinc-900 dark:hover:text-zinc-100">Orders</a>
            <a className="hover:text-zinc-900 dark:hover:text-zinc-100">Help</a>
          </nav>
          <div className="flex items-center gap-3">
            <span className="hidden sm:inline text-sm text-zinc-600 dark:text-zinc-400">
              Hi, {me.name.split(" ")[0]}
            </span>
            <div className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-800 grid place-items-center text-xs font-medium">
              {me.initials}
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-10">
        <h2 className="text-lg font-semibold mb-4">Trending now</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {PRODUCTS.map((p) => (
            <div
              key={p.name}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 hover:shadow-sm transition-shadow"
            >
              <div className="aspect-square rounded-lg bg-zinc-100 dark:bg-zinc-800 grid place-items-center text-5xl mb-3">
                {p.emoji}
              </div>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{p.name}</div>
                  <div className="text-sm text-zinc-500">${p.price}</div>
                </div>
                {p.tag && (
                  <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900">
                    {p.tag}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </main>

      <footer className="border-t border-zinc-200 dark:border-zinc-800 mt-16">
        <div className="max-w-6xl mx-auto px-6 py-6 text-xs text-zinc-500 flex items-center justify-between">
          <span>© Voltway, Inc.</span>
          <span>Need help? Tap the chat bubble below.</span>
        </div>
      </footer>
    </>
  );
}
