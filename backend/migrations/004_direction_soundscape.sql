-- Rejissyorlik (ijro koʻrsatmalari), nomsiz spikerlar va muhit tovushlari (soundscape)

ALTER TABLE text_blocks ADD COLUMN IF NOT EXISTS delivery TEXT;            -- "hushed, fearful, slower"
ALTER TABLE book_characters ADD COLUMN IF NOT EXISTS is_minor BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE book_projects ADD COLUMN IF NOT EXISTS soundscape_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE book_projects ADD COLUMN IF NOT EXISTS directed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE dialogue_segments ADD COLUMN IF NOT EXISTS delivery TEXT;

CREATE TABLE IF NOT EXISTS book_scenes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id UUID NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
  start_seq INT NOT NULL,                 -- text_blocks.sequence_order (boshlanish)
  end_seq INT NOT NULL,                   -- (oxiri, ichida)
  label VARCHAR(120) NOT NULL,            -- oʻzbekcha: "Maktab hovlisi, tanaffus"
  ambience_prompt TEXT NOT NULL,          -- inglizcha SFX tavsifi
  intensity VARCHAR(10) NOT NULL DEFAULT 'low' CHECK (intensity IN ('low', 'medium')),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sfx_key TEXT,                           -- yaratilgan tovush (kesh)
  CHECK (end_seq >= start_seq)
);
CREATE INDEX IF NOT EXISTS idx_book_scenes_chapter ON book_scenes (chapter_id, start_seq);
