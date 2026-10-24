import { describe, expect, it } from 'vitest';
import { amountInCents, createPaperOrder, creatorVideos, freshQuote, paperBalance } from './creators';

describe('creator paper investments', () => {
  const video = creatorVideos[0];
  it('handles decimal amounts in cents and rejects invalid monetary input', () => {
    expect(amountInCents('25.10')).toBe(2510);
    expect(amountInCents('0.01')).toBe(1);
    for (const input of ['0', '-10', '1.001', 'Infinity', '1e3', '', 'NaN', '1000000000000000000']) expect(amountInCents(input)).toBeNull();
  });
  it('blocks overspending and missing prices', () => {
    expect(createPaperOrder({ amount: '100.01', price: 20, balanceCents: 10000, symbol: 'AAPL', video }).error).toContain('exceeds');
    expect(createPaperOrder({ amount: '50', price: null, balanceCents: 10000, symbol: 'AAPL', video }).error).toContain('fresh market quote');
  });
  it('records the source creator and debits the exact simulated amount', () => {
    const result = createPaperOrder({ amount: '25.10', price: 200, balanceCents: 1000000, symbol: 'AAPL', video });
    expect(result.error).toBeUndefined();
    if (!result.order) throw new Error('Expected a paper order');
    expect(result.order.shares).toBeCloseTo(0.1255);
    expect(result.order.videoId).toBe(video.id);
    expect(result.order.creator).toBe(video.creator);
    expect(paperBalance([result.order])).toBe(997490);
  });
  it('rejects stale, future, malformed, and non-positive quotes', () => {
    const now = Date.parse('2026-10-24T17:00:00Z');
    const data = { price: '200.50', timestamp: new Date(now - 1000).toISOString() };
    expect(freshQuote(data, now - 1000, now)).toBe(200.5);
    expect(freshQuote(data, now - 31000, now)).toBeNull();
    expect(freshQuote({ ...data, timestamp: new Date(now - 61000).toISOString() }, now, now)).toBeNull();
    expect(freshQuote({ ...data, timestamp: new Date(now + 10000).toISOString() }, now, now)).toBeNull();
    expect(freshQuote({ ...data, timestamp: 'unknown' }, now, now)).toBeNull();
    expect(freshQuote({ ...data, price: '0' }, now, now)).toBeNull();
    expect(freshQuote(undefined, undefined, now)).toBeNull();
  });
});
