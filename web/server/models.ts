// The server picks the model; the browser never chooses.
export const ROUTES = {
  analysis: { model: "anthropic/claude-sonnet-5.5", label: "Sonnet 5.5" },
  lookup: { model: "anthropic/claude-haiku-5.5", label: "Haiku 5.5" },
} as const;
export type Tier = keyof typeof ROUTES;
