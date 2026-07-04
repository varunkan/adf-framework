"use client";
// Reusable in-app modal — replaces native window.confirm/prompt so destructive
// actions can require typed confirmation, a reason-for-change, and on-screen
// record-integrity copy (WS3). Now backed by Radix Dialog: real focus-trap,
// scroll-lock, Escape/overlay close, portal, ARIA labelling + animations.
// Same props as before, so callers are unchanged.
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  labelledBy?: string; // accepted for API compatibility; Radix labels via Title
}) {
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="modal-content card glass">
          <div className="modal-head">
            <Dialog.Title className="modal-title">{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button className="ghost modal-x" aria-label="Close">
                <X size={16} aria-hidden />
              </button>
            </Dialog.Close>
          </div>
          {children}
          {footer && <div className="cta-row modal-foot">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
