import os
import jwt
import requests
from flask import Flask, request, jsonify, Response
from functools import wraps

app = Flask(__name__)

JWT_SECRET = os.getenv('JWT_SECRET', 'your-secret-key')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')

AUTH_SERVICE_URL = os.getenv('AUTH_SERVICE_URL', 'http://auth:8081')
SEAT_SERVICE_URL = os.getenv('SEAT_SERVICE_URL', 'http://seat:8082')
RESERVATION_SERVICE_URL = os.getenv('RESERVATION_SERVICE_URL', 'http://reservation:8083')
NOTIFY_SERVICE_URL = os.getenv('NOTIFY_SERVICE_URL', 'http://notify:8084')

def extract_token():
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        return auth_header.split(' ')[1]
    return None

def verify_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = extract_token()

        if not token:
            return jsonify({'error': 'Authentication token required'}), 401

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            request.user_id = payload['user_id']
            request.student_id = payload['student_id']
            return f(*args, **kwargs)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

    return decorated_function

def proxy_request(service_url, path, method='GET', data=None, params=None, stream=False):
    url = f"{service_url}{path}"

    try:
        if method == 'GET':
            response = requests.get(url, params=params, timeout=30, stream=stream)
        elif method == 'POST':
            response = requests.post(url, json=data, params=params, timeout=30, stream=stream)
        elif method == 'PUT':
            response = requests.put(url, json=data, params=params, timeout=30)
        elif method == 'DELETE':
            response = requests.delete(url, params=params, timeout=30)
        else:
            return jsonify({'error': 'Invalid HTTP method'}), 400

        if stream:
            return response

        return jsonify(response.json()), response.status_code

    except requests.Timeout:
        return jsonify({'error': 'Service timeout'}), 504
    except requests.ConnectionError:
        return jsonify({'error': 'Service unavailable'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'gateway'}), 200

@app.route('/auth/login', methods=['POST'])
def login():
    return proxy_request(AUTH_SERVICE_URL, '/login', method='POST', data=request.get_json())

@app.route('/auth/register', methods=['POST'])
def register():
    return proxy_request(AUTH_SERVICE_URL, '/register', method='POST', data=request.get_json())

@app.route('/seats', methods=['GET'])
@verify_token
def get_seats():
    return proxy_request(SEAT_SERVICE_URL, '/seats', params=request.args)

@app.route('/seats/<int:seat_id>', methods=['GET'])
@verify_token
def get_seat(seat_id):
    return proxy_request(SEAT_SERVICE_URL, f'/seats/{seat_id}')

@app.route('/seats/<int:seat_id>/availability', methods=['GET'])
@verify_token
def check_availability(seat_id):
    return proxy_request(SEAT_SERVICE_URL, f'/seats/{seat_id}/availability', params=request.args)

@app.route('/branches', methods=['GET'])
@verify_token
def get_branches():
    return proxy_request(SEAT_SERVICE_URL, '/branches')

@app.route('/reservations', methods=['POST'])
@verify_token
def create_reservation():
    data = request.get_json() or {}
    data['user_id'] = request.user_id
    return proxy_request(RESERVATION_SERVICE_URL, '/reservations', method='POST', data=data)

@app.route('/reservations/<int:reservation_id>', methods=['GET'])
@verify_token
def get_reservation(reservation_id):
    return proxy_request(RESERVATION_SERVICE_URL, f'/reservations/{reservation_id}')

@app.route('/reservations/<int:reservation_id>/checkin', methods=['POST'])
@verify_token
def checkin_reservation(reservation_id):
    return proxy_request(RESERVATION_SERVICE_URL, f'/reservations/{reservation_id}/checkin', method='POST')

@app.route('/reservations/<int:reservation_id>', methods=['DELETE'])
@verify_token
def cancel_reservation(reservation_id):
    return proxy_request(RESERVATION_SERVICE_URL, f'/reservations/{reservation_id}', method='DELETE')

@app.route('/reservations/mine', methods=['GET'])
@verify_token
def get_my_reservations():
    return proxy_request(RESERVATION_SERVICE_URL, f'/reservations/user/{request.user_id}', params=request.args)

@app.route('/reservations', methods=['GET'])
@verify_token
def get_all_reservations():
    return proxy_request(RESERVATION_SERVICE_URL, '/reservations', params=request.args)

@app.route('/waitlist', methods=['POST'])
@verify_token
def add_to_waitlist():
    data = request.get_json() or {}
    data['user_id'] = request.user_id
    return proxy_request(NOTIFY_SERVICE_URL, '/waitlist', method='POST', data=data)

@app.route('/waitlist/mine', methods=['GET'])
@verify_token
def get_my_waitlist():
    return proxy_request(NOTIFY_SERVICE_URL, f'/waitlist/user/{request.user_id}')

@app.route('/waitlist/<int:waitlist_id>', methods=['DELETE'])
@verify_token
def remove_from_waitlist(waitlist_id):
    return proxy_request(NOTIFY_SERVICE_URL, f'/waitlist/{waitlist_id}', method='DELETE')

@app.route('/notifications/stream', methods=['GET'])
@verify_token
def stream_notifications():
    try:
        user_id = request.user_id
        response = proxy_request(NOTIFY_SERVICE_URL, f'/stream/{user_id}', stream=True)

        if isinstance(response, tuple):
            return response

        def generate():
            try:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
            except Exception as e:
                print(f"Stream error: {e}")

        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
