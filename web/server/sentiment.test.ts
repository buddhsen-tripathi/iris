import { describe, expect, it, vi } from "vitest";
import type { Article } from "./news";
import { buildPrompt, createSentimentService, headlineHash, labelFor, mergeScores } from "./sentiment";

const article = (i: number, hoursAgo = i): Article => ({
  title: `Headline ${i}`,
  summary: "",
  url: `https://example.com/${i}`,
  source: "Wire",
  publishedAt: new Date(Date.parse("2026-10-24T17:00:00Z") - hoursAgo * 3_600_000).toISOString(),
  provider: "Google News",
});
const NOW = Date.parse("2026-10-24T17:00:00Z");

describe("scoring helpers", () => {
  it("labels by score so colour and number agree", () => {
    expect([labelFor(0.6), labelFor(0.2), labelFor(0.19), labelFor(-0.19), labelFor(-0.2)]).toEqual(["positive", "positive", "neutral", "neutral", "negative"]);
  });

  it("hashes the headline set by URL and order", () => {
    expect(headlineHash([article(1), article(2)])).toBe(headlineHash([article(1), article(2)]));
    expect(headlineHash([article(1), article(2)])).not.toBe(headlineHash([article(2), article(1)]));
  });

  it("numbers headlines with source and age, newest first", () => {
    const prompt = buildPrompt("NVDA", "NVIDIA", "stock", [article(0, 2), article(1, 5)], NOW);
    expect(prompt).toContain("Instrument: NVIDIA (NVDA), tokenized stock.");
    expect(prompt).toContain("0. [Wire · 2h ago] Headline 0");
    expect(prompt).toContain("1. [Wire · 5h ago] Headline 1");
  });

  it("joins scores back by index, clamps them, and treats skipped headlines as neutral", () => {
    const items = mergeScores([article(0), article(1), article(2)], {
      overall: { label: "mixed", score: 0, summary: "" },
      items: [
        { index: 0, score: 0.7, reason: "good" },
        { index: 2, score: -0.4, reason: "bad" },
      ],
    });
    expect(items.map((i) => [i.label, i.score, i.reason])).toEqual([
      ["positive", 0.7, "good"],
      ["neutral", 0, "Not scored"],
      ["negative", -0.4, "bad"],
    ]);
  });
});

describe("sentiment service", () => {
  type Tool = { function: { execute: (input: unknown) => Promise<unknown> } };
  const fakeClient = (output: unknown) => {
    const calls: { model: string; input: string }[] = [];
    const client = {
      callModel: (req: { model: string; input: string; tools: readonly Tool[] }) => {
        calls.push({ model: req.model, input: req.input });
        return {
          getResponse: async () => {
            if (output) await req.tools[0].function.execute(output);
            return {};
          },
          getUsage: async () => ({ modelCalls: 1, inputTokens: 500, outputTokens: 200, totalTokens: 700 }),
        };
      },
    };
    return { client: client as never, calls };
  };
  const news = (articles: Article[]) => ({ asset: vi.fn(async () => ({ articles, fetchedAt: "", sources: [] })), markets: vi.fn() }) as never;

  it("scores the latest 10 headlines on the lookup model", async () => {
    const { client, calls } = fakeClient({ overall: { label: "positive", score: 0.4, summary: "Good flow" }, items: [{ index: 0, score: 0.5, reason: "beat" }] });
    const service = createSentimentService({ client, news: news(Array.from({ length: 12 }, (_, i) => article(i))), now: () => NOW });
    const read = await service.analyze("NVDA", "NVIDIA", "stock");
    expect(calls[0].model).toBe("anthropic/claude-haiku-5.5");
    expect(calls[0].input).toContain("9. [Wire");
    expect(calls[0].input).not.toContain("10. [Wire");
    expect(read).toMatchObject({ reused: false, stored: false, overall: { label: "positive", score: 0.4 } });
    expect(read.items).toHaveLength(10);
    expect(read.items[0]).toMatchObject({ label: "positive", reason: "beat" });
  });

  it("skips the model when there are no headlines, retries once, then fails clearly", async () => {
    const { client, calls } = fakeClient(null);
    expect((await createSentimentService({ client, news: news([]) }).analyze("BIRB", undefined, "crypto")).overall).toBeNull();
    expect(calls).toHaveLength(0);
    await expect(createSentimentService({ client, news: news([article(0)]) }).analyze("BTC", "Bitcoin", "crypto")).rejects.toThrow("no sentiment");
    expect(calls).toHaveLength(2);
  });

  it("ignores out-of-range indexes and clamps scores", () => {
    const items = mergeScores([article(0)], { overall: { label: "neutral", score: 0, summary: "" }, items: [{ index: 5, score: 1, reason: "x" }, { index: 0, score: 3, reason: "y" }] });
    expect(items).toMatchObject([{ score: 1, label: "positive", reason: "y" }]);
  });

  it("shares one run between concurrent requests for the same symbol", async () => {
    const { client, calls } = fakeClient({ overall: { label: "neutral", score: 0, summary: "" }, items: [] });
    const service = createSentimentService({ client, news: news([article(0)]) });
    await Promise.all([service.analyze("BTC", "Bitcoin", "crypto"), service.analyze("BTC", "Bitcoin", "crypto")]);
    expect(calls).toHaveLength(1);
  });
});
