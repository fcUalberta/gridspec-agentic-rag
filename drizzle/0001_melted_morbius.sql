CREATE TABLE `compliance_assessments` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`requirement_id` text NOT NULL,
	`decision` text NOT NULL,
	`product_name` text NOT NULL,
	`rationale` text NOT NULL,
	`evidence_json` text NOT NULL,
	`alternate_json` text NOT NULL,
	`confidence` integer NOT NULL,
	`review_status` text NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `extracted_requirements` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`source_document_id` text NOT NULL,
	`requirement_key` text NOT NULL,
	`section` text NOT NULL,
	`requirement_text` text NOT NULL,
	`source_quote` text NOT NULL,
	`page_number` integer,
	`category` text NOT NULL,
	`criticality` text NOT NULL,
	`confidence` integer NOT NULL,
	`review_status` text NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `pipeline_documents` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`kind` text NOT NULL,
	`file_name` text NOT NULL,
	`object_key` text NOT NULL,
	`content_type` text NOT NULL,
	`byte_size` integer NOT NULL,
	`openai_file_id` text NOT NULL,
	`vector_store_file_id` text,
	`status` text NOT NULL,
	`error` text,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `pipeline_workspaces` (
	`id` text PRIMARY KEY NOT NULL,
	`vector_store_id` text,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `solution_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`solution_json` text NOT NULL,
	`review_status` text NOT NULL,
	`created_at` integer NOT NULL
);
