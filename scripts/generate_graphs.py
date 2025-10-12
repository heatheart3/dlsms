#!/usr/bin/env python3
"""
Generate performance comparison graphs for DL-SMS project
"""

import csv
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path

# Use non-interactive backend
matplotlib.use('Agg')

ROOT_DIR = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT_DIR / 'bench'
FIGURES_DIR = ROOT_DIR / 'figures'

def load_data(csv_path):
    """Load benchmark data from CSV"""
    data = {'REST': [], 'gRPC': []}

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            arch = row['architecture']
            data[arch].append({
                'concurrency': int(row['concurrency']),
                'rps': float(row['rps']),
                'p50_ms': float(row['p50_ms']),
                'p95_ms': float(row['p95_ms']),
                'p99_ms': float(row['p99_ms'])
            })

    # Sort by concurrency
    for arch in data:
        data[arch].sort(key=lambda x: x['concurrency'])

    return data

def generate_throughput_graph(data, output_path):
    """Generate throughput vs concurrency comparison"""
    fig, ax = plt.subplots(figsize=(10, 6))

    for arch, values in data.items():
        if values:
            concurrency = [v['concurrency'] for v in values]
            rps = [v['rps'] for v in values]
            ax.plot(concurrency, rps, marker='o', linewidth=2, markersize=8, label=arch)

    ax.set_xlabel('Concurrent Connections', fontsize=12)
    ax.set_ylabel('Requests per Second (RPS)', fontsize=12)
    ax.set_title('Throughput Comparison: REST vs gRPC', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()

    print(f"✓ Generated: {output_path}")

def generate_latency_graph(data, output_path):
    """Generate P95 latency vs concurrency comparison"""
    fig, ax = plt.subplots(figsize=(10, 6))

    for arch, values in data.items():
        if values:
            concurrency = [v['concurrency'] for v in values]
            p95 = [v['p95_ms'] for v in values]
            ax.plot(concurrency, p95, marker='s', linewidth=2, markersize=8, label=arch)

    ax.set_xlabel('Concurrent Connections', fontsize=12)
    ax.set_ylabel('P95 Latency (ms)', fontsize=12)
    ax.set_title('P95 Latency Comparison: REST vs gRPC', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()

    print(f"✓ Generated: {output_path}")

def generate_combined_metrics_graph(data, output_path):
    """Generate combined metrics graph showing RPS, P50, P95, P99"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))

    # RPS
    for arch, values in data.items():
        if values:
            concurrency = [v['concurrency'] for v in values]
            rps = [v['rps'] for v in values]
            ax1.plot(concurrency, rps, marker='o', linewidth=2, markersize=6, label=arch)

    ax1.set_xlabel('Concurrent Connections', fontsize=10)
    ax1.set_ylabel('Requests per Second', fontsize=10)
    ax1.set_title('Throughput (RPS)', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # P50 Latency
    for arch, values in data.items():
        if values:
            concurrency = [v['concurrency'] for v in values]
            p50 = [v['p50_ms'] for v in values]
            ax2.plot(concurrency, p50, marker='s', linewidth=2, markersize=6, label=arch)

    ax2.set_xlabel('Concurrent Connections', fontsize=10)
    ax2.set_ylabel('P50 Latency (ms)', fontsize=10)
    ax2.set_title('Median Latency (P50)', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    # P95 Latency
    for arch, values in data.items():
        if values:
            concurrency = [v['concurrency'] for v in values]
            p95 = [v['p95_ms'] for v in values]
            ax3.plot(concurrency, p95, marker='^', linewidth=2, markersize=6, label=arch)

    ax3.set_xlabel('Concurrent Connections', fontsize=10)
    ax3.set_ylabel('P95 Latency (ms)', fontsize=10)
    ax3.set_title('95th Percentile Latency (P95)', fontsize=12, fontweight='bold')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3)

    # P99 Latency
    for arch, values in data.items():
        if values:
            concurrency = [v['concurrency'] for v in values]
            p99 = [v['p99_ms'] for v in values]
            ax4.plot(concurrency, p99, marker='d', linewidth=2, markersize=6, label=arch)

    ax4.set_xlabel('Concurrent Connections', fontsize=10)
    ax4.set_ylabel('P99 Latency (ms)', fontsize=10)
    ax4.set_title('99th Percentile Latency (P99)', fontsize=12, fontweight='bold')
    ax4.legend(fontsize=9)
    ax4.grid(True, alpha=0.3)

    plt.suptitle('DL-SMS Performance Comparison: REST vs gRPC', fontsize=16, fontweight='bold', y=0.995)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()

    print(f"✓ Generated: {output_path}")

def main():
    figures_dir = FIGURES_DIR
    figures_dir.mkdir(exist_ok=True)

    csv_path = BENCH_DIR / 'performance_comparison.csv'

    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found!")
        return 1

    print("Loading benchmark data...")
    data = load_data(csv_path)

    print(f"  REST data points: {len(data['REST'])}")
    print(f"  gRPC data points: {len(data['gRPC'])}")
    print()

    print("Generating graphs...")
    generate_throughput_graph(data, figures_dir / 'throughput_vs_concurrency.png')
    generate_latency_graph(data, figures_dir / 'p95_latency_vs_concurrency.png')
    generate_combined_metrics_graph(data, figures_dir / 'combined_performance_metrics.png')

    print()
    print("✓ All graphs generated successfully!")
    print(f"  Output directory: {figures_dir}")

    return 0

if __name__ == '__main__':
    exit(main())
