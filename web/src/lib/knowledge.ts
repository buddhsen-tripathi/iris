import { z } from 'zod';

export const graphEdgeSchema = z.object({
  id: z.string(), subject_id: z.string(), object_id: z.string(), predicate: z.string(),
  status: z.enum(['reference', 'reported', 'candidate']), evidence_quote: z.string().nullable(),
  first_observed_at_utc: z.string(), published_at_utc: z.string().nullable(),
  valid_from_utc: z.string().nullable(), valid_to_utc: z.string().nullable(),
  metadata: z.record(z.string(), z.unknown()),
  source_url: z.string().url(), title: z.string(), source_name: z.string(),
  content_sha256: z.string(), page_number: z.number().nullable(),
});
export type GraphEdge = z.infer<typeof graphEdgeSchema>;
export const networkNodeSchema = z.object({
  id: z.string(), kind: z.string(), name: z.string(),
  aliases: z.array(z.string()), ticker: z.string().nullable(),
});
export const networkEdgeSchema = graphEdgeSchema.pick({
  id: true, subject_id: true, object_id: true, predicate: true, status: true,
});
export const networkResponseSchema = z.object({
  nodes: z.array(networkNodeSchema), edges: z.array(networkEdgeSchema),
  as_of: z.string(), storage: z.literal('neon'), complete: z.literal(true),
  snapshot_id: z.string().regex(/^[a-f0-9]{64}$/).optional(),
});
export type NetworkNode = z.infer<typeof networkNodeSchema>;
export type NetworkEdge = z.infer<typeof networkEdgeSchema>;
export type NetworkResponse = z.infer<typeof networkResponseSchema>;
export const passageSchema = z.object({
  id: z.string(), text: z.string(), page_number: z.number(), start_offset: z.number(), end_offset: z.number(),
  document_id: z.string(), title: z.string(), source_url: z.string().url(), source_name: z.string(),
  content_sha256: z.string(), first_observed_at_utc: z.string(), published_at_utc: z.string().nullable(),
  score: z.number(), matched_by: z.array(z.enum(['lexical', 'semantic'])),
  issuer_entity_id: z.string().nullable().optional(),
});
export const evidenceResponseSchema = z.object({
  passages: z.array(passageSchema), mode: z.enum(['hybrid', 'lexical']),
  warning: z.string().nullable(), as_of: z.string(),
});
export type EvidenceResponse = z.infer<typeof evidenceResponseSchema>;

export function safeSourceURL(value: string) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

export function relationLabel(predicate: string) {
  return predicate.toLowerCase().replaceAll('_', ' ');
}
