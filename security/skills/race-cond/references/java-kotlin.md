# Java/Kotlin Race Conditions

## Check-Then-Act

```java
// BUG: Value can change between check and use
if (map.containsKey(key)) {
    return map.get(key); // may return null if removed by another thread
}

// FIX: Use atomic operations
return map.computeIfAbsent(key, k -> createValue(k));

// Or use putIfAbsent for simple cases
Value existing = map.putIfAbsent(key, newValue);
return existing != null ? existing : newValue;
```

## Non-Atomic Compound Operations

```java
// BUG: ++ is not atomic (read-modify-write)
public class Counter {
    private int count = 0;
    
    public void increment() {
        count++; // race condition
    }
}

// FIX: Use AtomicInteger
public class Counter {
    private final AtomicInteger count = new AtomicInteger(0);
    
    public void increment() {
        count.incrementAndGet();
    }
}

// Or use synchronized
public class Counter {
    private int count = 0;
    
    public synchronized void increment() {
        count++;
    }
}
```

## Double-Checked Locking

```java
// BUG: Broken double-checked locking (pre-Java 5 or without volatile)
public class Singleton {
    private static Singleton instance;
    
    public static Singleton getInstance() {
        if (instance == null) {
            synchronized (Singleton.class) {
                if (instance == null) {
                    instance = new Singleton(); // may be seen partially constructed
                }
            }
        }
        return instance;
    }
}

// FIX: Use volatile (Java 5+)
public class Singleton {
    private static volatile Singleton instance;
    
    public static Singleton getInstance() {
        if (instance == null) {
            synchronized (Singleton.class) {
                if (instance == null) {
                    instance = new Singleton();
                }
            }
        }
        return instance;
    }
}

// BETTER: Use holder pattern (lazy, thread-safe, no synchronization)
public class Singleton {
    private static class Holder {
        static final Singleton INSTANCE = new Singleton();
    }
    
    public static Singleton getInstance() {
        return Holder.INSTANCE;
    }
}
```

## Collection Modification During Iteration

```java
// BUG: ConcurrentModificationException
for (String item : list) {
    if (shouldRemove(item)) {
        list.remove(item); // throws ConcurrentModificationException
    }
}

// FIX: Use iterator's remove method
Iterator<String> it = list.iterator();
while (it.hasNext()) {
    if (shouldRemove(it.next())) {
        it.remove();
    }
}

// Or use removeIf (Java 8+)
list.removeIf(item -> shouldRemove(item));

// For concurrent access, use ConcurrentHashMap or CopyOnWriteArrayList
ConcurrentHashMap<String, Value> map = new ConcurrentHashMap<>();
```

## Unsafe Publication

```java
// BUG: Object may be seen in partially constructed state
public class Holder {
    private Data data;
    
    public void initialize() {
        data = new Data(); // another thread may see data before constructor completes
    }
    
    public Data getData() {
        return data;
    }
}

// FIX: Use volatile or final
public class Holder {
    private volatile Data data;
    
    public void initialize() {
        data = new Data();
    }
    
    public Data getData() {
        return data;
    }
}

// BETTER: Make immutable with final
public class Holder {
    private final Data data;
    
    public Holder() {
        this.data = new Data(); // safely published via final field
    }
    
    public Data getData() {
        return data;
    }
}
```

## Lock Ordering Deadlock

```java
// BUG: Deadlock if thread 1 calls transfer(a, b) while thread 2 calls transfer(b, a)
public void transfer(Account from, Account to, int amount) {
    synchronized (from) {
        synchronized (to) {
            from.debit(amount);
            to.credit(amount);
        }
    }
}

// FIX: Always acquire locks in consistent order
public void transfer(Account from, Account to, int amount) {
    Account first = from.getId() < to.getId() ? from : to;
    Account second = from.getId() < to.getId() ? to : from;
    
    synchronized (first) {
        synchronized (second) {
            from.debit(amount);
            to.credit(amount);
        }
    }
}

// Or use tryLock with timeout
public void transfer(Account from, Account to, int amount) throws InterruptedException {
    while (true) {
        if (from.getLock().tryLock(100, TimeUnit.MILLISECONDS)) {
            try {
                if (to.getLock().tryLock(100, TimeUnit.MILLISECONDS)) {
                    try {
                        from.debit(amount);
                        to.credit(amount);
                        return;
                    } finally {
                        to.getLock().unlock();
                    }
                }
            } finally {
                from.getLock().unlock();
            }
        }
        Thread.sleep(10); // backoff before retry
    }
}
```

## Kotlin Coroutine Races

```kotlin
// BUG: Shared mutable state across coroutines
var counter = 0

suspend fun incrementAll() = coroutineScope {
    repeat(1000) {
        launch {
            counter++ // race condition
        }
    }
}

// FIX: Use Mutex
val mutex = Mutex()
var counter = 0

suspend fun incrementAll() = coroutineScope {
    repeat(1000) {
        launch {
            mutex.withLock {
                counter++
            }
        }
    }
}

// BETTER: Use AtomicInteger for simple counters
val counter = AtomicInteger(0)

suspend fun incrementAll() = coroutineScope {
    repeat(1000) {
        launch {
            counter.incrementAndGet()
        }
    }
}

// BEST: Use thread-safe data structures or single-threaded context
val counter = atomic(0) // from kotlinx.atomicfu

suspend fun incrementAll() = coroutineScope {
    repeat(1000) {
        launch {
            counter.incrementAndGet()
        }
    }
}
```

## Kotlin StateFlow/SharedFlow Races

```kotlin
// BUG: Check-then-act with StateFlow
class ViewModel {
    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state
    
    fun loadData() {
        if (_state.value == State.Idle) { // another coroutine may change this
            _state.value = State.Loading
            // load data...
        }
    }
}

// FIX: Use atomic update operations
class ViewModel {
    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state
    
    fun loadData() {
        _state.update { currentState ->
            if (currentState == State.Idle) State.Loading else currentState
        }
        if (_state.value == State.Loading) {
            // load data...
        }
    }
}

// Or use compareAndSet pattern
class ViewModel {
    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state
    
    fun loadData() {
        while (true) {
            val current = _state.value
            if (current != State.Idle) return
            if (_state.compareAndSet(current, State.Loading)) {
                // load data...
                break
            }
        }
    }
}
```

## ExecutorService Shutdown Race

```java
// BUG: Tasks may be rejected after shutdown check
if (!executor.isShutdown()) {
    executor.submit(task); // RejectedExecutionException if shutdown between check and submit
}

// FIX: Handle rejection
try {
    executor.submit(task);
} catch (RejectedExecutionException e) {
    // handle gracefully
}

// Or use a wrapper that handles this
public void safeSubmit(Runnable task) {
    try {
        executor.submit(task);
    } catch (RejectedExecutionException e) {
        if (!executor.isShutdown()) {
            throw e; // unexpected rejection
        }
        // expected during shutdown, handle gracefully
    }
}
```

## CompletableFuture Composition Race

```java
// BUG: Exception in one future may leave others hanging
CompletableFuture<A> futureA = loadA();
CompletableFuture<B> futureB = loadB();

// If futureA fails, futureB continues running unnecessarily
A a = futureA.join(); // throws if failed
B b = futureB.join();

// FIX: Use allOf with proper error handling
CompletableFuture<Void> both = CompletableFuture.allOf(futureA, futureB);
both.exceptionally(ex -> {
    futureA.cancel(true);
    futureB.cancel(true);
    return null;
});

try {
    both.join();
    A a = futureA.join();
    B b = futureB.join();
} catch (CompletionException e) {
    // handle failure
}
```

## Synchronized Method vs Synchronized Block

```java
// POTENTIAL ISSUE: Synchronized on 'this' allows external interference
public class Cache {
    public synchronized void put(String key, Object value) {
        // ...
    }
    
    public synchronized Object get(String key) {
        // ...
    }
}

// External code can interfere:
Cache cache = new Cache();
synchronized (cache) { // blocks all cache operations!
    Thread.sleep(10000);
}

// FIX: Use private lock object
public class Cache {
    private final Object lock = new Object();
    
    public void put(String key, Object value) {
        synchronized (lock) {
            // ...
        }
    }
    
    public Object get(String key) {
        synchronized (lock) {
            // ...
        }
    }
}
```

## Lazy Initialization in Kotlin

```kotlin
// BUG: lazy with LazyThreadSafetyMode.NONE in multi-threaded context
val config by lazy(LazyThreadSafetyMode.NONE) {
    loadConfig() // may be called multiple times
}

// FIX: Use default (synchronized) or PUBLICATION mode
val config by lazy { // default is SYNCHRONIZED
    loadConfig()
}

// Or PUBLICATION if multiple initializations are acceptable
val config by lazy(LazyThreadSafetyMode.PUBLICATION) {
    loadConfig() // may run multiple times, but only one value is used
}
```

## ReadWriteLock Pitfalls

```java
// BUG: Upgrading read lock to write lock causes deadlock
ReadWriteLock lock = new ReentrantReadWriteLock();

public void updateIfNeeded() {
    lock.readLock().lock();
    try {
        if (needsUpdate()) {
            lock.writeLock().lock(); // DEADLOCK: waiting for read lock to release
            try {
                doUpdate();
            } finally {
                lock.writeLock().unlock();
            }
        }
    } finally {
        lock.readLock().unlock();
    }
}

// FIX: Release read lock before acquiring write lock
public void updateIfNeeded() {
    lock.readLock().lock();
    boolean needsUpdate;
    try {
        needsUpdate = needsUpdate();
    } finally {
        lock.readLock().unlock();
    }
    
    if (needsUpdate) {
        lock.writeLock().lock();
        try {
            if (needsUpdate()) { // re-check under write lock
                doUpdate();
            }
        } finally {
            lock.writeLock().unlock();
        }
    }
}
```
