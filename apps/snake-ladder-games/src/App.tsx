import React, { useEffect, useState, useCallback } from 'react';
import Board from './components/Board';
import type { BoardInfo, Game, MoveResult, RollResponse } from './types';

const PLAYER_COLORS = ['text-red-600', 'text-blue-600', 'text-green-600', 'text-yellow-600'];

export default function App() {
  const [board, setBoard] = useState<BoardInfo | null>(null);
  const [game, setGame] = useState<Game | null>(null);
  const [playerCount, setPlayerCount] = useState(2);
  const [lastMove, setLastMove] = useState<MoveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rolling, setRolling] = useState(false);

  const loadBoard = useCallback(async () => {
    const res = await fetch('/api/snake-ladder-games/board');
    if (res.ok) setBoard(await res.json());
  }, []);

  useEffect(() => {
    loadBoard();
  }, [loadBoard]);

  const newGame = async () => {
    setError(null);
    setLastMove(null);
    const res = await fetch('/api/snake-ladder-games/games', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerCount })
    });
    if (res.ok) {
      setGame(await res.json());
    } else {
      const data = await res.json().catch(() => ({}));
      setError(data.error || 'Failed to create game');
    }
  };

  const roll = async () => {
    if (!game || game.status !== 'active') return;
    setError(null);
    setRolling(true);
    const res = await fetch(`/api/snake-ladder-games/games/${game.id}/roll`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    setRolling(false);
    if (res.ok) {
      const data: RollResponse = await res.json();
      setGame(data.game);
      setLastMove(data.move);
    } else {
      const data = await res.json().catch(() => ({}));
      setError(data.error || 'Failed to roll');
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 p-4 flex flex-col items-center">
      <header className="mb-4 text-center">
        <h1 className="text-3xl font-bold">🐍 Snakes & Ladders 🪜</h1>
        <p className="text-slate-500">Roll the dice and race to 100!</p>
      </header>

      <div className="flex flex-col lg:flex-row gap-6 w-full max-w-4xl">
        <div className="flex-shrink-0 flex justify-center">
          {board ? (
            <Board board={board} game={game} />
          ) : (
            <p className="text-slate-400">Loading board…</p>
          )}
        </div>

        <aside className="flex-1 space-y-4">
          <section className="bg-white rounded-lg p-4 shadow-sm border border-slate-200">
            <h2 className="font-semibold mb-2">New Game</h2>
            <div className="flex items-center gap-2">
              <label className="text-sm">Players:</label>
              <select
                className="border rounded px-2 py-1 text-sm"
                value={playerCount}
                onChange={(e) => setPlayerCount(Number(e.target.value))}
              >
                <option value={2}>2</option>
                <option value={3}>3</option>
                <option value={4}>4</option>
              </select>
              <button
                onClick={newGame}
                className="bg-indigo-600 text-white px-3 py-1 rounded text-sm hover:bg-indigo-700"
              >
                Start
              </button>
            </div>
          </section>

          {error && (
            <div className="bg-rose-100 text-rose-700 rounded p-2 text-sm border border-rose-300">
              {error}
            </div>
          )}

          {game && (
            <section className="bg-white rounded-lg p-4 shadow-sm border border-slate-200 space-y-3">
              <h2 className="font-semibold">Game #{game.id}</h2>
              <ul className="text-sm space-y-1">
                {game.positions.map((pos, idx) => (
                  <li
                    key={idx}
                    className={[
                      'flex justify-between',
                      idx === game.currentPlayer && game.status === 'active'
                        ? 'font-bold'
                        : '',
                      PLAYER_COLORS[idx]
                    ].join(' ')}
                  >
                    <span>
                      Player {idx + 1}
                      {idx === game.currentPlayer && game.status === 'active' ? ' ◀ turn' : ''}
                    </span>
                    <span>cell {pos}</span>
                  </li>
                ))}
              </ul>

              {game.status === 'finished' && game.winner !== null ? (
                <div className="bg-emerald-100 text-emerald-700 rounded p-2 text-center font-bold">
                  🎉 Player {game.winner + 1} wins!
                </div>
              ) : (
                <button
                  onClick={roll}
                  disabled={rolling}
                  className="w-full bg-amber-500 text-white py-2 rounded font-semibold hover:bg-amber-600 disabled:opacity-50"
                >
                  {rolling ? 'Rolling…' : `🎲 Roll (Player ${game.currentPlayer + 1})`}
                </button>
              )}

              {lastMove && (
                <p className="text-sm text-slate-600">
                  Player {lastMove.player + 1} rolled a{' '}
                  <span className="font-bold">{lastMove.dice}</span>: {lastMove.from} →{' '}
                  {lastMove.to}
                  {lastMove.jumped ? ' (snake/ladder!)' : ''}
                </p>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
