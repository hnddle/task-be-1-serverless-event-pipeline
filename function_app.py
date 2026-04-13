import azure.functions as func

from src.functions.event_api import bp as event_api_bp
from src.functions.outbox_publisher import bp as outbox_publisher_bp

app = func.FunctionApp()

# Blueprint 등록
app.register_functions(event_api_bp)
app.register_functions(outbox_publisher_bp)
