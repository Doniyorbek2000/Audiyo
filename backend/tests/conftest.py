"""Test muhiti. Integratsion testlar TEST_DATABASE_URL (Postgres) va REDIS_URL talab qiladi."""
import os

os.environ.setdefault("DATABASE_URL", os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://audiyo:audiyo@localhost:5432/audiyo_test"))
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["ENVIRONMENT"] = "development"
os.environ["ELEVENLABS_API_KEY"] = "test-eleven"
os.environ["GEMINI_API_KEY"] = "test-gemini"
os.environ["WORK_DIR"] = "/tmp/audiyo-test"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256"
