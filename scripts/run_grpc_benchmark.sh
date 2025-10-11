#!/bin/bash

# gRPC Performance Benchmark Script
# Runs ghz benchmarks with different concurrency levels

set -e

RESULTS_DIR="/Users/muhanzhang/Documents/coding/project2/dlsms/bench/results"
mkdir -p "$RESULTS_DIR"

PROTO_FILE="/Users/muhanzhang/Documents/coding/project2/dlsms/grpc/protos/library.proto"

echo "=== gRPC Architecture Performance Benchmarks ==="
echo ""

# Benchmark function
run_benchmark() {
    local concurrency=$1
    local output_file=$2

    echo "Running benchmark with concurrency=$concurrency..."
    ghz --insecure \
        --proto="$PROTO_FILE" \
        --call=library.SeatService.GetSeats \
        -d '{"available_only": true}' \
        -c $concurrency \
        -z 30s \
        localhost:9090 > "$output_file"

    echo "  Results saved to: $output_file"
}

# Run benchmarks with different concurrency levels
echo "[1/3] Benchmarking with 50 concurrent connections..."
run_benchmark 50 "$RESULTS_DIR/grpc_seats_c50.txt"

echo ""
echo "[2/3] Benchmarking with 100 concurrent connections..."
run_benchmark 100 "$RESULTS_DIR/grpc_seats_c100.txt"

echo ""
echo "[3/3] Benchmarking with 200 concurrent connections..."
run_benchmark 200 "$RESULTS_DIR/grpc_seats_c200.txt"

echo ""
echo "=== gRPC Benchmarks Complete ==="
echo "Results saved in: $RESULTS_DIR"
