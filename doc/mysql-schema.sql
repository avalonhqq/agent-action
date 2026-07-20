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
  `operation` varchar(16) NOT NULL,
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

CREATE TABLE IF NOT EXISTS `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `alembic_version` (`version_num`)
VALUES ('20260719_0001')
ON DUPLICATE KEY UPDATE `version_num` = VALUES(`version_num`);
