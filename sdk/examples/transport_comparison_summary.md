# Transport Mechanism Comparison Summary

**Date**: October 24, 2025  
**Workload**: 10,000 events (JSON, ~80 bytes each)  
**Platform**: macOS 24.6.0, Apple Silicon

## Results

### File-based Transport (Baseline)
- **Mechanism**: Append-only file with `fsevents` notification
- **Latency (μs)**: Min=266, p50=5571, p95=10628, p99=11861, Max=21245
- **Time to first event**: 11.35 ms
- **Throughput**: 13,751 events/sec
- **CPU time**: User=0.08s, System=0.30s, Total=0.38s
- **Context switches**: 12,601 (all voluntary)

### FIFO (Named Pipe) Transport
- **Mechanism**: Named pipe with dual write (file + FIFO)
- **Latency (μs)**: Min=111, p50=1337, p95=3304, p99=3779, Max=10012145
- **Time to first event**: 4.54 ms
- **Throughput**: 939 events/sec
- **CPU time**: User=0.17s, System=0.31s, Total=0.49s
- **Context switches**: 23,190 (all voluntary)

### Unix Domain Socket Transport
- **Mechanism**: SOCK_STREAM with NDJSON
- **Latency (μs)**: Min=10, p50=129, p95=494, p99=778, Max=1893
- **Time to first event**: 0.13 ms
- **Throughput**: 47,869 events/sec
- **CPU time**: User=0.05s, System=0.03s, Total=0.09s
- **Context switches**: 6,262 (all voluntary)

## Analysis

### Latency
- **UDS wins decisively**: 43× lower p50 latency than file, 10× lower than FIFO
- File-based transport has highest latency due to `fsync()` + filesystem notification delay
- FIFO improves on file but still incurs dual-write overhead
- UDS has direct kernel-to-kernel transfer, no filesystem overhead

### Throughput
- **UDS wins**: 3.5× higher than file, 51× higher than FIFO
- FIFO suffers from dual-write overhead and pipe buffer management
- File transport limited by `fsync()` on every write
- UDS benefits from buffered socket I/O

### CPU Efficiency
- **UDS wins**: 4.4× less total CPU than file, 5.7× less than FIFO
- File transport spends most time in system calls (`fsync`, `fsevents`)
- FIFO has highest overhead due to dual write + select/poll
- UDS has minimal overhead (direct socket operations)

### Context Switches
- **UDS wins**: 2× fewer switches than file, 3.7× fewer than FIFO
- FIFO has most switches due to blocking I/O coordination between writer/reader
- File transport has moderate switches from `watchdog` polling
- UDS has fewest switches due to efficient socket buffer management

## Recommendations

### Use File-based Transport When:
- Durability is critical (events must survive crashes)
- Audit trail required
- Multiple consumers need to replay events
- Coordination across network boundaries
- Simplicity and debuggability matter most

### Use FIFO Transport When:
- You need both streaming and durability (dual write)
- Legacy systems expect named pipes
- Multiple consumers at different speeds

### Use Unix Domain Socket Transport When:
- Low latency is critical (< 200μs p50)
- High throughput required (> 40k events/sec)
- Single consumer per producer
- Local coordination only (same machine)
- CPU efficiency matters

## Conclusion

For local, high-performance agent coordination, **Unix domain sockets offer 40× better latency and 4× lower CPU usage** compared to file-based coordination. However, file-based coordination provides durability, debuggability, and network transparency that make it the right choice for most ConcordFS use cases.

The ~6ms p50 latency of file-based coordination is acceptable for most multi-agent workflows where agent think time dominates (100ms-10s per action). UDS would be the optimization target for high-frequency coordination patterns.

