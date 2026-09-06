// Cache only bounded image data, not full originals on every library record.
export class AssetCache {
  constructor(load, { maxEntries = 12, maxBytes = 32 * 1024 * 1024, concurrency = 4 } = {}) {
    this.load = load;
    this.maxEntries = maxEntries;
    this.maxBytes = maxBytes;
    this.concurrency = concurrency;
    this.entries = new Map();
    this.pending = new Map();
    this.queue = [];
    this.bytes = 0;
    this.active = 0;
  }

  remember(id, payload) {
    const size = String(payload?.dataUrl || "").length;
    const previous = this.entries.get(id);
    if (previous) this.bytes -= previous.size;
    this.entries.delete(id);
    if (!size || size > this.maxBytes) return payload;
    this.entries.set(id, { payload, size });
    this.bytes += size;
    while (this.entries.size > this.maxEntries || this.bytes > this.maxBytes) {
      const oldest = this.entries.keys().next().value;
      this.bytes -= this.entries.get(oldest).size;
      this.entries.delete(oldest);
    }
    return payload;
  }

  get(id) {
    const cached = this.entries.get(id);
    if (cached) {
      this.entries.delete(id);
      this.entries.set(id, cached);
      return Promise.resolve(cached.payload);
    }
    if (this.pending.has(id)) return this.pending.get(id);
    const promise = new Promise((resolve, reject) => {
      this.queue.push({ id, resolve, reject });
    });
    this.pending.set(id, promise);
    this.drain();
    return promise;
  }

  drain() {
    while (this.active < this.concurrency && this.queue.length) {
      const { id, resolve, reject } = this.queue.shift();
      this.active += 1;
      Promise.resolve().then(() => this.load(id))
        .then((payload) => {
          if (!payload?.dataUrl) throw new Error("图片资源为空");
          return this.remember(id, payload);
        }).then((payload) => {
          this.pending.delete(id);
          resolve(payload);
        }, (error) => {
          this.pending.delete(id);
          reject(error);
        }).finally(() => {
          this.active -= 1;
          this.drain();
        });
    }
  }
}
