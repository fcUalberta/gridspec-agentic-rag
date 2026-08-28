import { integer, sqliteTable, text } from 'drizzle-orm/sqlite-core';

export const projects = sqliteTable('projects', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  customer: text('customer').notNull(),
  stage: integer('stage').notNull().default(0),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull(),
});

export const reviewEvents = sqliteTable('review_events', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  projectId: text('project_id').notNull(),
  entityType: text('entity_type').notNull(),
  entityId: text('entity_id').notNull(),
  decision: text('decision').notNull(),
  note: text('note'),
  reviewer: text('reviewer').notNull(),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull(),
});

export const sourceDocuments = sqliteTable('source_documents', {
  id: text('id').primaryKey(),
  projectId: text('project_id').notNull(),
  fileName: text('file_name').notNull(),
  objectKey: text('object_key').notNull(),
  contentType: text('content_type').notNull(),
  byteSize: integer('byte_size').notNull(),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull(),
});
