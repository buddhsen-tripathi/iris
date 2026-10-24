import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv, type Plugin } from "vite";
import { aiMiddleware } from "./server/ai";
import { createTradingService, tradingMiddleware } from "./server/trading";
import { newsMiddleware } from "./server/news";
import { createKnowledgeService, knowledgeMiddleware } from "./server/knowledge";
import {graphAgentMiddleware} from './server/graph-agent';
import { creatorMediaMiddleware } from "./server/creator-media";
import {stockPerformanceMiddleware} from './server/stock-performance';
import {createExaPeopleService} from './server/exa-people';

// True Markets only allows its own origin over CORS, so REST goes through a same-origin proxy.
// The public market-data WebSocket accepts any origin and is opened directly.
const proxy = {
  "/tm": {
    target: "https://api.truemarkets.co",
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/tm/, ""),
  },
};

// Live news: Yahoo Finance and Google News RSS, fetched and cached server-side (no key, no browser CORS).
function news(): Plugin {
  const middleware = newsMiddleware();
  return {
    name: "live-news",
    configureServer: (server) => void server.middlewares.use(middleware),
    configurePreviewServer: (server) => void server.middlewares.use(middleware),
  };
}

// AI layer: OpenRouter Agent SDK on the dev server. Unprefixed env vars never reach the browser bundle.
function ai(env: Record<string, string>): Plugin {
  const middleware = aiMiddleware({ apiKey: env.OPENROUTER_API_KEY, databaseUrl: env.DATABASE_URL });
  return {
    name: "openrouter-agent",
    configureServer: (server) => void server.middlewares.use(middleware),
    configurePreviewServer: (server) => void server.middlewares.use(middleware),
  };
}

function knowledge(env: Record<string, string>): Plugin {
  const service=env.KNOWLEDGE_DATABASE_URL?createKnowledgeService({databaseURL:env.KNOWLEDGE_DATABASE_URL,apiKey:env.OPENROUTER_API_KEY}):null;
  const middleware = knowledgeMiddleware({service});
  const people=env.EXA_API_KEY?createExaPeopleService({apiKey:env.EXA_API_KEY,cacheDirectory:fileURLToPath(new URL('../data/knowledge/cache/exa-people',import.meta.url))}):null;
  const analyst=graphAgentMiddleware({service,apiKey:env.OPENROUTER_API_KEY,peopleSearch:people?.search});
  return {
    name: "neon-evidence-graph",
    configureServer: (server) => {server.middlewares.use(middleware);server.middlewares.use(analyst);},
    configurePreviewServer: (server) => {server.middlewares.use(middleware);server.middlewares.use(analyst);},
  };
}

function creatorMedia(): Plugin {
  const middleware = creatorMediaMiddleware(fileURLToPath(new URL('../data/raw/creator_videos', import.meta.url)));
  return {
    name: 'creator-media',
    configureServer: server => void server.middlewares.use(middleware),
    configurePreviewServer: server => void server.middlewares.use(middleware),
  };
}

function stockPerformance():Plugin{
  const middleware=stockPerformanceMiddleware();
  return {name:'listed-stock-performance',configureServer:server=>void server.middlewares.use(middleware),configurePreviewServer:server=>void server.middlewares.use(middleware)};
}

// Live trading (server/trading.ts): the key file stays here; every limit is enforced server-side.
function trading(env: Record<string, string>): Plugin {
  let service: ReturnType<typeof createTradingService> | null = null;
  if (env.TM_KEY_FILE) {
    try {
      service = createTradingService({
        keyFile: env.TM_KEY_FILE,
        enabled: env.TM_TRADING_ENABLED === "true",
        maxOrderUsd: Number(env.TM_MAX_ORDER_USD) || 10,
        dailyLimitUsd: Number(env.TM_DAILY_LIMIT_USD) || 25,
        databaseUrl: env.DATABASE_URL,
      });
    } catch (error) {
      console.warn(`[trading] disabled: ${error instanceof Error ? error.message : error}`);
    }
  }
  const middleware = tradingMiddleware(service);
  return {
    name: "true-markets-trading",
    configureServer: (server) => void server.middlewares.use(middleware),
    configurePreviewServer: (server) => void server.middlewares.use(middleware),
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), tailwindcss(), news(), ai(env), knowledge(env), creatorMedia(), stockPerformance(), trading(env)],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: { port: 5180, proxy },
    preview: { port: 4173, proxy },
  };
});
