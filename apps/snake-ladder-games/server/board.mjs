// Snakes and Ladders board definition (1..100)
// key = start cell, value = destination cell
export const LADDERS = {
  1: 38, 4: 14, 9: 31, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 80: 100
};

export const SNAKES = {
  16: 6, 47: 26, 49: 11, 56: 53, 62: 19, 64: 60, 87: 24, 93: 73, 95: 75, 98: 78
};

export const BOARD_SIZE = 100;

// Returns { to, jumped } where jumped is 1 if a snake/ladder applied
export function resolvePosition(from, dice) {
  let next = from + dice;
  if (next > BOARD_SIZE) {
    // bounce back if overshoot
    next = BOARD_SIZE - (next - BOARD_SIZE);
  }
  let jumped = 0;
  if (LADDERS[next] !== undefined) {
    next = LADDERS[next];
    jumped = 1;
  } else if (SNAKES[next] !== undefined) {
    next = SNAKES[next];
    jumped = 1;
  }
  return { to: next, jumped };
}
