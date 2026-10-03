import os
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///laundryflow_dev.db")
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    BUSINESS_UTC_OFFSET_MIN = int(os.getenv("BUSINESS_UTC_OFFSET_MIN", "330"))  # IST
