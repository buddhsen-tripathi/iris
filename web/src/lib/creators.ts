import { z } from 'zod';
import sourceVideos from '@/data/creator-videos.json';

const mentionSchema = z.object({ symbol: z.string(), name: z.string(), at: z.number().nonnegative(), evidence: z.string() });
const videoSchema = z.object({
  id: z.string(), creator: z.string(), channelURL: z.url(), title: z.string(), headline: z.string(),
  summary: z.string(), category: z.enum(['stocks', 'crypto']), publishedAt: z.string(),
  views: z.number(), sourceURL: z.url(), clipStart: z.number(), clipDuration: z.number(),
  hasCaptions: z.boolean(), mentions: z.array(mentionSchema),
});
export const creatorVideos = z.array(videoSchema).parse(sourceVideos);
export type CreatorVideo = z.infer<typeof videoSchema>;
export type Mention = z.infer<typeof mentionSchema>;
export const mediaURL = (id: string, file: 'clip.mp4' | 'poster.jpg' | 'captions.vtt') => `/creator-media/${id}/${file}`;

const paperOrderSchema = z.object({
  id: z.string(), symbol: z.string(), creator: z.string(), videoId: z.string(),
  amountCents: z.number().int().positive(), price: z.number().positive(),
  shares: z.number().positive(), createdAt: z.string(),
});
export const paperOrdersSchema = z.array(paperOrderSchema);
export type PaperOrder = z.infer<typeof paperOrderSchema>;
const PAPER_BALANCE_CENTS = 1_000_000;
export const paperBalance = (orders: PaperOrder[]) => PAPER_BALANCE_CENTS - orders.reduce((sum, order) => sum + order.amountCents, 0);

/** Decimal input is converted to cents before touching the simulated cash balance. */
export function amountInCents(input: string) {
  if (!/^\d+(\.\d{1,2})?$/.test(input.trim())) return null;
  const cents = Math.round(Number(input) * 100);
  return Number.isSafeInteger(cents) && cents > 0 ? cents : null;
}

const quoteSchema = z.object({ price: z.coerce.number().positive().finite(), timestamp: z.string() });
export function freshQuote(data: unknown, receivedAt: number | undefined, now: number) {
  const result = quoteSchema.safeParse(data);
  if (!result.success || receivedAt === undefined) return null;
  const sourceTime = Date.parse(result.data.timestamp);
  if (!Number.isFinite(sourceTime) || now - sourceTime > 60_000 || sourceTime > now + 5000 || now - receivedAt > 30_000) return null;
  return result.data.price;
}

export function createPaperOrder(input: { amount: string; price: number | null; balanceCents: number; symbol: string; video: CreatorVideo }) {
  const cents = amountInCents(input.amount);
  if (cents === null) return { error: 'Enter an amount greater than $0 with up to two decimal places.' };
  if (cents > input.balanceCents) return { error: 'This amount exceeds your available paper cash.' };
  if (input.price === null || !Number.isFinite(input.price) || input.price <= 0) return { error: 'A fresh market quote is required. Try again when the quote reconnects.' };
  return { order: paperOrderSchema.parse({
    id: crypto.randomUUID(), symbol: input.symbol, creator: input.video.creator, videoId: input.video.id,
    amountCents: cents, price: input.price, shares: cents / 100 / input.price, createdAt: new Date().toISOString(),
  }) };
}
