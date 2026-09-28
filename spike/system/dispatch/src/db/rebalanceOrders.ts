export interface RebalanceOrderRow {
  id: string;
  stationId: string;
  targetFill: number;
  createdAt: Date;
}

const rows: RebalanceOrderRow[] = [];
let nextId = 1;

export function resetRebalanceOrders(): void {
  rows.length = 0;
  nextId = 1;
}

export function insertRebalanceOrder(stationId: string, targetFill: number, createdAt: Date): RebalanceOrderRow {
  const row: RebalanceOrderRow = { id: `ro-${nextId++}`, stationId, targetFill, createdAt };
  rows.push(row);
  return row;
}

export function listRebalanceOrders(): RebalanceOrderRow[] {
  return [...rows];
}
