-- Apply manually with a database administrator, then integrate chat_backend.py.
-- These are SERVER-ONLY tables/functions. Never add them to app.SUPA_COLUMNS,
-- the HR report builder, browser Supabase clients, or a Realtime publication.
-- Bodies/subscriptions are Fernet ciphertext produced by the application.
-- IDs/timestamps/participants and keyed body digests are not encrypted.
-- This is server-side encryption, not E2EE. Back up CHAT_ENCRYPTION_KEY securely.
-- service_role bypasses RLS; every API call must retain application scoping.

BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id bigint GENERATED ALWAYS AS IDENTITY (MAXVALUE 9007199254740991) PRIMARY KEY,
    sender_id text NOT NULL CHECK (char_length(sender_id) BETWEEN 3 AND 256),
    recipient_id text NOT NULL CHECK (char_length(recipient_id) BETWEEN 3 AND 256),
    client_id uuid NOT NULL,
    body_ciphertext text NOT NULL CHECK (char_length(body_ciphertext) BETWEEN 80 AND 24000),
    body_digest text NOT NULL CHECK (body_digest ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    read_at timestamptz,
    CONSTRAINT chat_safe_message_id CHECK (id BETWEEN 1 AND 9007199254740991),
    CONSTRAINT chat_no_self_message CHECK (sender_id <> recipient_id),
    CONSTRAINT chat_sender_client_unique UNIQUE (sender_id, client_id)
);

CREATE INDEX IF NOT EXISTS chat_messages_pair_out ON public.chat_messages(sender_id, recipient_id, id DESC);
CREATE INDEX IF NOT EXISTS chat_messages_pair_in ON public.chat_messages(recipient_id, sender_id, id DESC);
CREATE INDEX IF NOT EXISTS chat_messages_events ON public.chat_messages(recipient_id, id);
CREATE INDEX IF NOT EXISTS chat_messages_unread ON public.chat_messages(recipient_id, sender_id, id)
    WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_messages_send_rate ON public.chat_messages(sender_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.chat_push_subscriptions (
    account_id text NOT NULL CHECK (char_length(account_id) BETWEEN 3 AND 256),
    endpoint_hash text NOT NULL CHECK (endpoint_hash ~ '^[0-9a-f]{64}$'),
    subscription_ciphertext text NOT NULL CHECK (char_length(subscription_ciphertext) BETWEEN 80 AND 8192),
    preview boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (account_id, endpoint_hash)
);

ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_push_subscriptions ENABLE ROW LEVEL SECURITY;
-- No anon/authenticated policies: an HR Admin is also just authenticated in a
-- browser and receives no privilege to inspect another person's conversations.
REVOKE ALL ON TABLE public.chat_messages, public.chat_push_subscriptions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_messages, public.chat_push_subscriptions TO service_role;
REVOKE ALL ON SEQUENCE public.chat_messages_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.chat_messages_id_seq TO service_role;

-- Atomic per-sender UUID idempotency and persistent send throttling. Same UUID
-- with a different peer/body digest conflicts, including during concurrent sends.
CREATE OR REPLACE FUNCTION public.chat_send_message(
    p_sender_id text, p_recipient_id text, p_client_id uuid,
    p_body_ciphertext text, p_body_digest text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
    existing public.chat_messages%ROWTYPE;
    recent_count bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('chat-send:' || p_sender_id, 0));
    SELECT m.* INTO existing FROM public.chat_messages m
        WHERE m.sender_id = p_sender_id AND m.client_id = p_client_id;
    IF FOUND THEN
        IF existing.recipient_id <> p_recipient_id OR existing.body_digest <> p_body_digest THEN
            RETURN jsonb_build_object('status', 'conflict');
        END IF;
        RETURN jsonb_build_object('status', 'existing', 'message', to_jsonb(existing));
    END IF;
    SELECT count(*) INTO recent_count FROM public.chat_messages m
        WHERE m.sender_id = p_sender_id AND m.created_at >= statement_timestamp() - interval '1 minute';
    IF recent_count >= 30 THEN
        RETURN jsonb_build_object('status', 'rate_limited');
    END IF;
    INSERT INTO public.chat_messages(sender_id, recipient_id, client_id, body_ciphertext, body_digest)
        VALUES(p_sender_id, p_recipient_id, p_client_id, p_body_ciphertext, p_body_digest)
        RETURNING * INTO existing;
    RETURN jsonb_build_object('status', 'created', 'message', to_jsonb(existing));
END;
$$;

-- Reject guessed/future/outgoing IDs; only a received message in THIS pair can
-- bound the update. No blanket "mark conversation read" or all-recipient update.
CREATE OR REPLACE FUNCTION public.chat_mark_read(
    p_account_id text, p_peer_id text, p_through_id bigint
) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.chat_messages m WHERE m.id = p_through_id
            AND m.recipient_id = p_account_id AND m.sender_id = p_peer_id
    ) THEN
        RETURN false;
    END IF;
    UPDATE public.chat_messages SET read_at = clock_timestamp()
        WHERE recipient_id = p_account_id AND sender_id = p_peer_id
            AND id <= p_through_id AND read_at IS NULL;
    RETURN true;
END;
$$;

-- A keyset page of latest-per-peer summaries, not a PostgREST all-table read.
-- Apply the cursor AFTER ranking so older messages cannot repeat a conversation.
-- The backend follows pages until empty, avoiding Supabase's 1000-row cap.
CREATE OR REPLACE FUNCTION public.chat_conversations(
    p_account_id text, p_before bigint DEFAULT 9007199254740992, p_limit integer DEFAULT 200
) RETURNS TABLE (
    peer_id text, id bigint, sender_id text, recipient_id text, client_id uuid,
    body_ciphertext text, body_digest text, created_at timestamptz, read_at timestamptz,
    unread_count bigint
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
    WITH mine AS (
        SELECT m.*, m.recipient_id AS peer FROM public.chat_messages m WHERE m.sender_id = p_account_id
        UNION ALL
        SELECT m.*, m.sender_id AS peer FROM public.chat_messages m WHERE m.recipient_id = p_account_id
    ), ranked AS (
        SELECT mine.*, row_number() OVER (PARTITION BY peer ORDER BY mine.id DESC) AS rn,
            sum(CASE WHEN mine.recipient_id = p_account_id AND mine.read_at IS NULL THEN 1 ELSE 0 END)
                OVER (PARTITION BY peer) AS unread
        FROM mine
    )
    SELECT r.peer, r.id, r.sender_id, r.recipient_id, r.client_id,
        r.body_ciphertext, r.body_digest, r.created_at, r.read_at, r.unread
    FROM ranked r WHERE r.rn = 1 AND r.id < p_before
    ORDER BY r.id DESC LIMIT least(greatest(p_limit, 1), 200);
$$;

-- Keep the device cap correct across multiple workers/processes as well.
CREATE OR REPLACE FUNCTION public.chat_save_subscription(
    p_account_id text, p_endpoint_hash text, p_subscription_ciphertext text, p_preview boolean DEFAULT false
) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('chat-push:' || p_account_id, 0));
    IF NOT EXISTS (
        SELECT 1 FROM public.chat_push_subscriptions s
            WHERE s.account_id = p_account_id AND s.endpoint_hash = p_endpoint_hash
    ) AND (SELECT count(*) FROM public.chat_push_subscriptions s WHERE s.account_id = p_account_id) >= 5 THEN
        RETURN false;
    END IF;
    INSERT INTO public.chat_push_subscriptions(account_id, endpoint_hash, subscription_ciphertext, preview)
        VALUES(p_account_id, p_endpoint_hash, p_subscription_ciphertext, p_preview)
        ON CONFLICT(account_id, endpoint_hash) DO UPDATE SET
            subscription_ciphertext = EXCLUDED.subscription_ciphertext,
            preview = EXCLUDED.preview, updated_at = clock_timestamp();
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.chat_send_message(text,text,uuid,text,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.chat_mark_read(text,text,bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.chat_conversations(text,bigint,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.chat_save_subscription(text,text,text,boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.chat_send_message(text,text,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.chat_mark_read(text,text,bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.chat_conversations(text,bigint,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.chat_save_subscription(text,text,text,boolean) TO service_role;

COMMIT;
