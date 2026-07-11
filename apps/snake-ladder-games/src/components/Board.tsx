import React from 'react';
import type { BoardInfo, Game } from '../types';

interface BoardProps {
  board: BoardInfo;
  game: Game | null;
}

const PLAYER_COLORS = ['bg-red-500', 'bg-blue-500', 'bg-green-500', 'bg-yellow-500'];
const PLAYER_LABELS = ['P1', 'P2', 'P3', 'P4'];

// Build the 10x10 boustrophedon layout (rows top to bottom, cell 100 top-left area)
function buildCells(): number[] {
  const rows: number[][] = [];
  for (let r = 0; r < 10; r++) {
    const base = r * 10;
    const row: number[] = [];
    for (let c = 0; c < 10; c++) {
      row.push(base + c + 1);
    }
    if (r % 2 === 1) row.reverse();
    rows.push(row);
  }
  rows.reverse(); // so that 100 is at top
  return rows.flat();
}

export default function Board({ board, game }: BoardProps) {
  const cells = buildCells();

  const cellPlayers = (cell: number): number[] => {
    if (!game) return [];
    const result: number[] = [];
    game.positions.forEach((pos, idx) => {
      if (pos === cell) result.push(idx);
    });
    return result;
  };

  return (
    <div className="grid grid-cols-10 gap-1 bg-slate-200 p-2 rounded-lg w-full max-w-xl">
      {cells.map((cell) => {
        const isLadder = board.ladders[String(cell)] !== undefined;
        const isSnake = board.snakes[String(cell)] !== undefined;
        const here = cellPlayers(cell);
        return (
          <div
            key={cell}
            className={[
              'relative aspect-square flex items-center justify-center rounded text-[10px] font-medium border',
              isLadder ? 'bg-emerald-100 border-emerald-400' :
                isSnake ? 'bg-rose-100 border-rose-400' :
                'bg-white border-slate-300'
            ].join(' ')}
          >
            <span className="absolute top-0.5 left-0.5 text-slate-400">{cell}</span>
            {isLadder && <span className="text-emerald-600 text-lg leading-none">🪜</span>}
            {isSnake && <span className="text-rose-600 text-lg leading-none">🐍</span>}
            <div className="absolute bottom-0.5 right-0.5 flex flex-wrap gap-0.5 justify-end">
              {here.map((p) => (
                <span
                  key={p}
                  className={`${PLAYER_COLORS[p]} text-white rounded-full w-4 h-4 flex items-center justify-center text-[8px]`}
                  title={PLAYER_LABELS[p]}
                >
                  {p + 1}
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
