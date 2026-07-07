// Round-9 ai_draft minor "No diff of AI draft vs user edits" (n=2): a small,
// dependency-free word-level diff (classic LCS) between two draft texts.
// Bounded: beyond ~3000 tokens per side we fall back to a coarse
// paragraph-level diff so the UI never hangs on a pathological input.

export type DiffOp = { kind: "same" | "del" | "ins"; text: string };

function tokenize(s: string): string[] {
  // keep whitespace attached so the joined output reads naturally
  return s.match(/\S+\s*/g) || [];
}

function lcsDiff(a: string[], b: string[]): DiffOp[] {
  const n = a.length;
  const m = b.length;
  // dp[i][j] = LCS length of a[i:], b[j:]
  const dp: Uint32Array[] = [];
  for (let i = 0; i <= n; i++) dp.push(new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffOp[] = [];
  let i = 0;
  let j = 0;
  const push = (kind: DiffOp["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("del", a[i]);
      i++;
    } else {
      push("ins", b[j]);
      j++;
    }
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("ins", b[j++]);
  return out;
}

export function diffWords(prev: string, next: string): DiffOp[] {
  const a = tokenize(prev);
  const b = tokenize(next);
  if (a.length > 3000 || b.length > 3000) {
    // coarse fallback: diff paragraph blocks instead of words
    const pa = prev.split(/\n{2,}/);
    const pb = next.split(/\n{2,}/);
    return lcsDiff(
      pa.map((p) => p + "\n\n"),
      pb.map((p) => p + "\n\n")
    );
  }
  return lcsDiff(a, b);
}

export function diffCounts(ops: DiffOp[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const op of ops) {
    const words = op.text.trim() ? op.text.trim().split(/\s+/).length : 0;
    if (op.kind === "ins") added += words;
    if (op.kind === "del") removed += words;
  }
  return { added, removed };
}
