#!/usr/bin/env python3
"""
Benchmark: FIFO (named pipe) event transport with dual write

Measures latency, CPU usage, and context switches for named pipe
with simultaneous file logging for durability.
"""

import argparse
import json
import os
import sys
import time
import threading
import tempfile
import shutil
import select
from pathlib import Path
from typing import List
import statistics

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Warning: psutil not available, CPU/context switch metrics will be limited")


class FIFOReader(threading.Thread):
    """Reader that consumes events from FIFO."""
    
    def __init__(self, fifo_path: Path):
        super().__init__(daemon=True)
        self.fifo_path = fifo_path
        self.events_received = []
        self.lock = threading.Lock()
        self.running = True
        
    def run(self):
        """Read events from FIFO."""
        # Open FIFO for reading (blocks until writer connects)
        with open(self.fifo_path, 'r') as fifo:
            buffer = ""
            while self.running:
                # Use select to avoid blocking indefinitely
                ready, _, _ = select.select([fifo], [], [], 0.1)
                if ready:
                    chunk = fifo.read(4096)
                    if not chunk:
                        break
                    
                    buffer += chunk
                    lines = buffer.split('\n')
                    buffer = lines[-1]  # Keep incomplete line
                    
                    for line in lines[:-1]:
                        if line.strip():
                            try:
                                event = json.loads(line)
                                receive_time = time.perf_counter()
                                with self.lock:
                                    self.events_received.append({
                                        'event': event,
                                        'receive_time': receive_time
                                    })
                            except json.JSONDecodeError:
                                pass
    
    def stop(self):
        """Stop the reader thread."""
        self.running = False
    
    def get_events(self) -> List[dict]:
        """Get all received events."""
        with self.lock:
            return list(self.events_received)


class FIFOWriter:
    """Writer that sends events to FIFO and file."""
    
    def __init__(self, fifo_path: Path, log_path: Path):
        self.fifo_path = fifo_path
        self.log_path = log_path
        self.fifo_fd = None
        
    def open(self):
        """Open FIFO for writing."""
        # Open FIFO in non-blocking mode to avoid hanging
        self.fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    
    def write_event(self, event: dict) -> float:
        """Write event to both FIFO and file, return send time."""
        send_time = time.perf_counter()
        event['send_time'] = send_time
        
        event_json = json.dumps(event) + '\n'
        event_bytes = event_json.encode('utf-8')
        
        # Write to FIFO first (streaming)
        if self.fifo_fd is not None:
            try:
                os.write(self.fifo_fd, event_bytes)
            except (BrokenPipeError, OSError):
                pass  # Reader may have disconnected
        
        # Write to file for durability
        fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, event_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        
        return send_time
    
    def close(self):
        """Close FIFO."""
        if self.fifo_fd is not None:
            os.close(self.fifo_fd)
            self.fifo_fd = None


def run_benchmark(num_events: int, base_path: Path):
    """Run FIFO transport benchmark."""
    
    print(f"=== FIFO Transport Benchmark ===")
    print(f"Events: {num_events}")
    print(f"Base path: {base_path}")
    print()
    
    # Setup
    fifo_path = base_path / "events.fifo"
    log_path = base_path / "events.jsonl"
    base_path.mkdir(parents=True, exist_ok=True)
    
    # Create FIFO
    if fifo_path.exists():
        fifo_path.unlink()
    os.mkfifo(fifo_path)
    
    # Start reader thread
    reader = FIFOReader(fifo_path)
    reader.start()
    
    # Wait for reader to open FIFO
    time.sleep(0.1)
    
    # Capture initial resource usage
    if HAS_PSUTIL:
        process = psutil.Process()
        initial_cpu_times = process.cpu_times()
        try:
            initial_ctx_switches = process.num_ctx_switches()
        except AttributeError:
            initial_ctx_switches = None
    else:
        process = None
        initial_cpu_times = None
        initial_ctx_switches = None
    
    # Initialize writer
    writer = FIFOWriter(fifo_path, log_path)
    writer.open()
    
    # Benchmark start
    t0 = time.perf_counter()
    
    # Write events
    send_times = []
    for i in range(num_events):
        event = {
            'id': i,
            'type': 'test_event',
            'data': f'payload_{i}'
        }
        send_time = writer.write_event(event)
        send_times.append(send_time)
        
        # Small delay to avoid overwhelming the pipe buffer
        if i % 100 == 0:
            time.sleep(0.001)
    
    # Wait for all events to be received
    timeout = 10.0
    wait_start = time.perf_counter()
    while len(reader.get_events()) < num_events:
        time.sleep(0.01)
        if time.perf_counter() - wait_start > timeout:
            print(f"Warning: Timeout waiting for events. Received {len(reader.get_events())}/{num_events}")
            break
    
    t1 = time.perf_counter()
    
    # Cleanup
    writer.close()
    reader.stop()
    reader.join(timeout=1.0)
    
    # Capture final resource usage
    if HAS_PSUTIL:
        final_cpu_times = process.cpu_times()
        try:
            final_ctx_switches = process.num_ctx_switches()
        except AttributeError:
            final_ctx_switches = None
    else:
        final_cpu_times = None
        final_ctx_switches = None
    
    # Calculate metrics
    received_events = reader.get_events()
    latencies = []
    
    for recv in received_events:
        event = recv['event']
        receive_time = recv['receive_time']
        send_time = event['send_time']
        latency_us = (receive_time - send_time) * 1_000_000
        latencies.append(latency_us)
    
    # Print results
    print("=== Results ===")
    print(f"Total time: {(t1 - t0) * 1000:.2f} ms")
    print(f"Events sent: {num_events}")
    print(f"Events received: {len(received_events)}")
    print()
    
    if latencies:
        latencies_sorted = sorted(latencies)
        print(f"Latency (μs):")
        print(f"  Min:  {min(latencies):.2f}")
        print(f"  p50:  {statistics.median(latencies):.2f}")
        print(f"  p95:  {latencies_sorted[int(len(latencies_sorted) * 0.95)]:.2f}")
        print(f"  p99:  {latencies_sorted[int(len(latencies_sorted) * 0.99)]:.2f}")
        print(f"  Max:  {max(latencies):.2f}")
        print(f"  Mean: {statistics.mean(latencies):.2f}")
        print()
    
    # Time to first event
    if received_events:
        first_event_time = received_events[0]['receive_time'] - t0
        print(f"Time to first event: {first_event_time * 1000:.2f} ms")
        print()
    
    # Throughput
    if t1 > t0:
        throughput = len(received_events) / (t1 - t0)
        print(f"Throughput: {throughput:.2f} events/sec")
        print()
    
    # CPU and context switches
    if HAS_PSUTIL and initial_cpu_times and final_cpu_times:
        user_cpu = final_cpu_times.user - initial_cpu_times.user
        system_cpu = final_cpu_times.system - initial_cpu_times.system
        total_cpu = user_cpu + system_cpu
        
        print(f"CPU time:")
        print(f"  User:   {user_cpu:.4f} s")
        print(f"  System: {system_cpu:.4f} s")
        print(f"  Total:  {total_cpu:.4f} s")
        print()
        
        if initial_ctx_switches and final_ctx_switches:
            voluntary = final_ctx_switches.voluntary - initial_ctx_switches.voluntary
            involuntary = final_ctx_switches.involuntary - initial_ctx_switches.involuntary
            
            print(f"Context switches:")
            print(f"  Voluntary:   {voluntary}")
            print(f"  Involuntary: {involuntary}")
            print(f"  Total:       {voluntary + involuntary}")
            print()
    
    return {
        'num_events': num_events,
        'events_received': len(received_events),
        'total_time_ms': (t1 - t0) * 1000,
        'latencies_us': latencies,
        'time_to_first_ms': first_event_time * 1000 if received_events else None,
        'throughput_eps': throughput if t1 > t0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description='Benchmark FIFO-based event transport')
    parser.add_argument('--events', type=int, default=10000, help='Number of events to send')
    parser.add_argument('--workdir', type=str, default=None, help='Working directory (default: temp)')
    args = parser.parse_args()
    
    # Create working directory
    if args.workdir:
        base_path = Path(args.workdir)
        base_path.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        base_path = Path(tempfile.mkdtemp(prefix='transport_fifo_'))
        cleanup = True
    
    try:
        run_benchmark(args.events, base_path)
    finally:
        if cleanup:
            shutil.rmtree(base_path, ignore_errors=True)


if __name__ == '__main__':
    main()


