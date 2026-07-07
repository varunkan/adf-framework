// Round-9 ai_draft MAJOR "side-by-side comparison … printable for paper
// review" (n=9) + minor "printable AI-vs-human summary" (n=2): a tiny helper
// that opens a clean printable window with self-contained inline styles —
// no app chrome, so the paper copy is just the review content.

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export { esc as escapeHtml };

export function openPrintWindow(title: string, bodyHtml: string): void {
  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) return;
  w.document.write(`<!doctype html><html><head><meta charset="utf-8">
<title>${esc(title)}</title>
<style>
  body { font: 13px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
         color: #16181d; margin: 28px; }
  h1 { font-size: 17px; margin: 0 0 4px; }
  h2 { font-size: 13px; margin: 18px 0 6px; }
  .mut { color: #5b6272; font-size: 11px; }
  .cols { display: flex; gap: 20px; align-items: flex-start; }
  .col { flex: 1; min-width: 0; }
  .box { border: 1px solid #cfd4e0; border-radius: 6px; padding: 12px;
         white-space: pre-wrap; word-break: break-word; }
  ins { background: #d9f2dd; text-decoration: none; }
  del { background: #f8d9d9; }
  ul { padding-left: 18px; margin: 6px 0; }
  li { margin-bottom: 8px; }
  @media print { .cols { display: flex; } }
</style></head><body>${bodyHtml}
<script>window.onload = function () { window.print(); };</script>
</body></html>`);
  w.document.close();
}
