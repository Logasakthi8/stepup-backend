from datetime import datetime, timedelta, timezone, date
from bson import ObjectId
import pytz
from typing import Optional, Dict, Any, List, Tuple, Union
import bcrypt
import re

# ------------------ HELPERS ------------------
def get_user_local_now(user_timezone_str="Asia/Kolkata"):
    """Gets current datetime in the user's local timezone."""
    try:
        user_tz = pytz.timezone(user_timezone_str)
        return datetime.now(user_tz)
    except pytz.exceptions.UnknownTimeZoneError:
        return datetime.now(pytz.timezone("Asia/Kolkata"))

def safe_objectid(val: Union[str, ObjectId, None]) -> Optional[ObjectId]:
    try:
        if val is None:
            return None
        if isinstance(val, ObjectId):
            return val
        return ObjectId(val)
    except Exception:
        return None

def convert_object_ids(obj):
    """Recursively convert Mongo ObjectId, datetime, and bytes to JSON-serializable values"""
    if obj is None:
        return None
        
    if isinstance(obj, list):
        return [convert_object_ids(i) for i in obj]
    elif isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(v, ObjectId):
                result[k] = str(v)
            elif isinstance(v, datetime):
                # Ensure datetime is timezone-aware for JSON serialization
                if v.tzinfo is None:
                    v = v.replace(tzinfo=timezone.utc)
                result[k] = v.isoformat()
            elif isinstance(v, bytes):
                try:
                    result[k] = v.decode('utf-8', errors='ignore')
                except:
                    result[k] = str(v)
            elif isinstance(v, (dict, list)):
                result[k] = convert_object_ids(v)
            else:
                result[k] = v
        return result
    elif isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.isoformat()
    elif isinstance(obj, bytes):
        try:
            return obj.decode('utf-8', errors='ignore')
        except:
            return str(obj)
    return obj

# ------------------ USER ------------------

class User:
    def __init__(self, db):
        self.collection = db.users if db else None

    def create_user(self, email, password, name=None, profile_photo=None, profile_photo_type=None):
        if not self.collection:
            return None
            
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        user = {
            "email": email,
            "password": hashed,
            "name": name or email.split('@')[0],
            "profile_photo": profile_photo,
            "profile_photo_type": profile_photo_type or "image/jpeg",
            "total_points": 0,
            "current_challenge": None,
            "followers": [],
            "following": [],
            "bio": "",
            "isVerified": False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        res = self.collection.insert_one(user)
        user["_id"] = res.inserted_id
        return convert_object_ids(user)

    def find_by_email(self, email):
        if not self.collection:
            return None
        return self.collection.find_one({"email": email})

    def find_by_id(self, user_id):
        oid = safe_objectid(user_id)
        if not oid or not self.collection:
            return None
        return self.collection.find_one({"_id": oid})

    def verify_password(self, hashed_password, password):
        if not hashed_password:
            return False
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        try:
            return bcrypt.checkpw(password.encode(), hashed_password)
        except Exception:
            return False

# ------------------ CHALLENGE ------------------

class Challenge:
    def __init__(self, db, default_timezone: str = "Asia/Kolkata"):
        self.collection = db.challenges if db else None
        self.db = db
        self.default_timezone = default_timezone
        self.ist_tz = pytz.timezone("Asia/Kolkata")
    
    # ------------------ PRIVATE HELPERS ------------------
    
    def _validate_time_format(self, time_str: str) -> bool:
        """Validate that time string is in HH:MM format (24-hour)."""
        pattern = r'^([01]?[0-9]|2[0-3]):([0-5][0-9])$'
        return bool(re.match(pattern, time_str))
    
    def _parse_time_string(self, time_str: str) -> Tuple[int, int]:
        """Parse HH:MM string into hour and minute integers."""
        if not self._validate_time_format(time_str):
            raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM (24-hour)")
        hour, minute = map(int, time_str.split(':'))
        return hour, minute
    
    def _get_user_now(self, user_timezone: str = None) -> datetime:
        """Get current datetime in user's timezone."""
        try:
            tz = pytz.timezone(user_timezone or self.default_timezone)
            return datetime.now(tz)
        except pytz.exceptions.UnknownTimeZoneError:
            return datetime.now(self.ist_tz)
    
    def _calculate_window_times(self, target_date: date, hour: int, minute: int, 
                               window_minutes: int) -> Tuple[datetime, datetime]:
        """Calculate window start and end datetimes for a specific date."""
        # Create window start for the target date
        window_start_naive = datetime.combine(target_date, datetime.min.time()).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        
        # Localize to IST
        window_start = self.ist_tz.localize(window_start_naive)
        
        # Calculate window end
        window_end = window_start + timedelta(minutes=window_minutes)
        
        return window_start, window_end
    
    def _get_today_user_date(self) -> date:
        """Get today's date in IST."""
        user_now = self._get_user_now(self.default_timezone)
        return user_now.date()
    
    def _get_current_calendar_day(self, challenge: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get the current day's calendar entry based on today's date."""
        today_ist = self._get_today_user_date()
        today_str = today_ist.isoformat()
        
        # Find today's entry
        for day in challenge.get("calendar_days", []):
            if day.get("date") == today_str:
                return day
        
        # If not found, find the first pending day
        for day in challenge.get("calendar_days", []):
            if day.get("status") == "pending":
                return day
        
        return None
    
    # ------------------ PUBLIC METHODS ------------------
    
    def create_challenge(self, user_id: str, challenge_name: str, duration: int, 
                        daily_post_time: str, time_window_minutes: int = 60, 
                        description: str = None) -> Dict[str, Any]:
        """
        Create a new challenge with IST timezone only.
        """
        if not self.collection:
            return None
            
        if not self._validate_time_format(daily_post_time):
            raise ValueError(f"Invalid daily_post_time format: {daily_post_time}. Use HH:MM (24-hour)")
        
        if duration <= 0:
            raise ValueError("Duration must be positive")
        
        if time_window_minutes <= 0:
            raise ValueError("Time window must be positive")
        
        target_hour, target_minute = self._parse_time_string(daily_post_time)
        
        # Get current time in IST for start date
        user_now = self._get_user_now(self.default_timezone)
        start_date = user_now.date()
        
        # Generate calendar days with dates in IST
        calendar_days = []
        
        for i in range(duration):
            day_date = start_date + timedelta(days=i)
            
            # Calculate window times for each day in IST
            window_start, window_end = self._calculate_window_times(
                day_date, target_hour, target_minute, time_window_minutes
            )
            
            calendar_days.append({
                "day_number": i + 1,
                "date": day_date.isoformat(),
                "status": "pending",
                "points_earned": 0,
                "post_id": None,
                "completed_at": None,
                "window_start_ist": window_start.isoformat(),
                "window_end_ist": window_end.isoformat(),
                "daily_post_time": daily_post_time,
                "time_window_minutes": time_window_minutes
            })
        
        # Store challenge
        challenge = {
            "user_id": safe_objectid(user_id),
            "challenge_name": challenge_name,
            "duration": int(duration),
            "current_day": 1,
            "daily_post_time": daily_post_time,
            "time_window_minutes": int(time_window_minutes),
            "description": description or "",
            "user_timezone": self.default_timezone,
            "start_date": start_date.isoformat(),
            "status": "active",
            "total_points": 0,
            "calendar_days": calendar_days,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        res = self.collection.insert_one(challenge)
        challenge["_id"] = res.inserted_id
        return convert_object_ids(challenge)
    
    def get_user_challenge(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get active challenge for a user with proper missed-day calculation.
        """
        if not self.collection:
            return None
            
        oid = safe_objectid(user_id)
        if not oid:
            return None
        
        # Get challenge from database
        challenge = self.collection.find_one({
            "user_id": oid, 
            "status": {"$in": ["active", "pending"]}
        })
        
        if not challenge:
            return None
        
        # Get today's date in user's timezone
        today_date = self._get_today_user_date()
        now_dt = self._get_user_now(self.default_timezone)
        
        calendar_days = challenge.get("calendar_days", [])
        updated = False
        found_today = False
        
        for day in calendar_days:
            day_date_str = day.get("date")
            if not day_date_str:
                continue
            
            try:
                day_date = date.fromisoformat(day_date_str)
            except ValueError:
                continue
            
            day_status = day.get("status", "pending")
            
            # Check if this is today's entry
            if day_date == today_date:
                found_today = True
            
            # Process missed days (date has passed and still pending)
            if day_date < today_date and day_status == "pending":
                window_end_str = day.get("window_end_ist")
                if window_end_str:
                    try:
                        window_end = datetime.fromisoformat(window_end_str)
                        if window_end.tzinfo is None:
                            window_end = self.ist_tz.localize(window_end)
                        
                        # Mark as missed if window has definitely passed
                        if now_dt > window_end:
                            day["status"] = "missed"
                            day["points_earned"] = 0
                            updated = True
                    except Exception:
                        # If we can't parse, mark as missed based on date only
                        day["status"] = "missed"
                        day["points_earned"] = 0
                        updated = True
        
        # Update current_day based on status
        current_day_calculated = 1
        for day in calendar_days:
            if day.get("status") == "completed":
                current_day_calculated = day.get("day_number", 1) + 1
            elif day.get("status") == "pending":
                # Found the first pending day
                break
            elif day.get("status") == "missed":
                current_day_calculated = day.get("day_number", 1) + 1
        
        # Ensure current_day doesn't exceed duration
        current_day_calculated = min(current_day_calculated, challenge.get("duration", 1))
        
        # If we're past the challenge duration, complete it
        if current_day_calculated > challenge.get("duration", 1):
            challenge["status"] = "completed"
            updated = True
        
        if updated or current_day_calculated != challenge.get("current_day", 1):
            now_utc = datetime.utcnow()
            self.collection.update_one(
                {"_id": challenge["_id"]},
                {"$set": {
                    "calendar_days": calendar_days,
                    "current_day": current_day_calculated,
                    "status": challenge.get("status", "active"),
                    "updated_at": now_utc
                }}
            )
            # Refresh the challenge
            challenge = self.collection.find_one({"_id": challenge["_id"]})
        
        # Convert to JSON serializable format
        converted_challenge = convert_object_ids(challenge)
        
        # Ensure all required fields exist
        converted_challenge.setdefault("calendar_days", [])
        converted_challenge.setdefault("current_day", 1)
        converted_challenge.setdefault("duration", 30)
        converted_challenge.setdefault("daily_post_time", "19:00")
        converted_challenge.setdefault("time_window_minutes", 60)
        converted_challenge.setdefault("total_points", 0)
        converted_challenge.setdefault("description", "")
        converted_challenge.setdefault("start_date", datetime.utcnow().date().isoformat())
        converted_challenge.setdefault("user_timezone", self.default_timezone)
        
        # Add calendarDays for backward compatibility
        if "calendarDays" not in converted_challenge:
            converted_challenge["calendarDays"] = converted_challenge.get("calendar_days", [])
        
        return converted_challenge
    
    def check_posting_availability(self, user_id: str) -> Dict[str, Any]:
        """Check if user can post today based on current time in user's timezone."""
        if not self.collection or not self.db:
            return {
                "allowed": False,
                "reason": "database_unavailable",
                "message": "Database not available",
                "already_posted": False
            }
            
        challenge = self.get_user_challenge(user_id)
        if not challenge:
            return {
                "allowed": False,
                "reason": "no_active_challenge",
                "message": "No active challenge found",
                "already_posted": False,
                "window_start": None,
                "window_end": None,
                "timezone": self.default_timezone,
                "current_day": 1,
                "daily_points": 100
            }
        
        now_dt = self._get_user_now(self.default_timezone)
        today_str = now_dt.date().isoformat()
        
        # Find today's calendar day or next pending day
        target_day = None
        for day in challenge.get("calendar_days", []):
            if day.get("date") == today_str:
                target_day = day
                break
        
        # If not found, find first pending day
        if not target_day:
            for day in challenge.get("calendar_days", []):
                if day.get("status") == "pending":
                    target_day = day
                    break
        
        if not target_day:
            return {
                "allowed": False,
                "reason": "no_valid_day",
                "message": "No valid challenge day found",
                "already_posted": False,
                "window_start": None,
                "window_end": None,
                "timezone": self.default_timezone,
                "current_day": challenge.get("current_day", 1),
                "daily_points": 100
            }
        
        # Get day details
        day_number = target_day.get("day_number", challenge.get("current_day", 1))
        day_date_str = target_day.get("date")
        day_status = target_day.get("status", "pending")
        
        # Check if day is already completed or missed
        if day_status in ["completed", "missed"]:
            window_start = target_day.get("window_start_ist")
            window_end = target_day.get("window_end_ist")
            
            return {
                "allowed": False,
                "reason": "day_already_processed",
                "message": f"Day {day_number} is already {day_status}",
                "day_number": day_number,
                "day_status": day_status,
                "already_posted": day_status == "completed",
                "window_start": window_start,
                "window_end": window_end,
                "timezone": self.default_timezone,
                "current_day": challenge.get("current_day", 1),
                "daily_points": 100 + (day_number - 1) * 50
            }
        
        # Get window times
        window_start_str = target_day.get("window_start_ist")
        window_end_str = target_day.get("window_end_ist")
        
        if not window_start_str or not window_end_str:
            # Calculate window based on daily time
            daily_time = challenge.get("daily_post_time", "19:00")
            window_minutes = challenge.get("time_window_minutes", 60)
            hour, minute = map(int, daily_time.split(':'))
            
            try:
                day_date = date.fromisoformat(day_date_str)
                window_start, window_end = self._calculate_window_times(
                    day_date, hour, minute, window_minutes
                )
                window_start_str = window_start.isoformat()
                window_end_str = window_end.isoformat()
            except Exception:
                return {
                    "allowed": False,
                    "reason": "invalid_window",
                    "message": "Unable to determine posting window",
                    "day_number": day_number,
                    "already_posted": False,
                    "window_start": None,
                    "window_end": None,
                    "timezone": self.default_timezone,
                    "current_day": day_number,
                    "daily_points": 100 + (day_number - 1) * 50
                }
        
        # Check if already posted for this day
        user_oid = safe_objectid(user_id)
        challenge_oid = safe_objectid(challenge["_id"])
        
        if not user_oid or not challenge_oid:
            return {
                "allowed": False,
                "reason": "invalid_ids",
                "message": "Invalid user or challenge ID",
                "already_posted": False,
                "window_start": window_start_str,
                "window_end": window_end_str,
                "timezone": self.default_timezone,
                "current_day": challenge.get("current_day", 1),
                "daily_points": 100 + (day_number - 1) * 50
            }
        
        # Check for existing post for this day
        already_posted = self.db.posts.find_one({
            "user_id": user_oid,
            "challenge_id": challenge_oid,
            "day_number": day_number
        })
        
        if already_posted:
            return {
                "allowed": False,
                "reason": "already_posted",
                "message": f"You have already posted for day {day_number}",
                "day_number": day_number,
                "already_posted": True,
                "window_start": window_start_str,
                "window_end": window_end_str,
                "timezone": self.default_timezone,
                "current_day": day_number,
                "daily_points": 100 + (day_number - 1) * 50
            }
        
        # Check if within window
        try:
            window_start = datetime.fromisoformat(window_start_str)
            window_end = datetime.fromisoformat(window_end_str)
            
            if window_start.tzinfo is None:
                window_start = self.ist_tz.localize(window_start)
            if window_end.tzinfo is None:
                window_end = self.ist_tz.localize(window_end)
            
            if window_start <= now_dt <= window_end:
                minutes_remaining = max(0, int((window_end - now_dt).total_seconds() / 60))
                return {
                    "allowed": True,
                    "reason": "within_window",
                    "message": f"You can post now for day {day_number}! Window closes in {minutes_remaining} minutes.",
                    "day_number": day_number,
                    "already_posted": False,
                    "window_start": window_start_str,
                    "window_end": window_end_str,
                    "timezone": self.default_timezone,
                    "current_day": day_number,
                    "daily_points": 100 + (day_number - 1) * 50,
                    "minutes_remaining": minutes_remaining
                }
            elif now_dt < window_start:
                minutes_until = max(0, int((window_start - now_dt).total_seconds() / 60))
                return {
                    "allowed": False,
                    "reason": "before_window",
                    "message": f"Posting window for day {day_number} opens in {minutes_until} minutes",
                    "day_number": day_number,
                    "already_posted": False,
                    "window_start": window_start_str,
                    "window_end": window_end_str,
                    "timezone": self.default_timezone,
                    "current_day": day_number,
                    "daily_points": 100 + (day_number - 1) * 50,
                    "time_until_window_minutes": minutes_until
                }
            else:
                # Window has passed - mark as missed
                if day_status == "pending":
                    # Update calendar day to missed
                    calendar_days = challenge.get("calendar_days", [])
                    for i, day in enumerate(calendar_days):
                        if day.get("day_number") == day_number:
                            calendar_days[i]["status"] = "missed"
                            calendar_days[i]["points_earned"] = 0
                            break
                    
                    # Update challenge in database
                    self.collection.update_one(
                        {"_id": challenge_oid},
                        {
                            "$set": {
                                "calendar_days": calendar_days,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                
                return {
                    "allowed": False,
                    "reason": "after_window",
                    "message": f"Posting window for day {day_number} has ended",
                    "day_number": day_number,
                    "already_posted": False,
                    "window_start": window_start_str,
                    "window_end": window_end_str,
                    "timezone": self.default_timezone,
                    "current_day": day_number,
                    "daily_points": 100 + (day_number - 1) * 50,
                    "day_status": "missed"
                }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error checking window: {str(e)}")
            
        # If we get here, there's an issue with window times
        return {
            "allowed": False,
            "reason": "invalid_window",
            "message": "Unable to determine posting window",
            "day_number": day_number,
            "already_posted": False,
            "window_start": window_start_str,
            "window_end": window_end_str,
            "timezone": self.default_timezone,
            "current_day": day_number,
            "daily_points": 100 + (day_number - 1) * 50
        }
    
    def update_challenge_day(self, challenge_id: str, day_number: int, 
                         post_id: str, points: int = 100) -> Dict[str, Any]:
        """Update a challenge day as completed and return updated challenge."""
        if not self.collection:
            return {"success": False, "error": "Database not available"}
            
        oid = safe_objectid(challenge_id)
        if not oid:
            return {"success": False, "error": "Invalid challenge ID"}
        
        challenge = self.collection.find_one({"_id": oid})
        if not challenge:
            return {"success": False, "error": "Challenge not found"}
        
        user_oid = challenge.get("user_id")
        calendar_days = challenge.get("calendar_days", [])
        
        # Find and update the day
        found_day = False
        for i, day in enumerate(calendar_days):
            if day.get("day_number") == day_number:
                calendar_days[i]["status"] = "completed"
                calendar_days[i]["points_earned"] = points
                calendar_days[i]["post_id"] = post_id
                calendar_days[i]["completed_at"] = datetime.utcnow()
                found_day = True
                break
        
        if not found_day:
            return {"success": False, "error": f"Day {day_number} not found"}
        
        # Calculate new current day (next pending day)
        new_current_day = day_number + 1
        for day in calendar_days:
            if day.get("day_number") == new_current_day and day.get("status") == "pending":
                break
            elif day.get("day_number") > new_current_day:
                new_current_day = day.get("day_number")
                break
        else:
            # If no more pending days, set to duration
            new_current_day = challenge.get("duration", day_number + 1)
        
        # Update challenge
        update_result = self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "calendar_days": calendar_days,
                    "current_day": new_current_day,
                    "updated_at": datetime.utcnow()
                },
                "$inc": {"total_points": points}
            }
        )
        
        # Update user points if user collection exists
        if user_oid and self.db and hasattr(self.db, 'users'):
            self.db.users.update_one(
                {"_id": user_oid},
                {"$inc": {"total_points": points}}
            )
        
        # Get updated challenge
        updated_challenge = self.collection.find_one({"_id": oid})
        
        if not updated_challenge:
            return {"success": False, "error": "Failed to update challenge"}
        
        return {
            "success": True,
            "challenge": convert_object_ids(updated_challenge),
            "current_day": new_current_day,
            "total_points": updated_challenge.get("total_points", points)
        }
    
    def get_challenge_calendar(self, challenge_id: str) -> Optional[List[Dict[str, Any]]]:
        if not self.collection:
            return None
            
        oid = safe_objectid(challenge_id)
        if not oid:
            return None
        
        challenge = self.collection.find_one(
            {"_id": oid},
            {"calendar_days": 1, "challenge_name": 1, "duration": 1}
        )
        
        if not challenge:
            return None
        
        return convert_object_ids(challenge.get("calendar_days", []))
    
    def complete_challenge(self, challenge_id: str) -> bool:
        if not self.collection:
            return False
            
        oid = safe_objectid(challenge_id)
        if not oid:
            return False
        
        result = self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "completed",
                    "updated_at": datetime.utcnow(),
                    "completed_at": datetime.utcnow()
                }
            }
        )
        
        return result.modified_count > 0
    
    def cancel_challenge(self, challenge_id: str) -> bool:
        if not self.collection:
            return False
            
        oid = safe_objectid(challenge_id)
        if not oid:
            return False
        
        result = self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "cancelled",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return result.modified_count > 0

# ------------------ POST ------------------

class Post:
    def __init__(self, db):
        self.db = db
        self.collection = db.posts if db else None

    def create_post(self, user_id, challenge_id, day_number, description='', image_url=None, image_type=None):
        if not self.collection or not self.db:
            return {"error": "Database not available"}
            
        user_oid = safe_objectid(user_id)
        challenge_oid = safe_objectid(challenge_id)
        
        if not user_oid or not challenge_oid:
            return {"error": "Invalid user or challenge ID"}
        
        # Check if post already exists for this day
        existing_post = self.collection.find_one({
            "user_id": user_oid,
            "challenge_id": challenge_oid,
            "day_number": int(day_number)
        })
        
        if existing_post:
            return {"error": "You have already posted for this day"}
        
        # Calculate points for this day
        points_earned = 100 + (day_number - 1) * 50
        
        post_data = {
            "user_id": user_oid,
            "challenge_id": challenge_oid,
            "day_number": int(day_number),
            "description": description,
            "image_url": image_url,
            "image_type": image_type or "image/jpeg",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "deleted_by_user": False,
            "boosts": [],
            "boosts_count": 0,
            "comments": [],
            "comment_count": 0,
            "points_earned": points_earned
        }
        
        result = self.collection.insert_one(post_data)
        post_id = result.inserted_id
        
        # Update challenge day
        challenge_handler = Challenge(self.db, default_timezone="Asia/Kolkata")
        update_result = challenge_handler.update_challenge_day(
            str(challenge_id), day_number, str(post_id), points_earned
        )
        
        if not update_result.get("success"):
            # Rollback post creation if challenge update fails
            self.collection.delete_one({"_id": post_id})
            return {"error": "Failed to update challenge"}
        
        # Get user and challenge info for response
        user = self.db.users.find_one({"_id": user_oid}) if self.db.users else None
        challenge = self.db.challenges.find_one({"_id": challenge_oid}) if self.db.challenges else None
        
        post_data["_id"] = post_id
        post_data["user_name"] = user.get("name") if user else "Anonymous"
        post_data["profile_photo"] = user.get("profile_photo") if user else None
        post_data["challenge_name"] = challenge.get("challenge_name") if challenge else None
        
        response_data = convert_object_ids(post_data)
        response_data["total_points"] = update_result.get("total_points", points_earned)
        response_data["current_day"] = update_result.get("current_day", day_number + 1)
        response_data["day_completed"] = day_number
        
        return response_data
    
    def boost_post(self, post_id, user_id):
        if not self.collection:
            return None
            
        oid = safe_objectid(post_id)
        user_oid = safe_objectid(user_id)
        
        if not oid or not user_oid:
            return None
        
        post = self.collection.find_one({"_id": oid})
        if not post:
            return None
        
        boosts = post.get("boosts", [])
        boosts_count = post.get("boosts_count", 0)
        is_boosted = user_oid in boosts
        
        if is_boosted:
            boosts.remove(user_oid)
            boosts_count -= 1
            action = "unboosted"
        else:
            boosts.append(user_oid)
            boosts_count += 1
            action = "boosted"
        
        self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "boosts": boosts,
                    "boosts_count": boosts_count,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "action": action,
            "boosts_count": boosts_count,
            "is_boosted": not is_boosted
        }
    
    def add_comment(self, post_id, user_id, text):
        if not self.collection:
            return None
            
        oid = safe_objectid(post_id)
        user_oid = safe_objectid(user_id)
        
        if not oid or not user_oid:
            return None
        
        post = self.collection.find_one({"_id": oid})
        if not post:
            return None
        
        comment = {
            "_id": ObjectId(),
            "user_id": user_oid,
            "text": text,
            "created_at": datetime.utcnow()
        }
        
        comments = post.get("comments", [])
        comments.append(comment)
        comment_count = len(comments)
        
        self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "comments": comments,
                    "comment_count": comment_count,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "comments": convert_object_ids(comments),
            "comment_count": comment_count
        }
    
    def delete_post_by_user(self, post_id, user_id):
        if not self.collection:
            return {"error": "Database not available"}, 503
            
        oid = safe_objectid(post_id)
        user_oid = safe_objectid(user_id)
        
        if not oid or not user_oid:
            return {"error": "Invalid post or user ID"}, 400
        
        post = self.collection.find_one({"_id": oid})
        if not post:
            return {"error": "Post not found"}, 404
        
        if post.get("user_id") != user_oid:
            return {"error": "Not authorized to delete this post"}, 403
        
        self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "deleted_by_user": True,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {"message": "Post deleted successfully"}, 200

# ------------------ FOLLOW ------------------

class Follow:
    def __init__(self, db):
        self.collection = db.users if db else None

    def follow_user(self, follower_id, following_id):
        if not self.collection:
            return False
            
        follower_oid = safe_objectid(follower_id)
        following_oid = safe_objectid(following_id)
        
        if not follower_oid or not following_oid:
            return False
        
        if follower_oid == following_oid:
            return False
        
        # Update follower's following list
        result1 = self.collection.update_one(
            {"_id": follower_oid},
            {"$addToSet": {"following": following_oid}}
        )
        
        # Update following user's followers list
        result2 = self.collection.update_one(
            {"_id": following_oid},
            {"$addToSet": {"followers": follower_oid}}
        )
        
        return result1.modified_count > 0 or result2.modified_count > 0
    
    def unfollow_user(self, follower_id, following_id):
        if not self.collection:
            return False
            
        follower_oid = safe_objectid(follower_id)
        following_oid = safe_objectid(following_id)
        
        if not follower_oid or not following_oid:
            return False
        
        # Update follower's following list
        result1 = self.collection.update_one(
            {"_id": follower_oid},
            {"$pull": {"following": following_oid}}
        )
        
        # Update following user's followers list
        result2 = self.collection.update_one(
            {"_id": following_oid},
            {"$pull": {"followers": follower_oid}}
        )
        
        return result1.modified_count > 0 or result2.modified_count > 0
