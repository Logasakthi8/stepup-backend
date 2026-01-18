from unittest import result
import bcrypt 
import re
from datetime import datetime, timedelta, timezone, date
from bson import ObjectId
import pytz
from typing import Optional, Dict, Any, List, Tuple, Union

# ------------------ HELPERS ------------------
def get_user_local_now(user_timezone_str="Asia/Kolkata"):
    """Gets current datetime in the user's local timezone."""
    try:
        user_tz = pytz.timezone(user_timezone_str)
        return datetime.now(user_tz)
    except pytz.exceptions.UnknownTimeZoneError:
        # Fallback to IST if timezone is invalid
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
    if isinstance(obj, list):
        return [convert_object_ids(i) for i in obj]
    elif isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(v, ObjectId):
                result[k] = str(v)
            elif isinstance(v, datetime):
                result[k] = v.isoformat()
            elif isinstance(v, bytes):
                result[k] = v.decode('utf-8', errors='ignore')
            elif isinstance(v, (dict, list)):
                result[k] = convert_object_ids(v)
            else:
                result[k] = v
        return result
    return obj

# ------------------ USER ------------------

class User:
    def __init__(self, db):
        self.collection = db.users

    def create_user(self, email, password, name=None, profile_photo=None, profile_photo_type=None):
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
            "created_at": datetime.utcnow()
        }
        res = self.collection.insert_one(user)
        user["_id"] = res.inserted_id
        return user

    def find_by_email(self, email):
        return self.collection.find_one({"email": email})

    def find_by_id(self, user_id):
        oid = safe_objectid(user_id)
        if not oid:
            return None
        return self.collection.find_one({"_id": oid}, {"password": 0})

    def verify_password(self, hashed_password, password):
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password.encode(), hashed_password)

# ------------------ CHALLENGE ------------------

from unittest import result
import bcrypt
import re
from datetime import datetime, timedelta, timezone, date
from bson import ObjectId
import pytz
from typing import Optional, Dict, Any, List, Tuple, Union

# ------------------ HELPERS ------------------
def get_user_local_now(user_timezone_str="Asia/Kolkata"):
    """Gets current datetime in the user's local timezone."""
    try:
        user_tz = pytz.timezone(user_timezone_str)
        return datetime.now(user_tz)
    except pytz.exceptions.UnknownTimeZoneError:
        # Fallback to IST if timezone is invalid
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
    if isinstance(obj, list):
        return [convert_object_ids(i) for i in obj]
    elif isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(v, ObjectId):
                result[k] = str(v)
            elif isinstance(v, datetime):
                result[k] = v.isoformat()
            elif isinstance(v, bytes):
                result[k] = v.decode('utf-8', errors='ignore')
            elif isinstance(v, (dict, list)):
                result[k] = convert_object_ids(v)
            else:
                result[k] = v
        return result
    return obj

# ------------------ USER ------------------

class User:
    def __init__(self, db):
        self.collection = db.users

    def create_user(self, email, password, name=None, profile_photo=None, profile_photo_type=None):
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
            "created_at": datetime.utcnow()
        }
        res = self.collection.insert_one(user)
        user["_id"] = res.inserted_id
        return user

    def find_by_email(self, email):
        return self.collection.find_one({"email": email})

    def find_by_id(self, user_id):
        oid = safe_objectid(user_id)
        if not oid:
            return None
        return self.collection.find_one({"_id": oid}, {"password": 0})

    def verify_password(self, hashed_password, password):
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password.encode(), hashed_password)

# ------------------ CHALLENGE ------------------

class Challenge:
    def __init__(self, db, default_timezone: str = "Asia/Kolkata"):
        self.collection = db.challenges
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
        """Get current datetime in user's timezone (always IST)."""
        # Always use IST regardless of input
        return datetime.now(self.ist_tz)
    
    def _calculate_window_times(self, base_date: date, hour: int, minute: int, 
                               window_minutes: int, user_timezone: str) -> Tuple[datetime, datetime]:
        """Calculate window start and end datetimes in IST."""
        # Always use IST
        user_tz = self.ist_tz
        
        # Create window start in IST
        window_start_naive = datetime.combine(base_date, datetime.min.time()).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        window_start = user_tz.localize(window_start_naive)
        
        # Calculate window end
        window_end = window_start + timedelta(minutes=window_minutes)
        
        return window_start, window_end
    
    def _is_within_window(self, current_time: datetime, window_start: datetime, 
                         window_end: datetime) -> bool:
        """Check if current time is within posting window."""
        return window_start <= current_time <= window_end
    
    def _get_today_user_date(self, user_timezone: str) -> date:
        """Get today's date in IST."""
        user_now = self._get_user_now(user_timezone)
        return user_now.date()
    
    def _fallback_window_calculation(self, challenge: Dict[str, Any], tz_str: str, user_now: datetime) -> Dict[str, Any]:
        """Fallback method if stored window times are invalid"""
        daily_time = challenge["daily_post_time"]
        try:
            target_hour, target_minute = self._parse_time_string(daily_time)
        except ValueError:
            return {
                "allowed": False,
                "reason": "invalid_time_format",
                "message": "Challenge has invalid time format."
            }
        
        window_minutes = challenge.get("time_window_minutes", 60)
        
        # Calculate today's window
        window_start, window_end = self._calculate_window_times(
            user_now.date(), target_hour, target_minute, window_minutes, "Asia/Kolkata"
        )
        
        if self._is_within_window(user_now, window_start, window_end):
            mins_remaining = max(0, int((window_end - user_now).total_seconds() / 60))
            return {
                "allowed": True,
                "reason": "within_window",
                "message": f"You can post now! Window closes in {mins_remaining} minutes.",
                "daily_post_time": daily_time,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "minutes_remaining": mins_remaining,
                "type": "WITHIN_WINDOW"
            }
        elif user_now < window_start:
            mins_until = max(0, int((window_start - user_now).total_seconds() / 60))
            return {
                "allowed": False,
                "reason": "before_window",
                "message": f"Posting window opens in {mins_until} minutes.",
                "daily_post_time": daily_time,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "time_until_window_minutes": mins_until,
                "type": "BEFORE_WINDOW"
            }
        else:
            return {
                "allowed": False,
                "reason": "after_window",
                "message": "Today's posting window has closed.",
                "daily_post_time": daily_time,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "type": "AFTER_WINDOW"
            }
    
    def _get_window_times_from_day(self, day: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Get window times from a calendar day with backward compatibility."""
        # Try new field names first, then old field names
        window_start = day.get("window_start_ist") or day.get("window_start_utc")
        window_end = day.get("window_end_ist") or day.get("window_end_utc")
        return window_start, window_end
    
    # ------------------ PUBLIC METHODS ------------------
    
    def create_challenge(self, user_id: str, challenge_name: str, duration: int, 
                        daily_post_time: str, time_window_minutes: int = 60, 
                        description: str = None, user_timezone: str = None) -> Dict[str, Any]:
        """
        Create a new challenge with IST timezone only.
        
        Args:
            user_id: User's MongoDB ID
            challenge_name: Name of the challenge
            duration: Number of days
            daily_post_time: Time in HH:MM format (e.g., "19:00")
            time_window_minutes: Posting window duration (default: 60)
            description: Optional challenge description
            user_timezone: Ignored, always uses IST
            
        Returns:
            Created challenge document
        """
        # Validate inputs
        if not self._validate_time_format(daily_post_time):
            raise ValueError(f"Invalid daily_post_time format: {daily_post_time}. Use HH:MM (24-hour)")
        
        if duration <= 0:
            raise ValueError("Duration must be positive")
        
        if time_window_minutes <= 0:
            raise ValueError("Time window must be positive")
        
        # Parse the posting time
        target_hour, target_minute = self._parse_time_string(daily_post_time)
        
        # Get current time in IST for start date
        user_now = self._get_user_now("Asia/Kolkata")
        start_date = user_now.date()
        
        # Generate calendar days with dates in IST
        calendar_days = []
        
        for i in range(duration):
            day_date = start_date + timedelta(days=i)
            
            # Calculate window times for each day in IST
            window_start, window_end = self._calculate_window_times(
                day_date, target_hour, target_minute, time_window_minutes, "Asia/Kolkata"
            )
            
            calendar_days.append({
                "day_number": i + 1,
                "date": day_date.isoformat(),  # Store as ISO date string (YYYY-MM-DD)
                "status": "pending",
                "points_earned": 0,
                "post_id": None,
                "completed_at": None,
                "window_start_ist": window_start.isoformat(),  # Store IST time directly
                "window_end_ist": window_end.isoformat(),      # Store IST time directly
                # Keep old field names for backward compatibility
                "window_start_utc": window_start.astimezone(timezone.utc).isoformat(),
                "window_end_utc": window_end.astimezone(timezone.utc).isoformat(),
                "daily_post_time": daily_post_time,
                "time_window_minutes": time_window_minutes
            })
        
        # Store challenge with IST timezone info
        challenge = {
            "user_id": safe_objectid(user_id),
            "challenge_name": challenge_name,
            "duration": int(duration),
            "current_day": 1,
            "daily_post_time": daily_post_time,
            "time_window_minutes": int(time_window_minutes),
            "description": description or "",
            "user_timezone": "Asia/Kolkata",  # Always store IST
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
    
    def get_user_challenge(self, user_id: str, user_timezone: str = None) -> Optional[Dict[str, Any]]:
        """
        Get active challenge for a user with proper missed-day calculation in IST.
        
        Args:
            user_id: User's MongoDB ID
            user_timezone: Ignored, always uses IST
            
        Returns:
            Challenge document or None
        """
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
        
        # Get today's date in IST
        today_ist = self._get_today_user_date("Asia/Kolkata")
        
        calendar_days = challenge.get("calendar_days", [])
        updated = False
        
        for day in calendar_days:
            day_date_str = day.get("date")
            if not day_date_str:
                continue
            
            try:
                # Parse the stored date (YYYY-MM-DD)
                day_date = date.fromisoformat(day_date_str)
            except ValueError:
                continue
            
            # Only mark as missed if:
            # 1. It's a past date IN IST
            # 2. The day is still pending
            # 3. We're past the posting window for that day in IST
            if (day_date < today_ist and day.get("status") == "pending"):

                # Check if window has passed for this specific day in IST
                window_start_str, window_end_str = self._get_window_times_from_day(day)
                
                if window_end_str:
                    try:
                        # Parse the window end time
                        window_end = datetime.fromisoformat(window_end_str)
                        if window_end.tzinfo is None:
                            window_end = self.ist_tz.localize(window_end)

                        current_ist = self._get_user_now()

                        
                        # If the stored time is UTC (old format), convert to IST
                        if "Z" in window_end_str or "+00:00" in window_end_str:
                            # It's UTC, convert to IST
                            window_end = datetime.fromisoformat(window_end_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                            window_end = window_end.astimezone(self.ist_tz)
                        
                        # Only mark missed if window has definitely passed in IST
                        if current_ist > window_end:
                            day["status"] = "missed"
                            day["points_earned"] = 0
                            updated = True
                    except (ValueError, AttributeError):
                        # If we can't parse, be conservative and don't mark missed
                        pass
        
        if updated:
            now_utc = datetime.utcnow()
            self.collection.update_one(
                {"_id": challenge["_id"]},
                {"$set": {
                    "calendar_days": calendar_days, 
                    "updated_at": now_utc
                }}
            )
            # Refresh the challenge
            challenge = self.collection.find_one({"_id": challenge["_id"]})
        
        return convert_object_ids(challenge)
    
    
    def check_posting_availability(self, user_id: str, user_timezone: str = None) -> Dict[str, Any]:
        challenge = self.get_user_challenge(user_id, user_timezone)
        if not challenge:
            return {
                "allowed": False,
                "reason": "no_active_challenge",
                "message": "No active challenge found"
            }
        
        # Always use IST
        tz_str = "Asia/Kolkata"
        user_tz = self.ist_tz
        
        now_ist = self._get_user_now()
        
        # Parse the daily posting time (stored in challenge)
        daily_time = challenge.get("daily_post_time", "19:00")
        time_window_minutes = challenge.get("time_window_minutes", 60)
        
        try:
            # Parse hour and minute from the stored time
            hour, minute = map(int, daily_time.split(':'))
        except ValueError:
            return {
                "allowed": False,
                "reason": "invalid_time_format",
                "message": "Challenge has invalid time format."
            }
        
        # Get today's calendar day entry
        today_str = now_ist.date().isoformat()
        today_entry = next(
            (d for d in challenge["calendar_days"] if d["date"] == today_str),
            None
        )
        if not today_entry:
            return {
                "allowed": False,
                "reason": "no_calendar_day",
                "message": "No challenge day found for today"
            }
        
        # Get window times from the calendar day (with backward compatibility)
        window_start_str, window_end_str = self._get_window_times_from_day(today_entry)
        
        if not window_start_str or not window_end_str:
            # Fallback calculation if window times are missing
            return self._fallback_window_calculation(challenge, tz_str, now_ist)
        
        try:
            # Parse window times
            if window_start.tzinfo is None:
                window_start = self.ist_tz.localize(window_start)
            if window_end.tzinfo is None:
                window_end = self.ist_tz.localize(window_end)

            
            # If the stored time is in UTC (old format), convert to IST
            if "Z" in window_start_str or "+00:00" in window_start_str:
                # It's UTC, convert to IST
                window_start = datetime.fromisoformat(window_start_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                window_start = window_start.astimezone(user_tz)
                window_end = datetime.fromisoformat(window_end_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                window_end = window_end.astimezone(user_tz)
            
        except (ValueError, AttributeError) as e:
            # Fallback calculation if window times are invalid
            return self._fallback_window_calculation(challenge, tz_str, now_ist)
        
        # Check if user has already posted today
        user_oid = safe_objectid(user_id)
        challenge_oid = safe_objectid(challenge["_id"])
        
        if not user_oid or not challenge_oid:
            return {
                "allowed": False,
                "reason": "invalid_ids",
                "message": "Invalid user or challenge ID"
            }
        
        # Convert IST window times to UTC for database query (since posts are stored with UTC timestamps)
        window_start_utc = window_start.astimezone(timezone.utc)
        window_end_utc = window_end.astimezone(timezone.utc)
        
        # Check if post exists within today's window
        already_posted = self.db.posts.find_one({
            "user_id": user_oid,
            "challenge_id": challenge_oid,
            "created_at": {
                "$gte": window_start_utc,
                "$lte": window_end_utc
            }
        })
        
        # Calculate daily points for current day
        current_day = challenge.get("current_day", 1)
        daily_points = 100 + (current_day - 1) * 50
        
        # Prepare base response
        response_base = {
            "daily_post_time": daily_time,
            "time_window_minutes": time_window_minutes,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "current_time": now_ist.strftime("%H:%M:%S"),
            "current_date": now_ist.date().isoformat(),
            "timezone": tz_str,
            "current_day": current_day,
            "daily_points": daily_points,
            "already_posted": bool(already_posted)
        }
        
        if already_posted:
            return {
                **response_base,
                "allowed": False,
                "reason": "already_posted",
                "message": "You have already posted today",
                "type": "ALREADY_POSTED"
            }
        
        # Check if we're within the posting window (using IST)
        if window_start <= now_ist <= window_end:
            # Calculate minutes remaining
            minutes_remaining = max(0, int((window_end - now_ist).total_seconds() / 60))
            
            return {
                **response_base,
                "allowed": True,
                "reason": "within_window",
                "message": f"You can post now! Window closes in {minutes_remaining} minutes.",
                "minutes_remaining": minutes_remaining,
                "type": "WITHIN_WINDOW"
            }
        elif now_ist < window_start:
            # Before window
            minutes_until = max(0, int((window_start - now_ist).total_seconds() / 60))
            
            return {
                **response_base,
                "allowed": False,
                "reason": "before_window",
                "message": f"Posting window opens in {minutes_until} minutes",
                "time_until_window_minutes": minutes_until,
                "type": "BEFORE_WINDOW"
            }
        else:
            # After window
            return {
                **response_base,
                "allowed": False,
                "reason": "after_window",
                "message": "Posting window has ended for today",
                "type": "AFTER_WINDOW"
            }
    
    def debug_window_calculation(self, user_id: str):
        """Debug function to see what's happening in IST"""
        challenge = self.get_user_challenge(user_id)
        if not challenge:
            return "No challenge found"
        
        now_ist = self._get_user_now()
        
        debug_info = {
            "current_time_ist": now_ist.isoformat(),
            "daily_post_time": challenge.get('daily_post_time'),
            "timezone": "Asia/Kolkata",
            "today_date": now_ist.date().isoformat(),
            "window_minutes": challenge.get('time_window_minutes'),
            "calendar_days": []
        }
        
        # Check all calendar days
        for i, day in enumerate(challenge.get("calendar_days", [])):
            day_info = {
                "day_number": day.get('day_number'),
                "date": day.get('date'),
                "status": day.get('status'),
                "window_start": None,
                "window_end": None,
                "is_today": day.get('date') == now_ist.date().isoformat()
            }
            
            # Get window times with backward compatibility
            window_start_str, window_end_str = self._get_window_times_from_day(day)
            
            if window_start_str and window_end_str:
                day_info["window_start"] = window_start_str
                day_info["window_end"] = window_end_str
                
                try:
                    # Parse window times
                    window_start = datetime.fromisoformat(window_start_str)
                    window_end = datetime.fromisoformat(window_end_str)
                    
                    # If UTC, convert to IST
                    if "Z" in window_start_str or "+00:00" in window_start_str:
                        window_start = datetime.fromisoformat(window_start_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                        window_start = window_start.astimezone(self.ist_tz)
                        window_end = datetime.fromisoformat(window_end_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                        window_end = window_end.astimezone(self.ist_tz)
                    
                    day_info["is_within_window"] = window_start <= now_ist <= window_end
                    day_info["time_until_window"] = (window_start - now_ist).total_seconds() / 60 if now_ist < window_start else 0
                    day_info["time_since_window_end"] = (now_ist - window_end).total_seconds() / 60 if now_ist > window_end else 0
                    
                except Exception as e:
                    day_info["parse_error"] = str(e)
            
            debug_info["calendar_days"].append(day_info)
        
        # Add posting availability info
        debug_info["posting_availability"] = self.check_posting_availability(user_id)
        
        return debug_info
    
    def update_challenge_day(self, challenge_id: str, day_number: int, 
                         post_id: str, points: int = 100) -> bool:
        oid = safe_objectid(challenge_id)
        if not oid:
            return False

        challenge = self.collection.find_one({"_id": oid})
        if not challenge:
            return False
        user_oid = challenge.get("user_id")

        calendar_days = challenge.get("calendar_days", [])
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
            return False

    # ✅ UPDATE BOTH CHALLENGE + USER
        self.collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "calendar_days": calendar_days,
                    "updated_at": datetime.utcnow(),
                    "current_day": min(day_number + 1, challenge.get("duration", day_number + 1))
                },
                "$inc": {"total_points": points}
            }
        )
    # 🔥 THIS WAS MISSING
        self.db.users.update_one(
            {"_id": user_oid},
            {"$inc": {"total_points": points}}
        )

        return True
    
    def get_challenge_calendar(self, challenge_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get calendar days for a challenge.
        
        Args:
            challenge_id: Challenge MongoDB ID
            
        Returns:
            List of calendar days
        """
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
        """
        Mark a challenge as completed.
        
        Args:
            challenge_id: Challenge MongoDB ID
            
        Returns:
            Success status
        """
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
        """
        Cancel an active challenge.
        
        Args:
            challenge_id: Challenge MongoDB ID
            
        Returns:
            Success status
        """
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
        self.db = db              # 🔥 ADD THIS
        self.collection = db.posts

    def create_post(self, user_id, challenge_id, day_number, description='', image_url=None, image_type=None):
        user_oid = safe_objectid(user_id)
        challenge_oid = safe_objectid(challenge_id)

        post_data = {
            "user_id": user_oid,
            "challenge_id": challenge_oid,
            "day_number": day_number,
            "description": description,
            "image_url": image_url,
            "image_type": image_type or "image/jpeg",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "deleted_by_user": False,
            "boosts": [],
            "boosts_count": 0,
            "comments": [],
            "comment_count": 0
        }
        result = self.collection.insert_one(post_data)
        post_data["_id"] = result.inserted_id

    # 🔥 HYDRATE POST FOR FEED
        user = self.db.users.find_one({"_id": user_oid})
        challenge = self.db.challenges.find_one({"_id": challenge_oid})

        post_data["user_name"] = user.get("name") if user else "Anonymous"
        post_data["profile_photo"] = user.get("profile_photo") if user else None
        post_data["challenge_name"] = challenge.get("challenge_name") if challenge else None

    # Optional points logic
        post_data["points_earned"] = 100 + (day_number - 1) * 50

        return convert_object_ids(post_data)


    def boost_post(self, post_id, user_id):
        """Toggle boost on a post"""
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
            # Remove boost
            boosts.remove(user_oid)
            boosts_count -= 1
            action = "unboosted"
        else:
            # Add boost
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
        """Add a comment to a post"""
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
        """Soft delete a post by user"""
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
        self.collection = db.users

    def follow_user(self, follower_id, following_id):
        """Follow a user"""
        follower_oid = safe_objectid(follower_id)
        following_oid = safe_objectid(following_id)
        
        if not follower_oid or not following_oid:
            return False

        # Add to follower's following list
        self.collection.update_one(
            {"_id": follower_oid},
            {"$addToSet": {"following": following_oid}}
        )
        
        # Add to following's followers list
        self.collection.update_one(
            {"_id": following_oid},
            {"$addToSet": {"followers": follower_oid}}
        )
        
        return True

    def unfollow_user(self, follower_id, following_id):
        """Unfollow a user"""
        follower_oid = safe_objectid(follower_id)
        following_oid = safe_objectid(following_id)
        
        if not follower_oid or not following_oid:
            return False

        # Remove from follower's following list
        self.collection.update_one(
            {"_id": follower_oid},
            {"$pull": {"following": following_oid}}
        )
        
        # Remove from following's followers list
        self.collection.update_one(
            {"_id": following_oid},
            {"$pull": {"followers": follower_oid}}
        )
        
        return True



