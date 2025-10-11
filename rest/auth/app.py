import os
import psycopg2
import bcrypt
import jwt
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from psycopg2.extras import RealDictCursor
from functools import wraps

app = Flask(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
JWT_SECRET = os.getenv('JWT_SECRET', 'your-secret-key')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def generate_jwt(user_id, student_id):
    payload = {
        'user_id': user_id,
        'student_id': student_id,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

@app.route('/healthz', methods=['GET'])
def health():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()

        if not data or 'student_id' not in data or 'password' not in data:
            return jsonify({'error': 'student_id and password are required'}), 400

        student_id = data['student_id']
        password = data['password']

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            'SELECT id, student_id, password_hash, name FROM users WHERE student_id = %s',
            (student_id,)
        )

        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401

        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        token = generate_jwt(user['id'], user['student_id'])

        return jsonify({
            'token': token,
            'user_id': user['id'],
            'student_id': user['student_id'],
            'name': user['name']
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()

        if not data or 'student_id' not in data or 'password' not in data or 'name' not in data:
            return jsonify({'error': 'student_id, password, and name are required'}), 400

        student_id = data['student_id']
        password = data['password']
        name = data['name']

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                'INSERT INTO users (student_id, password_hash, name) VALUES (%s, %s, %s) RETURNING id, student_id, name',
                (student_id, password_hash, name)
            )
            user = cur.fetchone()
            conn.commit()

            token = generate_jwt(user['id'], user['student_id'])

            cur.close()
            conn.close()

            return jsonify({
                'token': token,
                'user_id': user['id'],
                'student_id': user['student_id'],
                'name': user['name']
            }), 201

        except psycopg2.IntegrityError:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': 'Student ID already exists'}), 409

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/verify', methods=['POST'])
def verify():
    try:
        data = request.get_json()

        if not data or 'token' not in data:
            return jsonify({'error': 'token is required'}), 400

        token = data['token']

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return jsonify({
                'valid': True,
                'user_id': payload['user_id'],
                'student_id': payload['student_id']
            }), 200
        except jwt.ExpiredSignatureError:
            return jsonify({'valid': False, 'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'valid': False, 'error': 'Invalid token'}), 401

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=False)
