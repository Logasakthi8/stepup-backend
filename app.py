from flask import Flask, request, jsonify 
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity
)
from pymongo import MongoClient
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import json
import base64
import pytz

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    supports_credentials=True,
    allow_headers=["Authorization"],
    expose_headers=["Authorization"]
)

# JWT Configuration
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')

app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)
jwt = JWTManager(app)

# MongoDB Configuration
mongodb_uri = os.getenv('MONGODB_URI')

client = MongoClient(mongodb_uri)
db = client['discipline_builder']

# Initialize models
from models import User, Challenge, Post, Follow
user_model = User(db)
challenge_model = Challenge(db)
post_model = Post(db)
follow_model = Follow(db)

# Helper function to convert MongoDB documents to JSON serializable
def convert_object_ids(obj):
    """
    Recursively convert Mongo ObjectId, datetime, and bytes to JSON-serializable values
    """
    if isinstance(obj, list):
        return [convert_object_ids(item) for item in obj]
    elif isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key == '_id' and isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, ObjectId):
                # Keep ObjectId as string for all fields
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, bytes):
                # Handle bytes specifically for images
                try:
                    result[key] = value.decode('utf-8', errors='ignore')
                except:
                    result[key] = str(value)
            elif isinstance(value, (dict, list)):
                result[key] = convert_object_ids(value)
            else:
                result[key] = value
        return result
    elif isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        try:
            return obj.decode('utf-8', errors='ignore')
        except:
            return str(obj)
    return obj
# ---------------- AUTH ----------------

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        name = data.get('name')
        profile_photo = data.get('profile_photo')

        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400

        if user_model.find_by_email(email):
            return jsonify({'error': 'User already exists'}), 400

        user = user_model.create_user(email, password, name, profile_photo)
        token = create_access_token(identity=str(user['_id']))

        return jsonify({
            'message': 'User created successfully',
            'user': convert_object_ids(user),
            'token': token
        }), 201

    except Exception as e:
        app.logger.error(f"Signup error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        user = user_model.find_by_email(email)
        if not user or not user_model.verify_password(user['password'], password):
            return jsonify({'error': 'Invalid credentials'}), 401

        token = create_access_token(identity=str(user['_id']))
        user['password'] = None

        return jsonify({
            'message': 'Login successful',
            'user': convert_object_ids(user),
            'token': token
        }), 200

    except Exception as e:
        app.logger.error(f"Login error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ---------------- CHALLENGE ----------------

@app.route('/api/challenge/create', methods=['POST'])
@jwt_required()
def create_challenge():
    try:
        data = request.get_json()
        user_id = get_jwt_identity()

        # Check for existing active challenge
        existing = challenge_model.get_user_challenge(user_id)
        if existing:
            return jsonify({
                'error': 'You already have an active challenge',
                'challenge_id': existing.get('_id')
            }), 400

        # Validate required fields
        if not data.get('challenge_name'):
            return jsonify({'error': 'Challenge name is required'}), 400
        
        if not data.get('daily_post_time'):
            return jsonify({'error': 'Daily post time is required'}), 400

        # Create challenge with IST timezone (ignores user_timezone from frontend)
        challenge = challenge_model.create_challenge(
            user_id=user_id,
            challenge_name=data['challenge_name'],
            duration=data.get('duration', 30),
            daily_post_time=data['daily_post_time'],
            time_window_minutes=data.get('time_window_minutes', 60),
            description=data.get('description', '')
        )

        # Update user's current challenge
        db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'current_challenge': ObjectId(challenge['_id'])}}
        )

        return jsonify({'challenge': challenge}), 201

    except ValueError as e:
        app.logger.error(f"Validation error in create_challenge: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        app.logger.error(f"Create challenge error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/challenge/current', methods=['GET'])
@jwt_required()
def get_current_challenge():
    try:
        user_id = get_jwt_identity()
        challenge = challenge_model.get_user_challenge(user_id)

        if not challenge:
            return jsonify({'message': 'No active challenge'}), 404

        return jsonify({'challenge': challenge}), 200
    except Exception as e:
        app.logger.error(f"Get current challenge error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/challenge/calendar', methods=['GET'])
@jwt_required()
def get_challenge_calendar():
    try:
        user_id = get_jwt_identity()
        challenge = challenge_model.get_user_challenge(user_id)

        if not challenge:
            return jsonify({'error': 'No active challenge'}), 404

        calendar = challenge_model.get_challenge_calendar(challenge['_id'])

        return jsonify({
            'calendar': calendar,
            'challenge_name': challenge['challenge_name'],
            'current_day': challenge['current_day']
        }), 200
    except Exception as e:
        app.logger.error(f"Get calendar error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ---------------- POSTS ----------------
@app.route('/api/post/create', methods=['POST'])
@jwt_required()
def create_post():
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}

        # 1️⃣ Get user's active challenge
        challenge = challenge_model.get_user_challenge(user_id)
        if not challenge:
            return jsonify({'error': 'No active challenge found'}), 400

        # 2️⃣ Check posting availability (IST)
        availability = challenge_model.check_posting_availability(user_id)
        if not availability['allowed']:
            return jsonify({
                'error': availability.get('message', 'Cannot post at this time'),
                'reason': availability.get('reason', 'unknown')
            }), 400

        current_day = challenge['current_day']
        points = 100 + (current_day - 1) * 50

        # 3️⃣ Extract image data
        image_url = data.get('image_url')
        image_type = data.get('image_type')

        # Handle data URI → base64
        if image_url and image_url.startswith('data:'):
            try:
                header, encoded = image_url.split(',', 1)
                image_url = encoded
                if ':' in header and ';' in header:
                    image_type = header.split(':')[1].split(';')[0]
            except Exception:
                pass

        # 4️⃣ Create post (raw)
        post = post_model.create_post(
            user_id=user_id,
            challenge_id=str(challenge['_id']),
            day_number=current_day,
            description=data.get('description', ''),
            image_url=image_url,
            image_type=image_type
        )

        # 5️⃣ Update challenge progress
        

        # 6️⃣ Update user points
        
        # ================================
        # 🔥 HYDRATE POST (FEED FORMAT)
        # ================================

        user = user_model.find_by_id(user_id)

        challenge_data = challenge_model.collection.find_one(
            {'_id': ObjectId(challenge['_id'])}
        )

        image_data = None
        if post.get('image_url'):
            mime = post.get('image_type', 'image/jpeg')
            image_data = f"data:{mime};base64,{post['image_url']}"

        hydrated_post = {
            **convert_object_ids(post),
            "image_url": image_data,
            "user_name": user.get("name", "Unknown User"),
            "profile_photo": user.get("profile_photo"),
            "challenge_name": challenge_data.get("challenge_name"),
            "is_boosted_by_user": False,
            "boosts_count": 0,
            "comment_count": 0,
            "comments": []
        }

        return jsonify({
            "post": hydrated_post,
            "points_earned": points,
            "total_points": user.get("total_points", 0),
            "current_day": current_day + 1
        }), 201


    except Exception as e:
        app.logger.error(f"Create post error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/post/check-availability', methods=['GET'])
@jwt_required()
def check_posting_availability():
    try:
        user_id = get_jwt_identity()
        availability = challenge_model.check_posting_availability(user_id)
        return jsonify(availability), 200
    except Exception as e:
        app.logger.error(f"Check availability error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/post/<post_id>/boost', methods=['POST'])
@jwt_required()
def boost_post(post_id):
    try:
        user_id = get_jwt_identity()
        result = post_model.boost_post(post_id, user_id)
        
        if result:
            converted_result = convert_object_ids(result)
            return jsonify({
                'message': f'Post {converted_result.get("action", "updated")} successfully',
                'boosts_count': converted_result.get('boosts_count', 0),
                'is_boosted': converted_result.get('is_boosted', False)
            }), 200
        else:
            return jsonify({'error': 'Post not found'}), 404
            
    except Exception as e:
        app.logger.error(f"Boost error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/post/<post_id>/comment', methods=['POST'])
@jwt_required()
def add_comment(post_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        app.logger.info(f"Comment request data: {data}")
        app.logger.info(f"User ID: {user_id}, Post ID: {post_id}")
        
        comment_text = None
        if data:
            comment_text = data.get('text') or data.get('comment')
        
        app.logger.info(f"Extracted comment text: {comment_text}")
        
        if not comment_text or not str(comment_text).strip():
            return jsonify({'error': 'Comment text is required'}), 400
        
        result = post_model.add_comment(post_id, user_id, comment_text)
        
        app.logger.info(f"Comment result: {result}")
        
        if result:
            converted_result = convert_object_ids(result)
            return jsonify({
                'message': 'Comment added successfully',
                'comments': converted_result.get('comments', []),
                'comment_count': converted_result.get('comment_count', 0)
            }), 200
        else:
            return jsonify({'error': 'Failed to add comment'}), 400
            
    except Exception as e:
        app.logger.error(f"Comment error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500
@app.route('/api/feed', methods=['GET'])
@jwt_required()
def get_feed():
    try:
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        skip = (page - 1) * limit

        query = {
            '$or': [
                {'deleted_by_user': False},
                {'deleted_by_user': {'$exists': False}}
            ]
        }

        total_posts = post_model.collection.count_documents(query)

        posts_cursor = (
            post_model.collection
            .find(query)
            .sort('created_at', -1)
            .skip(skip)
            .limit(limit)
        )

        enriched = []

        for post in posts_cursor:
            try:
                # Convert ObjectId first
                post_dict = convert_object_ids(post)

                post_user_id = post_dict.get('user_id')
                if not post_user_id:
                    continue

                user = user_model.find_by_id(str(post_user_id))
                if not user:
                    continue

                # Get challenge info
                challenge = None
                if post_dict.get('challenge_id'):
                    challenge = challenge_model.collection.find_one(
                        {'_id': ObjectId(post_dict['challenge_id'])}
                    )
                
                # ✅ FIX: Proper image data handling
                image_data = None
                if post_dict.get('image_url'):
                    # Check if it's a base64 string
                    image_url = post_dict.get('image_url')
                    if isinstance(image_url, str):
                        if image_url.startswith('data:'):
                            image_data = image_url
                        else:
                            # It's a base64 string without data URI
                            mime_type = post_dict.get('image_type', 'image/jpeg')
                            image_data = f"data:{mime_type};base64,{image_url}"
                
                # Get description
                description = post_dict.get('description') or post_dict.get('content') or ''
                
                # Boost state
                boosts = post_dict.get('boosts', [])
                is_boosted_by_user = str(user_id) in boosts

                # ✅ FIX: Add challenge details even if None
                challenge_name = None
                if challenge:
                    challenge = convert_object_ids(challenge)
                    challenge_name = challenge.get("challenge_name")

                enriched.append({
                    "_id": post_dict.get("_id"),
                    "user_id": post_dict.get("user_id"),
                    "challenge_id": post_dict.get("challenge_id"),
                    "day_number": post_dict.get("day_number"),
                    "description": description,
                    "image_url": image_data,
                    "image_type": post_dict.get("image_type"),
                    "user_name": user.get("name", "Unknown User"),
                    "profile_photo": user.get("profile_photo"),
                    "challenge_name": challenge_name,
                    "points_earned": post_dict.get("points_earned", 0),
                    "total_points": post_dict.get("total_points", 0),
                    "is_boosted_by_user": is_boosted_by_user,
                    "boosts": boosts,
                    "boosts_count": len(boosts),
                    "comment_count": len(post_dict.get("comments", [])),
                    "comments": post_dict.get("comments", []),
                    "created_at": post_dict.get("created_at")
                })

            except Exception as e:
                app.logger.error(f"Feed post error: {str(e)}", exc_info=True)
                continue

        return jsonify({
            "posts": enriched,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_posts,
                "has_more": (skip + limit) < total_posts
            }
        }), 200

    except Exception as e:
        app.logger.error(f"Feed error: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Failed to load feed"
        }), 500
        
@app.route('/api/post/<post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    try:
        user_id = get_jwt_identity()
        result, status = post_model.delete_post_by_user(post_id, user_id)
        return jsonify(result), status
    except Exception as e:
        app.logger.error(f"Delete post error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ---------------- USERS ----------------

@app.route('/api/users', methods=['GET'])
@jwt_required()
def get_users():
    try:
        current_user_id = get_jwt_identity()

        # Find all users except current user
        users_cursor = db.users.find(
            {"_id": {"$ne": ObjectId(current_user_id)}},
            {"password": 0}
        )

        users = []

        for user in users_cursor:
            # Get active challenge details
            active_challenge = None
            if user.get("current_challenge"):
                challenge = db.challenges.find_one(
                    {"_id": ObjectId(user["current_challenge"]), "status": "active"}
                )
                if challenge:
                    active_challenge = {
                        "_id": str(challenge["_id"]),
                        "challenge_name": challenge.get("challenge_name", ""),
                        "current_day": challenge.get("current_day", 0),
                        "duration": challenge.get("duration", 30),
                        "total_points": challenge.get("total_points", 0),
                        "status": challenge.get("status", "active")
                    }
            
            # Convert followers/following to string lists
            followers = [str(follower_id) for follower_id in user.get("followers", [])]
            following = [str(following_id) for following_id in user.get("following", [])]
            
            # Create user object
            user_obj = {
                "_id": str(user["_id"]),
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "bio": user.get("bio", ""),
                "profile_photo": user.get("profile_photo"),
                "followers": followers,
                "following": following,
                "total_points": user.get("total_points", 0),
                "active_challenge": active_challenge,
                "isVerified": user.get("isVerified", False)
            }
            
            users.append(user_obj)

        return jsonify({"users": users}), 200

    except Exception as e:
        app.logger.error(f"Get users error: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to fetch users", "details": str(e)}), 500
        
# ---------------- MY PROFILE ----------------

@app.route('/api/user/profile', methods=['GET'])
@jwt_required()
def my_profile():
    try:
        user_id = get_jwt_identity()
        user = user_model.find_by_id(user_id)

        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Hide password
        user['password'] = None

        # Create profile image data URI
        profile_image = None
        if user.get('profile_photo'):
            mime_type = user.get('profile_photo_type', 'image/jpeg')
            profile_image = f"data:{mime_type};base64,{user['profile_photo']}"

        # Get active challenge
        active_challenge = None
        if user.get('current_challenge'):
            challenge = db.challenges.find_one({
                '_id': ObjectId(user['current_challenge']),
                'user_id': ObjectId(user_id)
            })
            if challenge:
                active_challenge = convert_object_ids(challenge)

        # Get completed challenges
        completed_challenges = []
        challenges_cursor = db.challenges.find({
            'user_id': ObjectId(user_id),
            'status': 'completed'
        }).sort('created_at', -1)
        
        for challenge in challenges_cursor:
            completed_challenges.append(convert_object_ids(challenge))

        # Build user response
        user_response = convert_object_ids(user)
        user_response["profileImage"] = profile_image
        
        # Ensure all required fields exist
        user_response.setdefault("followers", [])
        user_response.setdefault("following", [])
        user_response.setdefault("total_points", 0)
        user_response.setdefault("bio", "")

        return jsonify({
            "user": user_response,
            "active_challenge": active_challenge,
            "completed_challenges": completed_challenges
        }), 200
        
    except Exception as e:
        app.logger.error(f"My profile error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        

# ---------------- UPDATE PROFILE IMAGE ----------------

@app.route('/api/user/profile/image', methods=['PUT'])
@jwt_required()
def update_profile_photo():
    try:
        user_id = get_jwt_identity()
        user = user_model.find_by_id(user_id)

        if not user:
            return jsonify({'error': 'User not found'}), 404

        app.logger.info(f"FILES 👉 {request.files}")

        file = request.files.get('profile_photo')
        if not file:
            return jsonify({'error': 'Profile photo required'}), 400

        file.seek(0, 2)
        size_mb = file.tell() / (1024 * 1024)
        file.seek(0)
        if size_mb > 5:
            return jsonify({'error': 'File too large (max 5MB)'}), 400

        image_bytes = file.read()
        mime_type = file.mimetype or 'image/jpeg'
        encoded = base64.b64encode(image_bytes).decode('utf-8')

        db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'profile_photo': encoded,
                'profile_photo_type': mime_type,
                'updated_at': datetime.utcnow()
            }}
        )

        updated_user = user_model.find_by_id(user_id)

        return jsonify({
            'success': True,
            'user': {
                **convert_object_ids(updated_user),
                'profileImage': f"data:{mime_type};base64,{encoded}"
            }
        }), 200
    except Exception as e:
        app.logger.error(f"Update profile photo error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ---------------- GET USER BY ID ----------------
@app.route('/api/users/<user_id>', methods=['GET'])
@jwt_required()
def get_user_by_id(user_id):
    try:
        current_user_id = get_jwt_identity()
        user = user_model.find_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404

        user['password'] = None

        profile_image = None
        if user.get('profile_photo'):
            mime_type = user.get('profile_photo_type', 'image/jpeg')
            profile_image = f"data:{mime_type};base64,{user['profile_photo']}"

        active_challenge = None
        if user.get('current_challenge'):
            challenge = db.challenges.find_one({'_id': ObjectId(user['current_challenge'])})
            if challenge:
                active_challenge = convert_object_ids(challenge)

        completed_challenges = []
        challenges_cursor = db.challenges.find({
            'user_id': ObjectId(user_id),
            'status': 'completed'
        })
        for challenge in challenges_cursor:
            completed_challenges.append(convert_object_ids(challenge))

        return jsonify({
            "user": {
                **convert_object_ids(user),
                "profileImage": profile_image
            },
            "active_challenge": active_challenge,
            "completed_challenges": completed_challenges
        }), 200

    except Exception as e:
        app.logger.error(f"Get user by ID error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ---------------- HEALTH ----------------
@app.route('/api/health', methods=['GET'])
def health():
    try:
        db.command('ping')
        return jsonify({
            'status': 'healthy',
            'database': 'connected'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e)
        }), 500

# ---------------- FOLLOW USER ----------------

@app.route('/api/user/follow/<user_id>', methods=['POST'])
@jwt_required()
def follow_user(user_id):
    try:
        current_user_id = get_jwt_identity()

        if current_user_id == user_id:
            return jsonify({'error': 'You cannot follow yourself'}), 400

        result = follow_model.follow_user(current_user_id, user_id)

        if not result:
            return jsonify({'error': 'Already following'}), 409

        return jsonify({'success': True, 'message': 'User followed successfully'}), 200

    except Exception as e:
        app.logger.error(f"Follow user error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/user/unfollow/<user_id>', methods=['POST'])
@jwt_required()
def unfollow_user(user_id):
    try:
        current_user_id = get_jwt_identity()

        result = follow_model.unfollow_user(current_user_id, user_id)

        if not result:
            return jsonify({'error': 'Not following user'}), 400

        return jsonify({'success': True, 'message': 'User unfollowed successfully'}), 200

    except Exception as e:
        app.logger.error(f"Unfollow user error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)


