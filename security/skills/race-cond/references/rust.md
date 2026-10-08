# Rust Race Conditions

Rust's ownership system prevents most data races at compile time. Focus on these areas:

## Holding Mutex Guard Across Await

```rust
// BUG: std::sync::Mutex held across await blocks executor
use std::sync::Mutex;

async fn bad() {
    let guard = mutex.lock().unwrap();
    some_async_op().await; // deadlock risk!
}

// FIX: Use tokio::sync::Mutex for async
use tokio::sync::Mutex;

async fn good() {
    let guard = mutex.lock().await;
    some_async_op().await; // safe
}
```

## Arc<Mutex> Guard Lifetime

```rust
// BUG: Guard held too long
let data = Arc::new(Mutex::new(vec![]));
let data_clone = Arc::clone(&data);

// Thread 1
let mut vec = data.lock().unwrap();
vec.push(1);
// Guard still held - other threads blocked

// FIX: Scope the guard explicitly
{
    let mut vec = data.lock().unwrap();
    vec.push(1);
} // Guard dropped here
```

## Check-Then-Act with Mutex

```rust
// BUG: Lock released between check and action
if mutex.lock().unwrap().is_some() {
    let val = mutex.lock().unwrap().take(); // may be None now
}

// FIX: Hold lock for entire operation
let mut guard = mutex.lock().unwrap();
if guard.is_some() {
    let val = guard.take();
}
```

## RefCell in Multithreaded Context

```rust
// BUG: RefCell is not thread-safe
use std::cell::RefCell;

let data = RefCell::new(vec![1, 2, 3]);
// Sharing across threads = compile error (RefCell: !Sync)

// If you use unsafe to bypass: runtime panic on concurrent borrow

// FIX: Use RwLock or Mutex
use std::sync::RwLock;
let data = RwLock::new(vec![1, 2, 3]);
```

## Lazy Static Initialization

```rust
// CORRECT: Use once_cell or lazy_static
use once_cell::sync::Lazy;

static CONFIG: Lazy<Config> = Lazy::new(|| {
    Config::load()
});

// Or std::sync::OnceLock (Rust 1.70+)
use std::sync::OnceLock;

static CONFIG: OnceLock<Config> = OnceLock::new();

fn get_config() -> &'static Config {
    CONFIG.get_or_init(|| Config::load())
}
```

## Unsafe Blocks with Shared State

```rust
// BUG: Unsafe bypasses Rust's guarantees
static mut COUNTER: i32 = 0;

fn increment() {
    unsafe {
        COUNTER += 1; // data race!
    }
}

// FIX: Use AtomicI32
use std::sync::atomic::{AtomicI32, Ordering};

static COUNTER: AtomicI32 = AtomicI32::new(0);

fn increment() {
    COUNTER.fetch_add(1, Ordering::SeqCst);
}
```

## Send/Sync Trait Violations

```rust
// Compiler prevents most issues, but watch for:

// 1. Rc in threaded context (Rc: !Send)
// 2. Raw pointers in unsafe impl Send/Sync
// 3. Interior mutability with incorrect bounds

// When implementing unsafe impl, audit carefully:
unsafe impl Send for MyType {}
unsafe impl Sync for MyType {}
// Ask: Can this truly be safely shared/sent?
```

## Deadlock with Multiple Mutexes

```rust
// BUG: Inconsistent lock order
fn transfer(from: &Mutex<Account>, to: &Mutex<Account>) {
    let _from = from.lock().unwrap();
    let _to = to.lock().unwrap(); // deadlock if called with args swapped
}

// FIX: Consistent ordering by address
fn transfer(a: &Mutex<Account>, b: &Mutex<Account>) {
    let (first, second) = if std::ptr::addr_of!(*a) < std::ptr::addr_of!(*b) {
        (a, b)
    } else {
        (b, a)
    };
    let _first = first.lock().unwrap();
    let _second = second.lock().unwrap();
}
```

## Async Race with Shared State

```rust
// BUG: Multiple tasks modify shared state
let counter = Arc::new(Mutex::new(0));

let handles: Vec<_> = (0..10).map(|_| {
    let counter = Arc::clone(&counter);
    tokio::spawn(async move {
        let mut guard = counter.lock().await;
        *guard += 1;
    })
}).collect();

// This is actually CORRECT - Mutex serializes access
// But watch for: reading outside the lock, assuming ordering
```
