#!/bin/bash

set -e

echo "=================================================="
echo "Testing gRPC API - DL-SMS"
echo "=================================================="

cd /Users/muhanzhang/Documents/coding/project2/dlsms/grpc

echo -e "\nCompiling proto files..."
python -m grpc_tools.protoc -I./protos --python_out=. --grpc_python_out=. ./protos/library.proto

echo -e "\nRunning gRPC client tests..."
python client_test.py

echo -e "\n=================================================="
echo "All gRPC tests completed!"
echo "=================================================="
