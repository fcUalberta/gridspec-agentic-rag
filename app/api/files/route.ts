import { env } from 'cloudflare:workers';

export async function POST(request: Request) {
  const form = await request.formData();
  const file = form.get('file');
  if (!(file instanceof File)) return Response.json({ error: 'A file is required.' }, { status: 400 });
  if (file.size > 100 * 1024 * 1024) return Response.json({ error: 'File exceeds 100 MB.' }, { status: 413 });
  const allowed = new Set(['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/msword']);
  if (!allowed.has(file.type)) return Response.json({ error: 'Only PDF and Word files are supported.' }, { status: 415 });
  const id = crypto.randomUUID();
  const safeName = file.name.replace(/[^a-zA-Z0-9._-]+/g, '-');
  const objectKey = `projects/jps-1025947/${id}-${safeName}`;
  await env.FILES.put(objectKey, file.stream(), { httpMetadata: { contentType: file.type }, customMetadata: { originalName: file.name } });
  await env.DB.prepare('INSERT INTO source_documents (id, project_id, file_name, object_key, content_type, byte_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .bind(id, 'jps-1025947', file.name, objectKey, file.type, file.size, Math.floor(Date.now()/1000)).run();
  return Response.json({ id, fileName: file.name, objectKey, status: 'stored' }, { status: 201 });
}
