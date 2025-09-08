## System Architecture Overview

- **Processor**: `image_processor.py` orchestrates search → CLIP rank → download → optimize → route to approved/pending/declined → DB update → CLIP validation.
- **Search**: SerpAPI with retailer prioritization and learning-guided strategies. DB `search_cache` prevents repeat API calls.
- **GPU CLIP**: `src/clip_service.py` loads CLIP once (CUDA/MPS) and ranks candidate thumbnails. `clip_validator.py` validates downloaded images with OCR + quality heuristics.
- **OCR**: EasyOCR extracts brand/variant words to boost/penalize matches and enforce strict brand presence when configured.
- **DB**: `database.py` mirrors Excel columns and tracks image metadata, search cache, and learning feedback.

### Flow
1. Check local/DB cache for existing or cached URLs.
2. Query prioritized retailers; gather n candidates.
3. Download thumbnails; CLIP re-rank on GPU; pick best.
4. Score with variant/size/retailer trust + learning; download full; optimize.
5. Save to tiered folders; update DB; write JSON metadata.
6. Batch-run CLIP validation to mark approved/pending/declined.

### Strictness Controls
- `validation.strict_variant`: penalize wrong variant heavily.
- `validation.require_brand_ocr`: brand must appear in OCR text to auto-approve.
- `validation.size_tolerance_percent`: allow minor size variance.

### Config Keys
- `clip`: model, device preference, thresholds.
- `ocr`: enabled, languages, gpu.
- `search`: results_per_query, use_db_cache.

### Performance
- Async downloads with concurrency limits.
- CLIP model singleton + optional fp16/TF32.
- Result caching in-memory and in DB.

### Reliability
- File moves update DB safely and keep SKU in filenames.
- Path repair endpoints in `app.py`.

### Notes
- Apple Silicon uses MPS; NVIDIA uses CUDA.
- Ensure `opencv-python-headless` installed for server environments.
- **Package Compatibility**: Use numpy==1.26.4 with scikit-image==0.21.0 to avoid binary incompatibility errors.
- **Status Handling**: `not_found` products are reprocessable and included in remaining counts.
