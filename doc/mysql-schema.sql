-- BiliSupport AI MySQL 8 schema
-- Generated from Alembic revision 20260719_0001 and verified on MySQL 8.0.42.
-- Recommended execution path: python -m alembic upgrade head

CREATE DATABASE IF NOT EXISTS `bili_support`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `bili_support`;

CREATE TABLE IF NOT EXISTS `users` (
  `id` varchar(36) NOT NULL,
  `external_id` varchar(128) NOT NULL,
  `display_name` varchar(100) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_external_id` (`external_id`),
  KEY `ix_users_external_id` (`external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `conversations` (
  `id` varchar(36) NOT NULL,
  `thread_id` varchar(36) NOT NULL,
  `user_id` varchar(36) NOT NULL,
  `title` varchar(120) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_conversations_thread_id` (`thread_id`),
  KEY `ix_conversations_thread_id` (`thread_id`),
  KEY `ix_conversations_user_id` (`user_id`),
  KEY `ix_conversations_user_updated` (`user_id`, `updated_at`),
  CONSTRAINT `fk_conversations_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `messages` (
  `id` varchar(36) NOT NULL,
  `conversation_id` varchar(36) NOT NULL,
  `role` varchar(16) NOT NULL,
  `content` text NOT NULL,
  `request_id` varchar(128) NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_messages_conversation_id` (`conversation_id`),
  KEY `ix_messages_request_id` (`request_id`),
  KEY `ix_messages_conversation_created` (`conversation_id`, `created_at`),
  CONSTRAINT `fk_messages_conversation_id_conversations`
    FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_messages_ck_messages_role_allowed`
    CHECK (`role` IN ('user', 'assistant'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `model_calls` (
  `id` varchar(36) NOT NULL,
  `conversation_id` varchar(36) NOT NULL,
  `user_message_id` varchar(36) NOT NULL,
  `assistant_message_id` varchar(36) DEFAULT NULL,
  `request_id` varchar(128) NOT NULL,
  `operation` varchar(64) NOT NULL,
  `model` varchar(128) NOT NULL,
  `prompt_version` varchar(64) NOT NULL,
  `status` varchar(16) NOT NULL,
  `latency_ms` float NOT NULL,
  `prompt_tokens` int DEFAULT NULL,
  `completion_tokens` int DEFAULT NULL,
  `total_tokens` int DEFAULT NULL,
  `error_code` varchar(64) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_model_calls_conversation_id` (`conversation_id`),
  KEY `ix_model_calls_user_message_id` (`user_message_id`),
  KEY `ix_model_calls_assistant_message_id` (`assistant_message_id`),
  KEY `ix_model_calls_request_id` (`request_id`),
  KEY `ix_model_calls_conversation_created` (`conversation_id`, `created_at`),
  CONSTRAINT `fk_model_calls_assistant_message_id_messages`
    FOREIGN KEY (`assistant_message_id`) REFERENCES `messages` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_model_calls_conversation_id_conversations`
    FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_model_calls_user_message_id_messages`
    FOREIGN KEY (`user_message_id`) REFERENCES `messages` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_model_calls_ck_model_calls_latency_non_negative`
    CHECK (`latency_ms` >= 0),
  CONSTRAINT `ck_model_calls_ck_model_calls_status_allowed`
    CHECK (`status` IN ('success', 'error', 'cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE `model_calls`
  MODIFY COLUMN `operation` varchar(64) NOT NULL;

CREATE TABLE IF NOT EXISTS `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `alembic_version` (`version_num`)
VALUES ('20260728_0004')
ON DUPLICATE KEY UPDATE `version_num` = VALUES(`version_num`);

-- 第五周知识入库表的完整约束和索引以 Alembic 迁移为唯一可信来源：
-- migrations/versions/20260725_0003_week5_knowledge_ingestion.py
-- knowledge_type 后续变更见 migrations/versions/20260728_0004_knowledge_type.py
-- 请通过 `python -m alembic upgrade head` 创建，避免手工执行时漏掉外键或索引。

CREATE TABLE IF NOT EXISTS `knowledge_documents` (
  `id` varchar(36) NOT NULL,
  `created_by_user_id` varchar(36) NOT NULL,
  `title` varchar(200) NOT NULL,
  `business_domain` varchar(32) NOT NULL,
  `knowledge_type` varchar(16) NOT NULL DEFAULT 'mixed',
  `access_scope` json NOT NULL,
  `status` varchar(16) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_knowledge_documents_created_by_user_id` (`created_by_user_id`),
  KEY `ix_knowledge_documents_domain_status` (`business_domain`, `status`),
  CONSTRAINT `fk_knowledge_documents_user`
    FOREIGN KEY (`created_by_user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_knowledge_documents_status`
    CHECK (`status` IN ('active', 'deleted')),
  CONSTRAINT `ck_knowledge_documents_knowledge_type`
    CHECK (`knowledge_type` IN ('policy', 'manual', 'faq', 'generic', 'mixed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `knowledge_document_versions` (
  `id` varchar(36) NOT NULL,
  `document_id` varchar(36) NOT NULL,
  `version_number` int NOT NULL,
  `content_sha256` varchar(64) NOT NULL,
  `original_filename` varchar(255) NOT NULL,
  `media_type` varchar(100) NOT NULL,
  `size_bytes` int NOT NULL,
  `storage_key` varchar(255) NOT NULL,
  `status` varchar(16) NOT NULL,
  `is_current` boolean NOT NULL DEFAULT false,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_versions_document_sha256` (`document_id`, `content_sha256`),
  UNIQUE KEY `uq_knowledge_versions_document_number` (`document_id`, `version_number`),
  UNIQUE KEY `uq_knowledge_versions_storage_key` (`storage_key`),
  KEY `ix_knowledge_versions_document_id` (`document_id`),
  KEY `ix_knowledge_versions_content_sha256` (`content_sha256`),
  KEY `ix_knowledge_versions_document_created` (`document_id`, `created_at`),
  KEY `ix_knowledge_versions_document_current` (`document_id`, `is_current`),
  CONSTRAINT `fk_knowledge_versions_document`
    FOREIGN KEY (`document_id`) REFERENCES `knowledge_documents` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_knowledge_versions_size` CHECK (`size_bytes` > 0),
  CONSTRAINT `ck_knowledge_versions_status`
    CHECK (`status` IN ('pending', 'ready', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `knowledge_ingestion_jobs` (
  `id` varchar(36) NOT NULL,
  `version_id` varchar(36) NOT NULL,
  `status` varchar(16) NOT NULL,
  `attempt_count` int NOT NULL,
  `error_code` varchar(64) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_knowledge_jobs_version_id` (`version_id`),
  KEY `ix_knowledge_jobs_status_created` (`status`, `created_at`),
  CONSTRAINT `fk_knowledge_jobs_version`
    FOREIGN KEY (`version_id`) REFERENCES `knowledge_document_versions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_knowledge_jobs_attempt` CHECK (`attempt_count` >= 0),
  CONSTRAINT `ck_knowledge_jobs_status`
    CHECK (`status` IN ('queued', 'processing', 'succeeded', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `knowledge_source_blocks` (
  `id` varchar(36) NOT NULL,
  `version_id` varchar(36) NOT NULL,
  `ordinal` int NOT NULL,
  `block_type` varchar(32) NOT NULL,
  `content` text NOT NULL,
  `page_number` int DEFAULT NULL,
  `heading_path` json NOT NULL,
  `metadata_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_source_blocks_version_ordinal` (`version_id`, `ordinal`),
  KEY `ix_source_blocks_version_id` (`version_id`),
  CONSTRAINT `fk_source_blocks_version`
    FOREIGN KEY (`version_id`) REFERENCES `knowledge_document_versions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_source_blocks_ordinal` CHECK (`ordinal` >= 0),
  CONSTRAINT `ck_source_blocks_page` CHECK (`page_number` IS NULL OR `page_number` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `knowledge_chunks` (
  `id` varchar(36) NOT NULL,
  `version_id` varchar(36) NOT NULL,
  `source_block_id` varchar(36) DEFAULT NULL,
  `parent_chunk_id` varchar(36) DEFAULT NULL,
  `kind` varchar(16) NOT NULL,
  `ordinal` int NOT NULL,
  `content` text NOT NULL,
  `char_count` int NOT NULL,
  `metadata_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_chunks_version_ordinal` (`version_id`, `ordinal`),
  KEY `ix_knowledge_chunks_version_id` (`version_id`),
  KEY `ix_knowledge_chunks_source_block_id` (`source_block_id`),
  KEY `ix_knowledge_chunks_parent_chunk_id` (`parent_chunk_id`),
  CONSTRAINT `fk_chunks_version`
    FOREIGN KEY (`version_id`) REFERENCES `knowledge_document_versions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_chunks_source_block`
    FOREIGN KEY (`source_block_id`) REFERENCES `knowledge_source_blocks` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_chunks_parent`
    FOREIGN KEY (`parent_chunk_id`) REFERENCES `knowledge_chunks` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_chunks_kind` CHECK (`kind` IN ('parent', 'child')),
  CONSTRAINT `ck_chunks_ordinal` CHECK (`ordinal` >= 0),
  CONSTRAINT `ck_chunks_char_count` CHECK (`char_count` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `knowledge_dictionary_terms` (
  `id` varchar(36) NOT NULL,
  `term` varchar(100) NOT NULL,
  `normalized_term` varchar(100) NOT NULL,
  `aliases` json NOT NULL,
  `business_domain` varchar(32) NOT NULL,
  `term_type` varchar(32) NOT NULL,
  `frequency` int NOT NULL,
  `source_type` varchar(32) NOT NULL,
  `source_reference` varchar(255) DEFAULT NULL,
  `status` varchar(16) NOT NULL,
  `review_note` varchar(500) DEFAULT NULL,
  `created_by_user_id` varchar(36) NOT NULL,
  `reviewed_by_user_id` varchar(36) DEFAULT NULL,
  `reviewed_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dictionary_terms_domain_normalized`
    (`business_domain`, `normalized_term`),
  KEY `ix_dictionary_terms_domain_status` (`business_domain`, `status`),
  KEY `ix_dictionary_terms_created_by_user_id` (`created_by_user_id`),
  KEY `ix_dictionary_terms_reviewed_by_user_id` (`reviewed_by_user_id`),
  CONSTRAINT `fk_dictionary_terms_created_user`
    FOREIGN KEY (`created_by_user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_dictionary_terms_reviewed_user`
    FOREIGN KEY (`reviewed_by_user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_dictionary_terms_status`
    CHECK (`status` IN ('candidate', 'approved', 'rejected')),
  CONSTRAINT `ck_dictionary_terms_type`
    CHECK (`term_type` IN ('product', 'feature', 'issue', 'action', 'error_code', 'other')),
  CONSTRAINT `ck_dictionary_terms_source`
    CHECK (`source_type` IN ('manual', 'knowledge_keyword', 'product_catalog',
      'conversation_log_mock', 'ticket_mock')),
  CONSTRAINT `ck_dictionary_terms_frequency` CHECK (`frequency` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `knowledge_dictionary_versions` (
  `id` varchar(36) NOT NULL,
  `version_number` int NOT NULL,
  `status` varchar(16) NOT NULL,
  `content_sha256` varchar(64) NOT NULL,
  `artifact_content` longtext NOT NULL,
  `manifest_json` longtext NOT NULL COMMENT '规范词、别名、业务域和类型的不可变JSON快照',
  `term_count` int NOT NULL,
  `published_by_user_id` varchar(36) NOT NULL,
  `release_note` varchar(500) DEFAULT NULL,
  `published_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dictionary_versions_number` (`version_number`),
  UNIQUE KEY `uq_dictionary_versions_sha256` (`content_sha256`),
  KEY `ix_dictionary_versions_status_published` (`status`, `published_at`),
  KEY `ix_dictionary_versions_published_by_user_id` (`published_by_user_id`),
  CONSTRAINT `fk_dictionary_versions_published_user`
    FOREIGN KEY (`published_by_user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_dictionary_versions_status`
    CHECK (`status` IN ('active', 'superseded')),
  CONSTRAINT `ck_dictionary_versions_number` CHECK (`version_number` > 0),
  CONSTRAINT `ck_dictionary_versions_term_count` CHECK (`term_count` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
