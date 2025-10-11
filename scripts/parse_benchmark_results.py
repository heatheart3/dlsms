#!/usr/bin/env python3
"""
Parse benchmark results from hey (REST) and ghz (gRPC) and generate CSV for graphing
"""

import re
import csv
from pathlib import Path

def parse_hey_result(file_path):
    """Parse hey benchmark output"""
    with open(file_path, 'r') as f:
        content = f.read()

    # Extract metrics
    rps = float(re.search(r'Requests/sec:\s+([\d.]+)', content).group(1))
    p50 = float(re.search(r'50% in ([\d.]+) secs', content).group(1)) * 1000  # Convert to ms
    p95 = float(re.search(r'95% in ([\d.]+) secs', content).group(1)) * 1000
    p99 = float(re.search(r'99% in ([\d.]+) secs', content).group(1)) * 1000

    return {'rps': rps, 'p50_ms': p50, 'p95_ms': p95, 'p99_ms': p99}

def parse_ghz_result(file_path):
    """Parse ghz benchmark output"""
    with open(file_path, 'r') as f:
        content = f.read()

    # Extract metrics
    rps_match = re.search(r'Requests/sec:\s+([\d.]+)', content)
    if not rps_match:
        # Fallback: calculate from count and total
        count = int(re.search(r'Count:\s+(\d+)', content).group(1))
        total = float(re.search(r'Total:\s+([\d.]+) s', content).group(1))
        rps = count / total
    else:
        rps = float(rps_match.group(1))

    # Parse latency distribution
    p50_match = re.search(r'50 % in ([\d.]+) ([sm])', content)
    p95_match = re.search(r'95 % in ([\d.]+) ([sm])', content)
    p99_match = re.search(r'99 % in ([\d.]+) ([sm])', content)

    def convert_to_ms(value, unit):
        if unit == 's':
            return float(value) * 1000
        return float(value)

    p50 = convert_to_ms(p50_match.group(1), p50_match.group(2)) if p50_match else 0
    p95 = convert_to_ms(p95_match.group(1), p95_match.group(2)) if p95_match else 0
    p99 = convert_to_ms(p99_match.group(1), p99_match.group(2)) if p99_match else 0

    return {'rps': rps, 'p50_ms': p50, 'p95_ms': p95, 'p99_ms': p99}

def main():
    results_dir = Path('/Users/muhanzhang/Documents/coding/project2/dlsms/bench/results')
    bench_dir = Path('/Users/muhanzhang/Documents/coding/project2/dlsms/bench')

    # Parse REST results
    rest_data = []
    for concurrency in [50, 100, 200]:
        file_path = results_dir / f'rest_seats_c{concurrency}.txt'
        if file_path.exists():
            try:
                metrics = parse_hey_result(file_path)
                rest_data.append({
                    'architecture': 'REST',
                    'concurrency': concurrency,
                    'instances': 6,  # 6 microservices
                    **metrics
                })
            except Exception as e:
                print(f"Warning: Could not parse {file_path}: {e}")

    # Parse gRPC results
    grpc_data = []
    for concurrency in [50, 100, 200]:
        file_path = results_dir / f'grpc_seats_c{concurrency}.txt'
        if file_path.exists():
            try:
                metrics = parse_ghz_result(file_path)
                grpc_data.append({
                    'architecture': 'gRPC',
                    'concurrency': concurrency,
                    'instances': 1,
                    **metrics
                })
            except Exception as e:
                print(f"Warning: Could not parse {file_path}: {e}")

    # Combine and save to CSV
    all_data = rest_data + grpc_data

    if all_data:
        csv_path = bench_dir / 'performance_comparison.csv'
        with open(csv_path, 'w', newline='') as csvfile:
            fieldnames = ['architecture', 'concurrency', 'instances', 'rps', 'p50_ms', 'p95_ms', 'p99_ms']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_data:
                writer.writerow(row)

        print(f"✓ Generated: {csv_path}")
        print(f"  Total rows: {len(all_data)}")
        print(f"  REST rows: {len(rest_data)}")
        print(f"  gRPC rows: {len(grpc_data)}")
    else:
        print("ERROR: No benchmark data found!")
        return 1

    return 0

if __name__ == '__main__':
    exit(main())
