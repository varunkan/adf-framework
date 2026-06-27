import { useEffect, useState } from 'react';

interface CalcResult {
  bill_amount: number;
  tip_percent: number;
  people: number;
  tip_amount: number;
  total_amount: number;
  per_person: number;
}

interface SavedCalc extends CalcResult {
  id: number;
  created_at: string;
}

export default function App() {
  const [bill, setBill] = useState('50');
  const [tip, setTip] = useState('15');
  const [people, setPeople] = useState('2');
  const [result, setResult] = useState<CalcResult | null>(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<SavedCalc[]>([]);

  async function loadHistory() {
    try {
      const res = await fetch('/api/tip/calculations');
      if (res.ok) {
        const data: SavedCalc[] = await res.json();
        setHistory(data);
      }
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  function buildPayload() {
    return {
      bill_amount: Number(bill),
      tip_percent: Number(tip),
      people: Number(people),
    };
  }

  async function calculate() {
    setError('');
    try {
      const res = await fetch('/api/tip/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Calculation failed');
        setResult(null);
        return;
      }
      setResult(data as CalcResult);
    } catch {
      setError('Network error');
    }
  }

  async function save() {
    setError('');
    try {
      const res = await fetch('/api/tip/calculations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Save failed');
        return;
      }
      setResult({
        bill_amount: data.bill_amount,
        tip_percent: data.tip_percent,
        people: data.people,
        tip_amount: data.tip_amount,
        total_amount: data.total_amount,
        per_person: data.per_person,
      });
      loadHistory();
    } catch {
      setError('Network error');
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col items-center py-10 px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-lg p-6">
        <h1 className="text-2xl font-bold text-slate-800 mb-6">Tip Calculator</h1>

        <div className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-600">Bill Amount</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={bill}
              onChange={(e) => setBill(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Bill Amount"
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium text-slate-600">Tip Percent (%)</span>
            <input
              type="number"
              min="0"
              step="1"
              value={tip}
              onChange={(e) => setTip(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Tip Percent"
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium text-slate-600">Number of People</span>
            <input
              type="number"
              min="1"
              step="1"
              value={people}
              onChange={(e) => setPeople(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
              aria-label="Number of People"
            />
          </label>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={calculate}
            className="flex-1 bg-emerald-500 hover:bg-emerald-600 text-white font-semibold py-2 rounded-lg transition"
          >
            Calculate
          </button>
          <button
            onClick={save}
            className="flex-1 bg-slate-700 hover:bg-slate-800 text-white font-semibold py-2 rounded-lg transition"
          >
            Save
          </button>
        </div>

        {error && (
          <p className="mt-4 text-red-600 text-sm" role="alert">
            {error}
          </p>
        )}

        {result && (
          <div className="mt-6 bg-emerald-50 rounded-lg p-4 space-y-2" data-testid="result">
            <Row label="Tip Amount" value={result.tip_amount} />
            <Row label="Total" value={result.total_amount} />
            <Row label="Per Person" value={result.per_person} />
          </div>
        )}
      </div>

      {history.length > 0 && (
        <div className="w-full max-w-md bg-white rounded-2xl shadow-lg p-6 mt-6">
          <h2 className="text-lg font-bold text-slate-800 mb-4">History</h2>
          <ul className="space-y-2">
            {history.map((h) => (
              <li
                key={h.id}
                className="text-sm text-slate-600 flex justify-between border-b border-slate-100 pb-1"
              >
                <span>
                  ${h.bill_amount.toFixed(2)} @ {h.tip_percent}% / {h.people}p
                </span>
                <span className="font-medium">${h.per_person.toFixed(2)} ea</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-600">{label}</span>
      <span className="font-semibold text-slate-800">${value.toFixed(2)}</span>
    </div>
  );
}
