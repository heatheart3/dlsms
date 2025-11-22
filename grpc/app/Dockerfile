FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create protos directory and copy proto file
RUN mkdir -p /app/protos
COPY *.proto /app/protos/

RUN python -m grpc_tools.protoc -I/app/protos --python_out=. --grpc_python_out=. /app/protos/library.proto /app/protos/raft.proto

COPY server.py .

EXPOSE 9090

CMD ["python", "-u", "server.py"]
