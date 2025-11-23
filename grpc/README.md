# DL-SMS gRPC Stack

Deployment and development guide for the gRPC architecture. This folder hosts the 5-node gRPC service behind an Nginx load balancer plus protos, client example, and build artifacts. The repo root `README.md` stays the source of truth; this doc focuses on gRPC-specific workflows.

## Architecture at a Glance

```
Client ─▶ Nginx (grpc-lb:9090, round-robin)
              ├─ grpc-app1 :9090
              ├─ grpc-app2 :9090
              ├─ grpc-app3 :9090
              ├─ grpc-app4 :9090
              └─ grpc-app5 :9090
                      │
            PostgreSQL :5433   Redis :6379
```

Each `grpc-app*` contains:
- `AuthService` / `SeatService` / `ReservationService` / `NotifyService`
- Background worker: auto NO_SHOW, complete expired reservations, invalidate caches
- Raft operation replication (`OperationService` + `raft.proto`) for multi-node consistency
- DB connection pool (10–100 per instance) plus Redis caching

## Quick Start (Docker)

```bash
# 1) Ensure .env exists (copied from repo root .env.example)
docker compose --profile rest down    # if REST stack is running
docker compose --profile grpc up -d   # start gRPC + LB
docker compose ps

# 2) Verify entrypoint
# gRPC ingress: localhost:9090 (via Nginx to app instances)

# 3) Run the bundled client test
python3 grpc/client_test.py
```


## Directory Layout

- `app/server.py`: full gRPC services + Raft + background worker
- `app/Dockerfile`: gRPC app image
- `app/requirements.txt`: Python deps
- `protos/*.proto`: gRPC/Raft interface definitions (stubs emitted to repo root)
- `nginx.conf`: Nginx gRPC upstream (defaults to first 3 instances; update if you expand)
- `client_test.py`: sample client and end-to-end sanity script

## File Tree (grpc/)

```
grpc/
├── README.md
├── client_test.py
├── nginx.conf
├── library_pb2.py            
├── library_pb2_grpc.py        
├── raft_pb2.py                
├── raft_pb2_grpc.py            
├── raft_test.py                # basic test
├── protos/
│   ├── library.proto           
│   └── raft.proto
└── app/
    ├── server.py
    ├── Dockerfile
    ├── requirements.txt
    ├── library.proto           # grpc API of DL-SMS
    └── raft.proto              # grpc API of system's raft
```

## How to test 
  start containers first
```
docker compose --profile=grpc build
docker compose --profile=grpc up -d
```
### Test case 1: Leader down
mannually stop the leader container and check whether there is a new leader in containers' logs
### Test case 2: Follower down
manually stop one follower container and check whether when a follower goes down, the system continues to operate normally
### Test case 3: Operations forward to leader correctly
issue an operation
```
python -m unittest raft_test.RaftDockerTest.test_leader_probe 
```
then check each container's log and check whether the operation is forwarded to the leader.
### Test case 4: Log recovery after follower reboot
issue an operation
```
python -m unittest raft_test.RaftDockerTest.test_leader_probe 
```
then mannually stop one follower container and restart it. Check whether it successfully updated its log from empty to the newest logs.
### Test case 5: Log replication correctness
issuse some operations
```
python -m unittest raft_test.RaftDockerTest.test_log_replication_correctness
```
then inspect each container's logs and check whether logs are successfully replicated from the leader to all follower nodes


## Things to emphasize
1. This system uses nginx as a load balancer and we can't control the request will be sent to which node. Therefore, in "Test case 3", if a request is directly sent to the leader, you can run "python -m unittest raft_test.RaftDockerTest.test_leader_probe" again to verify operation forward.
2. The result screenshots of each test case have been put in the final_report. If you feel confused about results which you got in the tests, you can check corresponding screenshots in the final report.

