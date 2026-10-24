// Shared by the browser and the dev-server AI tools, so no browser or Vite globals here.

export type Timeframe = {
  id: string;
  window: string;
  resolution: string;
  seconds: number;
};

// Windows over 1d require a resolution of at least 1h, so intraday frames read one day of history.
export const TIMEFRAMES: Timeframe[] = [
  { id: "1m", window: "1d", resolution: "1m", seconds: 60 },
  { id: "5m", window: "1d", resolution: "5m", seconds: 300 },
  { id: "15m", window: "1d", resolution: "15m", seconds: 900 },
  { id: "1h", window: "1M", resolution: "1h", seconds: 3600 },
  { id: "4h", window: "6M", resolution: "4h", seconds: 14400 },
  { id: "1D", window: "12M", resolution: "1d", seconds: 86400 },
];
