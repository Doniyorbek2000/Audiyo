-- Video muharriri uchun poster kadri
ALTER TABLE media_projects ADD COLUMN IF NOT EXISTS poster_key TEXT;
