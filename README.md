# Distributed Library Seat Management System (DL-SMS) with Raft

**This project includes two architectures: REST and gRPC.
The Raft algorithm is implemented in the gRPC version.
Therefore, for subsequent testing and execution, please navigate to the ***grpc*** directory.**


## Team

- **Yang Song**
- **Zheng Zheng**

**Group 2**, Fall 2025

## Architecture

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
- Services of DLSMS `AuthService` / `SeatService` / `ReservationService` / `NotifyService`(Project 2)
- Background worker for DLSMS: auto NO_SHOW, complete expired reservations, invalidate caches(Project 2)
- **Raft operation replication (`OperationService` + `raft.proto`) for multi-node consistency**(Project 3)

## Quick Start (Docker)

```bash
docker compose --profile=grpc build
docker compose --profile=grpc up -d
```


## Directory Layout

- `app/server.py`: full gRPC services + background worker(Project 2) + Raft(Project 3)
- `protos/library.proto`: Seat reservation interface definitions 
- `protos/raft.proto`: Raft interface definitions 
- `nginx.conf`: Nginx gRPC upstream
- `raft_test.py`: include test cases

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
cd ./grpc
python -m unittest raft_test.RaftDockerTest.test_leader_probe 
```
then check each container's log and check whether the operation is forwarded to the leader.
### Test case 4: Log recovery after follower reboot
issue an operation
```
cd ./grpc
python -m unittest raft_test.RaftDockerTest.test_leader_probe 
```
then mannually stop one follower container and restart it. Check whether it successfully updated its log from empty to the newest logs.
### Test case 5: Log replication correctness
issuse some operations
```
python -m unittest raft_test.RaftDockerTest.test_log_replication_correctness
```
then inspect each container's logs and check whether logs are successfully replicated from the leader to all follower nodes


## Anything unusual about your solution that the TA should know
1. This system uses nginx as a load balancer and we can't control the request will be sent to which node. Therefore, in "Test case 3", if a request is directly sent to the leader, you can run "python -m unittest raft_test.RaftDockerTest.test_leader_probe" again to verify operation forward.
2. The result screenshots of each test case have been put in the final_report. If you feel confused about results which you got in the tests, you can check corresponding screenshots in the final report.
3. Because in the original systems design (Project 2), the severs are transparent to the client in which the only thing we know is the address of the loadbalancer. Therefore,  
