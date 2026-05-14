# TypeScript/JavaScript Race Conditions

## Check-Then-Act

```typescript
// BUG: Value can change between check and use
if (this.connection !== null) {
  await this.connection.query(sql); // may be null
}

// FIX: Capture reference
const conn = this.connection;
if (conn !== null) {
  await conn.query(sql);
}
```

## Read-Modify-Write Across Await

```typescript
// BUG: State can change during await
async increment() {
  const current = this.count;
  await someAsyncOp();
  this.count = current + 1; // overwrites concurrent changes
}

// FIX: No await between read and write
async increment() {
  this.count++;
  await someAsyncOp();
}
```

## Promise.all with Shared State

```typescript
// BUG: Concurrent pushes can corrupt array
const results: Result[] = [];
await Promise.all(items.map(async (item) => {
  const result = await process(item);
  results.push(result); // race condition
}));

// FIX: Use return values
const results = await Promise.all(items.map(item => process(item)));
```

## Missing Await

```typescript
// BUG: Returns before save completes
async function save(data: Data) {
  database.save(data); // missing await!
}

// FIX
async function save(data: Data) {
  await database.save(data);
}
```

## Memoization Race

```typescript
// BUG: Multiple calls compute same value
const cache = new Map<string, Promise<Result>>();

async function memoized(key: string) {
  if (!cache.has(key)) {
    const result = await compute(key); // both calls reach here
    cache.set(key, Promise.resolve(result));
    return result;
  }
  return cache.get(key)!;
}

// FIX: Store promise immediately
async function memoized(key: string) {
  if (!cache.has(key)) {
    cache.set(key, compute(key)); // store promise, not result
  }
  return cache.get(key)!;
}
```

## Event Handler Reentrancy

```typescript
// BUG: Rapid clicks bypass loading check
class DataManager {
  private loading = false;
  
  async onClick() {
    if (this.loading) return;
    this.loading = true;
    this.data = await fetchData();
    this.loading = false;
  }
}

// FIX: Track the request itself
class DataManager {
  private pending: Promise<Data> | null = null;
  
  async onClick() {
    if (this.pending) return;
    this.pending = fetchData();
    try {
      this.data = await this.pending;
    } finally {
      this.pending = null;
    }
  }
}
```

## Collection Modification During Iteration

```typescript
// BUG: Skips elements
for (const item of items) {
  if (shouldRemove(item)) {
    items.splice(items.indexOf(item), 1);
  }
}

// FIX: Filter to new array
items = items.filter(item => !shouldRemove(item));
```

## Async Mutex Pattern

When true mutual exclusion is needed:

```typescript
import { Mutex } from 'async-mutex';

class Resource {
  private mutex = new Mutex();
  
  async doWork() {
    const release = await this.mutex.acquire();
    try {
      await criticalSection();
    } finally {
      release();
    }
  }
}
```
