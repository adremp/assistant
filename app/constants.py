"""Application constants."""

# Google Calendar for reminders (separate from primary calendar)
REMINDERS_CALENDAR_NAME = "Напоминания"

# Event description contains LLM prompt
# Recurrence is set natively via Google Calendar UI (RRULE)

# Unified message when Google authorization is required
AUTH_REQUIRED_MESSAGE = (
    "🔐 Для доступа к вашим данным необходима авторизация в Google.\n\n"
    "Выполните команду /auth, чтобы подключить Google Calendar и Tasks."
)
