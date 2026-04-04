import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import jwt
from werkzeug.utils import secure_filename
from functools import wraps
from bson import ObjectId
import json
import traceback

load_dotenv()

class MongoJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return str(obj)
        return super().default(obj)

app = Flask(__name__)
app.json_encoder = MongoJSONEncoder
CORS(app, origins=['http://localhost:3000'], supports_credentials=True)

from models import mongo, User, Post
app.config['MONGO_URI'] = os.getenv('MONGODB_URI')
mongo.init_app(app)

app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-this')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            token = token.split(' ')[1]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = User.find_by_id(data['user_id'])
            if not current_user:
                return jsonify({'message': 'User not found!'}), 401
        except Exception as e:
            print(f"Token error: {e}")
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

@app.route('/api/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not username or not email or not password:
            return jsonify({'message': 'Missing fields'}), 400
        
        existing_user = User.find_by_email(email)
        if existing_user:
            return jsonify({'message': 'User already exists'}), 400
        
        result = User.create_user(username, email, password)
        token = jwt.encode({
            'user_id': str(result.inserted_id),
            'exp': datetime.utcnow() + timedelta(days=7)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'token': token,
            'user': {
                '_id': str(result.inserted_id),
                'username': username,
                'email': email,
                'points': 0,
                'total_blogs': 0
            }
        })
    except Exception as e:
        print(f"Signup error: {e}")
        traceback.print_exc()
        return jsonify({'message': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        user = User.find_by_email(email)
        if not user or not User.verify_password(user, password):
            return jsonify({'message': 'Invalid credentials'}), 401
        
        token = jwt.encode({
            'user_id': str(user['_id']),
            'exp': datetime.utcnow() + timedelta(days=7)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'token': token,
            'user': {
                '_id': str(user['_id']),
                'username': user['username'],
                'email': user['email'],
                'points': user.get('points', 0),
                'total_blogs': user.get('total_blogs', 0)
            }
        })
    except Exception as e:
        print(f"Login error: {e}")
        traceback.print_exc()
        return jsonify({'message': str(e)}), 500

@app.route('/api/posts', methods=['GET'])
def get_posts():
    try:
        posts = Post.get_all_posts(20)
        return jsonify(posts)
    except Exception as e:
        print(f"Error fetching posts: {e}")
        traceback.print_exc()
        return jsonify([]), 200

@app.route('/api/posts/<post_id>', methods=['GET'])
def get_post(post_id):
    try:
        post = Post.get_post_by_id(post_id)
        if not post:
            return jsonify({'message': 'Post not found'}), 404
        return jsonify(post)
    except Exception as e:
        print(f"Error fetching post: {e}")
        traceback.print_exc()
        return jsonify({'message': str(e)}), 500

# Update the create_post endpoint in app.py
@app.route('/api/posts', methods=['POST'])
@token_required
def create_post(current_user):
    try:
        title = request.form.get('title')
        category = request.form.get('category')
        content = request.form.get('content')
        cover_image = request.files.get('coverImage')
        
        print(f"Creating post: {title}")
        print(f"Cover image received: {cover_image}")
        
        cover_image_data = None
        cover_image_filename = None
        
        if cover_image and allowed_file(cover_image.filename):
            cover_image_data = cover_image.read()
            cover_image_filename = secure_filename(cover_image.filename)
            print(f"Cover image size: {len(cover_image_data)} bytes")
        
        result = Post.create_post(
            title=title,
            category=category,
            content=content,
            cover_image_data=cover_image_data,
            cover_image_filename=cover_image_filename,
            author_id=current_user['_id'],
            author_name=current_user['username']
        )
        
        User.update_points(current_user['_id'], 200)
        
        return jsonify({
            'message': 'Post created',
            'post_id': str(result.inserted_id),
            'points_earned': 200
        })
    except Exception as e:
        print(f"Error creating post: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'message': str(e)}), 500
@app.route('/api/posts/<post_id>/like', methods=['POST'])
@token_required
def like_post(current_user, post_id):
    try:
        print(f"Like request for post: {post_id} by user: {current_user['username']}")
        result = Post.like_post(post_id)
        if result.modified_count > 0:
            print(f"Post liked successfully. Modified count: {result.modified_count}")
            return jsonify({'message': 'Post liked', 'success': True})
        else:
            print("Post not found or already liked?")
            return jsonify({'message': 'Post not found', 'success': False}), 404
    except Exception as e:
        print(f"Error liking post: {e}")
        traceback.print_exc()
        return jsonify({'message': str(e), 'success': False}), 500

@app.route('/api/posts/<post_id>/comment', methods=['POST'])
@token_required
def add_comment(current_user, post_id):
    try:
        data = request.get_json()
        comment_text = data.get('text')
        
        if not comment_text:
            return jsonify({'message': 'Comment text is required'}), 400
        
        comment = {
            'user_id': str(current_user['_id']),
            'username': current_user['username'],
            'text': comment_text,
            'created_at': datetime.utcnow().isoformat()
        }
        Post.add_comment(post_id, comment)
        return jsonify({'message': 'Comment added'})
    except Exception as e:
        print(f"Error adding comment: {e}")
        traceback.print_exc()
        return jsonify({'message': str(e)}), 500

@app.route('/api/user/posts', methods=['GET'])
@token_required
def get_user_posts(current_user):
    try:
        posts = Post.get_posts_by_user(current_user['_id'])
        return jsonify(posts)
    except Exception as e:
        print(f"Error fetching user posts: {e}")
        return jsonify([]), 200

@app.route('/api/user/profile', methods=['GET'])
@token_required
def get_profile(current_user):
    try:
        return jsonify({
            '_id': str(current_user['_id']),
            'username': current_user['username'],
            'email': current_user['email'],
            'points': current_user.get('points', 0),
            'total_blogs': current_user.get('total_blogs', 0)
        })
    except Exception as e:
        print(f"Error fetching profile: {e}")
        return jsonify({'message': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'message': 'Server is running'})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5001)
