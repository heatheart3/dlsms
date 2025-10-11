import os
import json
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

def get_seat_availability(seat_id, start_time=None, end_time=None):
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
        conn.close()

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
        conn.close()

        return result['active_count'] == 0

@app.route('/healthz', methods=['GET'])
def health():
    try:
        conn = get_db_connection()
        conn.close()
        redis_client.ping()
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/seats', methods=['GET'])
def get_seats():
    try:
        branch = request.args.get('branch')
        area = request.args.get('area')
        has_power = request.args.get('has_power')
        has_monitor = request.args.get('has_monitor')
        available_only = request.args.get('available_only', 'true').lower() == 'true'
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')

        cache_key = f"seats:{branch}:{area}:{has_power}:{has_monitor}:{available_only}:{start_time}:{end_time}"
        cached_result = redis_client.get(cache_key)

        if cached_result:
            return jsonify(json.loads(cached_result)), 200

        query = 'SELECT * FROM seats WHERE 1=1'
        params = []

        if branch:
            query += ' AND branch = %s'
            params.append(branch)

        if area:
            query += ' AND area = %s'
            params.append(area)

        if has_power is not None:
            query += ' AND has_power = %s'
            params.append(has_power.lower() == 'true')

        if has_monitor is not None:
            query += ' AND has_monitor = %s'
            params.append(has_monitor.lower() == 'true')

        query += ' ORDER BY id'

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        seats = cur.fetchall()
        cur.close()
        conn.close()

        result_seats = []
        for seat in seats:
            seat_dict = dict(seat)

            if start_time and end_time:
                is_available = get_seat_availability(seat['id'], start_time, end_time)
            else:
                is_available = get_seat_availability(seat['id'])

            seat_dict['is_available'] = is_available

            if not available_only or is_available:
                result_seats.append(seat_dict)

        response_data = {'seats': result_seats, 'count': len(result_seats)}

        redis_client.setex(cache_key, 30, json.dumps(response_data, default=str))

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/seats/<int:seat_id>', methods=['GET'])
def get_seat(seat_id):
    try:
        cache_key = f"seat:{seat_id}"
        cached_result = redis_client.get(cache_key)

        if cached_result:
            return jsonify(json.loads(cached_result)), 200

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('SELECT * FROM seats WHERE id = %s', (seat_id,))
        seat = cur.fetchone()

        if not seat:
            cur.close()
            conn.close()
            return jsonify({'error': 'Seat not found'}), 404

        seat_dict = dict(seat)
        is_available = get_seat_availability(seat_id)
        seat_dict['is_available'] = is_available

        cur.execute('''
            SELECT id, user_id, start_time, end_time, status
            FROM reservations
            WHERE seat_id = %s
            AND status IN ('CONFIRMED', 'CHECKED_IN')
            AND end_time > NOW()
            ORDER BY start_time
            LIMIT 5
        ''', (seat_id,))

        upcoming_reservations = cur.fetchall()
        seat_dict['upcoming_reservations'] = [dict(r) for r in upcoming_reservations]

        cur.close()
        conn.close()

        redis_client.setex(cache_key, 60, json.dumps(seat_dict, default=str))

        return jsonify(seat_dict), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/seats/<int:seat_id>/availability', methods=['GET'])
def check_availability(seat_id):
    try:
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')

        if not start_time or not end_time:
            return jsonify({'error': 'start_time and end_time are required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('SELECT * FROM seats WHERE id = %s', (seat_id,))
        seat = cur.fetchone()

        if not seat:
            cur.close()
            conn.close()
            return jsonify({'error': 'Seat not found'}), 404

        is_available = get_seat_availability(seat_id, start_time, end_time)

        cur.execute('''
            SELECT id, user_id, start_time, end_time, status
            FROM reservations
            WHERE seat_id = %s
            AND status NOT IN ('CANCELLED', 'NO_SHOW')
            AND tsrange(start_time, end_time) && tsrange(%s, %s)
        ''', (seat_id, start_time, end_time))

        conflicts = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'seat_id': seat_id,
            'available': is_available,
            'start_time': start_time,
            'end_time': end_time,
            'conflicts': [dict(c) for c in conflicts]
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/branches', methods=['GET'])
def get_branches():
    try:
        cache_key = "branches"
        cached_result = redis_client.get(cache_key)

        if cached_result:
            return jsonify(json.loads(cached_result)), 200

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
        conn.close()

        result = {'branches': [dict(b) for b in branches]}

        redis_client.setex(cache_key, 300, json.dumps(result, default=str))

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8082, debug=False)
