import { env } from 'cloudflare:workers';

export async function POST(request: Request) {
  const body = await request.json() as { entityType?:string; entityId?:string; decision?:string; note?:string; reviewer?:string };
  if (!body.entityType || !body.entityId || !body.decision) return Response.json({ error:'entityType, entityId and decision are required.' },{status:400});
  const result = await env.DB.prepare('INSERT INTO review_events (project_id, entity_type, entity_id, decision, note, reviewer, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .bind('jps-1025947',body.entityType,body.entityId,body.decision,body.note ?? null,body.reviewer ?? 'Alex Morgan',Math.floor(Date.now()/1000)).run();
  return Response.json({ id:result.meta.last_row_id, status:'recorded' },{status:201});
}
