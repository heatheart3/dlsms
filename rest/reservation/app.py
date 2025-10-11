import os
import psycopg2
import redis
from datetime import datetime
from flask import Flask, request, jsonify
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
REDIS_URL = os.getenv('REDIS_URL')

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def invalidate_seat_cache(seat_id):
    try:
        redis_client.delete(f"seat:{seat_id}")
        keys = redis_client.keys(f"seats:*")
        for key in keys:
            redis_client.delete(key)
    except Exception as e:
        print(f"Cache invalidation error: {e}")

@app.route('/healthz', methods=['GET'])
def health():
    try:
        conn = get_db_connection()
        conn.close()
        redis_client.ping()
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/reservations', methods=['POST'])
def create_reservation():
    try:
        data = request.get_json()

        if not data or 'user_id' not in data or 'seat_id' not in data or 'start_time' not in data or 'end_time' not in data:
            return jsonify({'error': 'user_id, seat_id, start_time, and end_time are required'}), 400

        user_id = data['user_id']
        seat_id = data['seat_id']
        start_time = data['start_time']
        end_time = data['end_time']

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('SELECT id FROM seats WHERE id = %s', (seat_id,))
        seat = cur.fetchone()

        if not seat:
            cur.close()
            conn.close()
            return jsonify({'error': 'Seat not found'}), 404

        try:
            cur.execute('''
                INSERT INTO reservations (user_id, seat_id, start_time, end_time, status)
                VALUES (%s, %s, %s, %s, 'CONFIRMED')
                RETURNING id, user_id, seat_id, start_time, end_time, status, created_at, checked_in_at
            ''', (user_id, seat_id, start_time, end_time))

            reservation = cur.fetchone()
            conn.commit()

            cur.close()
            conn.close()

            invalidate_seat_cache(seat_id)

            return jsonify(dict(reservation)), 201

        except psycopg2.IntegrityError as e:
            conn.rollback()
            cur.close()
            conn.close()

            if 'reservations_no_overlap' in str(e):
                return jsonify({'error': 'Time slot conflict: seat already reserved for this time period'}), 409
            else:
                return jsonify({'error': 'Database constraint violation'}), 409

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reservations/<int:reservation_id>', methods=['GET'])
def get_reservation(reservation_id):
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
        ''', (reservation_id,))

        reservation = cur.fetchone()
        cur.close()
        conn.close()

        if not reservation:
            return jsonify({'error': 'Reservation not found'}), 404

        return jsonify(dict(reservation)), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reservations/<int:reservation_id>/checkin', methods=['POST'])
def checkin_reservation(reservation_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('''
            SELECT id, status, start_time, end_time, seat_id
            FROM reservations
            WHERE id = %s
        ''', (reservation_id,))

        reservation = cur.fetchone()

        if not reservation:
            cur.close()
            conn.close()
            return jsonify({'error': 'Reservation not found'}), 404

        if reservation['status'] != 'CONFIRMED':
            cur.close()
            conn.close()
            return jsonify({'error': f'Cannot check in: reservation status is {reservation["status"]}'}), 400

        now = datetime.utcnow()
        start_time = reservation['start_time']
        end_time = reservation['end_time']

        if now < start_time:
            cur.close()
            conn.close()
            return jsonify({'error': 'Cannot check in before reservation start time'}), 400

        if now > end_time:
            cur.close()
            conn.close()
            return jsonify({'error': 'Cannot check in after reservation end time'}), 400

        cur.execute('''
            UPDATE reservations
            SET status = 'CHECKED_IN', checked_in_at = NOW()
            WHERE id = %s
            RETURNING id, user_id, seat_id, start_time, end_time, status, created_at, checked_in_at
        ''', (reservation_id,))

        updated_reservation = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        invalidate_seat_cache(reservation['seat_id'])

        return jsonify(dict(updated_reservation)), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reservations/<int:reservation_id>', methods=['DELETE'])
def cancel_reservation(reservation_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('''
            SELECT id, status, seat_id, start_time
            FROM reservations
            WHERE id = %s
        ''', (reservation_id,))

        reservation = cur.fetchone()

        if not reservation:
            cur.close()
            conn.close()
            return jsonify({'error': 'Reservation not found'}), 404

        if reservation['status'] in ('CANCELLED', 'NO_SHOW', 'COMPLETED'):
            cur.close()
            conn.close()
            return jsonify({'error': f'Cannot cancel: reservation status is {reservation["status"]}'}), 400

        cur.execute('''
            UPDATE reservations
            SET status = 'CANCELLED'
            WHERE id = %s
            RETURNING id, user_id, seat_id, start_time, end_time, status
        ''', (reservation_id,))

        cancelled_reservation = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        invalidate_seat_cache(reservation['seat_id'])

        return jsonify(dict(cancelled_reservation)), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reservations/user/<int:user_id>', methods=['GET'])
def get_user_reservations(user_id):
    try:
        status = request.args.get('status')
        upcoming_only = request.args.get('upcoming_only', 'false').lower() == 'true'

        query = '''
            SELECT r.*, s.branch, s.area, s.has_power, s.has_monitor
            FROM reservations r
            JOIN seats s ON r.seat_id = s.id
            WHERE r.user_id = %s
        '''
        params = [user_id]

        if status:
            query += ' AND r.status = %s'
            params.append(status)

        if upcoming_only:
            query += ' AND r.end_time > NOW()'

        query += ' ORDER BY r.start_time DESC'

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        reservations = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'reservations': [dict(r) for r in reservations],
            'count': len(reservations)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reservations/seat/<int:seat_id>', methods=['GET'])
def get_seat_reservations(seat_id):
    try:
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')

        query = '''
            SELECT r.*, u.student_id, u.name as user_name
            FROM reservations r
            JOIN users u ON r.user_id = u.id
            WHERE r.seat_id = %s
            AND r.status NOT IN ('CANCELLED', 'NO_SHOW')
        '''
        params = [seat_id]

        if start_time and end_time:
            query += ' AND tsrange(r.start_time, r.end_time) && tsrange(%s, %s)'
            params.extend([start_time, end_time])

        query += ' ORDER BY r.start_time'

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        reservations = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'reservations': [dict(r) for r in reservations],
            'count': len(reservations)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/reservations', methods=['GET'])
def get_all_reservations():
    try:
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        query = '''
            SELECT r.*, s.branch, s.area, u.student_id, u.name as user_name
            FROM reservations r
            JOIN seats s ON r.seat_id = s.id
            JOIN users u ON r.user_id = u.id
            WHERE 1=1
        '''
        params = []

        if status:
            query += ' AND r.status = %s'
            params.append(status)

        query += ' ORDER BY r.created_at DESC LIMIT %s OFFSET %s'
        params.extend([limit, offset])

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        reservations = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'reservations': [dict(r) for r in reservations],
            'count': len(reservations),
            'limit': limit,
            'offset': offset
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8083, debug=False)
