"""
Integration test for Raft leader election and log replication against the running
Docker-based gRPC cluster.

Default target is the load balancer at localhost:9090. To hit individual nodes
inside the Docker network, set RAFT_TARGETS to a comma-separated list such as
\"grpc-app1:9090,grpc-app2:9090,grpc-app3:9090\" and run this script from a
container attached to the same network (e.g. docker-compose --profile grpc run).
"""

import os
import sys
import time
import unittest
from typing import List

import grpc

# Ensure generated stubs are importable when run from repo root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "app")))

import raft_pb2  # noqa: E402
import raft_pb2_grpc  # noqa: E402


def make_channels(targets: List[str]):
    stubs = []
    for target in targets:
        channel = grpc.insecure_channel(target)
        stub = raft_pb2_grpc.RaftServiceStub(channel)
        stubs.append((target, stub))
    return stubs


class RaftDockerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        targets_env = os.getenv("RAFT_TARGETS", "localhost:9090")
        cls.targets = [t.strip() for t in targets_env.split(",") if t.strip()]
        cls.stubs = make_channels(cls.targets)

    def _wait_for_leader(self, timeout=10.0):
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            for target, stub in self.stubs:
                attempt += 1
                op = f"probe-{attempt}"
                print(f"Node test-client sends RPC SubmitOperation to Node {target}")
                try:
                    resp = stub.SubmitOperation(
                        raft_pb2.OperationRequest(operation=op, source_id="test-client"),
                        timeout=2.0,
                    )
                except grpc.RpcError as e:
                    print(f"[probe] RPC error to {target}: {e}")
                    continue

                if resp.success and resp.leader_id:
                    print(f"Detected leader {resp.leader_id} via {target}")
                    return resp.leader_id
            time.sleep(0.2)
        self.fail("Leader not detected within timeout")

    def test_leader_election_and_forwarding(self):
        leader_id = self._wait_for_leader()
        self.assertTrue(leader_id, "Leader ID should be non-empty")

        # Submit via each target to ensure forwarding to leader works
        for idx, (target, stub) in enumerate(self.stubs):
            op = f"op-{idx+1}"
            print(f"Node test-client sends RPC SubmitOperation to Node {target}")
            resp = stub.SubmitOperation(
                raft_pb2.OperationRequest(operation=op, source_id="test-client"),
                timeout=3.0,
            )
            self.assertTrue(resp.success, f"Operation via {target} failed: {resp.result}")
            self.assertEqual(resp.leader_id, leader_id, "Requests should route to the same leader")

        # Second round to check log can grow and commit multiple entries
        for idx, (target, stub) in enumerate(self.stubs):
            op = f"op-second-{idx+1}"
            print(f"Node test-client sends RPC SubmitOperation to Node {target}")
            resp = stub.SubmitOperation(
                raft_pb2.OperationRequest(operation=op, source_id="test-client"),
                timeout=3.0,
            )
            self.assertTrue(resp.success, f"Second operation via {target} failed: {resp.result}")
            self.assertEqual(resp.leader_id, leader_id)


if __name__ == "__main__":
    unittest.main()
