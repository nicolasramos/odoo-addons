/** @file embed_semantic_search.js
 *  Client-side semantic search via runonweb/embed (all-MiniLM-L6-v2, 384-dim).
 *
 *  Design decisions
 *  ────────────────
 *  • Model download is **lazy**: zero downloads on page load; the model is
 *    fetched the first time the user explicitly enables semantic search.
 *  • Embeddings are stored in **IndexedDB** (keyed DB `wvc-embeddings`) with
 *    an on-disk vector index (brute-force cosine) — no server round-trip.
 *  • Semantic results are **mixed** with lexical results at the UI layer;
 *    the lexical pipeline is untouched and remains the default.
 *  • Size budget: 5 000 entries × 384 floats × 4 B ≈ 7,7 MB.  When the
 *    budget is exceeded the oldest 10 % are pruned.
 *  • WebGPU is used when available; a measured CPU fallback is shown to the
 *    user (no silent degradation).
 */

/* global runonweb */

(function () {
    "use strict";

    // ── Constants ──────────────────────────────────────────────────────

    /** HuggingFace repo for the ONNX model (matches stage 1 bundle). */
    const MODEL_REPO = "all-MiniLM-L6-v2";
    const MODEL_FILE = "model.onnx";
    const VOCAB_FILE = "tokenizer.json";
    const EMBED_DIM = 384;

    /** IndexedDB database name. */
    const DB_NAME = "wvc-embeddings";
    const DB_VERSION = 1;

    /** IndexedDB object store for vectors. */
    const STORE_NAME = "embeddings";

    /** Max entries before pruning (oldest 10 % removed). */
    const MAX_ENTRIES = 5000;
    const PRUNE_RATIO = 0.1;

    /** Per-entry size budget warning threshold (bytes of text). */
    const MAX_TEXT_LENGTH = 4096;

    /** Session cache TTL for unvectorised text (ms). */
    const SESSION_CACHE_TTL = 5 * 60 * 1000; // 5 minutes

    // ── IndexedDB helpers ──────────────────────────────────────────────

    /**
     * Open (or create) the IndexedDB database.
     * @returns {Promise<IDBDatabase>}
     */
    function openDB() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(STORE_NAME)) {
                    const store = db.createObjectStore(STORE_NAME, {
                        keyPath: "id",
                    });
                    store.createIndex("hash", "hash", { unique: true });
                    store.createIndex("created", "created", { unique: false });
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }

    /**
     * Save an embedding vector to IndexedDB.
     * @param {Object} entry - { id, hash, text, vector, created }
     * @returns {Promise<void>}
     */
    async function saveEmbedding(entry) {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, "readwrite");
            const store = tx.objectStore(STORE_NAME);
            entry.created = entry.created || Date.now();
            const putReq = store.put(entry);
            putReq.onsuccess = () => resolve();
            putReq.onerror = () => reject(putReq.error);
        });
    }

    /**
     * Load all embeddings from IndexedDB.
     * @returns {Promise<Array>} Array of { id, hash, text, vector, created }
     */
    async function loadAllEmbeddings() {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, "readonly");
            const store = tx.objectStore(STORE_NAME);
            const req = store.getAll();
            req.onsuccess = () => resolve(req.result || []);
            req.onerror = () => reject(req.error);
        });
    }

    /**
     * Delete embeddings by hash.
     * @param {string[]} hashes - Array of hashes to delete
     * @returns {Promise<void>}
     */
    async function deleteByHash(hashes) {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, "readwrite");
            const store = tx.objectStore(STORE_NAME);
            hashes.forEach((h) => store.delete(h));
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    }

    /**
     * Prune oldest entries when over budget.
     * @returns {Promise<void>}
     */
    async function pruneIfNeeded() {
        const all = await loadAllEmbeddings();
        if (all.length <= MAX_ENTRIES) return;

        const toPrune = Math.ceil(all.length * PRUNE_RATIO);
        // Sort by created ascending, take oldest
        all.sort((a, b) => a.created - b.created);
        const hashes = all.slice(0, toPrune).map((e) => e.hash);
        if (hashes.length) {
            await deleteByHash(hashes);
        }
    }

    // ── Session cache (in-memory, short-lived) ─────────────────────────

    /**
     * Simple LRU-like session cache for text → vector mapping.
     * Evicts entries older than SESSION_CACHE_TTL.
     */
    class SessionCache {
        constructor() {
            this.entries = new Map(); // hash -> { text, vector, timestamp }
        }

        has(hash) {
            return this.entries.has(hash);
        }

        get(hash) {
            const entry = this.entries.get(hash);
            if (!entry) return null;
            if (Date.now() - entry.timestamp > SESSION_CACHE_TTL) {
                this.entries.delete(hash);
                return null;
            }
            return entry.vector;
        }

        set(hash, text, vector) {
            this.entries.set(hash, { text, vector, timestamp: Date.now() });
            // Trim to 200 entries to bound memory
            if (this.entries.size > 200) {
                const oldest = Math.max(0, this.entries.size - 150);
                const sorted = [...this.entries.entries()].sort(
                    (a, b) => a[1].timestamp - b[1].timestamp
                );
                sorted.slice(0, oldest).forEach(([k]) => this.entries.delete(k));
            }
        }

        clear() {
            this.entries.clear();
        }
    }

    const sessionCache = new SessionCache();

    // ── Vector math ────────────────────────────────────────────────────

    /** Dot product of two float32 arrays. */
    function dotProduct(a, b) {
        let sum = 0;
        const len = Math.min(a.length, b.length);
        for (let i = 0; i < len; i++) {
            sum += a[i] * b[i];
        }
        return sum;
    }

    /** L2 norm of a float32 array. */
    function norm(v) {
        let sum = 0;
        for (let i = 0; i < v.length; i++) {
            sum += v[i] * v[i];
        }
        return Math.sqrt(sum);
    }

    /** Cosine similarity between two float32 arrays. */
    function cosineSimilarity(a, b) {
        const nA = norm(a);
        const nB = norm(b);
        if (nA === 0 || nB === 0) return 0;
        return dotProduct(a, b) / (nA * nB);
    }

    // ── Text normalisation ─────────────────────────────────────────────

    /**
     * Normalise text for embedding: lowercase, collapse whitespace,
     * strip control characters, truncate to MAX_TEXT_LENGTH.
     * @param {string} text
     * @returns {string}
     */
    function normaliseText(text) {
        if (typeof text !== "string") return "";
        return text
            .toLowerCase()
            .replace(/\s+/g, " ")
            .replace(/[^\x20-\x7E\u00A0-\u024F]/g, " ")
            .trim()
            .slice(0, MAX_TEXT_LENGTH);
    }

    /** Simple hash for deduplication (djb2 variant). */
    function hashText(text) {
        let hash = 5381;
        for (let i = 0; i < text.length; i++) {
            hash = (hash * 33) ^ text.charCodeAt(i);
        }
        return (hash >>> 0).toString(36);
    }

    // ── Model loading ──────────────────────────────────────────────────

    /**
     * Lazy-load the ONNX model via runonweb/embed.
     * Returns the loaded model instance or null on failure.
     * @returns {Promise<Object|null>} Model instance or null
     */
    async function loadModel() {
        if (!runonweb || !runonweb.embed) {
            console.warn("[embed] runonweb.embed not available");
            return null;
        }

        try {
            // runonweb.embed loads the model from the bundle cache
            // (pulled by stage 1's runonweb_bundle.js)
            const model = await runonweb.embed.load(MODEL_REPO, {
                modelFile: MODEL_FILE,
                vocabFile: VOCAB_FILE,
            });
            return model;
        } catch (err) {
            console.error("[embed] Failed to load model:", err);
            return null;
        }
    }

    /**
     * Check for WebGPU availability and report performance.
     * @returns {{ available: boolean, gpuName?: string, isWebGPU: boolean }}
     */
    function checkWebGPU() {
        if (typeof navigator === "undefined") {
            return { available: false, isWebGPU: false };
        }
        if (navigator.gpu) {
            try {
                const adapter = navigator.gpu.requestAdapter();
                if (adapter) {
                    return { available: true, gpuName: adapter.name || "WebGPU", isWebGPU: true };
                }
            } catch (_) {
                // requestAdapter can throw in some contexts
            }
        }
        return { available: false, isWebGPU: false };
    }

    // ── Embedding generation ───────────────────────────────────────────

    /**
     * Generate an embedding vector for a text string.
     * @param {Object} model - The runonweb/embed model instance
     * @param {string} text - Text to embed
     * @returns {Promise<Float32Array>} 384-dimensional vector
     */
    async function embedText(model, text) {
        const normalised = normaliseText(text);
        if (!normalised) {
            return new Float32Array(EMBED_DIM);
        }

        try {
            const result = await runonweb.embed.encode(model, normalised);
            // runonweb/embed returns a typed array or plain array
            const vector = Array.isArray(result)
                ? new Float32Array(result)
                : result;
            // Ensure correct dimension
            if (vector.length !== EMBED_DIM) {
                console.warn(
                    `[embed] Expected ${EMBED_DIM} dims, got ${vector.length}`
                );
            }
            return vector;
        } catch (err) {
            console.error("[embed] encode failed:", err);
            throw err;
        }
    }

    // ── Public API ─────────────────────────────────────────────────────

    /**
     * EmbedSemanticSearch — client-side semantic search engine.
     *
     * Usage:
     *   const engine = new EmbedSemanticSearch();
     *   await engine.init();
     *   await engine.addText("some text", "unique-id");
     *   const results = await engine.search("query text", { topK: 5 });
     */
    class EmbedSemanticSearch {
        constructor() {
            this._model = null;
            this._ready = false;
            this._loading = false;
            this._pruned = false;
        }

        /**
         * Initialise the engine — loads model lazily on first use.
         * @returns {Promise<void>}
         */
        async init() {
            if (this._ready || this._loading) return;
            this._loading = true;
            try {
                this._model = await loadModel();
                if (this._model) {
                    this._ready = true;
                } else {
                    console.warn("[embed] Model unavailable; semantic search disabled.");
                }
            } finally {
                this._loading = false;
            }
        }

        /** Check if the engine is ready to embed. */
        isReady() {
            return this._ready;
        }

        /** Get WebGPU status for diagnostics. */
        getWebGPUStatus() {
            return checkWebGPU();
        }

        /**
         * Add text for semantic indexing.
         * Skips if already indexed or text is too short.
         * @param {string} text - Text to embed
         * @param {string} id - Unique identifier for this entry
         * @returns {Promise<boolean>} true if indexed, false if skipped
         */
        async addText(text, id) {
            if (!this._ready) {
                await this.init();
                if (!this._ready) return false;
            }

            const normalised = normaliseText(text);
            if (normalised.length < 10) {
                // Skip very short text — too noisy for embeddings
                return false;
            }

            const hash = hashText(normalised);

            // Check session cache first
            const cached = sessionCache.get(hash);
            if (cached) {
                // Even from cache, persist to IndexedDB
                await saveEmbedding({
                    id,
                    hash,
                    text: normalised,
                    vector: cached,
                });
                return true;
            }

            // Check if already in IndexedDB
            const existing = await this._getByHash(hash);
            if (existing) {
                return true;
            }

            // Generate embedding
            const vector = await embedText(this._model, normalised);

            // Save to IndexedDB
            await saveEmbedding({ id, hash, text: normalised, vector });
            sessionCache.set(hash, normalised, vector);

            // Prune if over budget
            if (!this._pruned) {
                await pruneIfNeeded();
                this._pruned = true;
            }

            return true;
        }

        /**
         * Search for semantically similar texts.
         * @param {string} query - Search query
         * @param {Object} [options] - Search options
         * @param {number} [options.topK=10] - Number of results to return
         * @param {number} [options.minScore=0.3] - Minimum cosine similarity threshold
         * @returns {Promise<Array<{ id: string, text: string, score: number }>>}
         */
        async search(query, options = {}) {
            if (!this._ready) {
                await this.init();
                if (!this._ready) return [];
            }

            const topK = options.topK || 10;
            const minScore = options.minScore || 0.3;

            // Embed the query
            const queryVector = await embedText(this._model, query);

            // Load all stored embeddings and compute cosine similarity
            const all = await loadAllEmbeddings();
            const scored = [];

            for (const entry of all) {
                const score = cosineSimilarity(queryVector, entry.vector);
                if (score >= minScore) {
                    scored.push({
                        id: entry.id,
                        text: entry.text,
                        score: parseFloat(score.toFixed(4)),
                    });
                }
            }

            // Sort by score descending, take top K
            scored.sort((a, b) => b.score - a.score);
            return scored.slice(0, topK);
        }

        /**
         * Get an embedding by hash from IndexedDB.
         * @param {string} hash
         * @returns {Promise<Object|null>}
         */
        async _getByHash(hash) {
            const all = await loadAllEmbeddings();
            return all.find((e) => e.hash === hash) || null;
        }

        /**
         * Clear all stored embeddings.
         * @returns {Promise<void>}
         */
        async clear() {
            const db = await openDB();
            return new Promise((resolve, reject) => {
                const tx = db.transaction(STORE_NAME, "readwrite");
                const store = tx.objectStore(STORE_NAME);
                const req = store.clear();
                tx.oncomplete = () => {
                    sessionCache.clear();
                    resolve();
                };
                tx.onerror = () => reject(tx.error);
            });
        }

        /**
         * Get statistics about stored embeddings.
         * @returns {Promise<{ count: number, totalBytes: number, webGPU: object }>}
         */
        async stats() {
            const all = await loadAllEmbeddings();
            const totalBytes = all.length * (EMBED_DIM * 4 + 128); // vector + metadata
            return {
                count: all.length,
                totalBytes,
                webGPU: checkWebGPU(),
            };
        }
    }

    // ── Export ─────────────────────────────────────────────────────────

    // Make available on the global scope for Odoo JS integration
    if (typeof window !== "undefined") {
        window.EmbedSemanticSearch = EmbedSemanticSearch;
    }

    // Also export as ES module if supported
    if (typeof module !== "undefined" && module.exports) {
        module.exports = { EmbedSemanticSearch, cosineSimilarity, hashText, normaliseText };
    }
})();
