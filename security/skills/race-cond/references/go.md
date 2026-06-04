# Go Race Conditions

Run `go test -race ./...` to detect races automatically.

## Map Concurrent Access

```go
// BUG: fatal error: concurrent map read and map write
var cache = make(map[string]string)

// Goroutine 1
cache["key"] = "value"

// Goroutine 2
val := cache["key"]

// FIX: Use sync.Map
var cache sync.Map

cache.Store("key", "value")
val, _ := cache.Load("key")

// OR mutex
var (
    cache = make(map[string]string)
    mu    sync.RWMutex
)

mu.Lock()
cache["key"] = "value"
mu.Unlock()
```

## Check-Then-Act

```go
// BUG: Entry deleted between check and use
if val, ok := cache[key]; ok {
    process(cache[key]) // may panic or return zero value
}

// FIX: Use captured value
if val, ok := cache[key]; ok {
    process(val)
}
```

## Non-Atomic Counter

```go
// BUG: Data race
var counter int

func increment() {
    counter++
}

// FIX: Use atomic
var counter int64

func increment() {
    atomic.AddInt64(&counter, 1)
}
```

## Singleton with sync.Once

```go
// BUG: Race condition
var instance *Config

func GetConfig() *Config {
    if instance == nil {
        instance = loadConfig()
    }
    return instance
}

// FIX: Use sync.Once
var (
    instance *Config
    once     sync.Once
)

func GetConfig() *Config {
    once.Do(func() {
        instance = loadConfig()
    })
    return instance
}
```

## Goroutine Leak

```go
// BUG: Goroutine blocks forever if caller abandons
func startWorker() {
    results := make(chan Result)
    go func() {
        results <- doWork() // blocks forever if not read
    }()
    return nil, errors.New("changed mind")
}

// FIX: Buffered channel + context
func startWorker(ctx context.Context) (*Result, error) {
    results := make(chan Result, 1)
    go func() {
        select {
        case results <- doWork():
        case <-ctx.Done():
        }
    }()
    
    select {
    case r := <-results:
        return &r, nil
    case <-ctx.Done():
        return nil, ctx.Err()
    }
}
```

## Double Close Channel

```go
// BUG: panic: close of closed channel
close(ch)
close(ch)

// FIX: Use sync.Once
var closeOnce sync.Once

func safeClose(ch chan int) {
    closeOnce.Do(func() { close(ch) })
}
```

## Range Over Nil Channel

```go
// BUG: Blocks forever
var ch chan int // nil

for val := range ch {
    fmt.Println(val)
}

// FIX: Initialize channel
ch := make(chan int)
```

## Unsafe Publication

```go
// BUG: Struct fields may not be visible to other goroutines
var config *Config

func init() {
    config = &Config{Host: "localhost", Port: 8080}
}

// FIX: Use atomic.Value
var config atomic.Value

func init() {
    config.Store(&Config{Host: "localhost", Port: 8080})
}

func getConfig() *Config {
    return config.Load().(*Config)
}
```

## Channel Deadlock

```go
// BUG: Both goroutines waiting on each other
func process(in, out chan int) {
    val := <-in
    out <- val
}
// Two goroutines with swapped channels = deadlock

// FIX: Use select with timeout
func process(in, out chan int, timeout time.Duration) {
    select {
    case val := <-in:
        select {
        case out <- val:
        case <-time.After(timeout):
        }
    case <-time.After(timeout):
    }
}
```

## False Sharing

```go
// BUG: Counters on same cache line cause contention
type Counters struct {
    counter1 int64
    counter2 int64
}

// FIX: Pad to cache line
type Counters struct {
    counter1 int64
    _        [56]byte
    counter2 int64
}
```
