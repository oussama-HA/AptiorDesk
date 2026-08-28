-- AptiorDesk schema v6: extraction provenance and profile item origin.
--
-- Two concerns, one migration:
--
-- 1. Resume versions keep the extraction report that produced them, so the
--    review screen can be reopened later and the user can see which fields the
--    AI inferred rather than read.
-- 2. Profile items record where they came from and whether the user has since
--    edited them. Re-importing a resume must never silently overwrite a
--    correction the user made by hand — `user_edited` is what protects it.

ALTER TABLE resume_versions ADD COLUMN extraction_report_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE resume_versions ADD COLUMN source_diagnosis TEXT NOT NULL DEFAULT '';

ALTER TABLE profile_items ADD COLUMN provenance TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE profile_items ADD COLUMN source_resume_version_id INTEGER
    REFERENCES resume_versions(id) ON DELETE SET NULL;
ALTER TABLE profile_items ADD COLUMN user_edited INTEGER NOT NULL DEFAULT 0;
ALTER TABLE profile_items ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0;

-- Profile scalar fields need the same protection as items: if the user typed
-- their own summary, an import must ask before replacing it.
ALTER TABLE profiles ADD COLUMN field_origin_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX idx_profile_items_source
    ON profile_items(source_resume_version_id);
