import os
import sys
import random
import grpc
import psycopg2
from psycopg2 import pool
import redis
import bcrypt
import jwt
import json
import time
import threading
from datetime import datetime, timedelta
from concurrent import futures
from psycopg2.extras import RealDictCursor

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import library_pb2
import library_pb2_grpc
import raft_pb2
import raft_pb2_grpc

# Shared Raft node instance for logging hooks
RAFT_NODE_INSTANCE = None

DATABASE_URL = os.getenv('DATABASE_URL')
REDIS_URL = os.getenv('REDIS_URL')
JWT_SECRET = os.getenv('JWT_SECRET', 'your-secret-key')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))
GRACE_MINUTES = int(os.getenv('GRACE_MINUTES', '15'))
DB_MAX_CONCURRENT = int(os.getenv('DB_MAX_CONCURRENT', '60'))
RAFT_HEARTBEAT_INTERVAL = 1.0
RAFT_ELECTION_TIMEOUT_RANGE = (1.5, 3.0)
RAFT_NODE_ID = str(os.getenv('RAFT_NODE_ID') or os.getenv('INSTANCE_ID') or 'node-1')
RAFT_SELF_ADDRESS = os.getenv('RAFT_SELF_ADDRESS')
RAFT_PEERS_RAW = os.getenv('RAFT_PEERS', '')
RAFT_RPC_TIMEOUT = float(os.getenv('RAFT_RPC_TIMEOUT', '0.75'))

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
db_semaphore = threading.BoundedSemaphore(DB_MAX_CONCURRENT)

# Connection pool: min 10, max 100 connections per instance
# With 3 instances: total 300 connections (matching PostgreSQL max_connections=300)
connection_pool = None

def init_connection_pool():
    global connection_pool
    try:
        connection_pool = pool.ThreadedConnectionPool(
            minconn=10,
            maxconn=100,
            dsn=DATABASE_URL
        )
        print(f"Database connection pool initialized (10-100 connections)")
    except Exception as e:
        print(f"Error creating connection pool: {e}")
        raise

def get_db_connection():
    """Get a connection from the pool"""
    try:
        return connection_pool.getconn()
    except Exception as e:
        print(f"Error getting connection from pool: {e}")
        raise

def return_db_connection(conn):
    """Return a connection to the pool"""
    try:
        if conn:
            connection_pool.putconn(conn)
    except Exception as e:
        print(f"Error returning connection to pool: {e}")

def generate_jwt(user_id, student_id):
    payload = {
        'user_id': user_id,
        'student_id': student_id,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise Exception('Token expired')
    except jwt.InvalidTokenError:
        raise Exception('Invalid token')

def invalidate_seat_cache(seat_id):
    try:
        redis_client.delete(f"seat:{seat_id}")
        keys = redis_client.keys(f"seats:*")
        for key in keys:
            redis_client.delete(key)
    except Exception as e:
        print(f"Cache invalidation error: {e}")


def parse_peer_config(raw_peers, node_id, self_address=None):
    peers = []
    for raw in raw_peers.split(','):
        entry = raw.strip()
        if not entry:
            continue
        if '@' in entry:
            peer_id, address = entry.split('@', 1)
        else:
            peer_id, address = entry, entry

        if peer_id == node_id or (self_address and address == self_address):
            continue

        peers.append({'id': peer_id or address, 'address': address})
    return peers


def submit_raft_operation_log(operation: str):
    """Send a best-effort operation log to the Raft leader for replication."""
    node = RAFT_NODE_INSTANCE
    if not node:
        return
    leader_address = node._get_leader_address() or node.self_address
    if not leader_address:
        return
    leader_id = node.leader_id or node.node_id
    try:
        stub = node._get_stub_by_address(leader_address, leader_id)
        node._log_client("SubmitOperation", leader_id)
        response = stub.SubmitOperation(
            raft_pb2.OperationRequest(operation=operation, source_id=node.node_id),
            timeout=RAFT_RPC_TIMEOUT
        )
        if not response.success:
            print(f"[Raft] Operation log not committed: {response.result}")
    except Exception as e:
        print(f"[Raft] Failed to submit operation log: {e}")


class RaftNode(raft_pb2_grpc.RaftServiceServicer):
    def __init__(self, node_id, peers, self_address=None):
        self.node_id = str(node_id)
        self.peers = peers
        self.self_address = self_address
        self.id_to_address = {}
        if self_address:
            self.id_to_address[self.node_id] = self_address
        for peer in peers:
            self.id_to_address[peer['id']] = peer['address']

        self.current_term = 0
        self.voted_for = None
        self.leader_id = None
        self.role = 'follower'
        self.log = []
        self.commit_index = 0
        self.last_applied = 0
        self.pending_events = {}
        self.pending_results = {}

        self.state_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.last_heartbeat = time.time()
        self.last_heartbeat_sent = 0.0
        self.election_timeout = self._random_election_timeout()

        self.peer_channels = {}
        self.peer_stubs = {}
        self.monitor_thread = None

        self.last_p_log_time = 0

        self.failed_time={}
        for peer in self.peers:
            self.failed_time[peer["id"]] = 0
        print(self.role)


    def start(self):
        if not self.monitor_thread:
            self.monitor_thread = threading.Thread(target=self._run, daemon=True)
            self.monitor_thread.start()

    def _random_election_timeout(self):
        return random.uniform(*RAFT_ELECTION_TIMEOUT_RANGE)

    def _majority(self):
        return (len(self.peers) + 1) // 2 + 1

    def _log_client(self, rpc_name, peer_id):
        print(f"Node {self.node_id} sends RPC {rpc_name} to Node {peer_id}")

    def _should_step_down(self, response_term):
        return response_term > self.current_term

    def _get_stub(self, peer):
        address = peer['address']
        return self._get_stub_by_address(address, peer['id'])

    def _get_stub_by_address(self, address, peer_id=None):
        if address not in self.peer_stubs:
            self.peer_channels[address] = grpc.insecure_channel(address)
            self.peer_stubs[address] = raft_pb2_grpc.RaftServiceStub(self.peer_channels[address])
        return self.peer_stubs[address]

    def _reset_timer(self):
        self.last_heartbeat = time.time()
        self.election_timeout = self._random_election_timeout()

    def _get_leader_address(self):
        if self.leader_id and self.leader_id in self.id_to_address:
            return self.id_to_address[self.leader_id]
        if self.leader_id == self.node_id and self.self_address:
            return self.self_address
        return None

    def _apply_commits_locked(self):
        while self.last_applied < self.commit_index and self.last_applied < len(self.log):
            entry = self.log[self.last_applied]
            result = f"Executed {entry['operation']} at index {entry['index']} (term {entry['term']})"
            self.pending_results[entry['index']] = result
            if entry['index'] in self.pending_events:
                self.pending_events[entry['index']].set()
            print(f"[Raft] {self.node_id} applied log index {entry['index']}: {entry['operation']}")
            self.last_applied += 1

    def _start_election(self):
        with self.state_lock:
            if self.role == 'leader':
                return
            if time.time() - self.last_heartbeat < self.election_timeout:
                return
            self.role = 'candidate'
            self.current_term += 1
            term = self.current_term
            self.voted_for = self.node_id
            self.leader_id = None
            self._reset_timer()
            peers_snapshot = list(self.peers)

        votes = 1
        majority = self._majority()
        for peer in peers_snapshot:
            stub = self._get_stub(peer)
            peer_id = peer['id']
            try:
                self._log_client("RequestVote", peer_id)
                response = stub.RequestVote(
                    raft_pb2.VoteRequest(
                        term=term,
                        candidate_id=self.node_id,
                        last_log_index=0,
                        last_log_term=0
                    ),
                    timeout=RAFT_RPC_TIMEOUT
                )
            except Exception as e:
                print(f"[Raft] RequestVote to {peer_id} failed: {e}")
                continue

            with self.state_lock:
                if self.role != 'candidate' or term != self.current_term:
                    return

                if self._should_step_down(response.term):
                    self.current_term = response.term
                    self.role = 'follower'
                    self.voted_for = None
                    self._reset_timer()
                    return

                if response.vote_granted:
                    votes += 1
                    if votes >= majority:
                        self.role = 'leader'
                        self.leader_id = self.node_id
                        self.last_heartbeat_sent = 0.0
                        print(f"Node {self.node_id} become the new leader")
                        return

    def _broadcast_heartbeats(self):
        with self.state_lock:
            if self.role != 'leader':
                return
            term = self.current_term
            peers_snapshot = list(self.peers)
            commit_index = self.commit_index
            entries_proto = [
                raft_pb2.LogEntry(index=e['index'], term=e['term'], operation=e['operation'])
                for e in self.log
            ]

        request = raft_pb2.AppendEntriesRequest(
            term=term,
            leader_id=self.node_id,
            prev_log_index=0,
            prev_log_term=0,
            entries=entries_proto,
            leader_commit=commit_index
        )

        success_count = 1  # self

        for peer in peers_snapshot:
            stub = self._get_stub(peer)
            peer_id = peer['id']
            try:
                self._log_client("AppendEntries", peer_id)
                response = stub.AppendEntries(request, timeout=RAFT_RPC_TIMEOUT)
            except Exception as e:
                print(f"[Raft] AppendEntries to {peer_id} failed: {e}")
                del self.peer_stubs[peer['address']]
                del self.peer_channels[peer['address']]
                # stub = self._get_stub(peer)
                continue

            with self.state_lock:
                if self._should_step_down(response.term):
                    self.current_term = response.term
                    self.role = 'follower'
                    self.voted_for = None
                    self.leader_id = None
                    self._reset_timer()
                    return
                if response.success:
                    success_count += 1

        with self.state_lock:
            if self.role == 'leader' and success_count >= self._majority():
                if len(self.log) > self.commit_index:
                    self.commit_index = len(self.log)
                    self._apply_commits_locked()

    def _run(self):
        # Election/heartbeat loop
        while not self.stop_event.is_set():
            time.sleep(0.1)
            send_heartbeat = False
            start_election = False

            with self.state_lock:
                now = time.time()
                if self.role == 'leader':
                    if now - self.last_heartbeat_sent >= RAFT_HEARTBEAT_INTERVAL:
                        self.last_heartbeat_sent = now
                        send_heartbeat = True
                else:
                    if now - self.last_p_log_time >= 3:
                        self.last_p_log_time = now
                        print(f"Print current log on node{self.node_id} {self.log}")
                    if now - self.last_heartbeat >= self.election_timeout:
                        start_election = True

            if send_heartbeat:
                self._broadcast_heartbeats()

            if start_election:
                self._start_election()

    def RequestVote(self, request, context):
        caller_id = request.candidate_id or "unknown"
        print(f"Node {self.node_id} runs RPC RequestVote called by Node {caller_id}")

        with self.state_lock:
            if request.term < self.current_term:
                return raft_pb2.VoteResponse(term=self.current_term, vote_granted=False)

            reset_timer = False
            if request.term > self.current_term:
                self.current_term = request.term
                self.role = 'follower'
                self.voted_for = None
                reset_timer = True

            vote_granted = False
            if self.voted_for in (None, caller_id):
                vote_granted = True
                self.voted_for = caller_id
                reset_timer = True

            if reset_timer:
                self._reset_timer()

            return raft_pb2.VoteResponse(term=self.current_term, vote_granted=vote_granted)

    def AppendEntries(self, request, context):
        caller_id = request.leader_id or "unknown"
        print(f"Node {self.node_id} runs RPC AppendEntries called by Node {caller_id}")

        with self.state_lock:
            if request.term < self.current_term:
                return raft_pb2.AppendEntriesResponse(term=self.current_term, success=False)

            if request.term >= self.current_term:
                if request.term > self.current_term:
                    self.current_term = request.term
                self.role = 'follower'
                self.leader_id = caller_id
                self.voted_for = None
                self._reset_timer()

            # Replace local log with leader's log (simplified replication of entire log)
            self.log = [
                {'index': entry.index, 'term': entry.term, 'operation': entry.operation}
                for entry in request.entries
            ]
            self.commit_index = min(request.leader_commit, len(self.log))
            self.last_applied = min(self.last_applied, self.commit_index, len(self.log))
            self._apply_commits_locked()

            return raft_pb2.AppendEntriesResponse(term=self.current_term, success=True)

    def SubmitOperation(self, request, context):
        caller_id = request.source_id or "client"
        print(f"Node {self.node_id} runs RPC SubmitOperation called by Node {caller_id}")

        # If not leader, forward to leader if known
        if self.role != 'leader' or (self.leader_id and self.leader_id != self.node_id):
            leader_address = self._get_leader_address()
            if leader_address:
                try:
                    stub = self._get_stub_by_address(leader_address, self.leader_id or leader_address)
                    self._log_client("SubmitOperation", self.leader_id or leader_address)
                    forward_request = raft_pb2.OperationRequest(operation=request.operation, source_id=self.node_id)
                    response = stub.SubmitOperation(forward_request, timeout=RAFT_RPC_TIMEOUT)
                    print(f"Node {self.node_id} has forward op:{request.operation} to leader")
                    return response
                except Exception as e:
                    print(f"[Raft] Forward SubmitOperation failed: {e}")
            return raft_pb2.OperationResponse(success=False, result="No known leader", leader_id=self.leader_id or "")

        # Leader path
        with self.state_lock:
            index = len(self.log) + 1
            entry = {'index': index, 'term': self.current_term, 'operation': request.operation}
            self.log.append(entry)
            event = threading.Event()
            self.pending_events[index] = event
            self.pending_results[index] = None
            # Trigger a near-immediate heartbeat to replicate
            self.last_heartbeat_sent = 0.0
            pending_event = event

        # Wait for commit after replication
        committed = pending_event.wait(timeout=5.0)
        with self.state_lock:
            result = self.pending_results.get(index) or ""
        if not committed:
            return raft_pb2.OperationResponse(success=False, result="Commit timeout", leader_id=self.node_id)

        return raft_pb2.OperationResponse(success=True, result=result or "Committed", leader_id=self.node_id)

class AuthServiceServicer(library_pb2_grpc.AuthServiceServicer):
    def Login(self, request, context):
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                'SELECT id, student_id, password_hash, name FROM users WHERE student_id = %s',
                (request.student_id,)
            )

            user = cur.fetchone()
            cur.close()
            return_db_connection(conn)

            if not user:
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details('Invalid credentials')
                return library_pb2.LoginResponse()

            if not bcrypt.checkpw(request.password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details('Invalid credentials')
                return library_pb2.LoginResponse()

            token = generate_jwt(user['id'], user['student_id'])

            return library_pb2.LoginResponse(
                token=token,
                user_id=user['id'],
                student_id=user['student_id'],
                name=user['name'] or ''
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.LoginResponse()

    def Register(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Auth.Register",
                        "student_id": request.student_id,
                        "name": request.name,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"AuthService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.RegisterResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.RegisterResponse()

            # Step 2: execute the actual user registration against the database
            password_hash = bcrypt.hashpw(request.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            try:
                cur.execute(
                    'INSERT INTO users (student_id, password_hash, name) VALUES (%s, %s, %s) RETURNING id, student_id, name',
                    (request.student_id, password_hash, request.name)
                )
                user = cur.fetchone()
                conn.commit()

                token = generate_jwt(user['id'], user['student_id'])

                cur.close()
                return_db_connection(conn)

                return library_pb2.RegisterResponse(
                    token=token,
                    user_id=user['id'],
                    student_id=user['student_id'],
                    name=user['name'] or ''
                )

            except psycopg2.IntegrityError:
                conn.rollback()
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                context.set_details('Student ID already exists')
                return library_pb2.RegisterResponse()

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.RegisterResponse()

    def Verify(self, request, context):
        try:
            payload = verify_token(request.token)
            return library_pb2.VerifyResponse(
                valid=True,
                user_id=payload['user_id'],
                student_id=payload['student_id']
            )
        except Exception as e:
            return library_pb2.VerifyResponse(valid=False)


class OperationServiceServicer(library_pb2_grpc.OperationServiceServicer):
    def __init__(self, raft_node: 'RaftNode'):
        self.raft_node = raft_node

    def SubmitOperation(self, request, context):
        # Forward through Raft service to ensure log replication and proper logging
        operation = request.operation or "noop"
        target_address = self.raft_node._get_leader_address() or self.raft_node.self_address
        target_id = self.raft_node.leader_id or self.raft_node.node_id

        if not target_address:
            return library_pb2.OperationResponse(
                success=False, result="No leader available", leader_id=self.raft_node.leader_id or ""
            )

        try:
            stub = self.raft_node._get_stub_by_address(target_address, target_id)
            self.raft_node._log_client("SubmitOperation", target_id)
            raft_resp = stub.SubmitOperation(
                raft_pb2.OperationRequest(operation=operation, source_id=request.source_id or self.raft_node.node_id),
                timeout=RAFT_RPC_TIMEOUT,
            )
            return library_pb2.OperationResponse(
                success=raft_resp.success, result=raft_resp.result, leader_id=raft_resp.leader_id
            )
        except Exception as e:
            print(f"[OperationService] SubmitOperation failed: {e}")
            return library_pb2.OperationResponse(
                success=False, result=str(e), leader_id=self.raft_node.leader_id or ""
            )

class SeatServiceServicer(library_pb2_grpc.SeatServiceServicer):
    def get_seat_availability(self, seat_id, start_time=None, end_time=None):
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if start_time and end_time:
            cur.execute('''
                SELECT COUNT(*) as conflict_count
                FROM reservations
                WHERE seat_id = %s
                AND status NOT IN ('CANCELLED', 'NO_SHOW')
                AND tsrange(start_time, end_time) && tsrange(%s, %s)
            ''', (seat_id, start_time, end_time))

            result = cur.fetchone()
            cur.close()
            return_db_connection(conn)

            return result['conflict_count'] == 0
        else:
            cur.execute('''
                SELECT COUNT(*) as active_count
                FROM reservations
                WHERE seat_id = %s
                AND status IN ('CONFIRMED', 'CHECKED_IN')
                AND start_time <= NOW()
                AND end_time > NOW()
            ''', (seat_id,))

            result = cur.fetchone()
            cur.close()
            return_db_connection(conn)

            return result['active_count'] == 0

    def GetSeats(self, request, context):
        try:
            cache_key_parts = [
                request.branch or 'any',
                request.area or 'any',
                str(request.has_power) if request.HasField('has_power') else 'any',
                str(request.has_monitor) if request.HasField('has_monitor') else 'any',
                str(request.available_only),
                request.start_time or '',
                request.end_time or ''
            ]
            cache_key = f"seats:{':'.join(cache_key_parts)}"
            lock_key = f"{cache_key}:lock"

            def build_response_from_cache(payload: str):
                cached_seats = json.loads(payload)
                seat_messages = [
                    library_pb2.Seat(
                        id=seat['id'],
                        branch=seat['branch'],
                        area=seat.get('area', ''),
                        has_power=seat['has_power'],
                        has_monitor=seat['has_monitor'],
                        status=seat['status'],
                        is_available=seat['is_available']
                    )
                    for seat in cached_seats
                ]
                return library_pb2.GetSeatsResponse(seats=seat_messages, count=len(seat_messages))

            cached_payload = redis_client.get(cache_key)
            if cached_payload:
                return build_response_from_cache(cached_payload)

            acquired_lock = redis_client.set(lock_key, "1", nx=True, ex=10)
            if not acquired_lock:
                for _ in range(50):
                    time.sleep(0.1)
                    cached_payload = redis_client.get(cache_key)
                    if cached_payload:
                        return build_response_from_cache(cached_payload)
                acquired_lock = redis_client.set(lock_key, "1", nx=True, ex=10)

            availability_clause = """
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM reservations r
                        WHERE r.seat_id = s.id
                        AND r.status IN ('CONFIRMED', 'CHECKED_IN')
                        AND r.start_time <= NOW()
                        AND r.end_time > NOW()
                    )
                    THEN FALSE
                    ELSE TRUE
                END AS is_available
            """

            params = []
            query_filters = []

            if request.branch:
                query_filters.append('s.branch = %s')
                params.append(request.branch)

            if request.area:
                query_filters.append('s.area = %s')
                params.append(request.area)

            if request.HasField('has_power'):
                query_filters.append('s.has_power = %s')
                params.append(request.has_power)

            if request.HasField('has_monitor'):
                query_filters.append('s.has_monitor = %s')
                params.append(request.has_monitor)

            if request.start_time and request.end_time:
                availability_clause = """
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM reservations r
                            WHERE r.seat_id = s.id
                            AND r.status NOT IN ('CANCELLED', 'NO_SHOW')
                            AND tsrange(r.start_time, r.end_time) && tsrange(%s, %s)
                        )
                        THEN FALSE
                        ELSE TRUE
                    END AS is_available
                """
                params.append(request.start_time)
                params.append(request.end_time)

            query = f"""
                SELECT
                    s.id,
                    s.branch,
                    s.area,
                    s.has_power,
                    s.has_monitor,
                    s.status,
                    {availability_clause}
                FROM seats s
            """

            if query_filters:
                query += ' WHERE ' + ' AND '.join(query_filters)

            query += ' ORDER BY s.id'

            conn = None
            cur = None
            try:
                with db_semaphore:
                    conn = get_db_connection()
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    cur.execute(query, params)
                    seats = cur.fetchall()
            except Exception:
                if acquired_lock:
                    redis_client.delete(lock_key)
                raise
            finally:
                if cur:
                    cur.close()
                if conn:
                    return_db_connection(conn)

            result_payload = []
            result_seats = []
            for seat in seats:
                seat_info = {
                    'id': seat['id'],
                    'branch': seat['branch'],
                    'area': seat['area'] or '',
                    'has_power': seat['has_power'],
                    'has_monitor': seat['has_monitor'],
                    'status': seat['status'],
                    'is_available': seat['is_available']
                }

                if not request.available_only or seat_info['is_available']:
                    result_payload.append(seat_info)
                    result_seats.append(library_pb2.Seat(**seat_info))

            if acquired_lock:
                redis_client.setex(cache_key, 30, json.dumps(result_payload))
                redis_client.delete(lock_key)

            return library_pb2.GetSeatsResponse(seats=result_seats, count=len(result_seats))

        except Exception as e:
            print(f"[GetSeats] error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.GetSeatsResponse()

    def GetSeat(self, request, context):
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('SELECT * FROM seats WHERE id = %s', (request.seat_id,))
            seat = cur.fetchone()

            if not seat:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Seat not found')
                return library_pb2.GetSeatResponse()

            is_available = self.get_seat_availability(request.seat_id)

            cur.close()
            return_db_connection(conn)

            return library_pb2.GetSeatResponse(
                seat=library_pb2.Seat(
                    id=seat['id'],
                    branch=seat['branch'],
                    area=seat['area'] or '',
                    has_power=seat['has_power'],
                    has_monitor=seat['has_monitor'],
                    status=seat['status'],
                    is_available=is_available
                )
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.GetSeatResponse()

    def CheckAvailability(self, request, context):
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('SELECT * FROM seats WHERE id = %s', (request.seat_id,))
            seat = cur.fetchone()

            if not seat:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Seat not found')
                return library_pb2.CheckAvailabilityResponse()

            is_available = self.get_seat_availability(request.seat_id, request.start_time, request.end_time)

            cur.close()
            return_db_connection(conn)

            return library_pb2.CheckAvailabilityResponse(
                seat_id=request.seat_id,
                available=is_available,
                start_time=request.start_time,
                end_time=request.end_time
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.CheckAvailabilityResponse()

    def GetBranches(self, request, context):
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT branch, COUNT(*) as total_seats,
                       COUNT(*) FILTER (WHERE has_power) as power_seats,
                       COUNT(*) FILTER (WHERE has_monitor) as monitor_seats
                FROM seats
                GROUP BY branch
                ORDER BY branch
            ''')

            branches = cur.fetchall()
            cur.close()
            return_db_connection(conn)

            result = [library_pb2.Branch(
                branch=b['branch'],
                total_seats=b['total_seats'],
                power_seats=b['power_seats'],
                monitor_seats=b['monitor_seats']
            ) for b in branches]

            return library_pb2.GetBranchesResponse(branches=result)

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.GetBranchesResponse()

class ReservationServiceServicer(library_pb2_grpc.ReservationServiceServicer):
    def CreateReservation(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Reservation.Create",
                        "user_id": request.user_id,
                        "seat_id": request.seat_id,
                        "start_time": request.start_time,
                        "end_time": request.end_time,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"ReservationService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.CreateReservationResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.CreateReservationResponse()

            # Step 2: execute the actual reservation creation against the database
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('SELECT id FROM seats WHERE id = %s', (request.seat_id,))
            seat = cur.fetchone()

            if not seat:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Seat not found')
                return library_pb2.CreateReservationResponse()

            try:
                cur.execute('''
                    INSERT INTO reservations (user_id, seat_id, start_time, end_time, status)
                    VALUES (%s, %s, %s, %s, 'CONFIRMED')
                    RETURNING id, user_id, seat_id, start_time, end_time, status, created_at, checked_in_at
                ''', (request.user_id, request.seat_id, request.start_time, request.end_time))

                reservation = cur.fetchone()
                conn.commit()

                cur.close()
                return_db_connection(conn)

                invalidate_seat_cache(request.seat_id)

                return library_pb2.CreateReservationResponse(
                    reservation=library_pb2.Reservation(
                        id=reservation['id'],
                        user_id=reservation['user_id'],
                        seat_id=reservation['seat_id'],
                        start_time=str(reservation['start_time']),
                        end_time=str(reservation['end_time']),
                        status=reservation['status'],
                        created_at=str(reservation['created_at']),
                        checked_in_at=str(reservation['checked_in_at']) if reservation['checked_in_at'] else ''
                    )
                )

            except psycopg2.IntegrityError as e:
                conn.rollback()
                cur.close()
                return_db_connection(conn)

                if 'reservations_no_overlap' in str(e):
                    context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                    context.set_details('Time slot conflict: seat already reserved for this time period')
                else:
                    context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                    context.set_details('Database constraint violation')

                return library_pb2.CreateReservationResponse()

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.CreateReservationResponse()

    def GetReservation(self, request, context):
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT r.*, s.branch, s.area, s.has_power, s.has_monitor,
                       u.student_id, u.name as user_name
                FROM reservations r
                JOIN seats s ON r.seat_id = s.id
                JOIN users u ON r.user_id = u.id
                WHERE r.id = %s
            ''', (request.reservation_id,))

            reservation = cur.fetchone()
            cur.close()
            return_db_connection(conn)

            if not reservation:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Reservation not found')
                return library_pb2.GetReservationResponse()

            return library_pb2.GetReservationResponse(
                reservation=library_pb2.ReservationDetail(
                    id=reservation['id'],
                    user_id=reservation['user_id'],
                    seat_id=reservation['seat_id'],
                    start_time=str(reservation['start_time']),
                    end_time=str(reservation['end_time']),
                    status=reservation['status'],
                    created_at=str(reservation['created_at']),
                    checked_in_at=str(reservation['checked_in_at']) if reservation['checked_in_at'] else '',
                    branch=reservation['branch'],
                    area=reservation['area'] or '',
                    has_power=reservation['has_power'],
                    has_monitor=reservation['has_monitor'],
                    student_id=reservation['student_id'],
                    user_name=reservation['user_name'] or ''
                )
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.GetReservationResponse()

    def CheckIn(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Reservation.CheckIn",
                        "reservation_id": request.reservation_id,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"ReservationService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.CheckInResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.CheckInResponse()

            # Step 2: execute the actual check-in against the database
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT id, status, start_time, end_time, seat_id
                FROM reservations
                WHERE id = %s
            ''', (request.reservation_id,))

            reservation = cur.fetchone()

            if not reservation:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Reservation not found')
                return library_pb2.CheckInResponse()

            if reservation['status'] != 'CONFIRMED':
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details(f'Cannot check in: reservation status is {reservation["status"]}')
                return library_pb2.CheckInResponse()

            now = datetime.utcnow()
            start_time = reservation['start_time']
            end_time = reservation['end_time']

            if now < start_time:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details('Cannot check in before reservation start time')
                return library_pb2.CheckInResponse()

            if now > end_time:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details('Cannot check in after reservation end time')
                return library_pb2.CheckInResponse()

            cur.execute('''
                UPDATE reservations
                SET status = 'CHECKED_IN', checked_in_at = NOW()
                WHERE id = %s
                RETURNING id, user_id, seat_id, start_time, end_time, status, created_at, checked_in_at
            ''', (request.reservation_id,))

            updated_reservation = cur.fetchone()
            conn.commit()

            cur.close()
            return_db_connection(conn)

            invalidate_seat_cache(reservation['seat_id'])

            return library_pb2.CheckInResponse(
                reservation=library_pb2.Reservation(
                    id=updated_reservation['id'],
                    user_id=updated_reservation['user_id'],
                    seat_id=updated_reservation['seat_id'],
                    start_time=str(updated_reservation['start_time']),
                    end_time=str(updated_reservation['end_time']),
                    status=updated_reservation['status'],
                    created_at=str(updated_reservation['created_at']),
                    checked_in_at=str(updated_reservation['checked_in_at']) if updated_reservation['checked_in_at'] else ''
                )
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.CheckInResponse()

    def CancelReservation(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Reservation.Cancel",
                        "reservation_id": request.reservation_id,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"ReservationService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.CancelReservationResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.CancelReservationResponse()

            # Step 2: execute the actual cancellation against the database
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT id, status, seat_id, start_time
                FROM reservations
                WHERE id = %s
            ''', (request.reservation_id,))

            reservation = cur.fetchone()

            if not reservation:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Reservation not found')
                return library_pb2.CancelReservationResponse()

            if reservation['status'] in ('CANCELLED', 'NO_SHOW', 'COMPLETED'):
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details(f'Cannot cancel: reservation status is {reservation["status"]}')
                return library_pb2.CancelReservationResponse()

            cur.execute('''
                UPDATE reservations
                SET status = 'CANCELLED'
                WHERE id = %s
                RETURNING id, user_id, seat_id, start_time, end_time, status, created_at, checked_in_at
            ''', (request.reservation_id,))

            cancelled_reservation = cur.fetchone()
            conn.commit()

            cur.close()
            return_db_connection(conn)

            invalidate_seat_cache(reservation['seat_id'])

            return library_pb2.CancelReservationResponse(
                reservation=library_pb2.Reservation(
                    id=cancelled_reservation['id'],
                    user_id=cancelled_reservation['user_id'],
                    seat_id=cancelled_reservation['seat_id'],
                    start_time=str(cancelled_reservation['start_time']),
                    end_time=str(cancelled_reservation['end_time']),
                    status=cancelled_reservation['status'],
                    created_at=str(cancelled_reservation['created_at']),
                    checked_in_at=str(cancelled_reservation['checked_in_at']) if cancelled_reservation['checked_in_at'] else ''
                )
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.CancelReservationResponse()

    def GetUserReservations(self, request, context):
        try:
            query = '''
                SELECT r.*, s.branch, s.area, s.has_power, s.has_monitor
                FROM reservations r
                JOIN seats s ON r.seat_id = s.id
                WHERE r.user_id = %s
            '''
            params = [request.user_id]

            if request.status:
                query += ' AND r.status = %s'
                params.append(request.status)

            if request.upcoming_only:
                query += ' AND r.end_time > NOW()'

            query += ' ORDER BY r.start_time DESC'

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            reservations = cur.fetchall()
            cur.close()
            return_db_connection(conn)

            result = [library_pb2.ReservationDetail(
                id=r['id'],
                user_id=r['user_id'],
                seat_id=r['seat_id'],
                start_time=str(r['start_time']),
                end_time=str(r['end_time']),
                status=r['status'],
                created_at=str(r['created_at']),
                checked_in_at=str(r['checked_in_at']) if r['checked_in_at'] else '',
                branch=r['branch'],
                area=r['area'] or '',
                has_power=r['has_power'],
                has_monitor=r['has_monitor'],
                student_id='',
                user_name=''
            ) for r in reservations]

            return library_pb2.GetUserReservationsResponse(reservations=result, count=len(result))

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.GetUserReservationsResponse()

class NotifyServiceServicer(library_pb2_grpc.NotifyServiceServicer):
    def AddToWaitlist(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Waitlist.Add",
                        "user_id": request.user_id,
                        "seat_id": request.seat_id if request.HasField('seat_id') else None,
                        "branch": request.branch,
                        "desired_time": request.desired_time,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"NotifyService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.AddToWaitlistResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.AddToWaitlistResponse()

            # Step 2: execute the actual waitlist insertion against the database
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            seat_id = request.seat_id if request.HasField('seat_id') else None

            cur.execute('''
                INSERT INTO waitlist (user_id, seat_id, branch, desired_time)
                VALUES (%s, %s, %s, %s)
                RETURNING id, user_id, seat_id, branch, desired_time, created_at
            ''', (request.user_id, seat_id, request.branch, request.desired_time))

            waitlist_entry = cur.fetchone()
            conn.commit()

            cur.close()
            return_db_connection(conn)

            desired_time = waitlist_entry['desired_time']

            return library_pb2.AddToWaitlistResponse(
                entry=library_pb2.WaitlistEntry(
                    id=waitlist_entry['id'],
                    user_id=waitlist_entry['user_id'],
                    seat_id=waitlist_entry['seat_id'] if waitlist_entry['seat_id'] else 0,
                    branch=waitlist_entry['branch'] or '',
                    desired_time=str(desired_time) if desired_time else '',
                    created_at=str(waitlist_entry['created_at'])
                )
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.AddToWaitlistResponse()

    def GetUserWaitlist(self, request, context):
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT w.*, s.branch as seat_branch, s.area
                FROM waitlist w
                LEFT JOIN seats s ON w.seat_id = s.id
                WHERE w.user_id = %s
                ORDER BY w.created_at DESC
            ''', (request.user_id,))

            waitlist_entries = cur.fetchall()
            cur.close()
            return_db_connection(conn)

            result = [library_pb2.WaitlistEntry(
                id=e['id'],
                user_id=e['user_id'],
                seat_id=e['seat_id'] if e['seat_id'] else 0,
                branch=e['branch'] or e['seat_branch'] or '',
                desired_time=str(e['desired_time']) if e['desired_time'] else '',
                created_at=str(e['created_at'])
            ) for e in waitlist_entries]

            return library_pb2.GetUserWaitlistResponse(entries=result, count=len(result))

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.GetUserWaitlistResponse()

    def RemoveFromWaitlist(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Waitlist.Remove",
                        "waitlist_id": request.waitlist_id,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"NotifyService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.RemoveFromWaitlistResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.RemoveFromWaitlistResponse()

            # Step 2: execute the actual removal against the database
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('DELETE FROM waitlist WHERE id = %s RETURNING id', (request.waitlist_id,))
            deleted = cur.fetchone()

            if not deleted:
                cur.close()
                return_db_connection(conn)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details('Waitlist entry not found')
                return library_pb2.RemoveFromWaitlistResponse()

            conn.commit()
            cur.close()
            return_db_connection(conn)

            return library_pb2.RemoveFromWaitlistResponse(
                message='Removed from waitlist',
                id=deleted['id']
            )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.RemoveFromWaitlistResponse()

    def NotifyUsers(self, request, context):
        try:
            # Step 1: replicate the intent through Raft before executing
            if RAFT_NODE_INSTANCE is not None:
                try:
                    op_payload = {
                        "type": "Waitlist.Notify",
                        "seat_id": request.seat_id,
                        "message": request.message,
                    }
                    raft_request = raft_pb2.OperationRequest(
                        operation=json.dumps(op_payload),
                        source_id=f"NotifyService:{RAFT_NODE_ID}",
                    )
                    raft_response = RAFT_NODE_INSTANCE.SubmitOperation(raft_request, None)
                    if not raft_response.success:
                        context.set_code(grpc.StatusCode.ABORTED)
                        context.set_details(f"Raft commit failed: {raft_response.result}")
                        return library_pb2.NotifyUsersResponse()
                except Exception as e:
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details(f"Raft submit error: {e}")
                    return library_pb2.NotifyUsersResponse()

            # Step 2: execute the actual notification bookkeeping against the database
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT w.*, u.student_id, u.name
                FROM waitlist w
                JOIN users u ON w.user_id = u.id
                WHERE w.seat_id = %s AND w.notified_at IS NULL
                ORDER BY w.created_at
                LIMIT 1
            ''', (request.seat_id,))

            waitlist_entry = cur.fetchone()

            if not waitlist_entry:
                cur.execute('''
                    SELECT w.*, u.student_id, u.name, s.branch
                    FROM waitlist w
                    JOIN users u ON w.user_id = u.id
                    JOIN seats s ON s.id = %s
                    WHERE w.branch = s.branch AND w.seat_id IS NULL AND w.notified_at IS NULL
                    ORDER BY w.created_at
                    LIMIT 1
                ''', (request.seat_id,))

                waitlist_entry = cur.fetchone()

            if waitlist_entry:
                cur.execute('''
                    UPDATE waitlist
                    SET notified_at = NOW()
                    WHERE id = %s
                ''', (waitlist_entry['id'],))

                conn.commit()

                cur.close()
                return_db_connection(conn)

                return library_pb2.NotifyUsersResponse(
                    notified=True,
                    user_id=waitlist_entry['user_id'],
                    student_id=waitlist_entry['student_id'],
                    message=request.message or 'A seat has become available'
                )
            else:
                cur.close()
                return_db_connection(conn)

                return library_pb2.NotifyUsersResponse(
                    notified=False,
                    user_id=0,
                    student_id='',
                    message='No users in waitlist for this seat'
                )

        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return library_pb2.NotifyUsersResponse()

def background_worker():
    print(f"Background worker started with grace period of {GRACE_MINUTES} minutes")

    def invalidate_cache(seat_id):
        try:
            redis_client.delete(f"seat:{seat_id}")
            keys = redis_client.keys(f"seats:*")
            for key in keys:
                redis_client.delete(key)
        except Exception as e:
            print(f"Cache invalidation error: {e}")

    def process_no_shows():
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            grace_threshold = datetime.utcnow() - timedelta(minutes=GRACE_MINUTES)

            cur.execute('''
                SELECT id, user_id, seat_id, start_time, end_time
                FROM reservations
                WHERE status = 'CONFIRMED'
                AND checked_in_at IS NULL
                AND start_time <= %s
            ''', (grace_threshold,))

            no_show_reservations = cur.fetchall()

            if no_show_reservations:
                print(f"Found {len(no_show_reservations)} no-show reservations to process")

                for reservation in no_show_reservations:
                    try:
                        cur.execute('''
                            UPDATE reservations
                            SET status = 'NO_SHOW'
                            WHERE id = %s
                        ''', (reservation['id'],))

                        conn.commit()

                        print(f"Marked reservation {reservation['id']} as NO_SHOW")

                        invalidate_cache(reservation['seat_id'])

                    except Exception as e:
                        print(f"Error processing reservation {reservation['id']}: {e}")
                        conn.rollback()

            cur.close()
            return_db_connection(conn)

            return len(no_show_reservations)

        except Exception as e:
            print(f"Error in process_no_shows: {e}")
            return 0

    def complete_past_reservations():
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute('''
                SELECT id, seat_id
                FROM reservations
                WHERE status = 'CHECKED_IN'
                AND end_time < NOW()
            ''')

            completed_reservations = cur.fetchall()

            if completed_reservations:
                print(f"Found {len(completed_reservations)} reservations to complete")

                for reservation in completed_reservations:
                    try:
                        cur.execute('''
                            UPDATE reservations
                            SET status = 'COMPLETED'
                            WHERE id = %s
                        ''', (reservation['id'],))

                        conn.commit()

                        print(f"Marked reservation {reservation['id']} as COMPLETED")

                        invalidate_cache(reservation['seat_id'])

                    except Exception as e:
                        print(f"Error completing reservation {reservation['id']}: {e}")
                        conn.rollback()

            cur.close()
            return_db_connection(conn)

            return len(completed_reservations)

        except Exception as e:
            print(f"Error in complete_past_reservations: {e}")
            return 0

    time.sleep(10)

    while True:
        try:
            print(f"\n[{datetime.utcnow().isoformat()}] Running background check...")

            no_shows = process_no_shows()
            completed = complete_past_reservations()

            print(f"Processed {no_shows} no-shows and {completed} completions")

        except Exception as e:
            print(f"Error in background worker loop: {e}")

        time.sleep(60)

def serve():
    # Initialize connection pool BEFORE starting server
    print("Initializing database connection pool...")
    init_connection_pool()

    # Increase max_workers to match connection pool size
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=100))

    library_pb2_grpc.add_AuthServiceServicer_to_server(AuthServiceServicer(), server)
    library_pb2_grpc.add_SeatServiceServicer_to_server(SeatServiceServicer(), server)
    library_pb2_grpc.add_ReservationServiceServicer_to_server(ReservationServiceServicer(), server)
    library_pb2_grpc.add_NotifyServiceServicer_to_server(NotifyServiceServicer(), server)
    raft_servicer = RaftNode(
        node_id=RAFT_NODE_ID,
        peers=parse_peer_config(RAFT_PEERS_RAW, RAFT_NODE_ID, RAFT_SELF_ADDRESS),
        self_address=RAFT_SELF_ADDRESS
    )
    global RAFT_NODE_INSTANCE
    RAFT_NODE_INSTANCE = raft_servicer
    library_pb2_grpc.add_OperationServiceServicer_to_server(OperationServiceServicer(raft_servicer), server)
    raft_pb2_grpc.add_RaftServiceServicer_to_server(raft_servicer, server)

    server.add_insecure_port('[::]:9090')

    worker_thread = threading.Thread(target=background_worker, daemon=True)
    worker_thread.start()

    print('gRPC server started on port 9090 with 100-connection pool (10-100 per instance)')
    server.start()
    raft_servicer.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
