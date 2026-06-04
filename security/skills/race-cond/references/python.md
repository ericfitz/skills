# Python Race Conditions

## Check-Then-Act (TOCTOU)

```python
# BUG: File can be deleted between check and open
if os.path.exists(filepath):
    with open(filepath) as f:
        return f.read()

# FIX: EAFP pattern
try:
    with open(filepath) as f:
        return f.read()
except FileNotFoundError:
    return None
```

## Non-Atomic Increment

```python
# BUG: += is not atomic (read-modify-write)
counter = 0

def increment():
    global counter
    counter += 1  # race condition

# FIX: Use lock
from threading import Lock
lock = Lock()

def increment():
    global counter
    with lock:
        counter += 1
```

## Double-Checked Locking

```python
# BUG: Race between check and assignment
class Singleton:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()  # two threads can create
        return cls._instance

# FIX: Lock with double-check
import threading

class Singleton:
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
```

## Dict Modification During Iteration

```python
# BUG: RuntimeError: dictionary changed size
for key in my_dict:
    if should_remove(key):
        del my_dict[key]

# FIX: Iterate over copy
for key in list(my_dict.keys()):
    if should_remove(key):
        del my_dict[key]
```

## Async Lock vs Threading Lock

```python
# BUG: Wrong lock type for async
import threading
lock = threading.Lock()

async def bad():
    with lock:  # blocks event loop!
        await async_operation()

# FIX: Use asyncio.Lock for async
import asyncio
lock = asyncio.Lock()

async def good():
    async with lock:
        await async_operation()
```

## Holding Lock Across Await

```python
# BUG: Holds lock during I/O, starving others
async def bad_pattern():
    async with lock:
        await long_network_call()  # others blocked

# FIX: Minimize critical section
async def good_pattern():
    data = await long_network_call()  # I/O outside lock
    async with lock:
        process(data)  # only hold for memory ops
```

## GIL Misconceptions

The GIL doesn't protect against all races:

```python
# BUG: GIL releases during I/O
shared_list = []

def worker():
    data = fetch_from_network()  # GIL released here
    shared_list.append(data)  # another thread may interfere

# FIX: Explicit synchronization
lock = threading.Lock()

def worker():
    data = fetch_from_network()
    with lock:
        shared_list.append(data)
```

## File Handle Sharing

```python
# BUG: Interleaved writes corrupt output
file = open('log.txt', 'a')

def log(msg):
    file.write(msg + '\n')  # writes interleave

# FIX: Lock or per-thread handles
lock = threading.Lock()

def log(msg):
    with lock:
        file.write(msg + '\n')
        file.flush()
```

## Forgetting to Await

```python
# BUG: Coroutine never executes
async def process():
    fetch_data()  # returns coroutine object, doesn't run!
    # Warning: coroutine was never awaited

# FIX
async def process():
    await fetch_data()
```
