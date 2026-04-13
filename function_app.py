import azure.functions as func

from src.functions.event_api import bp as event_api_bp
from src.functions.outbox_publisher import bp as outbox_publisher_bp
from src.functions.outbox_retry import bp as outbox_retry_bp

app = func.FunctionApp()

# Blueprint 등록
app.register_functions(event_api_bp)
app.register_functions(outbox_publisher_bp)
app.register_functions(outbox_retry_bp)
