/**
 * embed_semantic_search.js — Client-side semantic search with runonweb/embed.
 *
 * Uses `all-MiniLM-L6-v2` (384-dim) for embedding user text. Vectors stored in
 * IndexedDB with cosine similarity search. Lazy-loaded: model only downloads
 * when the user explicitly activates semantic search.
 *
 * Inherits lazy-load + IndexedDB cache from Stage 1 (runonweb_bundle.js).
 */

import { _ } from "web_translate";
import { runonwebBridge } from "./runonweb_bridge";

// ──────────────────────────────────────────────────────────────────────────
// 0. Model configuration
// ──────────────────────────────────────────────────────────────────────────

const EMBED_MODEL_NAME = "all-MiniLM-L6-v2";
const EMBED_DIMENSIONS = 384;

// Session cache: 200 entries, 5-minute TTL
const SESSION_CACHE_MAX = 200;
const SESSION_CACHE_TTL_MS = 5 * 60 * 1000;

// IndexedDB limits: ~5,000 entries (~7.7 MB), evict oldest 10% when exceeded
const IDB_ENTRY_LIMIT = 5_000;
const IDB_EVICT_FRACTION = 0.1;

// Text preprocessing: truncate to this many characters
const MAX_TEXT_LENGTH = 4_096;

// ──────────────────────────────────────────────────────────────────────────
// 1. Text normalisation & hashing
// ──────────────────────────────────────────────────────────────────────────

/**
 * Normalise text before embedding: lowercase, collapse whitespace, strip
 * control characters, truncate.
 */
function normaliseText(text) {
  if (typeof text !== "string") return "";
  return (
    text
      .toLowerCase()
      .replace(/\s+/g, " ")
      .replace(/[\x00-\x1F\x7F-\x9F]/g, "")
      .slice(0, MAX_TEXT_LENGTH)
      .trim()
  );
}

/**
 * Simple djb2 hash for deduplication (not cryptographic).
 */
function djb2Hash(str) {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash + str.charCodeAt(i)) | 0;
  }
  return hash >>> 0; // unsigned
}

// ──────────────────────────────────────────────────────────────────────────
// 2. Session cache (in-memory, LRU-like with TTL)
// ──────────────────────────────────────────────────────────────────────────

class SessionCache {
  constructor() {
    this._entries = new Map(); // hash -> { embedding, timestamp }
  }

  get(hash) {
    const entry = this._entries.get(hash);
    if (!entry) return null;
    // TTL check
    if (Date.now() - entry.timestamp > SESSION_CACHE_TTL_MS) {
      this._entries.delete(hash);
      return null;
    }
    return entry.embedding;
  }

  set(hash, embedding) {
    // Evict oldest if at capacity
    if (this._entries.size >= SESSION_CACHE_MAX) {
      let oldestKey = null;
      let oldestTime = Infinity;
      for (const [k, v] of this._entries) {
        if (v.timestamp < oldestTime) {
          oldestTime = v.timestamp;
          oldestKey = k;
        }
      }
      if (oldestKey) this._entries.delete(oldestKey);
    }
    this._entries.set(hash, { embedding, timestamp: Date.now() });
  }

  clear() {
    this._entries.clear();
  }
}

// ──────────────────────────────────────────────────────────────────────────
// 3. IndexedDB vector store
// ──────────────────────────────────────────────────────────────────────────

const IDB_NAME = "runonweb_embed_vectors";
const IDB_STORE = "embeddings";
const IDB_VERSION = 1;

class VectorStore {
  constructor() {
    this._db = null;
  }

  async _openDB() {
    if (this._db) return this._db;
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(IDB_NAME, IDB_VERSION);
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(IDB_STORE)) {
          const store = db.createObjectStore(IDB_STORE, { keyPath: "hash" });
          store.createIndex("timestamp", "timestamp", { unique: false });
        }
      };
      request.onsuccess = () => {
        this._db = request.result;
        resolve(this._db);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async get(hash) {
    const db = await this._openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readonly");
      const store = tx.objectStore(IDB_STORE);
      const request = store.get(hash);
      request.onsuccess = () => resolve(request.result ? request.result.vector : null);
      request.onerror = () => reject(request.error);
    });
  }

  async put(hash, vector, timestamp) {
    const db = await this._openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      const store = tx.objectStore(IDB_STORE);
      store.put({ hash, vector, timestamp });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async delete(hash) {
    const db = await this._openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      const store = tx.objectStore(IDB_STORE);
      store.delete(hash);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async count() {
    const db = await this._openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readonly");
      const store = tx.objectStore(IDB_STORE);
      const request = store.count();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async evictOldest(fraction) {
    const db = await this._openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      const store = tx.objectStore(IDB_STORE);
      const index = store.index("timestamp");
      const countRequest = index.count();

      countRequest.onsuccess = () => {
        const toDelete = Math.ceil(countRequest.result * fraction);
        if (toDelete === 0) { resolve(); return; }

        // Fetch oldest entries
        const fetchRequest = index.openCursor(null); // ascending
        const hashes = [];
        fetchRequest.onsuccess = (event) => {
          const cursor = event.target.result;
          if (hashes.length < toDelete && cursor) {
            hashes.push(cursor.primaryKey);
            cursor.continue();
          } else {
            // Delete them
            const deleteTx = db.transaction(IDB_STORE, "readwrite");
            const deleteStore = deleteTx.objectStore(IDB_STORE);
            for (const h of hashes) deleteStore.delete(h);
            deleteTx.oncomplete = () => resolve();
            deleteTx.onerror = () => reject(deleteTx.error);
          }
        };
        fetchRequest.onerror = () => reject(fetchRequest.error);
      };
      countRequest.onerror = () => reject(countRequest.error);
    });
  }

  async clear() {
    const db = await this._openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      const store = tx.objectStore(IDB_STORE);
      store.clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }
}

// ──────────────────────────────────────────────────────────────────────────
// 4. Cosine similarity helper
// ──────────────────────────────────────────────────────────────────────────

function cosineSimilarity(a, b) {
  let dot = 0, normA = 0, normB = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

// ──────────────────────────────────────────────────────────────────────────
// 5. Semantic search engine
// ──────────────────────────────────────────────────────────────────────────

class EmbedSemanticSearch {
  constructor() {
    this._cache = new SessionCache();
    this._store = new VectorStore();
    this._modelReady = false;
    this._modelPromise = null;
    this._webgpuAvailable = false;
  }

  /** Check WebGPU availability (informational only). */
  async checkWebGPU() {
    try {
      this._webgpuAvailable = !!navigator.gpu;
    } catch {
      this._webgpuAvailable = false;
    }
    return this._webgpuAvailable;
  }

  /** Is WebGPU available? (cached after first check). */
  isWebGPUAvailable() {
    return this._webgpuAvailable;
  }

  /**
   * Lazy-load the embedding model. Returns a promise that resolves when the
   * model is ready, or rejects if loading fails.
   */
  async ensureModelReady() {
    if (this._modelReady) return true;
    if (this._modelPromise) return this._modelPromise;

    this._modelPromise = (async () => {
      try {
        const bridge = await runonwebBridge();
        const embedModule = await bridge.importEmbed();

        this._embedModel = await embedModule.loadModel(EMBED_MODEL_NAME, {
          dimensions: EMBED_DIMENSIONS,
        });

        this._modelReady = true;
      } catch (err) {
        console.error("[runonweb/embed] Model load failed:", err);
        throw new Error(_("Embeddings model could not be loaded: ") + err.message);
      }
    })();

    return this._modelPromise;
  }

  /**
   * Generate an embedding for normalised text.
   * Uses session cache → IndexedDB → model computation (in that order).
   */
  async computeEmbedding(text) {
    await this.ensureModelReady();

    const normalised = normaliseText(text);
    if (!normalised) return null;

    const hash = djb2Hash(normalised);

    // 1. Session cache
    const cached = this._cache.get(hash);
    if (cached) return cached;

    // 2. IndexedDB
    const dbVector = await this._store.get(hash);
    if (dbVector) {
      this._cache.set(hash, dbVector);
      return dbVector;
    }

    // 3. Compute via model
    const vector = await this._embedModel.compute(normalised);

    // Store in session cache and IndexedDB
    this._cache.set(hash, vector);
    await this._store.put(hash, vector, Date.now());

    // Enforce IndexedDB size limit
    const count = await this._store.count();
    if (count > IDB_ENTRY_LIMIT) {
      await this._store.evictOldest(IDB_EVICT_FRACTION);
    }

    return vector;
  }

  /**
   * Search a list of texts against a query, returning results sorted by
   * cosine similarity (descending). Each result: { text, score }.
   */
  async search(query, texts) {
    if (!texts || texts.length === 0) return [];

    const queryEmbedding = await this.computeEmbedding(query);
    if (!queryEmbedding) return [];

    const results = [];
    for (const text of texts) {
      const embedding = await this.computeEmbedding(text);
      if (!embedding) continue;
      const score = cosineSimilarity(queryEmbedding, embedding);
      if (score > 0) {
        results.push({ text, score });
      }
    }

    // Sort descending by similarity
    results.sort((a, b) => b.score - a.score);
    return results;
  }

  /** Clear all cached and stored embeddings. */
  async clearAll() {
    this._cache.clear();
    await this._store.clear();
  }

  /** Destroy the instance and release resources. */
  destroy() {
    this._cache.clear();
    this._modelReady = false;
    this._modelPromise = null;
    this._embedModel = null;
  }
}

// ──────────────────────────────────────────────────────────────────────────
// 6. Singleton export
// ──────────────────────────────────────────────────────────────────────────

let _instance = null;

export function getEmbedSemanticSearch() {
  if (!_instance) {
    _instance = new EmbedSemanticSearch();
  }
  return _instance;
}

export function destroyEmbedSemanticSearch() {
  if (_instance) {
    _instance.destroy();
    _instance = null;
  }
}

export { EmbedSemanticSearch };
