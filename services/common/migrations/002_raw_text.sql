-- Arbitrary malformed source text can contain U+0000, which jsonb rejects.
-- Keep the JSON envelope serialized as text; its payload remains escaped.
ALTER TABLE raw_frames ALTER COLUMN envelope TYPE text USING envelope::text;
