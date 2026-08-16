import { useEffect, useState } from 'react';

interface Result {
  id: number;
  bill: number;
  tipPercent: number;
  people: number;
  tipAmount: number;
  total: number;
  perPerson: number;
  createdAt?: string;
}

function money(n: number): string {
  return `$${n.toFixed(2)}`;
}

export default function App() {
  const [bill, setBill] = useState('');
  const [tipPercent, setTipPercent] = useState('15');
  const [people, setPeople] = useState('1');
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Result[]>([]);

  async function loadHistory() {
    try {
      const res = await fetch('/api/tip');
      if (res.ok) {
        setHistory((await res.json()) as Result[]);
      }
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    try {
      const res = await fetch('/api/tip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bill: Number(bill),
          tipPercent: Number(tipPercent),
          people: Number(people),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError((data as { error?: string }).error ?? 'Calculation failed');
        return;
      }
      setResult(data as Result);
      loadHistory();
    } catch {
      setError('Network error');
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col items-center py-10 px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-lg p-6">
        <h1 className="text-2xl font-bold text-slate-800 mb-1">Tip Calculator</h1>
        <p className="text-sm text-slate-500 mb-6">
          Enter a bill, choose a tip percent, and split it.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="bill">
              Bill amount
            </label>
            <input
              id="bill"
              type="number"
              min="0"
              step="0.01"
              value={bill}
              onChange={(e) => setBill(e.target.value)}
              placeholder="0.00"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="tip">
              Tip percent (%)
            </label>
            <input
              id="tip"
              type="number"
              min="0"
              step="0.1"
              value={tipPercent}
              onChange={(e) => setTipPercent(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="people">
              Number of people
            </label>
            <input
              id="people"
              type="number"
              min="1"
              step="1"
              value={people}
              onChange={(e) => setPeople(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <button
            type="submit"
            className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-lg py-2 transition-colors"
          >
            Calculate
          </button>
        </form>

        {error && (
          <div className="mt-4 rounded-lg bg-red-50 text-red-700 px-3 py-2 text-sm" role="alert">
            {error}
          </div>
        )}

        {result && (
          <div className="mt-6 rounded-xl bg-emerald-50 p-4 space-y-2" data-testid="result">
            <Row label="Tip amount" value={money(result.tipAmount)} />
            <Row label="Total" value={money(result.total)} />
            <div className="border-t border-emerald-200 my-2" />
            <Row
              label={`Per person (${result.people})`}
              value={money(result.perPerson)}
              emphasis
            />
          </div>
        )}
      </div>

      {history.length > 0 && (
        <div className="w-full max-w-md mt-6 bg-white rounded-2xl shadow p-4">
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Recent calculations</h2>
          <ul className="divide-y divide-slate-100">
            {history.map((h) => (
              <li key={h.id} className="py-2 text-sm flex justify-between text-slate-600">
                <span>
                  {money(h.bill)} @ {h.tipPercent}% / {h.people}p
                </span>
                <span className="font-medium text-slate-800">{money(h.perPerson)} ea</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="flex justify-between items-center">
      <span className={emphasis ? 'text-emerald-800 font-semibold' : 'text-slate-600'}>
        {label}
      </span>
      <span
        className={
          emphasis ? 'text-emerald-700 text-xl font-bold' : 'text-slate-800 font-medium'
        }
      >
        {value}
      </span>
    </div>
  );
}
