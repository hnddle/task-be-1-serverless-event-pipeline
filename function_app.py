import azure.functions as func

app = func.FunctionApp()

# Blueprint 등록은 각 Phase 구현 시 추가
# from src.functions.event_api import bp as event_api_bp
# app.register_functions(event_api_bp)
