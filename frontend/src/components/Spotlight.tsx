"use client";

import type { ReactNode } from "react";

/** Judge guide: pulsing yellow ring + floating "CLICK HERE" badge on the one control to press next. */
export function Spotlight({ on, children, className = "", label = "CLICK HERE", rounded = "rounded-full" }: {
  on: boolean;
  children: ReactNode;
  className?: string;
  label?: string;
  rounded?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      {on && (
        <>
          <span aria-hidden className={`pointer-events-none absolute -inset-1.5 z-10 ${rounded} ring-4 ring-yellow-400 animate-pulse`} />
          <span className="pointer-events-none absolute -top-3.5 left-1/2 z-20 -translate-x-1/2 animate-bounce whitespace-nowrap rounded-full bg-[#18181B] px-2 py-0.5 text-[9.5px] font-black tracking-wider text-[#FACC15] shadow">
            {label} ↓
          </span>
        </>
      )}
      {children}
    </div>
  );
}
