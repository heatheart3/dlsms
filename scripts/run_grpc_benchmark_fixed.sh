#!/bin/bash

# gRPC Performance Benchmark with Fixed Connection Pool
# Tests realistic load scenarios without overwhelming the system

RESULT_DIR="bench/results"
mkdir -p "$RESULT_DIR"

echo "=== gRPC Performance Benchmark (with connection pool fix) ==="
echo "Connection pool: 5-50 per instance × 3 instances = 150 total"
echo ""

# Check if ghz is installed
if ! command -v ghz &> /dev/null; then
    echo "Installing ghz..."
    if command -v brew &> /dev/null; then
        brew install ghz
    elif command -v go &> /dev/null; then
        go install github.com/bojand/ghz/cmd/ghz@latest
    else
        echo "Error: Please install ghz manually"
        exit 1
    fi
fi

# Test Parameters
# Concurrency 50: Well within capacity (150 connections available)
echo "[1/3] Testing concurrency=50 (30s)"
ghz --insecure \
  --proto ./grpc/protos/library.proto \
  --call library.SeatService/GetSeats \
  -d '{"available_only":true}' \
  -c 50 \
  -z 30s \
  localhost:9090 \
  --format json \
  > "$RESULT_DIR/grpc_seats_c50_fixed.json" 2>&1

ghz --insecure \
  --proto ./grpc/protos/library.proto \
  --call library.SeatService/GetSeats \
  -d '{"available_only":true}' \
  -c 50 \
  -z 30s \
  localhost:9090 \
  > "$RESULT_DIR/grpc_seats_c50_fixed.txt" 2>&1

# Concurrency 100: At capacity limit
echo "[2/3] Testing concurrency=100 (30s)"
ghz --insecure \
  --proto ./grpc/protos/library.proto \
  --call library.SeatService/GetSeats \
  -d '{"available_only":true}' \
  -c 100 \
  -z 30s \
  localhost:9090 \
  --format json \
  > "$RESULT_DIR/grpc_seats_c100_fixed.json" 2>&1

ghz --insecure \
  --proto ./grpc/protos/library.proto \
  --call library.SeatService/GetSeats \
  -d '{"available_only":true}' \
  -c 100 \
  -z 30s \
  localhost:9090 \
  > "$RESULT_DIR/grpc_seats_c100_fixed.txt" 2>&1

# Concurrency 150: Slightly over capacity to test queuing
echo "[3/3] Testing concurrency=150 (30s)"
ghz --insecure \
  --proto ./grpc/protos/library.proto \
  --call library.SeatService/GetSeats \
  -d '{"available_only":true}' \
  -c 150 \
  -z 30s \
  localhost:9090 \
  --format json \
  > "$RESULT_DIR/grpc_seats_c150_fixed.json" 2>&1

ghz --insecure \
  --proto ./grpc/protos/library.proto \
  --call library.SeatService/GetSeats \
  -d '{"available_only":true}' \
  -c 150 \
  -z 30s \
  localhost:9090 \
  > "$RESULT_DIR/grpc_seats_c150_fixed.txt" 2>&1

echo ""
echo "=== Benchmark Complete ==="
echo "Results saved to: $RESULT_DIR/grpc_seats_c*_fixed.{txt,json}"
echo ""
echo "Summary:"
for file in "$RESULT_DIR"/grpc_seats_c*_fixed.txt; do
    echo "---"
    echo "File: $(basename $file)"
    grep -E "Requests/sec|Average|Fastest|Slowest|Status code" "$file" | head -10
done
