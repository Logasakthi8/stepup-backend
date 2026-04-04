from datetime import datetime
from flask_pymongo import PyMongo
import bcrypt
from bson import Binary, ObjectId
import base64

mongo = PyMongo()

class User:
    @staticmethod
    def create_user(username, email, password):
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user = {
            'username': username,
            'email': email,
            'password': hashed,
            'points': 0,
            'total_blogs': 0,
            'created_at': datetime.utcnow()
        }
        return mongo.db.users.insert_one(user)
    
    @staticmethod
    def find_by_email(email):
        return mongo.db.users.find_one({'email': email})
    
    @staticmethod
    def find_by_id(user_id):
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        return mongo.db.users.find_one({'_id': user_id})
    
    @staticmethod
    def update_points(user_id, points):
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        return mongo.db.users.update_one(
            {'_id': user_id},
            {'$inc': {'points': points, 'total_blogs': 1}}
        )
    
    @staticmethod
    def verify_password(user, password):
        return bcrypt.checkpw(password.encode('utf-8'), user['password'])

class Post:
    @staticmethod
    def create_post(title, category, content, image_data, image_filename, author_id, author_name):
        post = {
            'title': title,
            'category': category if category else 'General',
            'content': content,
            'author_id': author_id,
            'author_name': author_name,
            'likes': 0,
            'comments': [],
            'created_at': datetime.utcnow()
        }
        
        # Store image data if exists - using consistent field name 'image_data'
        if image_data and image_filename:
            post['image_data'] = Binary(image_data)
            post['image_filename'] = image_filename
            print(f"Image saved for post: {title}, size: {len(image_data)} bytes")
        
        return mongo.db.posts.insert_one(post)
    
    @staticmethod
    def get_all_posts(limit=20):
        posts = list(mongo.db.posts.find().sort('created_at', -1).limit(limit))
        result = []
        for post in posts:
            post_dict = {
                '_id': str(post['_id']),
                'title': post.get('title', 'Untitled'),
                'category': post.get('category', 'General'),
                'content': post.get('content', ''),
                'author_id': str(post.get('author_id', '')),
                'author_name': post.get('author_name', 'Anonymous'),
                'likes': post.get('likes', 0),
                'comments': post.get('comments', []),
                'created_at': post['created_at'].isoformat() if post.get('created_at') else datetime.utcnow().isoformat(),
                'image_filename': post.get('image_filename')
            }
            
            # Check for image data - using 'image_data' field
            if 'image_data' in post and post['image_data']:
                try:
                    image_bytes = bytes(post['image_data'])
                    post_dict['image_base64'] = base64.b64encode(image_bytes).decode('utf-8')
                    print(f"Image found for post: {post.get('title')}, base64 length: {len(post_dict['image_base64'])}")
                except Exception as e:
                    print(f"Error converting image: {e}")
                    post_dict['image_base64'] = None
            else:
                print(f"No image data for post: {post.get('title')}")
                post_dict['image_base64'] = None
                
            result.append(post_dict)
        return result
    
    @staticmethod
    def get_post_by_id(post_id):
        if isinstance(post_id, str):
            post_id = ObjectId(post_id)
        post = mongo.db.posts.find_one({'_id': post_id})
        if post:
            post_dict = {
                '_id': str(post['_id']),
                'title': post.get('title', 'Untitled'),
                'category': post.get('category', 'General'),
                'content': post.get('content', ''),
                'author_id': str(post.get('author_id', '')),
                'author_name': post.get('author_name', 'Anonymous'),
                'likes': post.get('likes', 0),
                'comments': post.get('comments', []),
                'created_at': post['created_at'].isoformat() if post.get('created_at') else datetime.utcnow().isoformat(),
                'image_filename': post.get('image_filename')
            }
            
            if 'image_data' in post and post['image_data']:
                try:
                    image_bytes = bytes(post['image_data'])
                    post_dict['image_base64'] = base64.b64encode(image_bytes).decode('utf-8')
                except Exception as e:
                    print(f"Error converting image: {e}")
                    post_dict['image_base64'] = None
            else:
                post_dict['image_base64'] = None
                
            return post_dict
        return None
    
    @staticmethod
    def get_posts_by_user(user_id):
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        posts = list(mongo.db.posts.find({'author_id': user_id}).sort('created_at', -1))
        result = []
        for post in posts:
            post_dict = {
                '_id': str(post['_id']),
                'title': post.get('title', 'Untitled'),
                'category': post.get('category', 'General'),
                'content': post.get('content', ''),
                'author_id': str(post.get('author_id', '')),
                'author_name': post.get('author_name', 'Anonymous'),
                'likes': post.get('likes', 0),
                'comments': post.get('comments', []),
                'created_at': post['created_at'].isoformat() if post.get('created_at') else datetime.utcnow().isoformat(),
                'image_filename': post.get('image_filename')
            }
            
            if 'image_data' in post and post['image_data']:
                try:
                    image_bytes = bytes(post['image_data'])
                    post_dict['image_base64'] = base64.b64encode(image_bytes).decode('utf-8')
                except Exception as e:
                    print(f"Error converting image: {e}")
                    post_dict['image_base64'] = None
            else:
                post_dict['image_base64'] = None
                
            result.append(post_dict)
        return result
    
    @staticmethod
    def add_comment(post_id, comment):
        if isinstance(post_id, str):
            post_id = ObjectId(post_id)
        return mongo.db.posts.update_one(
            {'_id': post_id},
            {'$push': {'comments': comment}}
        )
    
    @staticmethod
    def like_post(post_id):
        if isinstance(post_id, str):
            post_id = ObjectId(post_id)
        return mongo.db.posts.update_one(
            {'_id': post_id},
            {'$inc': {'likes': 1}}
        )
