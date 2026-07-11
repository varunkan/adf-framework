export interface Game {
  id: number;
  playerCount: number;
  currentPlayer: number;
  positions: number[];
  winner: number | null;
  status: string;
  createdAt: string;
}

export interface MoveResult {
  player: number;
  dice: number;
  from: number;
  to: number;
  jumped: boolean;
}

export interface RollResponse {
  game: Game;
  move: MoveResult;
}

export interface BoardInfo {
  size: number;
  snakes: Record<string, number>;
  ladders: Record<string, number>;
}
