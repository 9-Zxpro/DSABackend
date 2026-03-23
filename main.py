"""
DSA Tracker — FastAPI Backend
Run: uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from pydantic import BaseModel
from typing import Optional, List
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ── Supabase client ───────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── App ───────────────────────────────────────────────────────
app = FastAPI(title="DSA Tracker API", version="1.0.0")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "https://9-zxpro.github.io", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────
class ProgressUpdate(BaseModel):
    status: str          # "todo" | "in_progress" | "done"
    notes: Optional[str] = ""

class BulkProgressUpdate(BaseModel):
    updates: List[dict]  # [{question_id, status, notes}]

# ── Helpers ───────────────────────────────────────────────────
def flatten_question(q: dict) -> dict:
    """Merge the nested progress list into the question dict."""
    prog = q.pop("progress", [])
    if prog:
        q["status"] = prog[0].get("status", "todo")
        q["notes"]  = prog[0].get("notes", "")
        q["updated_at"] = prog[0].get("updated_at", None)
    else:
        q["status"] = "todo"
        q["notes"]  = ""
        q["updated_at"] = None
    return q

# ── Routes ───────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "DSA Tracker API is running 🚀"}


@app.get("/questions")
def get_questions():
    """Return all questions, each enriched with its progress row."""
    try:
        result = (
            supabase
            .table("questions")
            .select("*, progress(*)")
            .order("sort_order")
            .order("id")
            .execute()
        )
        return [flatten_question(q) for q in result.data]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/questions/{question_id}")
def get_question(question_id: int):
    """Return a single question with its progress."""
    try:
        result = (
            supabase
            .table("questions")
            .select("*, progress(*)")
            .eq("id", question_id)
            .single()
            .execute()
        )
        return flatten_question(result.data)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Question {question_id} not found")


@app.put("/progress/{question_id}")
def update_progress(question_id: int, body: ProgressUpdate):
    """Upsert (insert or update) a progress row for a question."""
    valid_statuses = {"todo", "in_progress", "done"}
    if body.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid_statuses}")
    try:
        result = (
            supabase
            .table("progress")
            .upsert(
                {
                    "question_id": question_id,
                    "status": body.status,
                    "notes": body.notes or "",
                    "updated_at": datetime.utcnow().isoformat(),
                },
                on_conflict="question_id",
            )
            .execute()
        )
        return {"ok": True, "data": result.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
def get_stats():
    """Aggregate progress statistics."""
    try:
        q_res   = supabase.table("questions").select("id, topic, difficulty").execute()
        pr_res  = supabase.table("progress").select("question_id, status").execute()

        total      = len(q_res.data)
        prog_map   = {p["question_id"]: p["status"] for p in pr_res.data}

        done        = sum(1 for s in prog_map.values() if s == "done")
        in_progress = sum(1 for s in prog_map.values() if s == "in_progress")
        todo        = total - done - in_progress

        # per-topic breakdown
        by_topic: dict = {}
        for q in q_res.data:
            t = q["topic"]
            if t not in by_topic:
                by_topic[t] = {"total": 0, "done": 0, "in_progress": 0}
            by_topic[t]["total"] += 1
            st = prog_map.get(q["id"], "todo")
            if st == "done":
                by_topic[t]["done"] += 1
            elif st == "in_progress":
                by_topic[t]["in_progress"] += 1

        # per-difficulty breakdown
        by_difficulty: dict = {"Easy": 0, "Medium": 0, "Hard": 0}
        diff_total:    dict = {"Easy": 0, "Medium": 0, "Hard": 0}
        for q in q_res.data:
            d = q["difficulty"]
            diff_total[d] = diff_total.get(d, 0) + 1
            if prog_map.get(q["id"]) == "done":
                by_difficulty[d] = by_difficulty.get(d, 0) + 1

        return {
            "total":        total,
            "done":         done,
            "in_progress":  in_progress,
            "todo":         todo,
            "by_topic":     by_topic,
            "by_difficulty": {"done": by_difficulty, "total": diff_total},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/progress/{question_id}")
def reset_progress(question_id: int):
    """Reset a question back to 'todo' with no notes."""
    try:
        supabase.table("progress").delete().eq("question_id", question_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/progress/reset-all")
def reset_all():
    """Wipe all progress rows (dev helper)."""
    try:
        supabase.table("progress").delete().neq("id", 0).execute()
        return {"ok": True, "message": "All progress reset"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
