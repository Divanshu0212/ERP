"""Environment-driven config.

Defaults mirror the monorepo ``.env.example`` local-Docker values so the service
runs with zero configuration in the dev stack. All values are read once at
import time; nothing here is secret (the JWT default is the shared dev-only key).
"""

import os


class Settings:
    """Process configuration read from the environment."""

    # Shared HS256 signing key (same key across all services; zero-trust
    # signature verification). Dev default only — override in staging/prod.
    JWT_SIGNING_KEY: str = os.getenv("JWT_SIGNING_KEY", "dev-insecure-change-me")

    # RabbitMQ event bus. Topic exchange "suerp.events"; routing key = event type.
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

    # API gateway base URL — the chatbot calls owning services through it.
    GATEWAY_URL: str = os.getenv("GATEWAY_URL", "http://gateway:8080")


settings = Settings()
