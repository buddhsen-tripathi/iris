import {z} from 'zod';

export const personClaimSchema=z.object({
  topic:z.enum(['company_role','past_role','education','research','other']),
  text:z.string().trim().min(1).max(600),evidence_id:z.string().regex(/^E\d+$/),
  quote:z.string().trim().min(20).max(1200).describe('Exact contiguous excerpt from the returned Exa source text supporting this specific claim; do not paraphrase.'),
});
export const researchPersonSchema=z.object({
  company_id:z.string().max(300),name:z.string().trim().min(2).max(160),
  affiliation:z.enum(['current_reported','former_reported','unclear']).describe('As described by the retrieved source; a recent fetch alone does not confirm a role is still current.'),
  claims:z.array(personClaimSchema).min(1).max(6).describe('At least one company_role claim must establish a professional connection to this exact company. Other claims need their own source excerpts.'),
  identity_note:z.string().min(1).max(600).describe('Identity disambiguation, role-date uncertainty or missing verification. No name-only merges.'),
});
export const answerPersonSchema=researchPersonSchema.extend({company_name:z.string(),id:z.string(),status:z.literal('research_lead')});
