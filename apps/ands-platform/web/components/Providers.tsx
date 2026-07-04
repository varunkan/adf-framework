"use client";
// App-wide UI providers: Radix tooltips + Sonner toasts, themed to the Prism
// dark surface so feedback and hints feel native, not bolted on.
import { Toaster } from "sonner";
import * as Tooltip from "@radix-ui/react-tooltip";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={180} skipDelayDuration={300}>
      {children}
      <Toaster
        theme="dark"
        position="top-right"
        gap={10}
        toastOptions={{
          style: {
            background: "rgba(18,26,42,.94)",
            border: "1px solid var(--line)",
            color: "var(--ink)",
            backdropFilter: "blur(10px)",
            borderRadius: "12px",
          },
        }}
      />
    </Tooltip.Provider>
  );
}
