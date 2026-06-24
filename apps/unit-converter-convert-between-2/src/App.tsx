import { useEffect, useState } from 'react';

type Direction = 'm-to-ft' | 'ft-to-m';

interface ConvertResponse {
  direction: Direction;
  input: number;
  output: number;
}

interface HistoryRow {
  id: number;
  direction: Direction;
  input_value: number;
  output_value: number;
  created_at: string;
}

const directionLabel: Record<Direction, string> = {
  'm-to-ft': 'Meters → Feet',
  'ft-to-m': 'Feet → Meters',
};

const unitLabel: Record<Direction, { from: string; to: string }> = {
  'm-to-ft': { from: 'm', to: 'ft' },
  'ft-to-m': { from: 'ft', to: 'm' },
};

export default function App() {
  const [direction, setDirection] = useState<Direction>('m-to-ft');
  const [value, setValue] = useState<string>('1');
  const [result, setResult] = useState<ConvertResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);

  async function loadHistory() {
    try {
      const res = await fetch('/api/conversions');
      if (res.ok) {
        const data: HistoryRow[] = await res.json();
        setHistory(data);
      }
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  async function handleConvert(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);

    const num = Number(value);
    if (value.trim() === '' || Number.isNaN(num) || !Number.isFinite(num)) {
      setError('Please enter a valid number.');
      return;
    }

    try {
      const res = await fetch('/api/convert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction, value: num }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Conversion failed.');
        return;
      }
      setResult(data as ConvertResponse);
      loadHistory();
    } catch {
      setError('Network error.');
    }
  }

  function swapDirection() {
    setDirection((d) => (d === 'm-to-ft' ? 'ft-to-m' : 'm-to-ft'));
    setResult(null);
    setError(null);
  }

  const units = unitLabel[direction];

  return (
    <div className="min-h-screen bg-slate-100 flex items-start justify-center p-6">
      <div className="w-full max-w-lg space-y-6">
        <header className="text-center">
          <h1 className="text-3xl font-bold text-slate-800">Unit Converter</h1>
          <p className="text-slate-500 mt-1">Convert between meters and feet, both directions.</p>
        </header>

        <form
          onSubmit={handleConvert}
          className="bg-white rounded-xl shadow p-6 space-y-4"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-slate-600">
              {directionLabel[direction]}
            </span>
            <button
              type="button"
              onClick={swapDirection}
              className="text-sm px-3 py-1 rounded bg-slate-200 hover:bg-slate-300 text-slate-700"
            >
              ⇄ Swap
            </button>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="number"
              step="any"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="flex-1 border border-slate-300 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
              placeholder="Enter value"
              aria-label="value to convert"
            />
            <span className="w-10 text-slate-600 font-medium">{units.from}</span>
          </div>

          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 rounded"
          >
            Convert
          </button>

          {error && (
            <p className="text-red-600 text-sm" role="alert">
              {error}
            </p>
          )}

          {result && (
            <div className="bg-green-50 border border-green-200 rounded p-4 text-center">
              <p className="text-slate-600 text-sm">
                {result.input} {units.from} =
              </p>
              <p className="text-2xl font-bold text-green-700">
                {result.output} {units.to}
              </p>
            </div>
          )}
        </form>

        <section className="bg-white rounded-xl shadow p-6">
          <h2 className="text-lg font-semibold text-slate-700 mb-3">History</h2>
          {history.length === 0 ? (
            <p className="text-slate-400 text-sm">No conversions yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {history.map((row) => {
                const u = unitLabel[row.direction];
                return (
                  <li key={row.id} className="py-2 text-sm flex justify-between">
                    <span className="text-slate-600">
                      {row.input_value} {u.from} → {row.output_value} {u.to}
                    </span>
                    <span className="text-slate-400">{directionLabel[row.direction]}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
