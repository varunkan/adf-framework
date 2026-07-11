import { useEffect, useRef, useState, useCallback } from 'react';

interface Preset {
  id: number;
  name: string;
  minutes: number;
  seconds: number;
  created_at: string;
}

function clamp(n: number, min: number, max: number): number {
  if (Number.isNaN(n)) return min;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

export default function App() {
  const [minutes, setMinutes] = useState(5);
  const [seconds, setSeconds] = useState(0);
  const [remaining, setRemaining] = useState(5 * 60); // total seconds remaining
  const [running, setRunning] = useState(false);

  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetName, setPresetName] = useState('');
  const [error, setError] = useState('');

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimer = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (running) {
      intervalRef.current = setInterval(() => {
        setRemaining((prev) => {
          if (prev <= 1) {
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return clearTimer;
  }, [running, clearTimer]);

  useEffect(() => {
    if (remaining === 0 && running) {
      setRunning(false);
    }
  }, [remaining, running]);

  const loadPresets = useCallback(async () => {
    const res = await fetch('/api/presets');
    if (res.ok) {
      const data = (await res.json()) as Preset[];
      setPresets(data);
    }
  }, []);

  useEffect(() => {
    loadPresets();
  }, [loadPresets]);

  const applyInputs = useCallback(() => {
    const m = clamp(minutes, 0, 59);
    const s = clamp(seconds, 0, 59);
    setMinutes(m);
    setSeconds(s);
    setRemaining(m * 60 + s);
  }, [minutes, seconds]);

  const handleStart = () => {
    if (remaining <= 0) {
      applyInputs();
    }
    if (minutes * 60 + seconds > 0 || remaining > 0) {
      setRunning(true);
    }
  };

  const handlePause = () => {
    setRunning(false);
  };

  const handleReset = () => {
    setRunning(false);
    clearTimer();
    const m = clamp(minutes, 0, 59);
    const s = clamp(seconds, 0, 59);
    setMinutes(m);
    setSeconds(s);
    setRemaining(m * 60 + s);
  };

  const handleSetTime = () => {
    setRunning(false);
    applyInputs();
  };

  const dispMin = Math.floor(remaining / 60);
  const dispSec = remaining % 60;

  const savePreset = async () => {
    setError('');
    const m = clamp(minutes, 0, 59);
    const s = clamp(seconds, 0, 59);
    try {
      const res = await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: presetName.trim(), minutes: m, seconds: s }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { error?: string };
        setError(body.error || 'Failed to save preset');
        return;
      }
      setPresetName('');
      await loadPresets();
    } catch {
      setError('Network error');
    }
  };

  const usePreset = (p: Preset) => {
    setRunning(false);
    setMinutes(p.minutes);
    setSeconds(p.seconds);
    setRemaining(p.minutes * 60 + p.seconds);
  };

  const deletePreset = async (id: number) => {
    const res = await fetch(`/api/presets/${id}`, { method: 'DELETE' });
    if (res.ok) {
      await loadPresets();
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col items-center p-6">
      <h1 className="text-3xl font-bold mb-6">Countdown Timer</h1>

      <div
        className="text-8xl font-mono font-bold tabular-nums mb-8 select-none"
        data-testid="display"
      >
        {pad(dispMin)}:{pad(dispSec)}
      </div>

      <div className="flex flex-wrap items-end gap-4 mb-6 justify-center">
        <label className="flex flex-col text-sm">
          Minutes
          <input
            type="number"
            min={0}
            max={59}
            value={minutes}
            onChange={(e) => setMinutes(clamp(Number(e.target.value), 0, 59))}
            className="mt-1 w-24 rounded bg-slate-800 border border-slate-600 px-2 py-1 text-lg text-center"
          />
        </label>
        <label className="flex flex-col text-sm">
          Seconds
          <input
            type="number"
            min={0}
            max={59}
            value={seconds}
            onChange={(e) => setSeconds(clamp(Number(e.target.value), 0, 59))}
            className="mt-1 w-24 rounded bg-slate-800 border border-slate-600 px-2 py-1 text-lg text-center"
          />
        </label>
        <button
          onClick={handleSetTime}
          className="rounded bg-slate-600 hover:bg-slate-500 px-4 py-2 font-medium"
        >
          Set
        </button>
      </div>

      <div className="flex gap-4 mb-10">
        <button
          onClick={handleStart}
          disabled={running}
          className="rounded bg-green-600 hover:bg-green-500 disabled:opacity-40 px-6 py-2 font-semibold"
        >
          Start
        </button>
        <button
          onClick={handlePause}
          disabled={!running}
          className="rounded bg-yellow-600 hover:bg-yellow-500 disabled:opacity-40 px-6 py-2 font-semibold"
        >
          Pause
        </button>
        <button
          onClick={handleReset}
          className="rounded bg-red-600 hover:bg-red-500 px-6 py-2 font-semibold"
        >
          Reset
        </button>
      </div>

      <div className="w-full max-w-md bg-slate-800 rounded-lg p-4">
        <h2 className="text-xl font-semibold mb-3">Presets</h2>
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            placeholder="Preset name"
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            className="flex-1 rounded bg-slate-700 border border-slate-600 px-2 py-1"
          />
          <button
            onClick={savePreset}
            className="rounded bg-blue-600 hover:bg-blue-500 px-4 py-1 font-medium"
          >
            Save
          </button>
        </div>
        {error && (
          <p className="text-red-400 text-sm mb-2" role="alert">
            {error}
          </p>
        )}
        <ul className="space-y-2">
          {presets.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between bg-slate-700 rounded px-3 py-2"
            >
              <span className="font-mono">
                {p.name} — {pad(p.minutes)}:{pad(p.seconds)}
              </span>
              <span className="flex gap-2">
                <button
                  onClick={() => usePreset(p)}
                  className="rounded bg-green-700 hover:bg-green-600 px-3 py-1 text-sm"
                >
                  Use
                </button>
                <button
                  onClick={() => deletePreset(p.id)}
                  className="rounded bg-red-700 hover:bg-red-600 px-3 py-1 text-sm"
                >
                  Delete
                </button>
              </span>
            </li>
          ))}
          {presets.length === 0 && (
            <li className="text-slate-400 text-sm">No presets saved.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
