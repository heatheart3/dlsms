import os
import sys
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

import library_pb2
import library_pb2_grpc

DATABASE_URL = os.getenv('DATABASE_URL')
REDIS_URL = os.getenv('REDIS_URL')
JWT_SECRET = os.getenv('JWT_SECRET', 'your-secret-key')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))
GRACE_MINUTES = int(os.getenv('GRACE_MINUTES', '15'))

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

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
            query = 'SELECT * FROM seats WHERE 1=1'
            params = []

            if request.branch:
                query += ' AND branch = %s'
                params.append(request.branch)

            if request.area:
                query += ' AND area = %s'
                params.append(request.area)

            if request.HasField('has_power'):
                query += ' AND has_power = %s'
                params.append(request.has_power)

            if request.HasField('has_monitor'):
                query += ' AND has_monitor = %s'
                params.append(request.has_monitor)

            query += ' ORDER BY id'

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            seats = cur.fetchall()
            cur.close()
            return_db_connection(conn)

            result_seats = []
            for seat in seats:
                if request.start_time and request.end_time:
                    is_available = self.get_seat_availability(seat['id'], request.start_time, request.end_time)
                else:
                    is_available = self.get_seat_availability(seat['id'])

                if not request.available_only or is_available:
                    result_seats.append(library_pb2.Seat(
                        id=seat['id'],
                        branch=seat['branch'],
                        area=seat['area'] or '',
                        has_power=seat['has_power'],
                        has_monitor=seat['has_monitor'],
                        status=seat['status'],
                        is_available=is_available
                    ))

            return library_pb2.GetSeatsResponse(seats=result_seats, count=len(result_seats))

        except Exception as e:
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

            return library_pb2.AddToWaitlistResponse(
                entry=library_pb2.WaitlistEntry(
                    id=waitlist_entry['id'],
                    user_id=waitlist_entry['user_id'],
                    seat_id=waitlist_entry['seat_id'] if waitlist_entry['seat_id'] else 0,
                    branch=waitlist_entry['branch'] or '',
                    desired_time=waitlist_entry['desired_time'] or '',
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

    server.add_insecure_port('[::]:9090')

    worker_thread = threading.Thread(target=background_worker, daemon=True)
    worker_thread.start()

    print('gRPC server started on port 9090 with 100-connection pool (10-100 per instance)')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
