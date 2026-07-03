"use client";
// Reusable in-app modal dialog — replaces native window.confirm/prompt so
// destructive actions can require typed confirmation, a reason-for-change, and
// on-screen record-integrity copy (WS3). Focus-trapped-lite: Escape closes,
// backdrop click closes, the dialog is labelled for assistive tech.
import { useEffect, useRef } from "react";

export function Modal({
  title,
  onClose,
  children,
  footer,
  labelledBy = "modal-title",
}: {
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  labelledBy?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    // move focus into the dialog for keyboard users
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(6,10,18,0.55)",
        backdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: 16,
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className="card glass"
        style={{
          maxWidth: 520,
          width: "100%",
          padding: 20,
          outline: "none",
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 12,
            marginBottom: 10,
          }}
        >
          <h2 id={labelledBy} style={{ margin: 0, fontSize: 16 }}>
            {title}
          </h2>
          <span className="spacer" style={{ marginLeft: "auto" }} />
          <button
            className="ghost"
            aria-label="Close"
            onClick={onClose}
            style={{ fontSize: 16, lineHeight: 1, padding: "0 6px" }}
          >
            ✕
          </button>
        </div>
        {children}
        {footer && (
          <div
            className="cta-row"
            style={{ marginTop: 16, display: "flex", gap: 10, justifyContent: "flex-end" }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
