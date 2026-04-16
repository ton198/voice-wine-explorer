from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.assistant import WineAssistant
from app.config import CORS_ORIGINS, INDEX_HTML_PATH, STATIC_DIR
from app.schemas import AskRequest, AskResponse

assistant = WineAssistant()


@asynccontextmanager
async def lifespan(_: FastAPI):
    assistant.load_data()
    yield


app = FastAPI(title="Voice Wine Explorer API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.post("/api/ask", response_model=AskResponse)
def ask_wine_assistant(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")
    return assistant.ask(question)


@app.get("/health")
def healthcheck() -> dict:
    return assistant.health()


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(INDEX_HTML_PATH)
