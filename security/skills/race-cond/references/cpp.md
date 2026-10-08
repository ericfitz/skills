# C++ Race Conditions

Compile with `-fsanitize=thread` to detect races.

## Non-Atomic Shared Variable

```cpp
// BUG: Data race
int counter = 0;

void increment() {
    counter++; // read-modify-write not atomic
}

// FIX: Use std::atomic
std::atomic<int> counter{0};

void increment() {
    counter.fetch_add(1, std::memory_order_relaxed);
}
```

## Check-Then-Act

```cpp
// BUG: Pointer invalidated between check and use
if (ptr != nullptr) {
    ptr->doSomething(); // use-after-free possible
}

// FIX: Use shared_ptr with atomic load
auto local = std::atomic_load(&sharedPtr);
if (local) {
    local->doSomething();
}
```

## Double-Checked Locking (Broken)

```cpp
// BUG: Classic broken pattern
Singleton* instance = nullptr;

Singleton* getInstance() {
    if (instance == nullptr) {
        std::lock_guard<std::mutex> lock(mutex);
        if (instance == nullptr) {
            instance = new Singleton(); // can be reordered!
        }
    }
    return instance;
}

// FIX: C++11 static local (thread-safe)
Singleton& getInstance() {
    static Singleton instance;
    return instance;
}
```

## Memory Ordering Issues

```cpp
// BUG: Compiler/CPU reordering
bool ready = false;
int value = 0;

// Thread 1
value = 42;
ready = true;

// Thread 2
while (!ready) {}
assert(value == 42); // may fail!

// FIX: Use atomics with proper ordering
std::atomic<bool> ready{false};
std::atomic<int> value{0};

// Thread 1
value.store(42, std::memory_order_release);
ready.store(true, std::memory_order_release);

// Thread 2
while (!ready.load(std::memory_order_acquire)) {}
assert(value.load(std::memory_order_acquire) == 42);
```

## Iterator Invalidation

```cpp
// BUG: Erase invalidates iterator
std::vector<int> vec = {1, 2, 3, 4, 5};
for (auto it = vec.begin(); it != vec.end(); ++it) {
    if (*it % 2 == 0) {
        vec.erase(it); // undefined behavior
    }
}

// FIX: Use erase-remove idiom
vec.erase(
    std::remove_if(vec.begin(), vec.end(),
        [](int x) { return x % 2 == 0; }),
    vec.end()
);

// OR update iterator from erase return
for (auto it = vec.begin(); it != vec.end(); ) {
    if (*it % 2 == 0) {
        it = vec.erase(it);
    } else {
        ++it;
    }
}
```

## Destructor Race

```cpp
// BUG: Worker thread uses 'this' after destruction begins
class Resource {
    std::thread worker_;
    bool running_ = true;
    
public:
    ~Resource() {
        running_ = false; // not atomic, not visible
        worker_.join();
    }
    
    void workerLoop() {
        while (running_) { // may read stale value
            doWork();
        }
    }
};

// FIX: Use atomic
class Resource {
    std::thread worker_;
    std::atomic<bool> running_{true};
    
public:
    ~Resource() {
        running_.store(false, std::memory_order_release);
        worker_.join();
    }
};
```

## Signal Handler Races

```cpp
// BUG: Non-async-signal-safe in handler
volatile bool shutdown = false;
std::string lastError;

void handler(int sig) {
    lastError = "Signal!"; // malloc in signal handler!
    shutdown = true;
}

// FIX: Only sig_atomic_t and async-signal-safe functions
volatile sig_atomic_t shutdown = 0;

void handler(int sig) {
    shutdown = 1;
}
```

## False Sharing

```cpp
// BUG: Adjacent variables thrash cache
struct Counters {
    int counter1;
    int counter2; // same cache line
};

// FIX: Align to cache line
struct Counters {
    alignas(64) int counter1;
    alignas(64) int counter2;
};
```

## Lock Scope Issues

```cpp
// BUG: Lock scope too narrow
void update(int key, int value) {
    {
        std::lock_guard<std::mutex> lock(mutex);
        cache[key] = value;
    }
    notifyObservers(key); // observers see inconsistent state
}

// FIX: Include dependent operations
void update(int key, int value) {
    std::lock_guard<std::mutex> lock(mutex);
    cache[key] = value;
    notifyObservers(key);
}
```

## Condition Variable Spurious Wakeup

```cpp
// BUG: Not checking condition in loop
std::unique_lock<std::mutex> lock(mutex);
cv.wait(lock);
process(data); // may wake without data ready

// FIX: Always use predicate
std::unique_lock<std::mutex> lock(mutex);
cv.wait(lock, []{ return dataReady; });
process(data);
```

## RAII Lock Pattern

```cpp
// CORRECT: Always use RAII
{
    std::lock_guard<std::mutex> lock(mutex);
    // critical section
} // automatically unlocked

// For multiple mutexes, use std::scoped_lock (C++17)
{
    std::scoped_lock lock(mutex1, mutex2);
    // deadlock-free
}
```
