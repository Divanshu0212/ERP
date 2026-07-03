"""ai-service — FastAPI microservice for rule-based / lightweight-ML inference.

Scores grievances (sentiment + urgency), produces ``grievance.scored`` events,
and routes chatbot queries by intent. Stateless: no database, no ORM, no
suerp_common Django dependency.
"""
